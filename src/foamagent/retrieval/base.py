"""The shape of a retrieval result, and how the raw corpus is parsed into one.

Retrieval used to be one function, retrieve_faiss(), that both chose the method and
formatted the answer. The formatting is the part every method shares: callers depend on a
particular dict per database, whatever produced it. That contract lives here, so a new
retriever only has to return documents.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

ALLRUN_SCRIPTS = "openfoam_allrun_scripts"
TUTORIALS_STRUCTURE = "openfoam_tutorials_structure"
TUTORIALS_DETAILS = "openfoam_tutorials_details"
COMMAND_HELP = "openfoam_command_help"

DATABASES = (ALLRUN_SCRIPTS, TUTORIALS_STRUCTURE, TUTORIALS_DETAILS, COMMAND_HELP)

# Which raw corpus file each database is built from. The grep retriever reads these
# directly; the FAISS retriever reads an index built from them.
RAW_FILES: Dict[str, str] = {
    ALLRUN_SCRIPTS: "openfoam_allrun_scripts.txt",
    TUTORIALS_STRUCTURE: "openfoam_tutorials_structure.txt",
    TUTORIALS_DETAILS: "openfoam_tutorials_details.txt",
    COMMAND_HELP: "openfoam_command_help.txt",
}

# The metadata keys each database's results carry, beyond "index" and "score".
RESULT_FIELDS: Dict[str, Sequence[str]] = {
    ALLRUN_SCRIPTS: (
        "full_content", "case_name", "case_domain", "case_category", "case_solver",
        "dir_structure", "allrun_script",
    ),
    TUTORIALS_STRUCTURE: (
        "full_content", "case_name", "case_domain", "case_category", "case_solver",
        "dir_structure",
    ),
    TUTORIALS_DETAILS: (
        "full_content", "case_name", "case_domain", "case_category", "case_solver",
        "dir_structure", "tutorials",
    ),
    COMMAND_HELP: ("full_content", "command", "help_text"),
}

# What a missing metadata key becomes. Kept per key because the original formatter used
# "N/A" for the two large payload fields and "unknown" for everything else.
_MISSING = {"allrun_script": "N/A", "tutorials": "N/A"}


@dataclass
class Document:
    """One retrievable item: the text that is matched, plus what is returned with it."""

    page_content: str
    metadata: Dict[str, Any] = field(default_factory=dict)


class Retriever(ABC):
    """A way of finding relevant documents in the OpenFOAM corpus."""

    name: str

    @abstractmethod
    def search(self, database_name: str, query: str, topk: int = 1) -> List[Document]:
        """Return the best ``topk`` documents, most relevant first."""

    def scores(self, database_name: str, documents: Sequence[Document]) -> List[Optional[float]]:
        """Return a distance per document: smaller is closer.

        Distances, not similarities -- the candidate reranking in services.plan sorts
        ascending, which came from FAISS returning L2 distances.
        """
        return [None] * len(documents)

    def retrieve(self, database_name: str, query: str, topk: int = 1) -> List[Dict[str, Any]]:
        if database_name not in DATABASES:
            raise ValueError(f"Unknown database name: {database_name}")

        documents = self.search(database_name, query, topk)
        if not documents:
            raise ValueError(f"No documents found for query: {query}")

        return format_results(database_name, documents, self.scores(database_name, documents))


def format_results(
    database_name: str,
    documents: Sequence[Document],
    scores: Sequence[Optional[float]],
) -> List[Dict[str, Any]]:
    """Build the result dicts the callers expect."""
    fields = RESULT_FIELDS[database_name]

    results = []
    for document, score in zip(documents, scores):
        metadata = document.metadata or {}
        result: Dict[str, Any] = {"index": document.page_content}
        for key in fields:
            result[key] = metadata.get(key, _MISSING.get(key, "unknown"))
        result["score"] = score
        results.append(result)
    return results


def tokenize(text: str) -> str:
    """Normalise text for matching: camelCase to words, underscores to spaces, lowercase.

    The indexed documents were tokenized this way when they were built, so queries must be
    tokenized the same way for either retriever to match them.
    """
    text = text.replace("_", " ")
    text = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", text)
    return text.lower()


# --------------------------------------------------------------------------------------
# Parsing the raw corpus
#
# These mirror database/script/faiss_*.py, which build the shipped indices. The metadata
# keys must match, or a case retrieved by grep would carry different fields from the same
# case retrieved by FAISS.
# --------------------------------------------------------------------------------------

_CASE_PATTERN = re.compile(r"<case_begin>(.*?)</case_end>", re.DOTALL)
_COMMAND_PATTERN = re.compile(r"<command_begin>(.*?)</command_end>", re.DOTALL)


def _extract_field(field_name: str, text: str) -> str:
    match = re.search(rf"{field_name}:\s*(.*)", text)
    return match.group(1).strip() if match else "unknown"


def _extract_block(tag: str, text: str, *, keep_tags: bool = False) -> str:
    match = re.search(rf"<{tag}>(.*?)</{tag}>", text, re.DOTALL)
    if not match:
        return "Unknown"
    return match.group(0).strip() if keep_tags else match.group(1).strip()


def parse_corpus(database_name: str, text: str) -> List[Document]:
    """Turn a raw corpus file into documents."""
    if database_name == COMMAND_HELP:
        return _parse_command_help(text)
    return _parse_cases(database_name, text)


def _parse_command_help(text: str) -> List[Document]:
    documents = []
    for match in _COMMAND_PATTERN.findall(text):
        command_match = re.search(r"<command>(.*?)</command>", match, re.DOTALL)
        help_match = re.search(r"<help_text>(.*?)</help_text>", match, re.DOTALL)
        if not command_match:
            continue
        command = command_match.group(1).strip()
        documents.append(
            Document(
                page_content=tokenize(command),
                metadata={
                    "full_content": match.strip(),
                    "command": command,
                    "help_text": help_match.group(1).strip() if help_match else "unknown",
                },
            )
        )
    return documents


def _parse_cases(database_name: str, text: str) -> List[Document]:
    documents = []
    for match in _CASE_PATTERN.findall(text):
        index_match = re.search(r"<index>(.*?)</index>", match, re.DOTALL)
        if not index_match:
            continue

        full_content = match.strip()
        index_content = index_match.group(0).strip()
        dir_structure = _extract_block("directory_structure", match, keep_tags=True)

        case_name = _extract_field("case name", index_content)
        case_domain = _extract_field("case domain", index_content)
        case_category = _extract_field("case category", index_content)
        case_solver = _extract_field("case solver", index_content)

        metadata: Dict[str, Any] = {
            "full_content": full_content,
            "case_name": case_name,
            "case_domain": case_domain,
            "case_category": case_category,
            "case_solver": case_solver,
            "dir_structure": dir_structure,
        }

        if database_name == ALLRUN_SCRIPTS:
            # The Allrun script does not depend on domain or category, so the index that
            # is matched against drops them -- as database/script/faiss_allrun_scripts.py does.
            index_content = (
                f"<index>\ncase name: {case_name}\ncase solver: {case_solver}\n</index>\n"
            )
            metadata["allrun_script"] = _extract_block("allrun_script", full_content)
            page_content = tokenize(index_content + dir_structure)
        elif database_name == TUTORIALS_DETAILS:
            metadata["tutorials"] = _extract_block("tutorials", full_content)
            page_content = tokenize(index_content + "\n" + dir_structure)
        else:
            page_content = tokenize(index_content)

        documents.append(Document(page_content=page_content, metadata=metadata))
    return documents
