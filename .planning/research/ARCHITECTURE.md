# Architecture Research

**Domain:** Financial Document RAG Server
**Researched:** 2026-02-12
**Confidence:** MEDIUM (based on established RAG patterns, no access to current 2026 sources)

## Standard Architecture

### System Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                      API Layer                                   │
│  ┌────────────┐  ┌────────────┐                                 │
│  │ REST API   │  │ MCP Server │                                 │
│  └─────┬──────┘  └─────┬──────┘                                 │
│        │                │                                        │
├────────┴────────────────┴────────────────────────────────────────┤
│                   Query Orchestration                            │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │  Retriever   │  │ LLM Synthesis│  │ Doc Manager  │          │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘          │
│         │                  │                  │                  │
├─────────┴──────────────────┴──────────────────┴──────────────────┤
│                    Storage & Indexing                            │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │ Vector Store │  │ Metadata DB  │  │  LLM Engine  │          │
│  │  (embeddings)│  │  (chunks,    │  │  (vLLM/      │          │
│  │              │  │   docs)      │  │   Ollama)    │          │
│  └──────────────┘  └──────────────┘  └──────────────┘          │
│         ↑                  ↑                                     │
├─────────┴──────────────────┴─────────────────────────────────────┤
│                   Ingestion Pipeline                             │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐        │
│  │  PDF     │  │  LaTeX   │  │ Notebook │  │ Chunker  │        │
│  │  Parser  │  │  Parser  │  │ Parser   │  │ (smart)  │        │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘        │
│         ↓              ↓              ↓              ↓           │
│  ┌────────────────────────────────────────────────────────┐     │
│  │          Embedding Model (sentence-transformers)       │     │
│  └────────────────────────────────────────────────────────┘     │
└─────────────────────────────────────────────────────────────────┘
```

### Component Responsibilities

| Component | Responsibility | Typical Implementation |
|-----------|----------------|------------------------|
| **REST API** | HTTP endpoints for document lifecycle, queries | FastAPI/Flask with async handlers |
| **MCP Server** | Expose retrieve/ask tools + document management resources | Python MCP SDK with stdio transport |
| **PDF Parser** | Extract text, tables, formulas from PDFs with layout preservation | Marker, pypdf, or RAGFlow's DeepDoc |
| **LaTeX Parser** | Parse .tex files, preserve math notation | Custom parser or plasTeX |
| **Notebook Parser** | Extract code cells, markdown, outputs from .ipynb | nbformat library |
| **Chunker** | Split documents into semantic units while preserving structure | Formula-aware, table-aware, section-aware splitter |
| **Embedding Model** | Convert text chunks to dense vectors | sentence-transformers (all-MiniLM-L6-v2 or BGE models) |
| **Vector Store** | Index and similarity search over embeddings | ChromaDB, FAISS, or Qdrant |
| **Metadata DB** | Store document metadata, chunk mappings, citations | SQLite for local, PostgreSQL for production |
| **Retriever** | Execute semantic search, rank and filter chunks | Hybrid search (vector + keyword BM25) |
| **LLM Engine** | Local model serving for answer generation | vLLM (best performance) or Ollama (simplicity) |
| **LLM Synthesis** | Generate answers from retrieved chunks | Prompt engineering with RAG pattern |
| **Doc Manager** | Document CRUD operations, indexing status | Business logic layer |

## Recommended Project Structure

```
rag_server/
├── src/
│   ├── api/                     # API layer
│   │   ├── rest.py             # FastAPI REST endpoints
│   │   └── mcp_server.py       # MCP protocol server
│   ├── ingestion/              # Document ingestion pipeline
│   │   ├── parsers/
│   │   │   ├── pdf.py          # PDF parsing (Marker/RAGFlow)
│   │   │   ├── latex.py        # LaTeX parsing
│   │   │   └── notebook.py     # Jupyter notebook parsing
│   │   ├── chunkers/
│   │   │   ├── base.py         # Base chunker interface
│   │   │   ├── formula_aware.py  # Preserve math formulas
│   │   │   ├── table_aware.py    # Preserve table structure
│   │   │   └── section_aware.py  # Preserve document sections
│   │   └── pipeline.py         # Orchestrates parse → chunk → embed
│   ├── storage/                # Persistence layer
│   │   ├── vector_store.py     # Vector DB interface (ChromaDB/FAISS)
│   │   ├── metadata_db.py      # Document/chunk metadata (SQLite)
│   │   └── models.py           # Data models (Pydantic)
│   ├── retrieval/              # Query and retrieval
│   │   ├── retriever.py        # Semantic + keyword search
│   │   ├── reranker.py         # Optional reranking (cross-encoder)
│   │   └── citation.py         # Build citation metadata
│   ├── generation/             # LLM integration
│   │   ├── llm_engine.py       # vLLM/Ollama client
│   │   ├── prompts.py          # RAG prompt templates
│   │   └── synthesis.py        # Generate answers from chunks
│   ├── embeddings/             # Embedding models
│   │   └── encoder.py          # sentence-transformers wrapper
│   └── config.py               # Configuration management
├── tests/
│   ├── unit/                   # Unit tests per component
│   ├── integration/            # End-to-end pipeline tests
│   └── fixtures/               # Sample documents for testing
├── data/                       # Local data storage
│   ├── documents/              # Raw uploaded documents
│   ├── vector_db/              # Vector store files
│   └── metadata.db             # SQLite database
├── models/                     # Downloaded models
│   ├── embeddings/             # sentence-transformers models
│   └── llm/                    # Local LLM weights (if not using Ollama)
├── pyproject.toml              # Python dependencies
└── README.md                   # Setup and usage instructions
```

### Structure Rationale

- **src/ingestion/**: Encapsulates all document processing. Each parser handles format-specific logic. Chunkers are modular and composable.
- **src/storage/**: Clean separation between vector store (semantic search) and metadata DB (document lifecycle, chunk tracking).
- **src/retrieval/**: Isolated from ingestion. Can swap retrieval strategies without affecting document processing.
- **src/generation/**: LLM engine abstraction allows switching between vLLM/Ollama/llama.cpp without changing synthesis logic.
- **src/api/**: Both REST and MCP servers share underlying retrieval/generation components. Thin translation layer.

## Architectural Patterns

### Pattern 1: Dual-Mode Query Interface

**What:** Support both "retrieve" (return raw chunks) and "ask" (LLM-synthesized answer) modes

**When to use:** When consumers need different levels of control. Claude Code may want raw chunks to reason over, while CLI scripts want direct answers.

**Trade-offs:**
- PRO: Maximum flexibility, no forced abstraction
- PRO: Faster retrieve mode (no LLM call)
- CON: More complex API surface
- CON: Client needs to handle two different response formats

**Example:**
```python
# MCP Server Tools

@mcp_tool("retrieve")
async def retrieve_chunks(query: str, top_k: int = 5) -> list[Chunk]:
    """Return raw chunks with citations for manual reasoning."""
    chunks = await retriever.semantic_search(query, top_k)
    return [
        {
            "content": chunk.text,
            "metadata": {
                "source": chunk.document_title,
                "page": chunk.page_number,
                "section": chunk.section_header,
                "score": chunk.similarity_score
            }
        }
        for chunk in chunks
    ]

@mcp_tool("ask")
async def ask_question(query: str, top_k: int = 5) -> str:
    """Return LLM-synthesized answer with inline citations."""
    chunks = await retriever.semantic_search(query, top_k)
    answer = await llm_synthesis.generate_answer(
        query=query,
        context_chunks=chunks
    )
    return answer  # Format: "Answer text [1][2]...\n\nSources:\n[1] Doc A, p.5\n[2] Doc B, p.12"
```

### Pattern 2: Formula-Aware Chunking

**What:** Special handling during chunking to never split mathematical formulas or code blocks across chunk boundaries

**When to use:** Always for technical/scientific documents. Critical for preserving meaning.

**Trade-offs:**
- PRO: Preserves semantic units (formulas, equations, code blocks)
- PRO: Prevents garbage chunks like "where α = 0.05 and" (formula split mid-expression)
- CON: May produce uneven chunk sizes
- CON: Requires format-specific parsing (LaTeX math, markdown code fences)

**Example:**
```python
class FormulaAwareChunker:
    def __init__(self, max_chunk_size: int = 512):
        self.max_chunk_size = max_chunk_size

    def chunk(self, text: str) -> list[str]:
        chunks = []
        current_chunk = []
        current_size = 0

        for element in self._parse_elements(text):
            if element.type == "formula" or element.type == "code":
                # Never split atomic elements
                if current_size + len(element.text) > self.max_chunk_size:
                    # Flush current chunk, start new one
                    chunks.append("".join(current_chunk))
                    current_chunk = [element.text]
                    current_size = len(element.text)
                else:
                    current_chunk.append(element.text)
                    current_size += len(element.text)
            else:
                # Normal text can be split on sentence boundaries
                sentences = self._split_sentences(element.text)
                for sentence in sentences:
                    if current_size + len(sentence) > self.max_chunk_size:
                        chunks.append("".join(current_chunk))
                        current_chunk = [sentence]
                        current_size = len(sentence)
                    else:
                        current_chunk.append(sentence)
                        current_size += len(sentence)

        if current_chunk:
            chunks.append("".join(current_chunk))

        return chunks
```

### Pattern 3: Two-Stage Retrieval (Retrieve → Rerank)

**What:** First stage: fast semantic search returns top-N candidates (N=20-50). Second stage: reranker scores candidates with cross-encoder for better relevance.

**When to use:** When retrieval quality matters more than latency. Reranking significantly improves relevance for complex queries.

**Trade-offs:**
- PRO: Much better relevance than single-stage retrieval
- PRO: Cross-encoder sees query + chunk together (not just embeddings)
- CON: Adds latency (reranker inference on 20-50 chunks)
- CON: Requires second model (cross-encoder like ms-marco-MiniLM)

**Example:**
```python
async def retrieve_with_reranking(
    query: str,
    top_k: int = 5,
    retrieval_k: int = 20
) -> list[Chunk]:
    # Stage 1: Fast semantic search
    candidates = await vector_store.similarity_search(
        query_embedding=embedder.encode(query),
        top_k=retrieval_k
    )

    # Stage 2: Rerank with cross-encoder
    reranked = reranker.rerank(
        query=query,
        documents=[c.text for c in candidates]
    )

    # Return top-k after reranking
    return [candidates[idx] for idx in reranked.top_k_indices(top_k)]
```

### Pattern 4: MCP Server as Thin Wrapper

**What:** MCP server layer is a protocol translation shim over core RAG logic. All business logic lives in retrieval/generation modules.

**When to use:** Always. MCP is a transport protocol, not where domain logic belongs.

**Trade-offs:**
- PRO: Easy to add other interfaces (REST, CLI, gRPC) without duplicating logic
- PRO: MCP server can be regenerated/swapped without affecting core functionality
- CON: Extra layer of indirection

**Example:**
```python
# mcp_server.py - Thin translation layer
from mcp.server import Server
from src.retrieval.retriever import Retriever
from src.generation.synthesis import LLMSynthesis

server = Server("fellowquant-rag")
retriever = Retriever()
synthesis = LLMSynthesis()

@server.tool("retrieve")
async def retrieve_tool(query: str, top_k: int = 5):
    """MCP tool wrapping core retrieval logic."""
    chunks = await retriever.search(query, top_k)
    return [chunk.to_mcp_format() for chunk in chunks]

@server.tool("ask")
async def ask_tool(query: str, top_k: int = 5):
    """MCP tool wrapping core synthesis logic."""
    answer = await synthesis.answer_question(query, top_k)
    return answer

@server.resource("document://list")
async def list_documents():
    """MCP resource wrapping document manager."""
    docs = await doc_manager.list_all()
    return [doc.to_mcp_format() for doc in docs]
```

### Pattern 5: Hybrid Search (Vector + Keyword)

**What:** Combine dense vector search (semantic) with sparse keyword search (BM25). Fusion ranking produces final result set.

**When to use:** When queries include specific terminology, formulas, or named entities. Pure semantic search misses exact term matches.

**Trade-offs:**
- PRO: Catches both semantic similarity AND exact term matches
- PRO: Better for financial jargon, author names, specific formulas
- CON: More complex indexing (need both vector store and inverted index)
- CON: Fusion ranking adds complexity

**Example:**
```python
async def hybrid_search(query: str, top_k: int = 5) -> list[Chunk]:
    # Dense retrieval (semantic)
    vector_results = await vector_store.search(
        query_embedding=embedder.encode(query),
        top_k=top_k * 2  # Get more candidates for fusion
    )

    # Sparse retrieval (keyword BM25)
    bm25_results = await keyword_index.search(
        query=query,
        top_k=top_k * 2
    )

    # Reciprocal Rank Fusion
    fused = reciprocal_rank_fusion(
        results_list=[vector_results, bm25_results],
        k=60  # RRF parameter
    )

    return fused[:top_k]

def reciprocal_rank_fusion(results_list: list[list[Chunk]], k: int = 60) -> list[Chunk]:
    """Combine multiple result lists using RRF algorithm."""
    scores = defaultdict(float)

    for results in results_list:
        for rank, chunk in enumerate(results, start=1):
            scores[chunk.id] += 1.0 / (k + rank)

    # Sort by fused score
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    chunk_map = {c.id: c for results in results_list for c in results}

    return [chunk_map[chunk_id] for chunk_id, score in ranked]
```

## Data Flow

### Ingestion Flow

```
[Document Upload]
    ↓
[Format Detection] → (PDF | LaTeX | Notebook)
    ↓
[Parser Selection] → Format-specific parser
    ↓
[Text Extraction] → Preserve structure (tables, formulas, code)
    ↓
[Smart Chunking] → Formula-aware, table-aware splitting
    ↓ (parallel)
┌───┴────────────────────┐
│                        │
[Embedding]          [Metadata Extraction]
    ↓                    ↓
[Vector Store]      [Metadata DB]
    ↓                    ↓
    └────────┬───────────┘
             ↓
    [Indexing Complete]
```

### Retrieve Mode Flow

```
[MCP retrieve Tool Call] or [REST /query endpoint]
    ↓
[Query Embedding]
    ↓
[Hybrid Search] → Vector Search + BM25
    ↓
[Optional Reranking] → Cross-encoder scoring
    ↓
[Citation Building] → Map chunks to source docs, pages
    ↓
[Return Raw Chunks] → JSON with content + metadata
```

### Ask Mode Flow

```
[MCP ask Tool Call] or [REST /ask endpoint]
    ↓
[Query Embedding]
    ↓
[Hybrid Search] → Vector Search + BM25
    ↓
[Optional Reranking] → Cross-encoder scoring
    ↓
[LLM Prompt Construction] → Query + retrieved chunks
    ↓
[LLM Engine Call] → vLLM or Ollama inference
    ↓
[Answer Post-Processing] → Add inline citations
    ↓
[Return Synthesized Answer] → Text with source references
```

### Key Data Flows

1. **Document to embeddings:** Raw document → Parser → Chunks → Embedding model → Vector store
2. **Query to chunks:** Query text → Embedding → Vector/BM25 search → Rerank → Filtered chunks
3. **Chunks to answer:** Retrieved chunks + Query → LLM prompt → LLM inference → Cited answer
4. **MCP integration:** MCP tool call → REST-like handler → Core logic → MCP response format

## Build Order Implications

**Dependencies guide phasing:**

1. **Foundation (Phase 1):** Storage layer must exist before ingestion or retrieval
   - Vector store interface
   - Metadata database schema
   - Document/chunk data models

2. **Ingestion Pipeline (Phase 2):** Must be able to store before you can ingest
   - Depends on: Storage layer
   - PDF parser (start with simplest: pypdf or Marker)
   - Basic chunker (fixed-size, then enhance)
   - Embedding model integration

3. **Retrieval (Phase 3):** Needs indexed documents to search
   - Depends on: Storage + Ingestion
   - Semantic search
   - Citation building
   - Optional: Reranking, hybrid search

4. **LLM Integration (Phase 4):** Needs retrieval to provide context
   - Depends on: Retrieval
   - vLLM or Ollama client
   - Prompt templates
   - Answer synthesis

5. **REST API (Phase 5):** Exposes functionality via HTTP
   - Depends on: All core logic
   - FastAPI app
   - Endpoints for ingest, query, document management

6. **MCP Server (Phase 6):** Protocol wrapper over existing logic
   - Depends on: REST API logic (can share handlers)
   - MCP SDK integration
   - Tool definitions (retrieve, ask)
   - Resource definitions (document list, status)

7. **Advanced Parsers (Phase 7+):** Enhance what's already working
   - Depends on: Basic ingestion pipeline
   - LaTeX parser
   - Notebook parser
   - Formula-aware chunker
   - Table-aware chunker

**Critical path:** Storage → Ingestion → Retrieval → LLM → API → MCP

## Where MCP Server Sits

The MCP server is the **northernmost layer** — it's a thin protocol adapter that translates MCP tool/resource calls into internal API methods.

```
                    ┌─────────────┐
   MCP Client  ─────┤  MCP Server ├──── stdio/SSE transport
  (Claude Code)     └──────┬──────┘
                           │ (calls internal methods)
                    ┌──────┴──────┐
                    │  REST API   │ (shares logic)
                    └──────┬──────┘
                           │
            ┌──────────────┼──────────────┐
            │              │              │
     ┌──────┴─────┐ ┌─────┴──────┐ ┌────┴──────┐
     │ Retriever  │ │ Synthesis  │ │ Doc Mgr   │
     └────────────┘ └────────────┘ └───────────┘
```

**Key principles:**

1. **MCP server has no business logic** — it delegates to retrieval/generation/doc_manager
2. **REST API and MCP server are siblings** — they share the same underlying service layer
3. **MCP tools map to operations, not components:**
   - `retrieve` tool → calls `retriever.search()` + `citation_builder.format()`
   - `ask` tool → calls `synthesis.answer_question()`
   - Document resources → call `doc_manager.list()`, `doc_manager.get_status()`
4. **Transport is pluggable** — MCP uses stdio/SSE, but core logic is transport-agnostic

## Anti-Patterns to Avoid

### Anti-Pattern 1: Naive Fixed-Size Chunking

**What people do:** Split documents every N characters or N tokens without regard for structure

**Why it's wrong:** Destroys semantic units. Formulas split mid-expression. Tables cut in half. Code blocks chopped up. Retrieval quality tanks because chunks are meaningless fragments.

**Do this instead:** Use format-aware chunking. Detect formulas, tables, code blocks, and treat as atomic units. Split on section boundaries or paragraph breaks, not arbitrary character counts.

### Anti-Pattern 2: Embedding-Only Retrieval for Technical Documents

**What people do:** Rely purely on dense vector search without keyword matching

**Why it's wrong:** Financial documents use specific terminology, formulas, and named entities. Query "VWAP calculation" should match exact term, not just semantic neighbors. Pure embeddings miss exact matches.

**Do this instead:** Use hybrid search (vector + BM25). Fusion ranking combines semantic similarity with exact term matching. Catches both "what's similar" and "what contains this exact formula/term."

### Anti-Pattern 3: Synchronous Blocking Ingestion

**What people do:** Ingest documents in the request-response cycle. User uploads PDF, server blocks while parsing/embedding/indexing, returns success only after completion.

**Why it's wrong:** Large PDFs can take minutes to process (parsing, chunking, embedding). HTTP request times out. User has no visibility into progress. Server can't handle concurrent uploads.

**Do this instead:** Async ingestion with status tracking. Upload returns immediately with job ID. Background worker processes document. Status endpoint polls for completion. MCP resource exposes indexing progress.

### Anti-Pattern 4: Storing Embeddings in Metadata DB

**What people do:** Store high-dimensional vectors (384-1024 dims) as JSON/BLOB in SQLite or PostgreSQL

**Why it's wrong:** No efficient similarity search. Must load all vectors into memory and brute-force compute distances. Doesn't scale beyond a few thousand chunks. PostgreSQL pgvector helps but still not as optimized as dedicated vector stores.

**Do this instead:** Use a vector database (ChromaDB, FAISS, Qdrant). Optimized for high-dimensional similarity search with HNSW/IVF indexing. Keep metadata (doc_id, page, section) in relational DB. Vector DB references metadata DB by chunk_id.

### Anti-Pattern 5: LLM in the Retrieval Loop

**What people do:** Use LLM to generate better queries, rewrite user questions, or filter chunks during retrieval

**Why it's wrong:** Massive latency increase (LLM call before retrieval). Doesn't significantly improve retrieval quality in most cases. LLM is expensive (compute) for what's essentially a search task.

**Do this instead:** Do retrieval first (fast), then use LLM only for synthesis. If retrieval quality is poor, fix it with better embeddings, hybrid search, or reranking — not by adding LLM calls.

### Anti-Pattern 6: Monolithic MCP Server with Business Logic

**What people do:** Implement all retrieval logic, LLM calls, and document management inside MCP server tool handlers

**Why it's wrong:** Tightly couples business logic to MCP protocol. Can't expose same functionality via REST, CLI, or other interfaces. Hard to test (need to mock MCP runtime). Protocol changes break everything.

**Do this instead:** MCP server is a thin wrapper. Extract all logic into service classes (Retriever, Synthesis, DocManager). MCP tools call these services. REST API calls same services. Logic is protocol-agnostic.

## Scaling Considerations

| Scale | Architecture Adjustments |
|-------|--------------------------|
| 10-100 docs | Monolith with SQLite + FAISS/ChromaDB in-memory. Single process. No background workers needed. Synchronous ingestion acceptable. |
| 100-1000 docs | Add background job queue for ingestion (e.g., Celery). Use persistent vector store (ChromaDB with disk persistence or Qdrant). Consider PostgreSQL for metadata if complex queries needed. |
| 1000-10000 docs | Distributed vector store (Qdrant cluster). Separate ingestion workers from query service. Add Redis for job queue and caching. Consider reranking to improve precision. |
| 10000+ docs | Shard vector store by document type or date. Add query result caching (Redis). Horizontal scaling of query workers. Consider approximate search (lower HNSW ef_search) for speed. Dedicated embedding service. |

### Scaling Priorities

1. **First bottleneck:** Ingestion time for large PDFs (parsing, OCR if needed, embedding)
   - Fix: Batch embedding (embed multiple chunks in one call), parallel processing, use faster parser (Marker is optimized)

2. **Second bottleneck:** Retrieval latency with large vector index (10K+ documents → 100K+ chunks)
   - Fix: Use HNSW indexing (sub-linear search), approximate search with tuned ef_search parameter, add query result caching

3. **Third bottleneck:** LLM inference time for synthesis
   - Fix: Use vLLM with GPU (much faster than Ollama), smaller models (7B vs 13B), batch inference if possible

## Integration Points

### External Services

| Service | Integration Pattern | Notes |
|---------|---------------------|-------|
| vLLM | HTTP API (OpenAI-compatible) | Start vLLM server separately, RAG server sends requests to localhost:8000. Supports batching, streaming. |
| Ollama | HTTP API | Similar to vLLM. Easier setup (model management built-in), slower inference. Use for development, vLLM for production. |
| Embedding models | Direct library import | sentence-transformers library loads models locally. First run downloads from HuggingFace. Cache in models/ directory. |
| Vector stores | Library-specific client | ChromaDB (HTTP or direct), FAISS (in-process), Qdrant (HTTP). Abstract behind VectorStore interface. |

### Internal Boundaries

| Boundary | Communication | Notes |
|----------|---------------|-------|
| API ↔ Retrieval | Direct function call | Same process, no network. Async/await for I/O operations. |
| API ↔ LLM Synthesis | Direct function call | Same process. Synthesis orchestrates retrieval + LLM engine. |
| Ingestion ↔ Storage | Direct function call (synchronous) or Job queue (async) | Synchronous for small docs, async with Celery/RQ for production. |
| MCP Server ↔ Internal Services | Direct function call | MCP server imports and calls Retriever, Synthesis, DocManager. Pure delegation. |
| Retrieval ↔ Vector Store | Library client | ChromaDB/FAISS client. Abstract to allow swapping stores. |
| Retrieval ↔ Metadata DB | ORM or SQL | SQLAlchemy ORM for clean data access. |

## Sources

**Note:** This architecture research is based on established RAG system patterns from training data (up to January 2025). Unable to verify against current 2026 sources due to tool restrictions (WebSearch and WebFetch denied).

**Confidence levels:**
- **HIGH:** Standard RAG architecture patterns (ingestion → chunking → embedding → vector store → retrieval → LLM synthesis)
- **MEDIUM:** Specific tool choices (vLLM, ChromaDB, sentence-transformers, FastAPI) — widely used in 2024-2025 but may have alternatives in 2026
- **MEDIUM:** MCP integration patterns — protocol is relatively new (late 2024), best practices may have evolved
- **LOW:** Specific library versions and APIs — need verification against current documentation

**Recommended validation:**
- Verify vLLM vs Ollama vs llama.cpp performance characteristics for 2026
- Check MCP SDK current best practices (MCP protocol may have evolved)
- Validate ChromaDB vs Qdrant vs Weaviate for 100+ document corpus
- Confirm sentence-transformers latest recommended models (BGE, E5, etc.)

---
*Architecture research for: Financial Document RAG Server*
*Researched: 2026-02-12*
*Limited by: No access to WebSearch/WebFetch for 2026 verification*
