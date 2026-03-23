"""
RAG (Retrieval-Augmented Generation) Engine
Handles query embedding, vector similarity search, and contextual response generation
"""
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text, desc
from sqlalchemy.orm import selectinload

from app.models.workspace import Workspace
from app.models.document_chunk import DocumentChunk
from app.models.conversation import Conversation
from app.models.message import Message
from app.services.ai_provider import embedding_provider, llm_provider, AIProviderError
from app.services.embedding_service import EmbeddingService


class RAGError(Exception):
    """Base exception for RAG processing errors"""
    pass


class RAGEngine:
    """
    RAG engine for contextual response generation
    Combines vector similarity search with conversation history
    """
    
    # Similarity threshold for relevant chunks
    SIMILARITY_THRESHOLD = 0.75
    
    # Maximum chunks to retrieve
    MAX_CHUNKS = 5
    
    # Conversation history context (last N exchanges)
    CONTEXT_MESSAGES = 10

    # Generate a conversation summary every N messages
    SUMMARY_INTERVAL = 20
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.embedding_service = EmbeddingService(db)
    
    async def generate_query_embedding(self, query: str) -> List[float]:
        """
        Generate embedding for user query
        
        Args:
            query: User query text
        
        Returns:
            Query embedding vector
        
        Raises:
            RAGError: If embedding generation fails
        """
        try:
            if not embedding_provider:
                raise RAGError("Embedding provider not initialized")
            
            return await embedding_provider.generate_embedding(query)
            
        except AIProviderError as e:
            raise RAGError(f"Query embedding failed: {str(e)}")
        except Exception as e:
            raise RAGError(f"Query embedding error: {str(e)}")
    
    async def search_similar_chunks(
        self,
        workspace_id: str,
        query_embedding: List[float],
        similarity_threshold: float = None,
        max_chunks: int = None
    ) -> List[Tuple[DocumentChunk, float]]:
        """
        Search for similar document chunks using vector similarity
        
        Args:
            workspace_id: Workspace ID for isolation
            query_embedding: Query embedding vector
            similarity_threshold: Minimum similarity score (default: SIMILARITY_THRESHOLD)
            max_chunks: Maximum chunks to return (default: MAX_CHUNKS)
        
        Returns:
            List of (chunk, similarity_score) tuples ordered by similarity
        """
        if similarity_threshold is None:
            similarity_threshold = self.SIMILARITY_THRESHOLD
        if max_chunks is None:
            max_chunks = self.MAX_CHUNKS
        
        # Convert embedding to PostgreSQL array format
        embedding_str = '[' + ','.join(map(str, query_embedding)) + ']'
        
        # Vector similarity search using cosine similarity
        # Note: This uses pgvector extension with <=> operator for cosine distance
        query_sql = text("""
            SELECT dc.*, d.name as filename, d.workspace_id,
                   1 - (dc.embedding <=> :query_embedding) as similarity
            FROM document_chunks dc
            JOIN documents d ON dc.document_id = d.id
            WHERE d.workspace_id = :workspace_id
              AND d.status = 'completed'
              AND 1 - (dc.embedding <=> :query_embedding) >= :threshold
            ORDER BY dc.embedding <=> :query_embedding
            LIMIT :max_chunks
        """)
        
        result = await self.db.execute(
            query_sql,
            {
                'query_embedding': embedding_str,
                'workspace_id': workspace_id,
                'threshold': similarity_threshold,
                'max_chunks': max_chunks
            }
        )
        
        chunks_with_similarity = []
        for row in result:
            # Reconstruct DocumentChunk object
            chunk = DocumentChunk(
                id=row.id,
                workspace_id=row.workspace_id,
                document_id=row.document_id,
                chunk_index=row.chunk_index,
                content=row.content,
                embedding=row.embedding,
                created_at=row.created_at
            )
            
            # Store filename as an attribute on the chunk for context building
            chunk.filename = row.filename
            
            chunks_with_similarity.append((chunk, row.similarity))
        
        return chunks_with_similarity
    
    async def get_conversation_context(
        self,
        conversation_id: str,
        workspace_id: str,
        max_messages: int = None
    ) -> List[Message]:
        """
        Get recent conversation history for context
        
        Args:
            conversation_id: Conversation ID
            workspace_id: Workspace ID for isolation
            max_messages: Maximum messages to retrieve (default: CONTEXT_MESSAGES * 2)
        
        Returns:
            List of recent messages ordered by creation time
        """
        if max_messages is None:
            max_messages = self.CONTEXT_MESSAGES * 2  # User + assistant pairs
        
        # Verify conversation belongs to workspace
        conv_result = await self.db.execute(
            select(Conversation)
            .where(Conversation.id == conversation_id)
            .where(Conversation.workspace_id == workspace_id)
        )
        conversation = conv_result.scalar_one_or_none()
        if not conversation:
            return []
        
        # Get recent messages
        result = await self.db.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(desc(Message.created_at))
            .limit(max_messages)
        )
        
        messages = result.scalars().all()
        return list(reversed(messages))  # Return in chronological order
    
    async def maybe_generate_summary(
        self,
        conversation_id: str,
        workspace_id: str
    ) -> None:
        """
        Generate and store a conversation summary every SUMMARY_INTERVAL messages.
        Runs as a fire-and-forget task — does not raise exceptions to callers.
        """
        try:
            count_result = await self.db.execute(
                select(Message)
                .where(Message.conversation_id == conversation_id)
                .order_by(Message.created_at.asc())
            )
            messages = count_result.scalars().all()
            if len(messages) % self.SUMMARY_INTERVAL != 0:
                return

            # Check tier — only Growth+ gets auto-summaries
            ws_result = await self.db.execute(
                select(Workspace).where(Workspace.id == workspace_id)
            )
            workspace = ws_result.scalar_one_or_none()
            if not workspace:
                return
            from app.config import TIER_LIMITS
            if not TIER_LIMITS.get(workspace.tier or "free", {}).get("has_conversation_summary", False):
                return

            history_text = "\n".join(
                f"{'Customer' if m.role in ('customer', 'user') else 'Assistant'}: {m.content}"
                for m in messages
            )
            summary_prompt = (
                "Summarize this customer support conversation in 3-5 bullet points. "
                "Focus on the customer's main issues, key information shared, and resolutions so far.\n\n"
                + history_text
            )

            response_text, _, _ = await self.generate_response(
                prompt=summary_prompt, max_tokens=200, temperature=0.3
            )

            # Store summary in conversation.metadata
            conv_result = await self.db.execute(
                select(Conversation).where(Conversation.id == conversation_id)
            )
            conv = conv_result.scalar_one_or_none()
            if conv:
                from datetime import timezone
                meta = conv.metadata or {}
                meta["summary"] = response_text
                meta["summary_generated_at"] = datetime.now(timezone.utc).isoformat()
                conv.metadata = meta
                await self.db.commit()

        except Exception as e:
            # Non-fatal — log and continue
            import logging
            logging.getLogger(__name__).warning(f"Summary generation failed: {e}")

    async def build_context_prompt(
        self,
        query: str,
        relevant_chunks: List[Tuple[DocumentChunk, float]],
        conversation_history: List[Message],
        workspace_fallback_message: Optional[str] = None,
        conversation_summary: Optional[str] = None
    ) -> str:
        """
        Build context prompt for LLM with retrieved chunks and conversation history
        
        Args:
            query: User query
            relevant_chunks: Retrieved document chunks with similarity scores
            conversation_history: Recent conversation messages
            workspace_fallback_message: Fallback message when no relevant content
        
        Returns:
            Formatted prompt for LLM
        """
        prompt_parts = []

        # System instruction
        prompt_parts.append(
            "You are a helpful customer support assistant. Use the provided context "
            "to answer the user's question accurately and helpfully. If the context "
            "doesn't contain relevant information, politely say so and provide the "
            "fallback message if available."
        )

        # Add conversation summary if available
        if conversation_summary:
            prompt_parts.append(f"\n--- CONVERSATION SUMMARY SO FAR ---\n{conversation_summary}")

        # Add relevant document context
        if relevant_chunks:
            prompt_parts.append("\n--- RELEVANT KNOWLEDGE BASE ---")
            for i, (chunk, similarity) in enumerate(relevant_chunks, 1):
                filename = getattr(chunk, 'filename', 'Unknown')
                prompt_parts.append(
                    f"\nSource {i} (from {filename}, similarity: {similarity:.3f}):\n"
                    f"{chunk.content}"
                )
        
        # Add conversation history
        if conversation_history:
            prompt_parts.append("\n--- CONVERSATION HISTORY ---")
            for msg in conversation_history[-self.CONTEXT_MESSAGES * 2:]:
                role = "Customer" if msg.role in ("customer", "user") else "Assistant"
                prompt_parts.append(f"\n{role}: {msg.content}")
        
        # Add current query
        prompt_parts.append(f"\n--- CURRENT QUESTION ---\nCustomer: {query}")
        
        # Add fallback instruction
        if workspace_fallback_message:
            prompt_parts.append(
                f"\n--- FALLBACK MESSAGE ---\n"
                f"If you cannot answer based on the knowledge base, use this message:\n"
                f"{workspace_fallback_message}"
            )
        
        prompt_parts.append("\nAssistant:")
        
        return "\n".join(prompt_parts)
    
    async def generate_response(
        self,
        prompt: str,
        max_tokens: int = 300,
        temperature: float = 0.7
    ) -> Tuple[str, int, int]:
        """
        Generate response using LLM
        
        Args:
            prompt: Context prompt
            max_tokens: Maximum response tokens
            temperature: Response creativity (0.0-1.0)
        
        Returns:
            Tuple of (response_text, input_tokens, output_tokens)
        
        Raises:
            RAGError: If response generation fails
        """
        try:
            if not llm_provider:
                raise RAGError("LLM provider not initialized")
            
            messages = [{"role": "user", "content": prompt}]
            
            return await llm_provider.generate_response(
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature
            )
            
        except AIProviderError as e:
            raise RAGError(f"Response generation failed: {str(e)}")
        except Exception as e:
            raise RAGError(f"Response generation error: {str(e)}")
    
    async def process_rag_query(
        self,
        workspace_id: str,
        query: str,
        conversation_id: Optional[str] = None,
        max_tokens: int = 300,
        temperature: float = 0.7
    ) -> Dict[str, Any]:
        """
        Complete RAG processing pipeline
        
        Args:
            workspace_id: Workspace ID
            query: User query
            conversation_id: Optional conversation ID for context
            max_tokens: Maximum response tokens
            temperature: Response creativity
        
        Returns:
            Dict with response and processing metadata
        
        Raises:
            RAGError: If processing fails
        """
        try:
            # 1. Generate query embedding
            query_embedding = await self.generate_query_embedding(query)
            
            # 2. Search for similar chunks
            relevant_chunks = await self.search_similar_chunks(
                workspace_id, query_embedding
            )
            
            # 3. Get conversation context if available
            conversation_history = []
            conversation_summary = None
            if conversation_id:
                conversation_history = await self.get_conversation_context(
                    conversation_id, workspace_id
                )
                # Load any existing summary from conversation.metadata
                conv_result = await self.db.execute(
                    select(Conversation).where(Conversation.id == conversation_id)
                )
                conv = conv_result.scalar_one_or_none()
                if conv and conv.metadata:
                    conversation_summary = conv.metadata.get("summary")

            # 4. Get workspace fallback message
            workspace_result = await self.db.execute(
                select(Workspace.fallback_msg)
                .where(Workspace.id == workspace_id)
            )
            fallback_message = workspace_result.scalar_one_or_none()

            # 5. Build context prompt
            context_prompt = await self.build_context_prompt(
                query=query,
                relevant_chunks=relevant_chunks,
                conversation_history=conversation_history,
                workspace_fallback_message=fallback_message,
                conversation_summary=conversation_summary
            )
            
            # 6. Generate response
            response_text, input_tokens, output_tokens = await self.generate_response(
                prompt=context_prompt,
                max_tokens=max_tokens,
                temperature=temperature
            )
            
            return {
                'response': response_text,
                'input_tokens': input_tokens,
                'output_tokens': output_tokens,
                'total_tokens': input_tokens + output_tokens,
                'relevant_chunks_count': len(relevant_chunks),
                'chunks_used': [
                    {
                        'chunk_id': chunk.id,
                        'similarity': similarity,
                        'filename': getattr(chunk, 'filename', 'Unknown'),
                        'content_preview': chunk.content[:100] + '...' if len(chunk.content) > 100 else chunk.content
                    }
                    for chunk, similarity in relevant_chunks
                ],
                'has_conversation_context': len(conversation_history) > 0,
                'used_fallback': len(relevant_chunks) == 0
            }
            
        except RAGError:
            raise
        except Exception as e:
            raise RAGError(f"RAG processing failed: {str(e)}")
    
    async def get_workspace_fallback_response(self, workspace_id: str) -> str:
        """
        Get workspace fallback message when no relevant content is found
        
        Args:
            workspace_id: Workspace ID
        
        Returns:
            Fallback message or default message
        """
        result = await self.db.execute(
            select(Workspace.fallback_msg)
            .where(Workspace.id == workspace_id)
        )
        fallback_msg = result.scalar_one_or_none()
        
        if fallback_msg:
            return fallback_msg
        
        return (
            "I don't have specific information about that in my knowledge base. "
            "Please contact our support team for more detailed assistance."
        )


# ─── Convenience Functions ────────────────────────────────────────────────────

async def generate_rag_response(
    db: AsyncSession,
    workspace_id: str,
    query: str,
    conversation_id: Optional[str] = None,
    max_tokens: int = 300
) -> Dict[str, Any]:
    """
    Convenience function to generate RAG response.
    After generating, fires an async summary task if applicable.
    """
    import asyncio
    rag_engine = RAGEngine(db)
    result = await rag_engine.process_rag_query(
        workspace_id=workspace_id,
        query=query,
        conversation_id=conversation_id,
        max_tokens=max_tokens
    )
    if conversation_id:
        asyncio.create_task(
            rag_engine.maybe_generate_summary(conversation_id, workspace_id)
        )
    return result


async def search_knowledge_base(
    db: AsyncSession,
    workspace_id: str,
    query: str,
    max_results: int = 5
) -> List[Dict[str, Any]]:
    """
    Search knowledge base without generating response
    
    Args:
        db: Database session
        workspace_id: Workspace ID
        query: Search query
        max_results: Maximum results to return
    
    Returns:
        List of matching chunks with metadata
    """
    rag_engine = RAGEngine(db)
    
    # Generate query embedding
    query_embedding = await rag_engine.generate_query_embedding(query)
    
    # Search for similar chunks
    relevant_chunks = await rag_engine.search_similar_chunks(
        workspace_id, query_embedding, max_chunks=max_results
    )
    
    return [
        {
            'chunk_id': chunk.id,
            'content': chunk.content,
            'similarity': similarity,
            'filename': getattr(chunk, 'filename', 'Unknown'),
            'token_count': getattr(chunk, 'token_count', 0),
            'chunk_index': chunk.chunk_index
        }
        for chunk, similarity in relevant_chunks
    ]