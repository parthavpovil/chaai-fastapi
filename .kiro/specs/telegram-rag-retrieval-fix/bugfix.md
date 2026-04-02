# Bugfix Requirements Document

## Introduction

The RAG (Retrieval-Augmented Generation) engine is failing to retrieve relevant document chunks when processing Telegram messages, causing all queries to fall back to the default fallback message. The issue occurs during the vector similarity search in the `search_similar_chunks` method of the RAG engine. Despite documents being properly uploaded, chunked, and embedded (verified in database and OpenAI embedding usage), the similarity search consistently returns 0 relevant chunks.

The root cause is that the query embedding is being passed to PostgreSQL as a string in array format `'[1.0,2.0,3.0]'` without proper type casting to the `vector` type required by the pgvector extension. This prevents the cosine similarity operator `<=>` from functioning correctly, resulting in no matches being found regardless of the actual similarity between the query and document embeddings.

This bug affects all channels (Telegram, WhatsApp, Instagram, webchat) that use the RAG engine for response generation, not just Telegram specifically.

## Bug Analysis

### Current Behavior (Defect)

1.1 WHEN a user sends a message through Telegram asking a question that exists in the knowledge base THEN the RAG engine logs show "Found 0 relevant chunks" in Step 2 and the system returns the fallback message instead of the relevant answer

1.2 WHEN the `search_similar_chunks` method executes the vector similarity SQL query THEN the query embedding parameter is passed as a string `'[1.0,2.0,3.0]'` without the `::vector` type cast required by pgvector

1.3 WHEN the PostgreSQL query attempts to use the cosine distance operator `<=>` on the uncast string embedding THEN the comparison fails to match any document chunks even when semantically similar content exists

### Expected Behavior (Correct)

2.1 WHEN a user sends a message through Telegram asking a question that exists in the knowledge base THEN the RAG engine SHALL find relevant chunks (> 0) and return an answer based on the retrieved context

2.2 WHEN the `search_similar_chunks` method executes the vector similarity SQL query THEN the query embedding parameter SHALL be properly cast to the `vector` type using `::vector` syntax in the SQL query

2.3 WHEN the PostgreSQL query uses the cosine distance operator `<=>` on the properly cast vector embedding THEN the comparison SHALL successfully match document chunks based on semantic similarity and return chunks with similarity scores above the threshold

### Unchanged Behavior (Regression Prevention)

3.1 WHEN documents are uploaded and processed for embedding THEN the system SHALL CONTINUE TO store embeddings in the `document_chunks.embedding` column as `Vector(1536)` type

3.2 WHEN the RAG engine generates query embeddings using the embedding provider THEN the system SHALL CONTINUE TO return embeddings as Python lists of floats

3.3 WHEN the RAG engine builds context prompts and generates responses THEN the system SHALL CONTINUE TO use the same prompt structure and LLM generation logic

3.4 WHEN the RAG engine processes queries for non-Telegram channels (webchat, WhatsApp, Instagram) THEN the system SHALL CONTINUE TO use the same `search_similar_chunks` method with the corrected vector casting

3.5 WHEN the similarity threshold is set to 0.5 and max chunks is set to 5 THEN the system SHALL CONTINUE TO use these default values unless explicitly overridden
