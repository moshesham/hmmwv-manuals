"""
vector_index/reranker.py

Optional cross-encoder reranker for offline quality evaluation.
Uses cross-encoder/ms-marco-MiniLM-L-6-v2 (85 MB).

Disabled by default in the hot path; enable with --rerank flag.
"""
from __future__ import annotations

from typing import Optional

from vector_index.retriever import RetrievalResult

DEFAULT_RERANKER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"
RERANK_TEXT_LIMIT = 512


class CrossEncoderReranker:
    """
    Re-scores a list of RetrievalResult objects using a cross-encoder model.
    Returns results sorted by cross-encoder score (highest first).
    """

    def __init__(
        self,
        model_name: str = DEFAULT_RERANKER_MODEL,
        cache_dir: Optional[str] = None,
        device: str = "cpu",
    ):
        self.model_name = model_name
        self.cache_dir = cache_dir
        self.device = device
        self._model = None

    def _load(self):
        if self._model is not None:
            return
        try:
            from sentence_transformers import CrossEncoder
        except ImportError as exc:
            raise ImportError(
                "sentence-transformers is required. Install with: pip install sentence-transformers"
            ) from exc
        self._model = CrossEncoder(self.model_name, device=self.device)

    def rerank(self, query: str, candidates: list[RetrievalResult]) -> list[RetrievalResult]:
        """
        Score each (query, candidate.text_plain) pair and re-sort by cross-encoder score.
        Returns a new list sorted descending by cross-encoder score.
        """
        if not candidates:
            return candidates

        self._load()
        pairs = [
            [query, r.text_plain[:RERANK_TEXT_LIMIT]] for r in candidates
        ]
        scores = self._model.predict(pairs)

        reranked = sorted(
            zip(candidates, scores),
            key=lambda x: x[1],
            reverse=True,
        )
        results = []
        for rank, (result, score) in enumerate(reranked, start=1):
            results.append(RetrievalResult(
                content_id=result.content_id,
                rrf_score=float(score),
                rank=rank,
                semantic_rank=result.semantic_rank,
                bm25_rank=result.bm25_rank,
                retrieval_source=f"{result.retrieval_source}+reranked",
                title=result.title,
                text_plain=result.text_plain,
                source_path=result.source_path,
                anchor=result.anchor,
                manual_id=result.manual_id,
                unit_type=result.unit_type,
                metadata=result.metadata,
            ))
        return results
