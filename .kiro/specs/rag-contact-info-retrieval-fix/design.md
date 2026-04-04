# RAG Contact Info Retrieval Fix - Bugfix Design

## Overview

The RAG system fails to retrieve contact information when users ask for "contact details" or similar queries, despite the information existing in the knowledge base. The root cause is likely a combination of semantic mismatch in vector embeddings (generic query "contact details" vs. specific content like email addresses and phone numbers) and BM25 tokenization issues with special characters in email addresses and phone numbers. The fix will involve analyzing the hybrid search behavior, potentially adjusting query expansion, and ensuring both vector and BM25 components can properly match contact-related queries.

## Glossary

- **Bug_Condition (C)**: The condition that triggers the bug - when users query for contact information using generic terms like "contact details", "contact information", "how to contact"
- **Property (P)**: The desired behavior when contact queries are made - the system should retrieve chunks containing contact information (emails, phone numbers, addresses) with similarity scores above threshold
- **Preservation**: Existing query behavior for non-contact queries (like "who's the CEO") and fallback behavior for genuinely missing information must remain unchanged
- **Hybrid Search**: The combination of BM25 (full-text) and vector similarity search using Reciprocal Rank Fusion (RRF) to rank results
- **content_tsv**: PostgreSQL tsvector column populated via `to_tsvector('english', content)` for BM25 full-text search
- **RRF (Reciprocal Rank Fusion)**: Algorithm that combines rankings from multiple search methods using formula: `score = 1/(k + rank)` where k=60
- **Similarity Threshold**: Progressive thresholds (0.20, 0.15, 0.10) used to determine if chunks are relevant enough to return

## Bug Details

### Bug Condition

The bug manifests when a user queries for contact information using generic terms like "contact details", "contact information", or "how to contact". The hybrid search (BM25 + vector search) fails to identify chunks containing specific contact data (email addresses like info@, sales@, support@, press@, phone numbers, physical addresses) as relevant matches, causing the system to return the fallback message instead of the actual contact information.

**Formal Specification:**
```
FUNCTION isBugCondition(input)
  INPUT: input of type RAGQuery with properties {query: string, workspace_id: string}
  OUTPUT: boolean
  
  RETURN (input.query MATCHES_PATTERN ["contact details", "contact information", 
                                        "how to contact", "contact us", "get in touch"])
         AND contactInformationExistsInKnowledgeBase(input.workspace_id)
         AND hybridSearchReturnsNoRelevantChunks(input.query, input.workspace_id)
END FUNCTION
```

### Examples

- **Example 1**: User asks "contact details" → System returns fallback message "Sorry, I could not find an answer" instead of returning emails (info@, sales@, support@, press@), phone number, and address from SECTION 7
- **Example 2**: User asks "how can I contact you" → System fails to retrieve contact information chunk even though it exists in the knowledge base
- **Example 3**: User asks "contact information" → Hybrid search returns 0 chunks above similarity threshold, triggering fallback response
- **Edge Case**: User asks "who's the CEO" → System correctly retrieves "The CEO of TechNova Solutions is Dr. Sarah Mitchell" (this should continue working)

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**
- Queries for non-contact information (e.g., "who's the CEO") must continue to work correctly and return appropriate information
- Fallback message must still be returned when querying for information that genuinely does not exist in the knowledge base
- The hybrid BM25 + vector search with RRF, MMR re-ranking, and neighbor expansion pipeline must continue to function without breaking existing functionality
- Similarity thresholds (0.20, 0.15, 0.10) and MAX_CHUNKS limit (5) must remain respected

**Scope:**
All queries that do NOT involve contact information requests should be completely unaffected by this fix. This includes:
- Queries about company information, products, services, policies
- Queries about people, roles, organizational structure
- Queries that should legitimately return fallback messages (information not in knowledge base)

## Hypothesized Root Cause

Based on the bug description and analysis of the RAG engine code, the most likely issues are:

1. **Semantic Mismatch in Vector Embeddings**: The query "contact details" is a generic, abstract phrase, while the actual content contains specific concrete data (email addresses, phone numbers, street addresses). Vector embeddings may not recognize these as semantically similar because:
   - Generic query embedding: "contact details" → abstract concept vector
   - Chunk content embedding: "info@company.com, +1-555-0100, 123 Main St" → specific data vector
   - Cosine similarity between these vectors may fall below the 0.20 threshold

2. **BM25 Tokenization Issues with Special Characters**: The BM25 full-text search uses PostgreSQL's `to_tsvector('english', content)` which may not properly tokenize email addresses and phone numbers:
   - Email "info@company.com" may be tokenized as ["info", "company", "com"] losing the semantic unit
   - Phone "+1-555-0100" may be tokenized poorly or stripped of special characters
   - The query "contact details" contains no overlapping tokens with "info@company.com" or "+1-555-0100"

3. **Missing Query Terms in Content**: The actual contact information chunk may not contain the words "contact", "details", or "information" - it may just list the raw data (emails, phones, addresses) without descriptive labels, causing both vector and BM25 to fail

4. **Chunk Boundary Issues**: The contact information may be split across multiple chunks in a way that dilutes the relevance signal, or important context (like section headers "Contact Information") may be in a different chunk than the actual data

## Correctness Properties

Property 1: Bug Condition - Contact Information Retrieval

_For any_ query where the user requests contact information using terms like "contact details", "contact information", "how to contact", or similar phrases, and contact information exists in the knowledge base, the fixed hybrid search SHALL retrieve at least one chunk containing contact information (emails, phone numbers, addresses) with a similarity score above the threshold (0.20, 0.15, or 0.10).

**Validates: Requirements 2.1, 2.2, 2.3**

Property 2: Preservation - Non-Contact Query Behavior

_For any_ query that does NOT request contact information (e.g., queries about company information, people, products, or information that doesn't exist), the fixed hybrid search SHALL produce exactly the same results as the original implementation, preserving all existing retrieval behavior including correct responses for valid queries and fallback messages for missing information.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4**

## Fix Implementation

### Changes Required

Assuming our root cause analysis is correct, the fix will likely involve one or more of these approaches:

**File**: `backend/app/services/rag_engine.py`

**Function**: `process_rag_query` and potentially `_hybrid_search`

**Specific Changes**:

1. **Query Expansion for Contact Queries**: Detect contact-related queries and expand them to include common contact-related terms
   - When query matches pattern ["contact", "reach", "get in touch"], expand to include: "email", "phone", "address", "call", "write"
   - This helps BM25 match even if the chunk doesn't contain the word "contact"

2. **Adjust Similarity Thresholds for Contact Queries**: Contact information chunks may have lower semantic similarity due to being data-heavy rather than prose
   - Consider using a lower initial threshold (0.15 or 0.10) specifically for contact queries
   - Or add a fourth fallback threshold (0.05) for contact-specific queries

3. **Enhance BM25 Matching for Structured Data**: Improve how BM25 handles email addresses and phone numbers
   - Pre-process query to add email/phone pattern matching hints
   - Consider adding custom tokenization rules for contact data (may require database-level changes)

4. **Add Metadata-Based Filtering**: If chunks have metadata indicating they contain contact information, use that as an additional signal
   - Check if chunk metadata can be enriched during document processing to flag contact info sections
   - Use metadata as a boost factor in RRF scoring

5. **Implement Fallback Search Strategy**: If hybrid search returns no results for contact queries, try a regex-based search for email/phone patterns
   - Search for chunks containing email patterns (@domain.com) or phone patterns (+X-XXX-XXXX)
   - This ensures contact info is found even if semantic/BM25 matching fails

## Testing Strategy

### Validation Approach

The testing strategy follows a two-phase approach: first, surface counterexamples that demonstrate the bug on unfixed code, then verify the fix works correctly and preserves existing behavior.

### Exploratory Bug Condition Checking

**Goal**: Surface counterexamples that demonstrate the bug BEFORE implementing the fix. Confirm or refute the root cause analysis. If we refute, we will need to re-hypothesize.

**Test Plan**: Create a test document with contact information in a dedicated section (mimicking SECTION 7 structure), process it through the document pipeline to generate chunks and embeddings, then query for "contact details" and observe that the hybrid search fails to retrieve the contact information chunk. Run these tests on the UNFIXED code to observe failures and understand the root cause.

**Test Cases**:
1. **Contact Details Query Test**: Query "contact details" against a document containing contact info section (will fail on unfixed code - returns 0 chunks)
2. **Contact Information Query Test**: Query "contact information" against same document (will fail on unfixed code - returns 0 chunks)
3. **How to Contact Query Test**: Query "how can I contact you" against same document (will fail on unfixed code - returns 0 chunks)
4. **Direct Email Query Test**: Query "email address" against same document (may succeed or fail - helps diagnose if issue is query-specific)
5. **BM25 vs Vector Isolation Test**: Run vector-only and BM25-only searches separately to identify which component is failing (diagnostic test)

**Expected Counterexamples**:
- Hybrid search returns empty list or chunks with similarity scores below 0.20 threshold
- Possible causes: semantic mismatch in embeddings, BM25 tokenization issues with special characters, missing query terms in content
- Observability: Check `search_method` field in result to see if it's "hybrid", "vector_only", "bm25_only", or "none"

### Fix Checking

**Goal**: Verify that for all inputs where the bug condition holds, the fixed function produces the expected behavior.

**Pseudocode:**
```
FOR ALL query WHERE isBugCondition(query) DO
  result := hybridSearch_fixed(query)
  ASSERT result.relevant_chunks_count > 0
  ASSERT result.chunks_used CONTAINS_CONTACT_INFO
  ASSERT result.used_fallback == False
END FOR
```

**Test Plan**: After implementing the fix, run the same queries against the same test document and verify that contact information chunks are now retrieved with similarity scores above threshold.

**Test Cases**:
1. **Fixed Contact Details Retrieval**: Query "contact details" should return at least 1 chunk containing contact info with score ≥ threshold
2. **Fixed Contact Information Retrieval**: Query "contact information" should return contact info chunk
3. **Fixed How to Contact Retrieval**: Query "how can I contact you" should return contact info chunk
4. **Threshold Verification**: Verify returned chunks have similarity scores above the threshold used (0.20, 0.15, or 0.10)
5. **Content Verification**: Verify returned chunks actually contain email addresses, phone numbers, or physical addresses

### Preservation Checking

**Goal**: Verify that for all inputs where the bug condition does NOT hold, the fixed function produces the same result as the original function.

**Pseudocode:**
```
FOR ALL query WHERE NOT isBugCondition(query) DO
  ASSERT hybridSearch_original(query) = hybridSearch_fixed(query)
END FOR
```

**Testing Approach**: Property-based testing is recommended for preservation checking because:
- It generates many test cases automatically across the input domain
- It catches edge cases that manual unit tests might miss
- It provides strong guarantees that behavior is unchanged for all non-contact queries

**Test Plan**: Create test documents with various types of information (company info, people, products, policies). Query for non-contact information on UNFIXED code to observe correct behavior, then write property-based tests to verify the same behavior continues after the fix.

**Test Cases**:
1. **CEO Query Preservation**: Query "who's the CEO" should continue to return "The CEO of TechNova Solutions is Dr. Sarah Mitchell"
2. **Product Query Preservation**: Query about products should continue to return product information correctly
3. **Missing Info Fallback Preservation**: Query for information not in knowledge base should continue to return fallback message
4. **Similarity Threshold Preservation**: Queries that previously returned chunks with specific similarity scores should return the same scores (within small tolerance for floating point)
5. **Search Method Preservation**: Queries that previously used "hybrid", "vector_only", or "bm25_only" should continue using the same method

### Unit Tests

- Test query expansion logic for contact-related queries (if implemented)
- Test similarity threshold adjustment for contact queries (if implemented)
- Test that BM25 search correctly handles email addresses and phone numbers in content
- Test that vector search correctly handles generic contact queries vs. specific contact data
- Test RRF scoring with contact information chunks

### Property-Based Tests

- Generate random contact-related queries (variations of "contact", "reach", "get in touch") and verify all retrieve contact info
- Generate random non-contact queries and verify behavior is unchanged from original implementation
- Generate random document content with and without contact information and verify correct retrieval behavior
- Test across different similarity thresholds (0.20, 0.15, 0.10) to ensure progressive fallback works correctly

### Integration Tests

- Test full RAG pipeline with contact query: query → embedding → hybrid search → MMR → neighbor expansion → LLM response
- Test that contact information is properly included in the LLM prompt context
- Test that the final response contains the actual contact details (emails, phone, address)
- Test switching between contact queries and non-contact queries in the same conversation
- Test that conversation history doesn't interfere with contact information retrieval
