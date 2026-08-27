"""
vector_index/index_builder.py

Builds (and incrementally updates) the ChromaDB vector collection and BM25 index.

Usage as module:
    from vector_index.index_builder import build_index, incremental_update

CLI: see run_indexer.py
"""
from __future__ import annotations

import json
import pickle
import time
from pathlib import Path
from typing import Any, Optional

from vector_index.embedder import Embedder, build_embed_text
from vector_index.metadata_schema import CHROMADB_COLLECTION, unit_to_metadata

UNIT_IDS_FILENAME = "unit_ids.json"
BM25_INDEX_FILENAME = "bm25_index.pkl"
EMBED_BATCH = 64


def _get_or_create_collection(client, name: str):
    try:
        return client.get_collection(name=name)
    except Exception:
        return client.create_collection(
            name=name,
            metadata={"hnsw:space": "cosine"},
        )


def _load_units(content_units_path: Path) -> list[dict[str, Any]]:
    units = []
    with content_units_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                units.append(json.loads(line))
    return units


def _tokenize_for_bm25(text: str) -> list[str]:
    import re
    return re.findall(r"[a-zA-Z0-9]+(?:[-/][a-zA-Z0-9]+)*", text.lower())


def _build_bm25(units: list[dict[str, Any]], unit_ids: list[str]) -> Any:
    try:
        from rank_bm25 import BM25Okapi
    except ImportError as exc:
        raise ImportError(
            "rank_bm25 is required. Install with: pip install rank-bm25"
        ) from exc

    corpus = []
    for uid in unit_ids:
        unit = next((u for u in units if u["content_id"] == uid), None)
        if unit:
            text = build_embed_text(unit)
            corpus.append(_tokenize_for_bm25(text))
        else:
            corpus.append([])

    return BM25Okapi(corpus)


def build_index(
    content_units_path: Path,
    index_dir: Path,
    embedder: Embedder,
    force_rebuild: bool = False,
) -> None:
    """
    Build or rebuild the full ChromaDB collection and BM25 index.

    index_dir layout:
        chroma/              — ChromaDB persistent directory
        bm25_index.pkl       — pickled BM25Okapi object
        unit_ids.json        — ordered list of content_ids (BM25 corpus order)
    """
    try:
        import chromadb
    except ImportError as exc:
        raise ImportError(
            "chromadb is required. Install with: pip install chromadb"
        ) from exc

    index_dir.mkdir(parents=True, exist_ok=True)
    chroma_dir = index_dir / "chroma"
    bm25_path = index_dir / BM25_INDEX_FILENAME
    unit_ids_path = index_dir / UNIT_IDS_FILENAME

    print(f"Loading content units from {content_units_path}...")
    t0 = time.perf_counter()
    units = _load_units(content_units_path)
    print(f"  Loaded {len(units)} units ({time.perf_counter()-t0:.1f}s)")

    client = chromadb.PersistentClient(path=str(chroma_dir))
    collection = _get_or_create_collection(client, CHROMADB_COLLECTION)

    # Detect existing IDs for incremental logic
    if not force_rebuild:
        try:
            existing = set(collection.get(include=[])["ids"])
        except Exception:
            existing = set()
    else:
        existing = set()
        try:
            client.delete_collection(CHROMADB_COLLECTION)
        except Exception:
            pass
        collection = client.create_collection(
            name=CHROMADB_COLLECTION,
            metadata={"hnsw:space": "cosine"},
        )

    new_units = [u for u in units if u["content_id"] not in existing]
    print(f"  {len(existing)} existing, {len(new_units)} new units to embed.")

    if new_units:
        texts = [build_embed_text(u) for u in new_units]
        t1 = time.perf_counter()
        print(f"  Embedding {len(texts)} texts in batches of {EMBED_BATCH}...")
        embeddings = embedder.embed(texts, show_progress=True)
        embed_elapsed = time.perf_counter() - t1
        docs_per_sec = len(texts) / embed_elapsed if embed_elapsed > 0 else 0
        print(f"  Embedded {len(texts)} texts in {embed_elapsed:.1f}s ({docs_per_sec:.0f} docs/s)")

        # Upsert in batches of 500 (ChromaDB batch limit)
        UPSERT_BATCH = 500
        for start in range(0, len(new_units), UPSERT_BATCH):
            batch_units = new_units[start:start + UPSERT_BATCH]
            batch_embs = embeddings[start:start + UPSERT_BATCH].tolist()
            collection.upsert(
                ids=[u["content_id"] for u in batch_units],
                embeddings=batch_embs,
                metadatas=[unit_to_metadata(u) for u in batch_units],
                documents=[build_embed_text(u) for u in batch_units],
            )
        print(f"  Upserted {len(new_units)} units into ChromaDB.")

    # Rebuild BM25 over the full corpus (always, to keep order consistent)
    unit_ids = [u["content_id"] for u in units]
    unit_ids_path.write_text(json.dumps(unit_ids, indent=2), encoding="utf-8")

    print("  Building BM25 index...")
    t2 = time.perf_counter()
    bm25 = _build_bm25(units, unit_ids)
    with bm25_path.open("wb") as f:
        pickle.dump(bm25, f, protocol=pickle.HIGHEST_PROTOCOL)
    print(f"  BM25 index built in {time.perf_counter()-t2:.1f}s")

    total = time.perf_counter() - t0
    print(f"\nIndex build complete in {total:.1f}s.")
    print(f"  ChromaDB      : {chroma_dir}")
    print(f"  BM25 index    : {bm25_path}")
    print(f"  Unit IDs      : {unit_ids_path}")


def incremental_update(
    content_units_path: Path,
    index_dir: Path,
    embedder: Embedder,
) -> None:
    """
    Detect new or changed units and add them to the existing index.
    BM25 index is always rebuilt fully (fast for this corpus size).
    """
    try:
        import chromadb
    except ImportError as exc:
        raise ImportError("chromadb is required.") from exc

    chroma_dir = index_dir / "chroma"
    bm25_path = index_dir / BM25_INDEX_FILENAME
    unit_ids_path = index_dir / UNIT_IDS_FILENAME

    if not chroma_dir.exists():
        print("No existing index found; running full build.")
        build_index(content_units_path, index_dir, embedder)
        return

    client = chromadb.PersistentClient(path=str(chroma_dir))
    collection = _get_or_create_collection(client, CHROMADB_COLLECTION)
    existing_meta = collection.get(include=["metadatas"])
    existing_map: dict[str, dict] = {
        cid: meta for cid, meta in zip(existing_meta["ids"], existing_meta["metadatas"])
    }

    units = _load_units(content_units_path)
    new_or_changed: list[dict] = []
    for u in units:
        cid = u["content_id"]
        if cid not in existing_map:
            new_or_changed.append(u)
        else:
            source = u.get("source", {})
            stored = existing_map[cid]
            if (stored.get("source_path") != source.get("path", "")
                    or stored.get("anchor") != (source.get("anchor") or "")):
                new_or_changed.append(u)

    if new_or_changed:
        print(f"  {len(new_or_changed)} new/changed units to embed...")
        texts = [build_embed_text(u) for u in new_or_changed]
        embeddings = embedder.embed(texts, show_progress=True)
        collection.upsert(
            ids=[u["content_id"] for u in new_or_changed],
            embeddings=embeddings.tolist(),
            metadatas=[unit_to_metadata(u) for u in new_or_changed],
            documents=[build_embed_text(u) for u in new_or_changed],
        )
        print(f"  Upserted {len(new_or_changed)} units.")
    else:
        print("  No changes detected.")

    # Always rebuild BM25
    unit_ids = [u["content_id"] for u in units]
    unit_ids_path.write_text(json.dumps(unit_ids, indent=2), encoding="utf-8")
    bm25 = _build_bm25(units, unit_ids)
    with bm25_path.open("wb") as f:
        pickle.dump(bm25, f, protocol=pickle.HIGHEST_PROTOCOL)
    print("  BM25 index rebuilt.")
