# HMMWV RAG Diagnostic — Local Development Guide

## Overview

This guide covers running Stages 3 and 4 of the RAG diagnostic system on your local machine.
No GPU is required. No external API keys are needed. Everything runs offline after the first model download.

## Prerequisites

- Python 3.10+ (tested on 3.11)
- Docker + Docker Compose (optional; see Docker section)
- ~500 MB free disk space (model weights + index)

## Quick Start — Native Python

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Run Stage 3 — Ingestion pipeline

From the repository root:

```bash
python -m ingestion.run_ingestion \
    --corpus-root . \
    --output-dir output/ingestion
```

**What it does:**
- Parses all chapter markdown files from the 4 MVP manuals
- Produces domain-aware content units (procedure tasks, troubleshooting entries, diagnostic flows)
- Validates each unit against `schemas/rag-diagnostic/content-unit.schema.json`
- Writes QA report, keyword index, cross-reference map, and troubleshooting graph

**Expected output (approx):**
```
=== HMMWV RAG Ingestion Pipeline ===
Step 1/7  Discovering source files...
          Found N chapter files across 4 manuals.
...
Ingestion complete in ~10-30s.
```

**Output files:**
```
output/ingestion/
    content-units.jsonl        ← main artifact for Stage 4
    keyword-index.json
    cross-reference-map.json
    troubleshooting-graph.json
    qa-report.md               ← review this for coverage/safety issues
```

### 3. Run Stage 4 — Build vector index

```bash
python -m vector_index.run_indexer \
    --content-units output/ingestion/content-units.jsonl \
    --index-dir output/vector_index
```

**First run:** Downloads `all-MiniLM-L6-v2` (~80 MB) to `~/.cache/hmmwv-rag/models/`.  
**Subsequent runs:** Uses cached model; full index build < 4 min on CPU laptop.

**Output:**
```
output/vector_index/
    chroma/            ← ChromaDB persistent collection
    bm25_index.pkl     ← BM25 keyword index
    unit_ids.json      ← content ID ordering
```

### 4. Query the index

```bash
python -m vector_index.run_query \
    --query "engine does not start" \
    --top-k 5
```

With metadata filters:
```bash
python -m vector_index.run_query \
    --query "oil pressure warning light" \
    --filter manual_role=maintenance \
    --filter subsystem=engine \
    --top-k 5
```

With cross-encoder reranking (slower, higher quality):
```bash
python -m vector_index.run_query \
    --query "brake system noise" \
    --top-k 5 \
    --rerank
```

## Quick Start — Docker

### Run the full pipeline (ingestion + indexer):

```bash
docker compose run --rm pipeline
```

### Run only ingestion:

```bash
docker compose run --rm ingestion
```

### Run only indexer:

```bash
docker compose run --rm indexer
```

### Run a query:

```bash
docker compose run --rm query --query "engine does not start" --top-k 5
```

## Incremental Updates

When manual content changes, re-run ingestion then update the index incrementally:

```bash
python -m ingestion.run_ingestion --corpus-root . --output-dir output/ingestion
python -m vector_index.run_indexer --content-units output/ingestion/content-units.jsonl \
    --index-dir output/vector_index --incremental
```

Incremental update embeds and upserts only new/changed units; BM25 index is rebuilt in full (~5 s).

## Performance Targets

| Step | Expected time (CPU laptop) |
|------|---------------------------|
| Ingestion (all 4 manuals) | < 60 s |
| Index build (first run, ~3000 units) | < 4 min |
| Index build (incremental, 10 units) | < 15 s |
| Query (hybrid, no reranker) | < 500 ms |
| Query (hybrid + cross-encoder) | < 3 s |

## Embedding Model Options

| Model | Size | CPU Speed | Quality | Config flag |
|-------|------|-----------|---------|-------------|
| `all-MiniLM-L6-v2` *(default)* | 80 MB | Fast | Good | (default) |
| `bge-small-en-v1.5` | 130 MB | Medium | Better | `--model BAAI/bge-small-en-v1.5` |
| `nomic-embed-text-v1.5` | 270 MB | Slow | Best | `--model nomic-ai/nomic-embed-text-v1.5` |

Switch models by passing `--model <name>` to `run_indexer.py` and `run_query.py`.
You must re-run the full indexer when changing models.

## QA Report

After ingestion, review `output/ingestion/qa-report.md` to check:

- **Coverage errors**: any MVP chapter with zero content units
- **Broken anchors**: cross-references to anchors with no matching unit
- **Safety associations**: procedure tasks with risk language but no warning/caution blocks
- **Duplicate IDs**: content ID collisions
- **Schema failures**: units that fail the JSON schema

## Architecture

```
Corpus (markdown)
    │
    ▼
ingestion/          ← Stage 3
    parser.py       parses markdown → raw blocks
    chunker.py      assembles content units
    enrichment.py   keyword index, xref map, troubleshooting graph
    qa.py           QA checks + report
    validate.py     JSON schema validation
    run_ingestion.py  CLI entrypoint
    │
    ▼  content-units.jsonl
    │
    ▼
vector_index/       ← Stage 4
    embedder.py     sentence-transformers wrapper
    index_builder.py  ChromaDB + BM25 build/update
    retriever.py    hybrid retrieval (semantic + BM25 + RRF)
    reranker.py     optional cross-encoder reranker
    run_indexer.py  CLI entrypoint
    run_query.py    CLI query entrypoint
```

## Next Steps

- **Stage 5**: Local LLM runtime (Ollama + llama.cpp Docker container)
- **Stage 6**: RAG orchestration service connecting the retriever to the LLM
- **Stage 7**: Technician-facing interactive diagnostic UI
