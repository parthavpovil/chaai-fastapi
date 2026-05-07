"""
RAG (Retrieval-Augmented Generation) Engine
Handles query embedding, vector similarity search, and contextual response generation.

Retrieval pipeline:
  1. Embedding (cached) + conversation data + workspace fallback — parallel
  2. Hybrid BM25 + vector search with Reciprocal Rank Fusion (RRF)
  3. Maximum Marginal Relevance (MMR) re-ranking for diversity
  4. Neighbor chunk expansion for surrounding context
  5. LLM generation
"""
import asyncio
import logging
from collections import OrderedDict
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timezone

import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text, desc, func
from sqlalchemy.orm import selectinload

from app.models.workspace import Workspace
from app.models.document_chunk import DocumentChunk
from app.models.conversation import Conversation
from app.models.message import Message
from app.services.ai_provider import embedding_provider, llm_provider, AIProviderError
from app.services.embedding_service import EmbeddingService
from app.services.ai_agent_token_tracker import log_token_usage

logger = logging.getLogger(__name__)


# ─── Module-level embedding cache ─────────────────────────────────────────────
# Shared across all RAGEngine instances. Key = (query, model_name).
# OrderedDict gives O(1) LRU eviction (popitem(last=False)).
_embedding_cache: OrderedDict = OrderedDict()
_EMBEDDING_CACHE_MAX = 512


# ─── Small-talk shortcut ──────────────────────────────────────────────────────
# Filler messages that should skip retrieval entirely. The system prompt's
# greeting rule already handles these; running the full pipeline wastes tokens
# and occasionally surfaces spurious chunks.
_SMALL_TALK = frozenset({
    "hi", "hello", "hey", "yo", "sup", "hiya",
    "thanks", "thank you", "thx", "ty", "thank u",
    "ok", "okay", "k", "kk", "got it", "cool", "nice",
    "bye", "goodbye", "cya", "later",
})


def _is_small_talk(query: str) -> bool:
    """Return True if the query is a greeting or filler that should skip RAG."""
    s = query.strip().lower().rstrip("!.?")
    if s in _SMALL_TALK:
        return True
    # Single short alpha token like "hm", "yo" — almost certainly filler
    return len(s) <= 3 and s.isalpha()


class RAGError(Exception):
    """Base exception for RAG processing errors"""
    pass


class RAGEngine:
    """
    Production RAG engine: hybrid BM25+vector search, MMR re-ranking,
    neighbor expansion, and cached embeddings.
    """

    # ── Retrieval ──────────────────────────────────────────────────────────────
    # text-embedding-3-small (1536-d normalised cosine): genuine matches ≥ ~0.4,
    # below ~0.20 is essentially "shares a few common words". BM25 still rescues
    # exact-keyword queries that fail the vector floor via hybrid RRF.
    SIMILARITY_THRESHOLD = 0.35
    SIMILARITY_FALLBACK_THRESHOLDS = (0.25, 0.18)  # progressive retry tiers
    MAX_CHUNKS = 5
    HYBRID_CANDIDATE_POOL = 20   # retrieve top-N before MMR trims to MAX_CHUNKS
    RRF_K = 60                   # standard Reciprocal Rank Fusion constant

    # ── Re-ranking ─────────────────────────────────────────────────────────────
    MMR_LAMBDA = 0.7             # 1.0 = pure relevance, 0.0 = pure diversity

    # ── Generation ─────────────────────────────────────────────────────────────
    DEFAULT_TEMPERATURE = 0.4    # factual support answers (was 0.7)
    MAX_CHUNK_CHARS = 800        # aligned with CHUNK_SIZE * 4 (200 tokens × 4 chars)

    # ── Conversation ───────────────────────────────────────────────────────────
    CONTEXT_MESSAGES = 10
    SUMMARY_INTERVAL = 20

    def __init__(self, db: AsyncSession):
        self.db = db
        self.embedding_service = EmbeddingService(db)

    # ─── Embedding (with cache) ────────────────────────────────────────────────

    async def generate_query_embedding(self, query: str) -> List[float]:
        """Generate embedding vector for a query string (no cache)."""
        try:
            if not embedding_provider:
                raise RAGError("Embedding provider not initialized")
            return await embedding_provider.generate_embedding(query)
        except AIProviderError as e:
            raise RAGError(f"Query embedding failed: {e}")
        except Exception as e:
            raise RAGError(f"Query embedding error: {e}")

    async def _get_cached_embedding(self, query: str) -> List[float]:
        """
        Return embedding for query, using the module-level LRU cache.
        Cache key = (query, model_name) so a provider swap invalidates entries.
        """
        model_name = getattr(embedding_provider, 'embedding_model', 'default')
        cache_key = (query, model_name)

        if cache_key in _embedding_cache:
            # Move to end (most-recently-used)
            _embedding_cache.move_to_end(cache_key)
            return _embedding_cache[cache_key]

        embedding = await self.generate_query_embedding(query)

        # Evict oldest entry when at capacity
        if len(_embedding_cache) >= _EMBEDDING_CACHE_MAX:
            _embedding_cache.popitem(last=False)
        _embedding_cache[cache_key] = embedding
        return embedding

    # ─── Hybrid Search (BM25 + Vector with RRF) ───────────────────────────────

    async def _hybrid_search(
        self,
        workspace_id: str,
        query: str,
        query_embedding: List[float],
        similarity_threshold: float,
        pool: int,
    ) -> Tuple[List[Tuple[DocumentChunk, float]], str]:
        """
        Run vector similarity search and BM25 full-text search concurrently,
        then combine results using Reciprocal Rank Fusion (RRF).

        Returns (chunks_with_scores, search_method) where search_method is
        "hybrid", "vector_only", or "bm25_only".
        """
        embedding_str = '[' + ','.join(map(str, query_embedding)) + ']'

        vector_sql = text(f"""
            SELECT dc.id, dc.workspace_id, dc.document_id, dc.chunk_index,
                   dc.content, dc.embedding, dc.token_count,
                   dc.start_char, dc.end_char, dc.metadata, dc.created_at,
                   d.name AS filename,
                   1 - (dc.embedding <=> '{embedding_str}'::vector) AS similarity
            FROM document_chunks dc
            JOIN documents d ON dc.document_id = d.id
            WHERE d.workspace_id = CAST(:workspace_id AS UUID)
              AND d.status = 'completed'
              AND 1 - (dc.embedding <=> '{embedding_str}'::vector) >= :threshold
            ORDER BY dc.embedding <=> '{embedding_str}'::vector
            LIMIT :pool
        """)

        # BM25 uses OR between tokens so conversational words like "tell" or
        # "whats" (not English stop words) don't block chunks that contain only
        # the keyword part of the query (e.g. "ERDI"). plainto_tsquery produces
        # AND between all tokens; we convert to OR via a regexp_replace on the
        # cast-to-text representation. The CASE guard handles all-stop-word
        # queries that produce an empty tsquery string.
        bm25_sql = text("""
            SELECT dc.id,
                   CASE WHEN length(plainto_tsquery('english', :query)::text) > 0
                        THEN ts_rank_cd(dc.content_tsv, to_tsquery('english',
                                 regexp_replace(
                                     plainto_tsquery('english', :query)::text,
                                     ' & ', ' | ', 'g'
                                 )
                             ))
                        ELSE 0
                   END AS bm25_score
            FROM document_chunks dc
            JOIN documents d ON dc.document_id = d.id
            WHERE d.workspace_id = CAST(:workspace_id AS UUID)
              AND d.status = 'completed'
              AND dc.content_tsv IS NOT NULL
              AND CASE WHEN length(plainto_tsquery('english', :query)::text) > 0
                       THEN dc.content_tsv @@ to_tsquery('english',
                                regexp_replace(
                                    plainto_tsquery('english', :query)::text,
                                    ' & ', ' | ', 'g'
                                )
                            )
                       ELSE FALSE
                  END
            ORDER BY bm25_score DESC
            LIMIT :pool
        """)

        vector_result = await self.db.execute(vector_sql, {
            'workspace_id': workspace_id,
            'threshold': similarity_threshold,
            'pool': pool,
        })
        bm25_result = await self.db.execute(bm25_sql, {
            'workspace_id': workspace_id,
            'query': query,
            'pool': pool,
        })

        vector_rows = list(vector_result)
        bm25_rows = list(bm25_result)

        if not vector_rows and not bm25_rows:
            return [], "none"

        # Build rank maps (1-indexed)
        vector_rank: Dict[str, int] = {str(r.id): i + 1 for i, r in enumerate(vector_rows)}
        bm25_rank: Dict[str, int] = {str(r.id): i + 1 for i, r in enumerate(bm25_rows)}
        vector_row_map: Dict[str, Any] = {str(r.id): r for r in vector_rows}

        # Chunks that appear only in BM25 need their full row fetched
        bm25_only_ids = set(bm25_rank.keys()) - set(vector_rank.keys())
        bm25_only_rows: Dict[str, Any] = {}
        if bm25_only_ids:
            id_list = ', '.join(f"'{cid}'::uuid" for cid in bm25_only_ids)
            extra_result = await self.db.execute(text(f"""
                SELECT dc.id, dc.workspace_id, dc.document_id, dc.chunk_index,
                       dc.content, dc.embedding, dc.token_count,
                       dc.start_char, dc.end_char, dc.metadata, dc.created_at,
                       d.name AS filename, 0.0 AS similarity
                FROM document_chunks dc
                JOIN documents d ON dc.document_id = d.id
                WHERE dc.id IN ({id_list})
            """))
            for row in extra_result:
                bm25_only_rows[str(row.id)] = row

        # Compute RRF score for every chunk seen in either result
        all_ids = set(vector_rank.keys()) | set(bm25_rank.keys())
        rrf_scores: List[Tuple[str, float]] = []
        for cid in all_ids:
            score = 0.0
            v_rank = vector_rank.get(cid)
            b_rank = bm25_rank.get(cid)
            if v_rank is not None:
                score += 1.0 / (self.RRF_K + v_rank)
            if b_rank is not None:
                score += 1.0 / (self.RRF_K + b_rank)
            rrf_scores.append((cid, score))

        rrf_scores.sort(key=lambda x: x[1], reverse=True)
        top_ids = [cid for cid, _ in rrf_scores[:pool]]

        # Determine search method for observability
        has_vector = bool(vector_rows)
        has_bm25 = bool(bm25_rows)
        if has_vector and has_bm25:
            search_method = "hybrid"
        elif has_vector:
            search_method = "vector_only"
        else:
            search_method = "bm25_only"

        # Reconstruct DocumentChunk objects in RRF order
        result: List[Tuple[DocumentChunk, float]] = []
        for cid in top_ids:
            row = vector_row_map.get(cid) or bm25_only_rows.get(cid)
            if row is None:
                continue
            chunk = DocumentChunk(
                id=row.id,
                workspace_id=row.workspace_id,
                document_id=row.document_id,
                chunk_index=row.chunk_index,
                content=row.content,
                embedding=row.embedding,
                created_at=row.created_at,
            )
            chunk.filename = row.filename
            similarity = getattr(row, 'similarity', 0.0) or 0.0
            result.append((chunk, float(similarity)))

        return result, search_method

    # ─── Backward-compatible vector-only search ────────────────────────────────

    async def search_similar_chunks(
        self,
        workspace_id: str,
        query_embedding: List[float],
        similarity_threshold: float = None,
        max_chunks: int = None
    ) -> List[Tuple[DocumentChunk, float]]:
        """
        Vector-only similarity search (public, backward-compatible).
        Used by search_knowledge_base which has no query text for BM25.
        """
        if similarity_threshold is None:
            similarity_threshold = self.SIMILARITY_THRESHOLD
        if max_chunks is None:
            max_chunks = self.MAX_CHUNKS

        embedding_str = '[' + ','.join(map(str, query_embedding)) + ']'

        # NOTE: embedding_str is interpolated directly (not a bind param) because
        # asyncpg does not support ::vector cast on named parameters. The value is
        # always a list of floats from the embedding provider — no injection risk.
        query_sql = text(f"""
            SELECT dc.*, d.name AS filename, d.workspace_id,
                   1 - (dc.embedding <=> '{embedding_str}'::vector) AS similarity
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
                'max_chunks': max_chunks,
            }
        )

        chunks_with_similarity = []
        for row in result:
            chunk = DocumentChunk(
                id=row.id,
                workspace_id=row.workspace_id,
                document_id=row.document_id,
                chunk_index=row.chunk_index,
                content=row.content,
                embedding=row.embedding,
                created_at=row.created_at,
            )
            chunk.filename = row.filename
            chunks_with_similarity.append((chunk, row.similarity))

        return chunks_with_similarity

    # ─── MMR Re-ranking ────────────────────────────────────────────────────────

    def _apply_mmr(
        self,
        candidates: List[Tuple[DocumentChunk, float]],
        max_chunks: int,
    ) -> List[Tuple[DocumentChunk, float]]:
        """
        Maximum Marginal Relevance: iteratively select chunks that maximise
        λ × relevance − (1−λ) × max_cosine_similarity_to_already_selected.

        Operates on the embedding vectors already loaded from the DB.
        Requires numpy (available transitively via pgvector).
        """
        if len(candidates) <= max_chunks:
            return candidates

        # Build embedding matrix; replace None/missing with zero vector
        dim = 1536
        emb_list = []
        for chunk, _ in candidates:
            emb = chunk.embedding
            if emb is None:
                emb = [0.0] * dim
            elif isinstance(emb, str):
                import json
                emb = json.loads(emb)
            emb_list.append(emb)

        emb_matrix = np.array(emb_list, dtype=np.float32)

        # L2-normalise so dot product == cosine similarity
        norms = np.linalg.norm(emb_matrix, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1.0, norms)
        emb_matrix = emb_matrix / norms

        relevance = np.array([score for _, score in candidates], dtype=np.float32)

        selected_indices: List[int] = []
        remaining = list(range(len(candidates)))

        while len(selected_indices) < max_chunks and remaining:
            if not selected_indices:
                # First pick: highest relevance
                rel_remaining = np.array([relevance[i] for i in remaining])
                best_local = int(np.argmax(rel_remaining))
                chosen = remaining[best_local]
            else:
                selected_embs = emb_matrix[selected_indices]  # (k, dim)
                best_score = -float('inf')
                chosen = remaining[0]
                for idx in remaining:
                    rel = float(relevance[idx])
                    # max cosine similarity to any already-selected chunk
                    sims = emb_matrix[idx] @ selected_embs.T  # (k,)
                    max_sim = float(np.max(sims))
                    mmr_score = self.MMR_LAMBDA * rel - (1.0 - self.MMR_LAMBDA) * max_sim
                    if mmr_score > best_score:
                        best_score = mmr_score
                        chosen = idx

            selected_indices.append(chosen)
            remaining.remove(chosen)

        return [candidates[i] for i in selected_indices]

    # ─── Neighbor Chunk Expansion ──────────────────────────────────────────────

    async def _expand_with_neighbors(
        self,
        chunks: List[Tuple[DocumentChunk, float]],
    ) -> List[Tuple[DocumentChunk, float]]:
        """
        For each selected chunk, fetch chunk_index ± 1 (same document_id).
        Neighbor chunks are appended with score=0.0 to provide surrounding context.
        Uses a single batched SQL query. Deduplicates by chunk id.
        """
        if not chunks:
            return chunks

        existing_ids = {str(chunk.id) for chunk, _ in chunks}

        # Build (document_id, chunk_index) pairs for neighbors
        neighbor_pairs = []
        for chunk, _ in chunks:
            for delta in (-1, 1):
                neighbor_pairs.append((str(chunk.document_id), chunk.chunk_index + delta))

        if not neighbor_pairs:
            return chunks

        # Build a single IN query using parameterised values
        values_clauses = []
        params: Dict[str, Any] = {}
        for i, (doc_id, idx) in enumerate(neighbor_pairs):
            values_clauses.append(f"(CAST(:doc_{i} AS UUID), :idx_{i})")
            params[f"doc_{i}"] = doc_id
            params[f"idx_{i}"] = idx

        values_sql = ', '.join(values_clauses)
        neighbor_sql = text(f"""
            SELECT dc.id, dc.workspace_id, dc.document_id, dc.chunk_index,
                   dc.content, dc.embedding, dc.token_count,
                   dc.start_char, dc.end_char, dc.metadata, dc.created_at,
                   d.name AS filename
            FROM document_chunks dc
            JOIN documents d ON dc.document_id = d.id
            WHERE (dc.document_id, dc.chunk_index) IN ({values_sql})
        """)

        result = await self.db.execute(neighbor_sql, params)

        neighbors: List[Tuple[DocumentChunk, float]] = []
        for row in result:
            cid = str(row.id)
            if cid in existing_ids:
                continue
            chunk = DocumentChunk(
                id=row.id,
                workspace_id=row.workspace_id,
                document_id=row.document_id,
                chunk_index=row.chunk_index,
                content=row.content,
                embedding=row.embedding,
                created_at=row.created_at,
            )
            chunk.filename = row.filename
            neighbors.append((chunk, 0.0))
            existing_ids.add(cid)

        return chunks + neighbors

    # ─── Conversation Data ─────────────────────────────────────────────────────

    async def get_conversation_context(
        self,
        conversation_id: str,
        workspace_id: str,
        max_messages: int = None
    ) -> List[Message]:
        """Return recent messages for a conversation (public, backward-compat)."""
        messages, _ = await self._get_conversation_data(
            conversation_id, workspace_id, max_messages
        )
        return messages

    async def _get_conversation_data(
        self,
        conversation_id: str,
        workspace_id: str,
        max_messages: int = None,
    ) -> Tuple[List[Message], Optional[str]]:
        """
        Fetch conversation messages and summary in two queries.
        Returns (messages, summary_text).
        """
        if max_messages is None:
            max_messages = self.CONTEXT_MESSAGES * 2

        conv_result = await self.db.execute(
            select(Conversation)
            .where(Conversation.id == conversation_id)
            .where(Conversation.workspace_id == workspace_id)
        )
        conv = conv_result.scalar_one_or_none()
        if not conv:
            return [], None

        msg_result = await self.db.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(desc(Message.created_at))
            .limit(max_messages)
        )
        messages = list(reversed(msg_result.scalars().all()))
        summary = conv.meta.get("summary") if conv.meta else None
        return messages, summary

    async def _get_workspace_persona(self, workspace_id: str) -> Dict[str, Optional[str]]:
        """
        Fetch workspace fallback message + assistant identity in a single query.
        Returns {'fallback_msg', 'assistant_name', 'assistant_persona'}.
        """
        result = await self.db.execute(
            select(
                Workspace.fallback_msg,
                Workspace.assistant_name,
                Workspace.assistant_persona,
            ).where(Workspace.id == workspace_id)
        )
        row = result.first()
        if row is None:
            return {"fallback_msg": None, "assistant_name": None, "assistant_persona": None}
        return {
            "fallback_msg": row.fallback_msg,
            "assistant_name": row.assistant_name,
            "assistant_persona": row.assistant_persona,
        }

    async def _get_workspace_fallback(self, workspace_id: str) -> Optional[str]:
        """Fetch workspace fallback message (compatibility wrapper)."""
        return (await self._get_workspace_persona(workspace_id))["fallback_msg"]

    # ─── Prompt Building ───────────────────────────────────────────────────────

    @staticmethod
    def _build_persona_opener(
        assistant_name: Optional[str],
        assistant_persona: Optional[str],
    ) -> str:
        """
        Construct the first line of the system prompt from optional workspace
        identity fields. Defense-in-depth: strip newlines and clamp length even
        though the settings endpoint already validates these.
        """
        def clean(s: Optional[str], cap: int) -> Optional[str]:
            if not s:
                return None
            s = s.replace("\r", " ").replace("\n", " ").strip()
            if not s:
                return None
            return s[:cap]

        name = clean(assistant_name, 60)
        persona = clean(assistant_persona, 300)

        if name and persona:
            return f"You are {name}, {persona}. You provide precise customer support."
        if name:
            return f"You are {name}, a precise customer support assistant."
        if persona:
            return f"You are {persona}, providing precise customer support."
        return "You are a precise customer support assistant."

    def build_context_prompt(
        self,
        query: str,
        relevant_chunks: List[Tuple[DocumentChunk, float]],
        conversation_history: List[Message],
        workspace_fallback_message: Optional[str] = None,
        conversation_summary: Optional[str] = None,
        assistant_name: Optional[str] = None,
        assistant_persona: Optional[str] = None,
    ) -> List[Dict[str, str]]:
        """
        Build [system, user] message pair for the LLM.
        Chunks are truncated to MAX_CHUNK_CHARS to control token usage.
        """
        fallback = workspace_fallback_message or "Sorry, I could not find an answer. Our team will get back to you."
        opener = self._build_persona_opener(assistant_name, assistant_persona)
        system_parts = [
            f"{opener}\n"
            "RULES:\n"
            "1. Answer ONLY from the [Knowledge base] passages provided. Do not use prior knowledge.\n"
            "2. After EVERY factual claim, append a citation in the form [N] referencing "
            "the passage number. If a sentence draws on multiple passages, cite each: [1][3]. "
            "Citations are not required for greetings, meta-question replies, or the fallback message.\n"
            "3. Be concise and direct — one to three sentences unless the question requires more detail. "
            "If the passages contain a partial answer, give that partial answer clearly.\n"
            "4. When passages conflict, prefer the one with the highest relevance score "
            "(passages are listed in descending relevance order; later passages may be neighbor "
            "context with no score).\n"
            "5. If the customer sends a greeting or small talk (e.g. 'hi', 'hello', 'hey', 'how are you'), "
            "respond with a brief, friendly reply and invite them to ask their question — do NOT use the fallback for greetings.\n"
            "6. If the customer asks what you know, what you can help with, what topics you cover, or similar "
            "meta-questions about your capabilities (e.g. 'what do you know?', 'what can you tell me?', "
            "'what can you help me with?', 'what topics do you cover?'), respond with a brief, friendly "
            "message that you're here to help with questions about this service and invite them to ask "
            "their specific question. Do NOT use the fallback message for these meta-questions.\n"
            "7. If the passages do not contain enough information to answer a real question, reply with exactly:\n"
            f"   {fallback}\n"
            "8. Never invent facts, numbers, dates, or names not present in the passages."
        ]

        user_parts = []

        if conversation_summary:
            user_parts.append(f"[Conversation summary]\n{conversation_summary}")

        if relevant_chunks:
            user_parts.append("[Knowledge base]")
            for i, (chunk, score) in enumerate(relevant_chunks, 1):
                filename = getattr(chunk, 'filename', 'Unknown')
                content = chunk.content
                if len(content) > self.MAX_CHUNK_CHARS:
                    content = content[:self.MAX_CHUNK_CHARS] + "…"
                user_parts.append(
                    f"[{i}] (source: {filename}, chunk {chunk.chunk_index})\n{content}"
                )

        if conversation_history:
            # Exclude the most recent message if it's the customer's current query.
            # process_incoming_message writes the message to DB before RAG is called,
            # so _get_conversation_data picks it up — but it's already appended below
            # as "Customer: {query}", so including it here creates an unhelpful duplicate.
            history_to_show = (
                conversation_history[:-1]
                if conversation_history
                and conversation_history[-1].role in ("customer", "user")
                and conversation_history[-1].content == query
                else conversation_history
            )
            if history_to_show:
                user_parts.append("[Recent conversation]")
                for msg in history_to_show[-self.CONTEXT_MESSAGES * 2:]:
                    role = "Customer" if msg.role in ("customer", "user") else "Assistant"
                    user_parts.append(f"{role}: {msg.content}")

        user_parts.append(f"Customer: {query}\nAssistant:")

        return [
            {"role": "system", "content": "\n".join(system_parts)},
            {"role": "user", "content": "\n\n".join(user_parts)},
        ]

    # ─── Query Rewriting ───────────────────────────────────────────────────────

    async def _rewrite_query(
        self,
        query: str,
        history: Optional[List[Message]] = None,
    ) -> Tuple[str, int, int]:
        """
        Rewrite a conversational query into a self-contained, keyword-rich
        search query. When `history` is provided the rewriter resolves
        coreferences ("it", "that") against the prior turns — this is the
        primary reason the rewriter exists. Falls back to the original on any
        error. Used only for retrieval; the original query is shown to users.
        """
        if not llm_provider:
            return query, 0, 0
        stripped = query.strip()
        if not stripped:
            return query, 0, 0
        # Skip rewriting only when there is no history AND the query is short.
        # Short queries WITH history (e.g. "what about it?") are exactly when
        # coreference resolution matters most.
        has_history = bool(history)
        if not has_history and len(stripped.split()) <= 3:
            return query, 0, 0

        history_block = ""
        if has_history:
            # Last 4 turns max — recent context is what matters for coreference
            recent = history[-4:]
            lines = []
            for msg in recent:
                role = "Customer" if msg.role in ("customer", "user") else "Assistant"
                # Truncate each turn so the rewriter doesn't drown in context
                content = (msg.content or "").strip().replace("\n", " ")
                if len(content) > 200:
                    content = content[:200] + "…"
                lines.append(f"{role}: {content}")
            history_block = "\n".join(lines)

        try:
            system_content = (
                "You rewrite a customer's latest question into a self-contained, "
                "keyword-rich search query for a knowledge base. Use the prior "
                "turns ONLY to resolve pronouns and references (it / that / the X) "
                "— do NOT add new topics. PRESERVE proper nouns, product names, "
                "error codes, and numeric identifiers exactly as written. "
                "Output ONLY the rewritten query — no prefix, no quotes, no explanation.\n\n"
                "Example:\n"
                "History:\n"
                "Customer: I was charged twice for my Pro subscription last month.\n"
                "Assistant: I can help look into that.\n"
                "Latest: how do I get a refund?\n"
                "Rewrite: refund duplicate Pro subscription charge"
            )
            user_content = (
                f"History:\n{history_block}\nLatest: {stripped}\nRewrite:"
                if history_block
                else stripped
            )
            messages = [
                {"role": "system", "content": system_content},
                {"role": "user", "content": user_content},
            ]
            rewritten, rw_in_tok, rw_out_tok = await llm_provider.generate_response(
                messages=messages, max_tokens=40, temperature=0.0
            )
            rewritten = rewritten.strip().strip('"').strip("'")
            # Defensive: if model returned a "Rewrite:" prefix anyway, strip it
            if rewritten.lower().startswith("rewrite:"):
                rewritten = rewritten[len("rewrite:"):].strip()
            return (rewritten if rewritten else query), rw_in_tok, rw_out_tok
        except Exception:
            return query, 0, 0

    # ─── LLM Generation ────────────────────────────────────────────────────────

    async def generate_response(
        self,
        prompt: str = None,
        messages: List[Dict[str, str]] = None,
        max_tokens: int = 300,
        temperature: float = 0.7,
    ) -> Tuple[str, int, int]:
        """
        Generate a response from the LLM.
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
                temperature=temperature,
            )
        except AIProviderError as e:
            raise RAGError(f"Response generation failed: {e}")
        except Exception as e:
            raise RAGError(f"Response generation error: {e}")

    # ─── Main Pipeline ─────────────────────────────────────────────────────────

    async def process_rag_query(
        self,
        workspace_id: str,
        query: str,
        conversation_id: Optional[str] = None,
        max_tokens: int = 300,
        temperature: float = DEFAULT_TEMPERATURE,
    ) -> Dict[str, Any]:
        """
        Full RAG pipeline with parallelised I/O and advanced retrieval.

        Execution order:
          1. Parallel: conversation data + workspace persona
          2. Conversation-aware query rewriting (uses history from step 1)
          3. Cached embedding for the rewritten query
          4. Progressive hybrid search (BM25 + vector → RRF)
          5. MMR re-ranking for diversity
          6. Neighbor chunk expansion for context
          7. Build prompt and generate LLM response

        Small-talk shortcut: greetings/filler skip retrieval entirely.
        """
        try:
            # ── Step 1: sequential fetch — conv data + workspace persona ───────
            if conversation_id:
                conversation_history, conversation_summary = await self._get_conversation_data(
                    conversation_id, workspace_id
                )
            else:
                conversation_history, conversation_summary = [], None

            persona = await self._get_workspace_persona(workspace_id)

            fallback_message = persona["fallback_msg"]
            assistant_name = persona["assistant_name"]
            assistant_persona = persona["assistant_persona"]

            # ── Small-talk shortcut: skip retrieval entirely ──────────────────
            if _is_small_talk(query):
                logger.debug("RAG small-talk shortcut — query=%r", query)
                context_messages = self.build_context_prompt(
                    query=query,
                    relevant_chunks=[],
                    conversation_history=conversation_history,
                    workspace_fallback_message=fallback_message,
                    conversation_summary=conversation_summary,
                    assistant_name=assistant_name,
                    assistant_persona=assistant_persona,
                )
                response_text, input_tokens, output_tokens = await self.generate_response(
                    messages=context_messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
                await log_token_usage(
                    db=self.db,
                    workspace_id=workspace_id,
                    model=getattr(llm_provider, "llm_model", "unknown"),
                    call_type="rag_response",
                    call_source="rag_response",
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    conversation_id=conversation_id,
                )
                return {
                    'response': response_text,
                    'input_tokens': input_tokens,
                    'output_tokens': output_tokens,
                    'total_tokens': input_tokens + output_tokens,
                    'relevant_chunks_count': 0,
                    'chunks_used': [],
                    'has_conversation_context': bool(conversation_history),
                    'used_fallback': False,
                    'search_method': 'small_talk',
                    'threshold_used': None,
                }

            # ── Step 2: conversation-aware query rewriting ────────────────────
            # Pass the prior turns so the rewriter can resolve "it"/"that"/etc.
            # _get_conversation_data appends the customer's current turn (it's
            # already in the DB), so trim it off before handing to the rewriter.
            history_for_rewrite = conversation_history
            if (
                history_for_rewrite
                and history_for_rewrite[-1].role in ("customer", "user")
                and history_for_rewrite[-1].content == query
            ):
                history_for_rewrite = history_for_rewrite[:-1]

            search_query, rw_in_tok, rw_out_tok = await self._rewrite_query(query, history=history_for_rewrite)
            if rw_in_tok > 0:
                await log_token_usage(
                    db=self.db,
                    workspace_id=workspace_id,
                    model=getattr(llm_provider, "llm_model", "unknown"),
                    call_type="rag_rewrite",
                    call_source="rag_rewrite",
                    input_tokens=rw_in_tok,
                    output_tokens=rw_out_tok,
                    conversation_id=conversation_id,
                )
            if search_query != query:
                logger.debug(
                    "RAG query rewritten — original=%r rewritten=%r history_turns=%d",
                    query, search_query, len(history_for_rewrite),
                )

            # ── Step 3: embedding (depends on rewritten query) ────────────────
            query_embedding = await self._get_cached_embedding(search_query)

            logger.debug(
                "RAG fetched — embedding_dims=%d history=%d has_summary=%s",
                len(query_embedding), len(conversation_history), bool(conversation_summary),
            )

            # ── Step 4: progressive hybrid search ─────────────────────────────
            candidates: List[Tuple[DocumentChunk, float]] = []
            search_method = "none"
            threshold_used = None

            for threshold in (self.SIMILARITY_THRESHOLD,) + self.SIMILARITY_FALLBACK_THRESHOLDS:
                candidates, search_method = await self._hybrid_search(
                    workspace_id=workspace_id,
                    query=search_query,
                    query_embedding=query_embedding,
                    similarity_threshold=threshold,
                    pool=self.HYBRID_CANDIDATE_POOL,
                )
                if candidates:
                    threshold_used = threshold
                    break

            logger.debug(
                "RAG search — method=%s threshold=%.2f candidates=%d",
                search_method, threshold_used or 0, len(candidates),
            )

            # ── Step 5: MMR re-ranking ────────────────────────────────────────
            final_chunks = self._apply_mmr(candidates, self.MAX_CHUNKS)

            # ── Step 6: neighbor expansion ────────────────────────────────────
            if final_chunks:
                final_chunks = await self._expand_with_neighbors(final_chunks)

            # ── Step 7: build prompt and generate ─────────────────────────────
            context_messages = self.build_context_prompt(
                query=query,
                relevant_chunks=final_chunks,
                conversation_history=conversation_history,
                workspace_fallback_message=fallback_message,
                conversation_summary=conversation_summary,
                assistant_name=assistant_name,
                assistant_persona=assistant_persona,
            )

            response_text, input_tokens, output_tokens = await self.generate_response(
                messages=context_messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )

            await log_token_usage(
                db=self.db,
                workspace_id=workspace_id,
                model=getattr(llm_provider, "llm_model", "unknown"),
                call_type="rag_response",
                call_source="rag_response",
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                conversation_id=conversation_id,
            )

            logger.debug(
                "RAG response — chars=%d tokens_in=%d tokens_out=%d",
                len(response_text), input_tokens, output_tokens,
            )

            # Only the hits (score > 0) count as "relevant"; neighbors have score=0
            hit_chunks = [(c, s) for c, s in final_chunks if s > 0]

            return {
                'response': response_text,
                'input_tokens': input_tokens,
                'output_tokens': output_tokens,
                'total_tokens': input_tokens + output_tokens,
                'relevant_chunks_count': len(hit_chunks),
                'chunks_used': [
                    {
                        'chunk_id': chunk.id,
                        'similarity': similarity,
                        'filename': getattr(chunk, 'filename', 'Unknown'),
                        'content_preview': (
                            chunk.content[:100] + '…'
                            if len(chunk.content) > 100
                            else chunk.content
                        ),
                    }
                    for chunk, similarity in hit_chunks
                ],
                'has_conversation_context': bool(conversation_history),
                'used_fallback': len(hit_chunks) == 0,
                # Observability extras (non-breaking additions)
                'search_method': search_method,
                'threshold_used': threshold_used,
            }

        except RAGError:
            raise
        except Exception as e:
            logger.error("RAG processing failed: %s", e, exc_info=True)
            raise RAGError(f"RAG processing failed: {e}")

    # ─── Conversation Summarisation ────────────────────────────────────────────

    async def maybe_generate_summary(
        self,
        conversation_id: str,
        workspace_id: str,
    ) -> None:
        """
        Generate and store a conversation summary every SUMMARY_INTERVAL messages.
        Uses its own DB session — safe to call fire-and-forget.
        """
        from app.database import AsyncSessionLocal
        async with AsyncSessionLocal() as db:
            await self._do_generate_summary(db, conversation_id, workspace_id)

    async def _do_generate_summary(
        self,
        db,
        conversation_id: str,
        workspace_id: str,
    ) -> None:
        try:
            # COUNT(*) — do not fetch all rows just to measure length
            count_result = await db.execute(
                select(func.count())
                .select_from(Message)
                .where(Message.conversation_id == conversation_id)
            )
            count = count_result.scalar()
            if count % self.SUMMARY_INTERVAL != 0:
                return

            ws_result = await db.execute(
                select(Workspace).where(Workspace.id == workspace_id)
            )
            workspace = ws_result.scalar_one_or_none()
            if not workspace:
                return

            from app.config import TIER_LIMITS
            if not TIER_LIMITS.get(workspace.tier or "free", {}).get("has_conversation_summary", False):
                return

            msg_result = await db.execute(
                select(Message)
                .where(Message.conversation_id == conversation_id)
                .order_by(Message.created_at.asc())
            )
            messages = msg_result.scalars().all()

            history_text = "\n".join(
                f"{'Customer' if m.role in ('customer', 'user') else 'Assistant'}: {m.content}"
                for m in messages
            )
            summary_prompt = (
                "Summarize this customer support conversation in 3-5 bullet points. "
                "Focus on the customer's main issues, key information shared, and resolutions so far.\n\n"
                + history_text
            )

            response_text, s_in_tok, s_out_tok = await self.generate_response(
                prompt=summary_prompt, max_tokens=200, temperature=0.3
            )

            conv_result = await db.execute(
                select(Conversation).where(Conversation.id == conversation_id)
            )
            conv = conv_result.scalar_one_or_none()
            if conv:
                meta = conv.meta or {}
                meta["summary"] = response_text
                meta["summary_generated_at"] = datetime.now(timezone.utc).isoformat()
                conv.meta = meta
                await db.commit()

            if s_in_tok > 0:
                await log_token_usage(
                    db=db,
                    workspace_id=workspace_id,
                    model=getattr(llm_provider, "llm_model", "unknown"),
                    call_type="rag_summary",
                    call_source="rag_summary",
                    input_tokens=s_in_tok,
                    output_tokens=s_out_tok,
                    conversation_id=conversation_id,
                )

        except Exception as e:
            logger.warning("Summary generation failed: %s", e)

    # ─── Legacy / Fallback ─────────────────────────────────────────────────────

    async def get_workspace_fallback_response(self, workspace_id: str) -> str:
        """Return workspace fallback message or a generic default."""
        fallback = await self._get_workspace_fallback(workspace_id)
        return fallback or (
            "I don't have specific information about that in my knowledge base. "
            "Please contact our support team for more detailed assistance."
        )

    async def expand_query(self, query: str) -> str:
        """
        Expand vague or short queries to improve retrieval.
        NOTE: Not called in the default pipeline — use explicitly if needed.
        """
        if len(query.split()) >= 5:
            return query
        try:
            expansion_prompt = (
                f"Rephrase this customer question to be more specific and detailed, "
                f"keeping the same meaning: '{query}'"
            )
            expanded, _, _ = await self.generate_response(
                prompt=expansion_prompt,
                max_tokens=50,
                temperature=0.3,
            )
            return expanded.strip()
        except Exception:
            return query


# ─── Convenience Functions ─────────────────────────────────────────────────────

async def generate_rag_response(
    db: AsyncSession,
    workspace_id: str,
    query: str,
    conversation_id: Optional[str] = None,
    max_tokens: int = 300,
) -> Dict[str, Any]:
    """Convenience wrapper around RAGEngine.process_rag_query."""
    return await RAGEngine(db).process_rag_query(
        workspace_id=workspace_id,
        query=query,
        conversation_id=conversation_id,
        max_tokens=max_tokens,
        temperature=RAGEngine.DEFAULT_TEMPERATURE,
    )


async def search_knowledge_base(
    db: AsyncSession,
    workspace_id: str,
    query: str,
    max_results: int = 5,
) -> List[Dict[str, Any]]:
    """Search the knowledge base without generating a response."""
    engine = RAGEngine(db)
    query_embedding = await engine.generate_query_embedding(query)
    relevant_chunks = await engine.search_similar_chunks(
        workspace_id, query_embedding, max_chunks=max_results
    )
    return [
        {
            'chunk_id': chunk.id,
            'content': chunk.content,
            'similarity': similarity,
            'filename': getattr(chunk, 'filename', 'Unknown'),
            'token_count': getattr(chunk, 'token_count', 0),
            'chunk_index': chunk.chunk_index,
        }
        for chunk, similarity in relevant_chunks
    ]
