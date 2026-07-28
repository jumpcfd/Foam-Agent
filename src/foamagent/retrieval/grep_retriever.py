"""Retrieval by matching query words against the raw corpus.

No embedding model, so no torch: the `rag-local` extra is not needed. It is weaker than the
FAISS retriever at paraphrase -- "lid driven cavity" finds the cavity tutorial, "flow in a
square box with a moving wall" does not -- which is why FAISS remains the default. It
becomes the interesting option once the search terms are chosen by an agent that already
knows OpenFOAM vocabulary, which is where phase 4 is heading.

The corpus files are Git LFS objects. Reading a pointer file as if it were text would match
nothing and report an empty corpus, so the pointer is detected and named.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from foamagent import paths
from foamagent.logger import get_logger
from foamagent.retrieval.base import (
    RAW_FILES,
    Document,
    Retriever,
    parse_corpus,
    tokenize,
)

logger = get_logger(__name__)


class CorpusUnavailableError(RuntimeError):
    """The raw corpus file cannot be read as text."""


def _detected_environment():
    """The OpenFOAM this machine has, or None when that cannot be established.

    Only used to pick between a built index and the shipped one. A failure here is not a
    retrieval failure -- it just means the shipped corpus is used.
    """
    try:
        from foamagent.environment import detect_environment

        environment = detect_environment()
    except Exception as exc:
        logger.debug("Could not detect the OpenFOAM environment: %s", exc)
        return None

    return environment if environment.detected else None


def _query_terms(query: str) -> List[str]:
    return [term for term in tokenize(query).split() if term]


def score_document(document: Document, terms: Sequence[str]) -> float:
    """Return a distance in [0, 1]: 0 when every query term appears, 1 when none do.

    A distance rather than a similarity, because the caller-side reranking sorts ascending
    -- see Retriever.scores.

    Terms are weighted by length. Counting matches equally makes a query like "cavity
    icoFoam" score every icoFoam case identically, since "ico" and "foam" outnumber the one
    term that actually identifies the case. Length is a cheap stand-in for specificity:
    short tokens are the ones OpenFOAM names share.
    """
    unique_terms = set(terms)
    total = sum(len(term) for term in unique_terms)
    if not total:
        return 1.0

    haystack = document.page_content
    matched = sum(len(term) for term in unique_terms if term in haystack)
    return 1.0 - matched / total


class GrepRetriever(Retriever):
    name = "grep"

    def __init__(self, corpus_dir: Optional[os.PathLike] = None):
        self._corpus_dir = Path(corpus_dir) if corpus_dir else None
        self._cache: Dict[str, List[Document]] = {}
        self._last_scores: List[Optional[float]] = []

    def corpus_dir(self) -> Path:
        if self._corpus_dir is not None:
            return self._corpus_dir

        # An index built from the installed OpenFOAM describes that OpenFOAM; the shipped
        # one describes Foundation v10. Prefer the former when it exists.
        from foamagent.indexing import resolve_corpus_dir

        return resolve_corpus_dir(_detected_environment())

    def corpus_path(self, database_name: str) -> Path:
        return self.corpus_dir() / RAW_FILES[database_name]

    def documents(self, database_name: str) -> List[Document]:
        if database_name not in self._cache:
            self._cache[database_name] = self._load(database_name)
        return self._cache[database_name]

    def _load(self, database_name: str) -> List[Document]:
        path = self.corpus_path(database_name)
        if not path.is_file():
            raise CorpusUnavailableError(
                f"Corpus file for '{database_name}' not found at {path}. "
                f"Build it with `foamagent index build`, or fetch the shipped one with "
                f"`git lfs pull`."
            )

        # Deferred so that the grep retriever does not drag in the rest of utils.
        from foamagent.utils import _lfs_pointer_reason

        pointer_reason = _lfs_pointer_reason(path)
        if pointer_reason:
            raise CorpusUnavailableError(
                f"Corpus file for '{database_name}' is not usable: {pointer_reason}"
            )

        documents = parse_corpus(database_name, path.read_text(encoding="utf-8", errors="ignore"))
        logger.info("Loaded %d documents for %s from %s", len(documents), database_name, path)
        return documents

    def search(self, database_name: str, query: str, topk: int = 1) -> List[Document]:
        documents = self.documents(database_name)
        terms = _query_terms(query)

        ranked: List[Tuple[float, int, Document]] = [
            (score_document(document, terms), position, document)
            for position, document in enumerate(documents)
        ]
        # Ties keep corpus order, so results do not shuffle between runs.
        ranked.sort(key=lambda item: (item[0], item[1]))

        # A document matching no query term is noise; returning it would be worse than
        # returning fewer results.
        hits = [item for item in ranked[:topk] if item[0] < 1.0]

        self._last_scores = [score for score, _, _ in hits]
        return [document for _, _, document in hits]

    def scores(self, database_name: str, documents: Sequence[Document]) -> List[Optional[float]]:
        return list(self._last_scores[: len(documents)])
