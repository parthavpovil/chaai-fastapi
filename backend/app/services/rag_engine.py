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
    SIMILARITY_THRESHOLD = 0.5
    
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
        # Note: embedding_str is injected directly (not as a bind param) because asyncpg
        # does not support the ::vector cast syntax on named parameters. The value is
        # always a list of floats from the embedding provider, so there is no injection risk.
        
        # DEBUG: Log workspace_id and check for documents
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"🔍 search_similar_chunks: workspace_id={workspace_id} (type: {type(workspace_id)})")
        
        # Check if there are ANY documents for this workspace
        debug_query = text("""
            SELECT COUNT(*) as total_docs, 
                   COUNT(CASE WHEN status = 'completed' THEN 1 END) as completed_docs
            FROM documents 
            WHERE workspace_id = CAST(:workspace_id AS UUID)
        """)
        debug_result = await self.db.execute(debug_query, {'workspace_id': workspace_id})
        debug_row = debug_result.fetchone()
        logger.info(f"📊 Documents in workspace: total={debug_row.total_docs}, completed={debug_row.completed_docs}")
        
        # Check if there are ANY chunks for this workspace
        chunk_debug_query = text("""
            SELECT COUNT(*) as total_chunks
            FROM document_chunks dc
            JOIN documents d ON dc.document_id = d.id
            WHERE d.workspace_id = CAST(:workspace_id AS UUID)
        """)
        chunk_debug_result = await self.db.execute(chunk_debug_query, {'workspace_id': workspace_id})
        chunk_debug_row = chunk_debug_result.fetchone()
        logger.info(f"📊 Chunks in workspace: total={chunk_debug_row.total_chunks}")
        
        # Check top similarities WITHOUT threshold to see what we're getting
        similarity_check_query = text(f"""
            SELECT d.name as filename,
                   1 - (dc.embedding <=> '{embedding_str}'::vector) as similarity
            FROM document_chunks dc
            JOIN documents d ON dc.document_id = d.id
            WHERE d.workspace_id = CAST(:workspace_id AS UUID)
              AND d.status = 'completed'
            ORDER BY dc.embedding <=> '{embedding_str}'::vector
            LIMIT 5
        """)
        similarity_check_result = await self.db.execute(similarity_check_query, {'workspace_id': workspace_id})
        top_similarities = similarity_check_result.fetchall()
        logger.info(f"🎯 Top 5 similarities (threshold={similarity_threshold}):")
        for row in top_similarities:
            logger.info(f"   - {row.filename}: {row.similarity:.4f}")
        
        query_sql = text(f"""
            SELECT dc.*, d.name as filename, d.workspace_id,
                   1 - (dc.embedding <=> '{embedding_str}'::vector) as similarity
            FROM document_chunks dc
            JOIN documents d ON dc.document_id = d.id
            WHERE d.workspace_id = CAST(:workspace_id AS UUID)
              AND d.status = 'completed'
              AND 1 - (dc.embedding <=> '{embedding_str}'::vector) >= :threshold
            ORDER BY dc.embedding <=> '{embedding_str}'::vector
            LIMIT :max_chunks
        """)

        result = await self.db.execute(
            query_sql,
            {
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
        Uses its own DB session to avoid conflicts with the caller's session.
        """
        from app.database import AsyncSessionLocal
        async with AsyncSessionLocal() as db:
            await self._do_generate_summary(db, conversation_id, workspace_id)

    async def _do_generate_summary(
        self,
        db,
        conversation_id: str,
        workspace_id: str
    ) -> None:
        try:
            count_result = await db.execute(
                select(Message)
                .where(Message.conversation_id == conversation_id)
                .order_by(Message.created_at.asc())
            )
            messages = count_result.scalars().all()
            if len(messages) % self.SUMMARY_INTERVAL != 0:
                return

            # Check tier — only Growth+ gets auto-summaries
            ws_result = await db.execute(
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
            conv_result = await db.execute(
                select(Conversation).where(Conversation.id == conversation_id)
            )
            conv = conv_result.scalar_one_or_none()
            if conv:
                from datetime import timezone
                meta = conv.meta or {}
                meta["summary"] = response_text
                meta["summary_generated_at"] = datetime.now(timezone.utc).isoformat()
                conv.meta = meta
                await db.commit()

        except Exception as e:
            # Non-fatal — log and continue
            import logging
            logging.getLogger(__name__).warning(f"Summary generation failed: {e}")

    def build_context_prompt(
        self,
        query: str,
        relevant_chunks: List[Tuple[DocumentChunk, float]],
        conversation_history: List[Message],
        workspace_fallback_message: Optional[str] = None,
        conversation_summary: Optional[str] = None
    ) -> List[Dict[str, str]]:
        """
        Build messages list for LLM with retrieved chunks and conversation history.
        Returns a [system, user] message pair for efficient token usage.
        """
        system_parts = [
            "You are a helpful customer support assistant. "
            "Answer using the knowledge base context below. "
            "Be concise. If context lacks the answer, use the fallback message if provided."
        ]

        if workspace_fallback_message:
            system_parts.append(f"Fallback: {workspace_fallback_message}")

        user_parts = []

        if conversation_summary:
            user_parts.append(f"[Conversation summary]\n{conversation_summary}")

        if relevant_chunks:
            user_parts.append("[Knowledge base]")
            for i, (chunk, _) in enumerate(relevant_chunks, 1):
                filename = getattr(chunk, 'filename', 'Unknown')
                user_parts.append(f"[{i}] ({filename})\n{chunk.content}")

        if conversation_history:
            user_parts.append("[Recent conversation]")
            for msg in conversation_history[-self.CONTEXT_MESSAGES * 2:]:
                role = "Customer" if msg.role in ("customer", "user") else "Assistant"
                user_parts.append(f"{role}: {msg.content}")

        user_parts.append(f"Customer: {query}\nAssistant:")

        return [
            {"role": "system", "content": "\n".join(system_parts)},
            {"role": "user", "content": "\n\n".join(user_parts)},
        ]
    
    async def generate_response(
        self,
        prompt: str = None,
        messages: List[Dict[str, str]] = None,
        max_tokens: int = 300,
        temperature: float = 0.7
    ) -> Tuple[str, int, int]:
        """
        Generate response using LLM.
        Accepts either a messages list (preferred) or a plain prompt string.
        """
        try:
            if not llm_provider:
                raise RAGError("LLM provider not initialized")

            if messages is None:
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
        import logging
        logger = logging.getLogger(__name__)
        
        try:
            # 1. Generate query embedding
            logger.info("🔍 Step 1: Generating query embedding")
            query_embedding = await self.generate_query_embedding(query)
            logger.info(f"✅ Query embedding generated: {len(query_embedding)} dimensions")
            
            # 2. Search for similar chunks
            logger.info("🔍 Step 2: Searching for similar chunks")
            relevant_chunks = await self.search_similar_chunks(
                workspace_id, query_embedding
            )
            logger.info(f"✅ Found {len(relevant_chunks)} relevant chunks")
            
            # 3. Get conversation context if available
            conversation_history = []
            conversation_summary = None
            if conversation_id:
                logger.info("🔍 Step 3: Getting conversation context")
                conversation_history = await self.get_conversation_context(
                    conversation_id, workspace_id
                )
                logger.info(f"✅ Got {len(conversation_history)} conversation messages")
                
                # Load any existing summary from conversation.metadata
                logger.info("🔍 Step 3b: Loading conversation summary")
                conv_result = await self.db.execute(
                    select(Conversation).where(Conversation.id == conversation_id)
                )
                conv = conv_result.scalar_one_or_none()
                if conv and conv.meta:
                    conversation_summary = conv.meta.get("summary")
                logger.info(f"✅ Conversation summary loaded: {bool(conversation_summary)}")

            # 4. Get workspace fallback message
            logger.info("🔍 Step 4: Getting workspace fallback message")
            workspace_result = await self.db.execute(
                select(Workspace.fallback_msg)
                .where(Workspace.id == workspace_id)
            )
            fallback_message = workspace_result.scalar_one_or_none()
            logger.info(f"✅ Fallback message loaded: {bool(fallback_message)}")

            # 5. Build context messages (system + user split for token efficiency)
            logger.info("🔍 Step 5: Building context prompt")
            context_messages = self.build_context_prompt(
                query=query,
                relevant_chunks=relevant_chunks,
                conversation_history=conversation_history,
                workspace_fallback_message=fallback_message,
                conversation_summary=conversation_summary
            )
            logger.info(f"✅ Context prompt built: {len(context_messages)} messages")

            # 6. Generate response
            logger.info("🔍 Step 6: Generating AI response")
            response_text, input_tokens, output_tokens = await self.generate_response(
                messages=context_messages,
                max_tokens=max_tokens,
                temperature=temperature
            )
            logger.info(f"✅ AI response generated: {len(response_text)} chars, {input_tokens} in / {output_tokens} out")
            
            logger.info("🔍 Step 7: Building result dictionary")
            result = {
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
            logger.info("✅ Result dictionary built successfully")
            return result
            
        except RAGError:
            raise
        except Exception as e:
            logger.error(f"❌ RAG processing failed at some step: {str(e)}", exc_info=True)
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
    rag_engine = RAGEngine(db)
    result = await rag_engine.process_rag_query(
        workspace_id=workspace_id,
        query=query,
        conversation_id=conversation_id,
        max_tokens=max_tokens
    )
    # Don't fire background task - it causes async context issues
    # Summary generation can be done via a separate scheduled job if needed
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