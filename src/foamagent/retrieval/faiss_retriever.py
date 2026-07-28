"""Retrieval by nearest neighbour in a FAISS index.

The default, and what Foam-Agent has always used. It needs the `rag-local` extra: an
embedding model to turn the query into a vector, which on the default configuration is a
1.2 GB download.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence

from foamagent.logger import get_logger
from foamagent.retrieval.base import Document, Retriever, tokenize

logger = get_logger(__name__)


class FaissRetriever(Retriever):
    name = "faiss"

    def __init__(self, databases: Optional[Dict[str, object]] = None):
        self._databases = databases
        self._last_scores: List[Optional[float]] = []

    def databases(self) -> Dict[str, object]:
        if self._databases is None:
            from foamagent.utils import get_faiss_dbs

            self._databases = get_faiss_dbs()
        return self._databases

    def search(self, database_name: str, query: str, topk: int = 1) -> List[Document]:
        databases = self.databases()
        if database_name not in databases:
            raise ValueError(f"Database '{database_name}' is not loaded.")

        vectordb = databases[database_name]
        tokenized = tokenize(query)

        try:
            hits = vectordb.similarity_search_with_score(tokenized, k=topk)
            documents = [doc for doc, _ in hits]
            scores: List[Optional[float]] = [score for _, score in hits]
        except Exception:
            # Not every vector store implements the scored variant.
            documents = vectordb.similarity_search(tokenized, k=topk)
            scores = [None] * len(documents)

        self._last_scores = scores
        return [Document(page_content=d.page_content, metadata=dict(d.metadata or {})) for d in documents]

    def scores(self, database_name: str, documents: Sequence[Document]) -> List[Optional[float]]:
        # FAISS returns L2 distances, which are already "smaller is closer".
        return list(self._last_scores[: len(documents)])
