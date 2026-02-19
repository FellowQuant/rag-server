# Architecture Patterns

**Domain:** Financial Document RAG Server
**Researched:** 2026-02-18 (updated with SOTA verification)
**Confidence:** HIGH for established patterns; MEDIUM for newer patterns (visual RAG, GraphRAG)

---

## Recommended Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     CLIENT LAYER                             │
│         REST API (FastAPI)    MCP Server (stdio)             │
└───────────────────────┬─────────────────┬────────────────────┘
                        │                 │
┌───────────────────────▼─────────────────▼────────────────────┐
│                   ORCHESTRATION LAYER                         │
│   QueryOrchestrator   DocumentManager   JobQueue (async)      │
└───────────────────┬───────────────┬───────────────────────────┘
                    │               │
        ┌───────────▼──┐     ┌──────▼────────────────────────┐
        │  RETRIEVAL   │     │       INGESTION PIPELINE       │
        │              │     │                                │
        │ ┌──────────┐ │     │ Parser Router                  │
        │ │ BM25     │ │     │  ├─ Docling  (PDF)             │
        │ │ (sparse) │ │     │  ├─ Marker   (PDF fast path)   │
        │ ├──────────┤ │     │  ├─ nbformat (.ipynb)          │
        │ │ Dense    │ │     │  └─ LaTeX parser (.tex)        │
        │ │ Embed    │ │     │                                │
        │ ├──────────┤ │     │ Content-Aware Chunker          │
        │ │ Reranker │ │     │  ├─ Formula chunker (atomic)   │
        │ │ (cross-  │ │     │  ├─ Table chunker (preserve)   │
        │ │  encoder)│ │     │  ├─ Code block chunker         │
        │ └──────────┘ │     │  └─ Text semantic chunker      │
        │              │     │                                │
        │ RRF Fusion   │     │ Embedding model (BGE-M3)       │
        └──────┬───────┘     └───────────────────────────────┘
               │                         │
┌──────────────▼─────────────────────────▼────────────────────┐
│                    STORAGE LAYER                              │
│   Qdrant (vectors + multi-vector)    SQLite (metadata)        │
│   ├─ dense vectors (1024d)           ├─ documents table       │
│   ├─ sparse vectors (BM25 weights)   ├─ chunks table          │
│   └─ colbert multi-vector (optional) └─ jobs table            │
└──────────────────────────────────────────────────────────────┘
               │
┌──────────────▼──────────────┐
│        LLM LAYER            │
│   Ollama / vLLM (local)     │
│   ├─ answer synthesis       │
│   └─ citation injection     │
└─────────────────────────────┘
```

### Component Boundaries

| Component | Responsibility | Communicates With |
|-----------|---------------|-------------------|
| REST API | HTTP request handling, validation, routing | QueryOrchestrator, DocumentManager |
| MCP Server | MCP protocol translation, stdio transport | QueryOrchestrator, DocumentManager (same service) |
| QueryOrchestrator | Retrieval pipeline orchestration, RRF fusion, reranking | Retrieval components, LLM Layer |
| DocumentManager | Document CRUD, job queue management, status tracking | Ingestion Pipeline, SQLite |
| Parser Router | Format detection, parser dispatch | Docling, Marker, nbformat, LaTeX parser |
| Content-Aware Chunker | Structure-preserving segmentation | Parser output, Embedding model |
| Embedding model | Dense + sparse vector production | Qdrant |
| Retrieval (BM25) | Sparse keyword matching | SQLite (chunk text) or Qdrant sparse |
| Retrieval (Dense) | Semantic similarity search | Qdrant |
| Reranker | Cross-encoder precision scoring of top-N candidates | QueryOrchestrator |
| Qdrant | Vector persistence, similarity search, multi-vector | Embedding model, Retrieval |
| SQLite | Document metadata, chunk metadata, job tracking | DocumentManager, Retrieval (citations) |
| LLM Layer | Answer synthesis with citations | QueryOrchestrator |

### Data Flow

**Ingestion path:**
```
File upload
→ Parser Router (detect format)
→ Format-specific Parser (Docling/Marker/nbformat/LaTeX)
→ Structured document: typed blocks {text, formula, table, code, caption}
→ Content-Aware Chunker (atomic unit boundaries, formula context enrichment)
→ Each chunk: {text, chunk_type, doc_id, page, section, position}
→ Embedding model (BGE-M3) → {dense_vec, sparse_vec}
→ Qdrant (vectors) + SQLite (metadata) written atomically
→ Job status: indexed
```

**Retrieval path (hybrid):**
```
Query text
→ BM25 retrieval (top-50 sparse candidates)
→ Dense embedding retrieval (top-50 semantic candidates)
→ RRF fusion → merged top-20 candidates
→ Reranker cross-encoder → top-5 precise results
→ Citation builder (chunk_id → SQLite → doc_id, page, section)
→ Return: [chunks + citations]
```

**Ask path:**
```
Query text
→ [Retrieval path above → top-5 chunks]
→ Prompt builder: query + chunks + citation markers
→ LLM (Ollama/vLLM) → answer with inline citations
→ Return: {answer, citations: [{doc, page, section}]}
```

---

## Patterns to Follow

### Pattern 1: Content-Aware Atomic Chunking

**What:** Parse document into typed content blocks first, then chunk respecting block boundaries. Never split mid-formula or mid-table.

**When:** Always — for all document types in this system.

**Why it matters:** Fixed-size text chunking (512 tokens) destroys LaTeX formulas and table rows. A formula `E[R_p] = \sum_{i} w_i \mu_i` split at 256 tokens produces garbage that cannot be retrieved or displayed.

**Implementation approach:**
```python
# Docling output → typed blocks
class ContentBlock:
    type: Literal["text", "formula", "table", "code", "caption"]
    content: str          # raw text or LaTeX
    page: int
    section: str
    bbox: tuple[float, float, float, float]  # bounding box

# Chunking rules by type
ATOMIC_TYPES = {"formula", "table", "code"}  # never split these
TEXT_SPLIT_SIZE = 512   # tokens
FORMULA_MAX_SIZE = 2048  # allow larger chunks for complex formulas

def chunk(blocks: list[ContentBlock]) -> list[Chunk]:
    chunks = []
    current_text_chunk = []
    for block in blocks:
        if block.type in ATOMIC_TYPES:
            # Flush current text chunk first
            if current_text_chunk:
                chunks.append(merge_text_blocks(current_text_chunk))
                current_text_chunk = []
            # Atomic block becomes its own chunk
            chunks.append(Chunk(content=block.content, type=block.type, ...))
        else:
            current_text_chunk.append(block)
            if token_count(current_text_chunk) > TEXT_SPLIT_SIZE:
                chunks.append(merge_text_blocks(current_text_chunk))
                current_text_chunk = []
    return chunks
```

### Pattern 2: Three-Mode Hybrid Retrieval with BGE-M3

**What:** Use BGE-M3's single model to produce dense, sparse, and optionally multi-vector embeddings. Fuse results via Reciprocal Rank Fusion.

**When:** For all queries in production. This is the recommended default retrieval strategy.

**Why:** IBM research (2025) confirmed three-way hybrid retrieval (dense + sparse + BM25) consistently outperforms two-way or single-mode retrieval. For finance docs with specific jargon (Sharpe ratio, alpha, Black-Scholes), BM25 catches exact term matches that dense search misses.

**RRF fusion formula:**
```python
def reciprocal_rank_fusion(
    ranked_lists: list[list[str]],  # doc_ids in rank order per retrieval mode
    k: int = 60
) -> list[str]:
    scores: dict[str, float] = defaultdict(float)
    for ranked_list in ranked_lists:
        for rank, doc_id in enumerate(ranked_list):
            scores[doc_id] += 1.0 / (k + rank + 1)
    return sorted(scores, key=scores.get, reverse=True)

# Alpha tuning guidance for financial documents:
# - Queries with specific tickers/formulas/authors: favor BM25 (alpha=0.3)
# - Natural language conceptual queries: favor dense (alpha=0.7)
# - Default mixed: alpha=0.5
```

### Pattern 3: Two-Stage Retrieval with Cross-Encoder Reranking

**What:** Retrieve broad candidate set (top-20 to 50) cheaply via vector search, then rerank with expensive cross-encoder for top-5 to 10 results.

**When:** Always for the `ask` endpoint; optionally for `retrieve` endpoint.

**Why:** Cross-encoders (Qwen3-Reranker, jina-reranker-v3) jointly encode query+document in one forward pass — capturing fine-grained relevance impossible with bi-encoder embeddings. BEIR benchmarks show 10-20% precision improvement over bi-encoder-only retrieval.

**Latency model:**
```
Stage 1 (vector): ~10-30ms for top-50 candidates
Stage 2 (reranker): ~100-300ms for 50 candidates
Total: ~200-400ms -- acceptable for RAG
```

### Pattern 4: Formula Context Enrichment

**What:** Append natural language description to formula chunks during indexing so semantic search can find formulas via conceptual queries.

**When:** During chunking of formula blocks.

**Why:** General-purpose embedding models do not understand LaTeX syntax. Query "Black-Scholes formula" will not semantically match a chunk containing only `C = S_0 N(d_1) - K e^{-rT} N(d_2)`. Enriching the chunk bridges the gap. Research on formula retrieval (SSEmb 2025) confirms combined structural+semantic approaches outperform either alone by >5 percentage points on ARQMath-3.

**Implementation:**
```python
def enrich_formula_chunk(chunk: Chunk, surrounding_text: str) -> Chunk:
    # Prepend surrounding text context (section title + paragraph before formula)
    chunk.embedding_text = f"{surrounding_text}\n\nFormula: {chunk.content}"
    # Store original LaTeX separately for display
    chunk.display_content = chunk.content
    return chunk
```

### Pattern 5: Metadata Propagation Chain

**What:** Every chunk carries its full provenance chain from parse-time through to vector storage.

**When:** Always — design this from Phase 1, not as an afterthought.

**Schema:**
```python
class ChunkMetadata(BaseModel):
    chunk_id: str           # UUID
    document_id: str        # FK to documents table
    page_number: int        # 1-indexed
    section_header: str     # nearest section title above chunk
    chunk_type: str         # "text" | "formula" | "table" | "code" | "caption"
    position_in_page: int   # chunk order within page
    char_start: int         # character offset in original document text
    char_end: int
    embedding_model: str    # which model produced this embedding
    indexed_at: datetime
```

### Pattern 6: Async Ingestion with Job Queue

**What:** Ingestion endpoint returns job_id immediately; client polls separate status endpoint. Processing happens in background worker.

**When:** All document ingestion — parsing + embedding can take 10-60 seconds per PDF.

**Why:** MCP tools must return quickly. A synchronous ingest_document call that blocks for 60 seconds makes Claude Code appear frozen with no way to cancel. Docling processes ~4 seconds per page — a 20-page paper takes 80 seconds synchronously.

**States:** `pending -> processing -> indexed | failed`

### Pattern 7: MCP as Thin Protocol Wrapper

**What:** MCP server delegates all business logic to core service classes. No RAG logic in the MCP layer.

**When:** Phase 6 implementation.

**Why:** Keeps core logic testable (unit tests via direct function calls without MCP), and makes it easy to add other interfaces (REST, CLI, gRPC) without duplicating logic.

---

## Anti-Patterns to Avoid

### Anti-Pattern 1: Fixed-Size Text Chunking
**What:** Splitting documents into fixed 512-token windows regardless of content structure.
**Why bad:** Splits formulas mid-expression, separates table headers from data, destroys code indentation. Retrieved chunks become semantically meaningless.
**Instead:** Content-aware atomic chunking (Pattern 1 above).

### Anti-Pattern 2: Single-Mode Retrieval for Math-Dense Documents
**What:** Vector-only or BM25-only retrieval.
**Why bad:** Dense vectors miss exact term matches for `\alpha`, `\beta`, specific function names. BM25 misses conceptual similarity ("momentum factor" vs "cross-sectional return persistence"). Finance documents need both.
**Instead:** Three-mode hybrid retrieval with RRF fusion (Pattern 2).

### Anti-Pattern 3: Synchronous Ingestion in MCP/API Layer
**What:** Blocking the HTTP/MCP connection during document parsing.
**Why bad:** 60-second parse jobs timeout HTTP connections, freeze MCP clients, provide no progress feedback. Docling is 4s/page, so a 20-page paper = 80 seconds.
**Instead:** Async job queue with status polling (Pattern 6).

### Anti-Pattern 4: Interleaving Embedding and LLM Inference
**What:** Running embedding generation and LLM inference simultaneously on the same GPU.
**Why bad:** Combined VRAM usage causes CUDA OOM errors. BGE-M3 (~1GB) + Ollama 7B Q4 (~5GB) = 6GB, which is fine — but add Docling formula model during ingestion and it exceeds 8GB.
**Instead:** Sequence operations. Ingestion (parsing + embedding) runs when no LLM inference is active. Use job queue to enforce ordering.

### Anti-Pattern 5: Embedding LaTeX Directly Without Context
**What:** Storing formula chunks that contain only raw LaTeX as the embedding text.
**Why bad:** Embedding models tokenize LaTeX as random subword tokens. `\frac{d}{dt}` produces meaningless embeddings. Cannot be retrieved via natural language queries.
**Instead:** Formula context enrichment — prepend surrounding text before embedding (Pattern 4). Store original LaTeX for display.

### Anti-Pattern 6: GraphRAG for v1
**What:** Building a knowledge graph (entities, relations, cross-references) as the primary retrieval structure.
**Why bad:** GraphRAG construction requires LLM passes over every document (expensive, slow). Recent studies (2025) show GraphRAG frequently underperforms vanilla RAG on factual extraction tasks (0.91 vs 0.44 on multi-document synthesis — the hard problem is not solved). For v1 with fewer than 500 documents, overhead is not justified. 6% reduction in hallucinations with GraphRAG (FinanceBench 2025) is real but insufficient to justify the complexity cost at v1 scale.
**Instead:** Use hybrid retrieval with reranking for v1. Evaluate GraphRAG only if multi-hop cross-document reasoning becomes the primary use case in v2.

---

## Indexing Strategy Decision Matrix

| Document Characteristic | Recommended Strategy | Rationale |
|--------------------------|---------------------|-----------|
| Math-heavy papers (LaTeX formulas) | Text extraction (Docling) + formula context enrichment + hybrid retrieval | Formula images -> LaTeX via Docling formula model; enrich with context for semantic search |
| Financial tables (correlation matrices) | Text extraction (Docling) with table-as-atomic chunking | Docling 97.9% table accuracy; preserve table structure as markdown table in chunk |
| Code blocks (Python) | Code-as-atomic chunking; annotate with language tag | Prevents code from mixing with surrounding text |
| Dual-column academic papers | Docling (DocLayNet layout model) | DocLayNet trained on academic paper layouts; handles reading order across columns |
| Jupyter notebooks | nbformat parser; cell-by-cell chunking | Each cell = one chunk (code cell, markdown cell, output cell handled separately) |
| LaTeX source files | pylatexenc tokenizer; extract \section, \equation, \begin{table} | Ground-truth formula extraction; more reliable than PDF rendering |
| Figure-heavy reports (charts, plots) | Text extraction + optional ColFlor for figure retrieval | ColFlor for visual retrieval of charts if text captions are insufficient |

---

## Scalability Considerations

| Concern | At 50 docs | At 500 docs | At 5,000 docs |
|---------|------------|-------------|---------------|
| Vector search latency | FAISS in-memory viable | Qdrant HNSW <20ms | Qdrant + quantization + sharding |
| Embedding throughput | Sequential OK | Batch embedding, 1 GPU | Multi-GPU or embedding server |
| BM25 index size | In-memory (rank-bm25) | In-memory still OK | Elasticsearch or Qdrant sparse |
| Reranker latency | Always fast enough | Always fast enough | Cache reranker results for repeated queries |
| LLM throughput | Ollama single request | Ollama + request queue | vLLM with batching |
| Storage | SQLite fine | SQLite fine | PostgreSQL if complex queries |

---

## Sources

- [ColPali paper ICLR 2025](https://arxiv.org/abs/2407.01449v6) — Visual retrieval architecture
- [ViDoRe v2 benchmark](https://arxiv.org/abs/2505.17166) — ColFlor, ColQwen2 comparisons
- [BGE-M3 HuggingFace](https://huggingface.co/BAAI/bge-m3) — Three-mode retrieval architecture
- [Hybrid retrieval RRF](https://infiniflow.org/blog/best-hybrid-search-solution) — Dense+sparse+full-text comparison
- [Late chunking paper](https://arxiv.org/abs/2409.04701) — Contextual chunking strategies
- [Contextual retrieval comparison](https://medium.com/kx-systems/late-chunking-vs-contextual-retrieval-the-math-behind-rags-context-problem-d5a26b9bbd38) — LLM-enriched chunk context
- [RAPTOR hierarchical indexing](https://arxiv.org/html/2401.18059v1) — Recursive tree-organized retrieval
- [RAG vs GraphRAG systematic evaluation](https://arxiv.org/html/2502.11371v2) — When GraphRAG helps (and when it doesn't)
- [GraphRAG for Finance (ACL 2025)](https://aclanthology.org/2025.genaik-1.6/) — 6% hallucination reduction on FinanceBench
- [Vision-guided chunking](https://arxiv.org/abs/2506.16035) — Multimodal document chunking
- [Qdrant multi-vector late interaction](https://qdrant.tech/documentation/tutorials-search-engineering/using-multivector-representations/) — MaxSim ColBERT support
- [OmniDocBench CVPR 2025](https://github.com/opendatalab/OmniDocBench) — Multi-column layout parsing benchmarks
- [SSEmb formula retrieval 2025](https://arxiv.org/abs/2508.04162) — Structural+semantic formula embedding
