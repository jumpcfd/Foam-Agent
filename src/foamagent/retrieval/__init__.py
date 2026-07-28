"""Finding relevant OpenFOAM references.

Which method is used -- nearest neighbour in a FAISS index, or matching words in the raw
corpus -- is chosen here and nowhere else. Callers ask for references; they do not name a
method.

FAISS remains the default. The grep retriever exists because it needs no embedding model,
and so no torch: on a machine without the `rag-local` extra it is the difference between
retrieval working and not working at all.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from foamagent.logger import get_logger
from foamagent.retrieval.base import (
    ALLRUN_SCRIPTS,
    COMMAND_HELP,
    DATABASES,
    TUTORIALS_DETAILS,
    TUTORIALS_STRUCTURE,
    Document,
    Retriever,
    parse_corpus,
)
from foamagent.retrieval.faiss_retriever import FaissRetriever
from foamagent.retrieval.grep_retriever import CorpusUnavailableError, GrepRetriever

logger = get_logger(__name__)

DEFAULT_BACKEND = FaissRetriever.name

_RETRIEVERS = {
    FaissRetriever.name: FaissRetriever,
    GrepRetriever.name: GrepRetriever,
}

_retriever: Optional[Retriever] = None


def get_retriever(backend: Optional[str] = None) -> Retriever:
    """Return the retriever to use, building it on first call.

    Cached, because the FAISS retriever holds loaded indices and the grep retriever holds a
    parsed corpus; neither is cheap to rebuild per query.
    """
    global _retriever

    if backend is None and _retriever is not None:
        return _retriever

    name = (backend or os.getenv("FOAMAGENT_RETRIEVAL_BACKEND") or DEFAULT_BACKEND).strip().lower()
    retriever_class = _RETRIEVERS.get(name)
    if retriever_class is None:
        logger.warning("Unknown retrieval backend %r; using %s.", name, DEFAULT_BACKEND)
        retriever_class = _RETRIEVERS[DEFAULT_BACKEND]

    retriever = retriever_class()
    if backend is None:
        _retriever = retriever
    return retriever


def set_retriever(retriever: Optional[Retriever]) -> None:
    """Replace the cached retriever. Passing None makes the next call rebuild it."""
    global _retriever
    _retriever = retriever


def retrieve(database_name: str, query: str, topk: int = 1) -> List[Dict[str, Any]]:
    """Find the ``topk`` most relevant entries in ``database_name``."""
    return get_retriever().retrieve(database_name, query, topk)


__all__ = [
    "ALLRUN_SCRIPTS",
    "COMMAND_HELP",
    "DATABASES",
    "DEFAULT_BACKEND",
    "TUTORIALS_DETAILS",
    "TUTORIALS_STRUCTURE",
    "CorpusUnavailableError",
    "Document",
    "FaissRetriever",
    "GrepRetriever",
    "Retriever",
    "get_retriever",
    "parse_corpus",
    "retrieve",
    "set_retriever",
]
