# Indexing Strategies for Technical/Scientific Documents

**Domain:** Financial Document RAG Server
**Researched:** 2026-02-18
**Confidence:** HIGH for text-based strategies (well-established); MEDIUM for visual/hybrid strategies

---

## The Core Problem

Technical and quantitative finance documents contain content that defeats standard RAG indexing:

| Content Type | Problem | Standard RAG Failure |
|-------------|---------|---------------------|
| LaTeX formulas | OCR/extraction produces garbled tokens; semantic embeddings cannot bridge notation to language | Query "Sharpe ratio formula" does not retrieve `\frac{R_p - R_f}{\sigma_p}` |
| Financial tables (correlation matrices) | Column alignment destroyed; cells separated from headers | Linearized table row "0.87 0.23 -0.45" is uninterpretable |
| Dual-column academic layouts | Text extracted in reading order across columns | Left/right column words interleave into nonsense |
| Multi-page content | Chunk boundaries lose cross-page context | Multi-page derivation split; each half is meaningless |
| Jupyter notebooks | Code, prose, output mixed per cell; execution order matters | Code split from its output; markdown split from relevant code |

---

## Strategy 1: Text Extraction + Content-Aware Chunking (RECOMMENDED for v1)

**Approach:** Parse PDFs with a layout-aware parser (Docling), extract typed content blocks, then chunk respecting content type boundaries.

**Performance:** HIGH confidence for text-dense and formula-dense documents. Docling achieves 97.9% table extraction accuracy. DocLayNet layout model handles dual-column academic papers correctly.

**Cost:** Docling at ~4s/page is the processing bottleneck. Acceptable for background ingestion. Fast-path option: Marker at ~0.12s/page for text-heavy PDFs without complex formulas.

**Best for:** All document types in v1 corpus — quant papers, strategy research, LaTeX source, notebooks.

### Docling-Specific Capabilities (2025)

Docling (IBM, 2025) is the recommended primary parser because:
- **Code Formula Model**: Vision-language model (258M params, Granite-Docling) converts formula images to LaTeX. This is the key differentiator over Marker for formula-heavy documents.
- **DocLayNet**: Layout detection model trained on academic papers and financial documents. Correctly handles dual-column reading order.
- **TableFormer**: Dedicated table structure model. Handles merged cells, multi-row headers, and complex grid layouts.
- **Output format**: Structured JSON/markdown with typed blocks (text, formula, code, table, caption, figure) — directly usable for content-aware chunking.

### Chunking Strategy for This Corpus

```
1. Atomic units (never split):
   - Formula blocks → one chunk per formula
   - Table blocks → one chunk per table (regardless of size)
   - Code blocks → one chunk per code block

2. Text blocks → split on semantic boundaries:
   - Prefer paragraph boundaries over token count
   - Target: 256-512 tokens per text chunk
   - With 64-token overlap between adjacent text chunks (for context continuity)

3. Formula context enrichment:
   - Attach preceding paragraph text to formula chunk's embedding_text
   - Store original LaTeX separately in display_content
   - This bridges natural language queries to formula content

4. Caption-to-figure/table linking:
   - Attach figure/table caption to the parent block's chunk
   - Enables retrieval via "what does Figure 3 show?"
```

---

## Strategy 2: Hybrid Retrieval (BM25 + Dense + Sparse) (RECOMMENDED)

**Approach:** BGE-M3 produces dense vectors (semantic similarity) + sparse vectors (BM25-like term weights) simultaneously. Combine with traditional BM25 on raw chunk text. Fuse via Reciprocal Rank Fusion.

**Performance:** IBM research (2025) confirms three-way hybrid (dense + sparse + full-text BM25) outperforms two-way hybrid consistently. FinMTEB (2025) shows BM25 surprisingly outperforms dense embeddings on financial STS tasks — strongly validating hybrid for finance content.

**Cost:** BGE-M3 inference adds minimal overhead (same model, three outputs). BM25 index adds ~50MB RAM for 500 documents. RRF fusion is O(n log n) on candidate lists.

**Best for:** Finance documents with specific terminology (alpha, beta, Fama-French, VWAP), paper titles, author names, exact formula names.

### BGE-M3 Three-Mode Output

BGE-M3 is the only open-source model that produces all three from a single inference pass:

1. **Dense embedding (1024d):** Standard semantic similarity via cosine distance
2. **Sparse embedding (vocabulary-sized sparse vector):** Learned term weights similar to BM25 but trainable
3. **Multi-vector (ColBERT-style):** Token-level embeddings for MaxSim late interaction

For v1, use dense + sparse. The multi-vector mode requires storing 128d vectors per token per chunk (significant storage overhead at scale). Enable in v2 if precision requirements demand it.

### RRF Fusion Alpha Tuning

```
Financial document queries break into two types:
- Exact term: "Fama-French three-factor model" → favor sparse/BM25 (alpha=0.3)
- Conceptual: "momentum premium in equities" → favor dense (alpha=0.7)
- Default mixed: alpha=0.5

Set alpha adaptively based on query characteristics:
- Query contains LaTeX symbols → alpha=0.3
- Query contains quoted phrases → alpha=0.2
- Otherwise → alpha=0.5
```

---

## Strategy 3: Late Chunking (Contextual Embeddings)

**What:** Instead of splitting document into chunks and embedding each independently, embed the entire document (or long sections), then split the contextualized token embeddings into per-chunk mean-pooled vectors. Each chunk's embedding retains full-document context.

**Performance:** Improves recall by 10-12% on documents with anaphoric references ("the formula above", "as described in Section 3"). The LangChain 2024 blog and academic evaluations confirm improvement on context-dependent references. For finance: "this result implies" followed by a formula benefits strongly from late chunking.

**Cost:** Requires the document or section to fit in the model's context window. BGE-M3 context window: 8192 tokens (~6,000 words). Long papers exceed this. Solution: apply late chunking per section (split at section boundaries first), not per full document.

**Recommendation:** Late chunking is worth implementing as a chunking option for medium-length sections (1,000-4,000 tokens). Not a replacement for content-aware chunking — combine them: late-chunk text segments, atomic-chunk formulas/tables.

**Implementation note:** Requires models supporting long-context input — BGE-M3 supports 8192 tokens. jina-embeddings-v2-base-en supports 8192 tokens. Standard 512-token models cannot use late chunking.

---

## Strategy 4: Contextual Retrieval (Anthropic-style)

**What:** Use an LLM to generate a 2-3 sentence context summary for each chunk, describing where it appears in the document and what the surrounding discussion is about. Prepend this context to the chunk text before embedding.

**Performance:** Anthropic reports 49% reduction in retrieval failures in their September 2024 blog post. More expensive but particularly effective for cross-page content dependencies.

**Cost:** Requires an LLM call per chunk during ingestion. For a 500-document corpus with 30 chunks/document = 15,000 LLM calls. At Ollama 7B speeds (~2 seconds each) = 8.3 hours of ingestion time. This is a significant cost multiplier.

**Recommendation for v1:** Do NOT implement contextual retrieval for v1. The LLM call overhead makes batch ingestion prohibitively slow. The formula context enrichment (Pattern 4 in ARCHITECTURE.md) achieves a similar effect for the most important content type (formulas) without LLM overhead.

**Recommendation for v2:** Contextual retrieval is worth evaluating for very long documents (50+ page papers) where cross-page dependency is high. Gate it behind a flag — opt-in for specific document types.

---

## Strategy 5: Hierarchical / RAPTOR Indexing

**What:** Build a recursive tree of chunk summaries. At the leaf level: individual chunks. At higher levels: LLM-generated summaries of clusters of chunks. Query can retrieve at any tree level.

**Performance:** RAPTOR (Stanford, 2024) shows 10-20% improvement on long-document QA tasks requiring global understanding. Financial example: "What is the paper's main conclusion about momentum?" benefits from a high-level summary chunk rather than individual result chunks.

**Cost:** Very high. Requires LLM calls for summary generation at each tree level. Building the tree for 500 documents could take hours. Storage overhead is significant (2x-3x original chunk count).

**Recommendation:** Do NOT implement for v1. The main use case (retrieve specific formulas, tables, code) is better served by flat hybrid retrieval. RAPTOR's advantage is for global document understanding, which is a v2 use case (cross-document synthesis).

---

## Strategy 6: Parent-Child Chunk Indexing

**What:** Index small child chunks for precise retrieval, but when a child chunk is retrieved, return its parent chunk (larger context window) to the LLM for synthesis.

**Example:**
```
Parent: full section (1500 tokens)
  ├─ Child 1: paragraph 1 (300 tokens) [indexed for retrieval]
  ├─ Child 2: formula block (50 tokens) [indexed for retrieval]
  └─ Child 3: paragraph 2 (300 tokens) [indexed for retrieval]

Query "Sharpe ratio" → retrieves Child 2 (exact match)
LLM receives: Parent (full section with formula in context)
```

**Performance:** Better answer synthesis because the LLM sees the formula with surrounding explanation. Minimal retrieval quality impact.

**Cost:** Low overhead. 2x storage (store both parent and child). Minimal index size increase.

**Recommendation:** Implement in Phase 3 or 5. Particularly valuable for formula chunks — a formula in isolation is not enough; the LLM needs the surrounding text to explain it. The parent chunk provides this context automatically.

---

## Strategy 7: GraphRAG / Knowledge Graph Indexing

**What:** Extract entities (models, factors, authors, papers) and relations (A cites B, Model X uses Factor Y) from documents. Store as a knowledge graph. Retrieve via graph traversal.

**Performance:** GraphRAG (Microsoft, 2024) shows 6% hallucination reduction on FinanceBench (ACL 2025). Strong advantage for multi-hop queries: "What do papers by Fama and French say about momentum?" requires connecting multiple paper nodes.

**Cost:** Very high. Entity extraction requires LLM calls per document. Graph database (Neo4j or similar) adds infrastructure. Graph traversal adds query latency. Building graph for 500 documents = hundreds of LLM calls.

**Critical finding (2025):** Multiple studies report GraphRAG frequently underperforms vanilla RAG on factual extraction tasks. GraphRAG's advantage is specifically for multi-hop relational queries. For point-fact retrieval ("what is the Sharpe ratio formula in this paper?"), hybrid vector+BM25 retrieval outperforms GraphRAG.

**Recommendation:** Do NOT implement for v1. The corpus is small enough that hybrid retrieval handles most use cases well. Evaluate in v2 only if cross-paper relational queries become the primary use case.

---

## Strategy 8: Visual Retrieval (ColPali-style, OCR-free)

**What:** Skip text extraction entirely. Convert document pages to images. Embed page images as multi-vector representations using a vision-language model (ColFlor, ColQwen2). Query with text; retrieve via MaxSim over page patch embeddings.

**Performance:** On ViDoRe (ICLR 2025), ColPali "beats complex pipelines that involve OCR, layout analysis, captioning with large VLMs, and text embedding models" on visually rich documents. Particularly strong advantage on financial tables and infographics where layout carries meaning.

**Cost:** Significant. Index stores ~1000 128d patch embeddings per page (vs 1x 1024d vector for text). For 500 documents x 20 pages = 10,000 pages x 1000 vectors = 10M vectors. Requires Qdrant's multi-vector storage.

**Recommendation:** v2 only. If text extraction proves insufficient for a specific document type (e.g., fund fact sheets with complex visual tables), add ColFlor as a visual track alongside the text track. ColFlor (174M params, 9.8x faster than ColPali) is the production-viable option.

---

## Recommended Approach for v1

**Primary strategy:** Text extraction + content-aware atomic chunking + three-mode hybrid retrieval

**Specific decisions:**
1. Parser: Docling primary (formula model, DocLayNet), Marker fast-path fallback
2. Chunking: Atomic (formula/table/code) + semantic paragraph (text)
3. Enrichment: Formula context enrichment only (no LLM contextual retrieval)
4. Embedding: BGE-M3 (three-mode: dense + sparse + colbert-optional)
5. Retrieval: BM25 + dense fusion via RRF
6. Reranking: Qwen3-Reranker-0.6B cross-encoder
7. Parent-child: Implement in Phase 5 alongside reranking

**Deferred to v2:**
- Late chunking (implement after validating v1 retrieval quality)
- Contextual retrieval (LLM call per chunk; too slow for batch ingestion)
- RAPTOR (LLM-heavy; overkill for <500 doc corpus)
- GraphRAG (unproven ROI; high construction cost)
- Visual retrieval (adopt only if text extraction proves insufficient)

---

## Formula Retrieval: Special Case Analysis

Formula retrieval is the hardest problem in this domain. Research summary:

| Approach | Quality | Cost | Recommendation |
|----------|---------|------|----------------|
| Pure LaTeX embedding | Poor | Low | Do not use alone |
| Context enrichment (surrounding text + LaTeX) | Good | Low | Primary mitigation (v1) |
| BM25 on formula name in surrounding text | Good for named formulas | Low | Part of hybrid retrieval |
| SSEmb (structural graph + semantic) | Best | High | v2 research direction |
| Visual embedding of formula images | Good | Medium | v2 with ColFlor |

**Primary mitigation for v1:** Formula context enrichment. Prepend the paragraph before the formula to the embedding text. Formula name (e.g., "Sharpe ratio") appears in the text; BM25 catches the exact term; dense embedding catches the concept.

**Fundamental limitation (LOW confidence):** Whether standard embedding models can bridge natural language queries to LaTeX symbols without domain-specific training is unknown for this specific corpus. The formula context enrichment is a heuristic mitigation. Measure recall@5 on a labeled set of formula queries during Phase 3 to quantify.

---

## Sources

- [Docling IBM GitHub](https://github.com/docling-project/docling) — Formula model, TableFormer, DocLayNet capabilities
- [Granite-Docling IBM](https://www.ibm.com/new/announcements/granite-docling-end-to-end-document-understanding) — 258M VLM for document conversion
- [OmniDocBench CVPR 2025](https://github.com/opendatalab/OmniDocBench) — Parser accuracy on academic and financial documents
- [PDF Data Extraction Benchmark 2025](https://procycons.com/en/blogs/pdf-data-extraction-benchmark/) — Docling 97.9% table accuracy
- [Late chunking paper](https://arxiv.org/abs/2409.04701) — Contextual chunk embeddings; 10-12% recall improvement
- [Chunking strategy evaluation 2025](https://arxiv.org/abs/2504.19754) — Comparative evaluation of advanced chunking
- [Vision-guided chunking](https://arxiv.org/abs/2506.16035) — Multimodal chunking for complex documents
- [Hybrid retrieval RRF](https://infiniflow.org/blog/best-hybrid-search-solution) — Dense+sparse+full-text beats two-way
- [BGE-M3 three-mode retrieval](https://huggingface.co/BAAI/bge-m3) — Architecture and capabilities
- [RAPTOR paper](https://arxiv.org/html/2401.18059v1) — Recursive tree-organized retrieval
- [RAG vs GraphRAG evaluation 2025](https://arxiv.org/html/2502.11371v2) — When graph structures help vs hurt
- [GraphRAG for finance (ACL 2025)](https://aclanthology.org/2025.genaik-1.6/) — 6% hallucination reduction on FinanceBench
- [ColPali ICLR 2025](https://arxiv.org/abs/2407.01449v6) — Visual retrieval on financial tables
- [SSEmb formula retrieval](https://arxiv.org/abs/2508.04162) — Graph-based structural + semantic formula embedding
- [FinMTEB benchmark](https://arxiv.org/abs/2502.10990) — BM25 vs dense on financial STS tasks
