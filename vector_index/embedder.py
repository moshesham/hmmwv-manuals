"""
vector_index/embedder.py

Local embedding model wrapper using sentence-transformers.
Downloads the model once to a local cache; fully offline after first run.

Default model: all-MiniLM-L6-v2 (80 MB, 384-dim, fast on CPU)
Quality alternative: bge-small-en-v1.5 (130 MB, 384-dim)
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import numpy as np

DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
DEFAULT_CACHE_DIR = Path.home() / ".cache" / "hmmwv-rag" / "models"
DEFAULT_BATCH_SIZE = 64
EMBED_TEXT_LIMIT = 1024  # chars before truncation


class Embedder:
    """
    Wraps a SentenceTransformer model for batch and single-query embedding.

    Lazy-loads the model on first use to keep import time fast.
    """

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL,
        cache_dir: Optional[Path] = None,
        device: str = "cpu",
        batch_size: int = DEFAULT_BATCH_SIZE,
    ):
        self.model_name = model_name
        self.cache_dir = cache_dir or DEFAULT_CACHE_DIR
        self.device = device
        self.batch_size = batch_size
        self._model = None

        # BGE models need an instruction prefix for passage embedding
        self._is_bge = "bge" in model_name.lower()

    def _load(self):
        if self._model is not None:
            return
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise ImportError(
                "sentence-transformers is required. Install with: pip install sentence-transformers"
            ) from exc

        os.makedirs(self.cache_dir, exist_ok=True)
        self._model = SentenceTransformer(
            self.model_name,
            device=self.device,
            cache_folder=str(self.cache_dir),
        )

    def embed(self, texts: list[str], show_progress: bool = False) -> np.ndarray:
        """
        Embed a list of texts.
        Returns a float32 numpy array of shape (len(texts), embedding_dim).
        """
        self._load()
        prepared = [self._prepare_passage(t) for t in texts]
        return self._model.encode(
            prepared,
            batch_size=self.batch_size,
            show_progress_bar=show_progress,
            normalize_embeddings=True,
            convert_to_numpy=True,
        )

    def embed_query(self, query: str) -> np.ndarray:
        """
        Embed a single query string.
        For BGE models, uses the query instruction prefix.
        Returns a float32 numpy array of shape (embedding_dim,).
        """
        self._load()
        if self._is_bge:
            text = f"Represent this sentence for searching relevant passages: {query}"
        else:
            text = query
        result = self._model.encode(
            [text],
            batch_size=1,
            normalize_embeddings=True,
            convert_to_numpy=True,
        )
        return result[0]

    def _prepare_passage(self, text: str) -> str:
        """Truncate text for passage embedding."""
        return text[:EMBED_TEXT_LIMIT]

    @property
    def dimension(self) -> int:
        self._load()
        return self._model.get_sentence_embedding_dimension()


def build_embed_text(unit_dict: dict) -> str:
    """
    Construct the text to embed for a content unit.

    Ordering: title, subsystem, symptom_terms, then body text.
    Front-loading high-signal classification terms before prose improves
    retrieval precision for symptom-initiated queries.
    """
    parts: list[str] = []
    title = unit_dict.get("title", "")
    if title:
        parts.append(title)

    tax = unit_dict.get("taxonomy", {})
    subsystem = tax.get("subsystem") or ""
    if subsystem:
        parts.append(subsystem)

    symptom_terms = tax.get("symptom_terms", [])
    if symptom_terms:
        parts.append(", ".join(symptom_terms[:5]))

    body = unit_dict.get("text_plain", "")
    if body:
        parts.append(body)

    combined = ". ".join(filter(None, parts))
    return combined[:EMBED_TEXT_LIMIT]
