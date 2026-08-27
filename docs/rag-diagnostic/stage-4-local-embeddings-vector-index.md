# Stage 4 — Local Embeddings and Vector Index

## Objective
Build a fully offline, locally-executable embedding and vector retrieval layer on top of the Stage 3 content-unit JSONL. The system must run on a developer laptop without a GPU, return relevant results in under two seconds per query, and support metadata-filtered hybrid retrieval that combines dense semantic search with sparse BM25 keyword matching.

---

## Assessment: Embedding and Retrieval Trade-offs for Local Operation

### Model selection assessment

| Model | Size | CPU latency (384 docs) | Dimensions | Notes |
|-------|------|----------------------|-----------|-------|
| `all-MiniLM-L6-v2` | 80 MB | ~3–6 s full index | 384 | Best CPU speed; solid general quality |
| `all-MiniLM-L12-v2` | 120 MB | ~8–12 s full index | 384 | Better quality, 2× slower |
| `nomic-embed-text-v1.5` | 270 MB | ~25–40 s full index | 768 | High quality; slow on CPU |
| `bge-small-en-v1.5` | 130 MB | ~7–10 s full index | 384 | Competitive quality with MiniLM-L12 |

**Decision**: Use `all-MiniLM-L6-v2` as the default model with ONNX runtime via `sentence-transformers` for maximum local throughput. Provide `bge-small-en-v1.5` as the quality-optimized alternative via config flag. Both are downloaded once and cached locally; no internet required after first run.

### Vector store assessment

| Store | Local | Metadata filters | Persistence | Python API |
|-------|-------|-----------------|-------------|-----------|
| ChromaDB | Yes | Built-in | SQLite-backed | Native |
| FAISS | Yes | External (numpy mask) | Flat file | Via faiss-cpu |
| Qdrant (local) | Yes (Docker) | Built-in | Docker volume | REST/gRPC |
| Weaviate (local) | Yes (Docker) | Built-in | Docker volume | REST/gRPC |

**Decision**: Use **ChromaDB** in local persistent mode (no Docker required) for developer iteration. It supports metadata filtering natively, stores embeddings in SQLite+parquet, and has a pure Python client. For production deployment, the same interface can be pointed at a Qdrant container without changing retrieval logic.

### Hybrid retrieval assessment

Pure semantic search on a technical manual corpus systematically misses exact part numbers, task IDs, and acronyms (e.g., `PMCS`, `PCB`, `4L80-E`). BM25 excels on these but lacks semantic generalization. Hybrid retrieval via Reciprocal Rank Fusion (RRF) combines both signals with no additional model weight:

```
RRF_score(doc) = Σ  1 / (k + rank_i(doc))
                 i
```

where `k=60` (standard) and `rank_i` is the rank from semantic and BM25 results respectively.

RRF is chosen over a learned cross-encoder reranker to avoid an additional model download and inference cost at query time. A cross-encoder optional path is provided for offline quality evaluation.

---

## Architecture

```
content-units.jsonl
       │
       ▼
┌──────────────────────┐
│  1. Index Builder    │  — Loads content units, generates embeddings,
│                      │    builds ChromaDB collection + BM25 index.
└────────┬─────────────┘
         │  (persisted to disk)
         ▼
┌──────────────────────┐
│  2. Hybrid Retriever │  — At query time:
│     (semantic + BM25)│    a) embed query with same model
│                      │    b) semantic top-N from ChromaDB
│                      │    c) BM25 top-N from rank_bm25
│                      │    d) RRF merge → top-K
└────────┬─────────────┘
         │
         ▼
┌──────────────────────┐
│  3. Metadata Filter  │  — Apply pre-filter by manual_id, subsystem,
│                      │    safety_flag, manual_role before RRF.
└────────┬─────────────┘
         │
         ▼
┌──────────────────────┐
│  4. Optional Reranker│  — Cross-encoder pass on top-K candidates
│     (offline eval)   │    to produce a quality-reference ranking.
└──────────────────────┘
```

---

## Module Breakdown

### `vector_index/embedder.py`
- `Embedder` class wrapping `SentenceTransformer`.
- `__init__(model_name, cache_dir, device)` — loads model once; defaults to CPU.
- `embed(texts: list[str]) -> np.ndarray` — batched embedding with configurable batch size (default 64).
- `embed_query(text: str) -> np.ndarray` — single-query embedding with instruction prefix for `bge` models.
- **Text selection for embedding**: concatenates `title + " " + text_plain[:1024]` per unit. Truncation at 1024 chars avoids exceeding model context and keeps throughput high.
- Caches model locally at `~/.cache/hmmwv-rag/models/` on first download.

### `vector_index/index_builder.py`
- `build_index(content_units_path, chroma_persist_dir, bm25_index_path, embedder)`:
  1. Streams units from JSONL; skips units already in the collection (incremental mode).
  2. Embeds texts in batches; reports progress with estimated time remaining.
  3. Upserts to ChromaDB collection `hmmwv_units` with metadata dict per unit (see Metadata Schema below).
  4. Builds `BM25Okapi` corpus from tokenized `text_plain` values; pickles to `bm25_index_path`.
  5. Writes `unit_ids.json` (ordered list of content IDs matching BM25 corpus positions).
- `incremental_update(new_units, chroma_persist_dir, bm25_index_path)`:
  - Detects new or changed units by comparing `provenance.parser_confidence` and source line ranges.
  - Appends new embeddings to ChromaDB and rebuilds BM25 index (BM25 is rebuilt fully on any change; this is cheap given corpus size).

### `vector_index/metadata_schema.py`
Defines the flat metadata dict stored in ChromaDB per unit:

```python
{
    "content_id": str,
    "manual_id": str,
    "manual_role": str,          # operator | maintenance | ...
    "unit_type": str,
    "chapter": str | None,
    "subsystem": str | None,
    "maintenance_category": str | None,
    "has_warnings": bool,
    "has_cautions": bool,
    "has_steps": bool,
    "mode_detected": str,        # operator | maintenance | mixed_or_uncertain
    "source_path": str,
    "anchor": str | None,
}
```

Booleans are stored as integers (0/1) for ChromaDB compatibility.

### `vector_index/retriever.py`
- `HybridRetriever` class.
- `__init__(chroma_persist_dir, bm25_index_path, unit_ids_path, embedder, top_n=20, rrf_k=60)`.
- `retrieve(query, filters=None, top_k=5) -> list[RetrievalResult]`:
  1. Build ChromaDB `where` clause from `filters` dict (manual_id, subsystem, manual_role, has_warnings).
  2. Run semantic query: `collection.query(query_embeddings=[q_emb], n_results=top_n, where=where_clause)`.
  3. Run BM25 query: tokenize query, score corpus, apply post-hoc metadata filter, take top_n.
  4. RRF merge over semantic and BM25 result lists.
  5. Return `top_k` `RetrievalResult` objects with fields: `content_id`, `score`, `rank`, `unit` (full content unit dict), `retrieval_source` (semantic|bm25|both).

### `vector_index/reranker.py`
- `CrossEncoderReranker` (optional, for offline eval).
- Uses `cross-encoder/ms-marco-MiniLM-L-6-v2` (85 MB).
- `rerank(query, candidates: list[RetrievalResult]) -> list[RetrievalResult]` — scores each (query, unit.text_plain[:512]) pair and re-sorts.
- Disabled by default in the runtime path; enabled via `--rerank` flag on CLI.

### `vector_index/run_indexer.py`
- CLI entrypoint: `python -m vector_index.run_indexer --content-units output/ingestion/content-units.jsonl --index-dir output/vector_index`.
- Reports per-batch embedding throughput (docs/sec, tokens/sec).
- Exits non-zero on any embedding or persistence failure.

### `vector_index/run_query.py`
- CLI entrypoint: `python -m vector_index.run_query --index-dir output/vector_index --query "engine does not start"`.
- Supports `--filter manual_id=TM-9-2320-280-20-1`, `--filter subsystem=engine`, `--top-k 5`, `--rerank`.
- Prints results with `content_id`, `score`, `title`, `text_plain[:300]`, `source_path`, `anchor`.

---

## Metadata Filter Design

Filters are composable ANDs of equality or boolean checks, matching the Stage 1 acceptance criteria:

```python
# Example: maintenance manual, engine subsystem, units with warnings
filters = {
    "manual_role": "maintenance",
    "subsystem": "engine",
    "has_warnings": 1,
}
```

This limits ChromaDB's semantic search scope before RRF fusion, ensuring BM25 is also post-filtered to the same subset.

---

## Incremental Re-Index Workflow

```
New/updated markdown committed to repo
           │
           ▼
  run_ingestion.py      (produces updated content-units.jsonl)
           │
           ▼
  run_indexer.py --incremental
           │  — Detects new content_ids not in ChromaDB collection
           │  — Embeds and upserts only new/changed units
           │  — Rebuilds BM25 index from full corpus (fast: <5 s)
           ▼
  Index ready for queries
```

A content unit is considered changed if its `source_path + line_start + line_end` differs from the stored metadata. Changed units are deleted and re-inserted.

---

## Local Performance Targets

| Operation | Target |
|-----------|--------|
| Full index build (first run, ~3 000 units) | < 4 min on CPU laptop |
| Incremental update (10 new units) | < 15 s |
| Query latency (hybrid, no reranker) | < 500 ms |
| Query latency (hybrid + cross-encoder reranker, 20 candidates) | < 3 s |
| Index size on disk | < 200 MB |
| Model weight download (first run only) | 80 MB (MiniLM-L6-v2) |

---

## Embedding Text Construction — Refinement

After reviewing the unit schema, embedding text is constructed as:

```
{title}. {subsystem if set}. {symptom_terms if set}.
{text_plain truncated to 1024 chars}
```

This front-loads high-signal classification terms before the dense procedure prose, improving retrieval precision for symptom-initiated queries. Safety block text is included verbatim in `text_plain` so safety-relevant units surface on safety-related queries.

---

## Assumptions Challenged

- **Assumption**: Semantic-only retrieval is sufficient for technical manuals.
  - **Finding**: Exact task IDs and part numbers require BM25. Hybrid is mandatory.
- **Assumption**: A cross-encoder reranker is needed at query time.
  - **Finding**: For a corpus under 5 000 units, RRF over top-20 candidates produces high precision without model inference overhead. Cross-encoder reserved for evaluation.
- **Assumption**: Vector store requires a server process.
  - **Finding**: ChromaDB embedded mode (no server) meets all requirements for local development and single-node deployment.
- **Assumption**: GPU acceleration is required for useful embedding speed.
  - **Finding**: MiniLM-L6-v2 on CPU indexes the expected corpus in well under 4 minutes, acceptable for a setup step. Query latency on CPU is under 100 ms per query.

---

## Residual Questions
1. Should semantic and BM25 result counts (n=20 each) be tunable at runtime, or fixed?
2. Should the keyword index from Stage 3 be used to augment BM25 tokenization (synonym expansion), or kept separate?
3. At what corpus size does ChromaDB embedded mode become a bottleneck, and when should migration to Qdrant server be recommended?
