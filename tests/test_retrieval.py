"""Unit tests for the retrieval layer.

Built around a small corpus written into tmp_path, so nothing here loads a FAISS index,
downloads an embedding model or reads the shipped Git LFS files.
"""

from __future__ import annotations

import pytest

from foamagent.retrieval import (
    ALLRUN_SCRIPTS,
    COMMAND_HELP,
    DEFAULT_BACKEND,
    TUTORIALS_DETAILS,
    TUTORIALS_STRUCTURE,
    CorpusUnavailableError,
    Document,
    FaissRetriever,
    GrepRetriever,
    get_retriever,
    parse_corpus,
    set_retriever,
)
from foamagent.retrieval.base import RAW_FILES, RESULT_FIELDS, format_results


CASE_CORPUS = """
<case_begin>
<index>
case name: cavity
case domain: incompressible
case category: lidDrivenCavity
case solver: icoFoam
</index>

<directory_structure>
<dir>directory name: 0. File names in this directory: [U, p]</dir>
<dir>directory name: system. File names in this directory: [controlDict]</dir>
</directory_structure>

<allrun_script>
blockMesh
icoFoam
</allrun_script>
</case_end>

<case_begin>
<index>
case name: pitzDaily
case domain: incompressible
case category: None
case solver: simpleFoam
</index>

<directory_structure>
<dir>directory name: 0. File names in this directory: [U, p, k, epsilon]</dir>
</directory_structure>

<allrun_script>
blockMesh
simpleFoam
</allrun_script>
</case_end>
"""

COMMAND_CORPUS = """
<command_begin><command>blockMesh</command><help_text>
Usage: blockMesh [OPTIONS]
</help_text></command_end>
<command_begin><command>snappyHexMesh</command><help_text>
Usage: snappyHexMesh [OPTIONS]
</help_text></command_end>
"""


@pytest.fixture
def corpus_dir(tmp_path):
    for database in (ALLRUN_SCRIPTS, TUTORIALS_STRUCTURE, TUTORIALS_DETAILS):
        (tmp_path / RAW_FILES[database]).write_text(CASE_CORPUS, encoding="utf-8")
    (tmp_path / RAW_FILES[COMMAND_HELP]).write_text(COMMAND_CORPUS, encoding="utf-8")
    return tmp_path


@pytest.fixture(autouse=True)
def _reset_cached_retriever():
    set_retriever(None)
    yield
    set_retriever(None)


# ---------------------------------------------------------------------------
# Corpus parsing
# ---------------------------------------------------------------------------


def test_parses_cases_with_the_metadata_the_index_scripts_produce():
    documents = parse_corpus(TUTORIALS_STRUCTURE, CASE_CORPUS)

    assert len(documents) == 2
    cavity = documents[0].metadata
    assert cavity["case_name"] == "cavity"
    assert cavity["case_domain"] == "incompressible"
    assert cavity["case_category"] == "lidDrivenCavity"
    assert cavity["case_solver"] == "icoFoam"
    assert "<directory_structure>" in cavity["dir_structure"]


def test_allrun_documents_carry_the_script():
    documents = parse_corpus(ALLRUN_SCRIPTS, CASE_CORPUS)

    assert "icoFoam" in documents[0].metadata["allrun_script"]


def test_allrun_matching_text_omits_domain_and_category():
    """Mirrors database/script/faiss_allrun_scripts.py: the script does not depend on them."""
    documents = parse_corpus(ALLRUN_SCRIPTS, CASE_CORPUS)

    assert "lid driven cavity" not in documents[0].page_content
    assert "ico foam" in documents[0].page_content


def test_parses_command_help():
    documents = parse_corpus(COMMAND_HELP, COMMAND_CORPUS)

    assert [d.metadata["command"] for d in documents] == ["blockMesh", "snappyHexMesh"]
    assert "Usage: blockMesh" in documents[0].metadata["help_text"]


def test_an_empty_corpus_yields_no_documents():
    assert parse_corpus(TUTORIALS_STRUCTURE, "") == []


# ---------------------------------------------------------------------------
# Result formatting
# ---------------------------------------------------------------------------


def test_results_carry_every_field_for_the_database():
    documents = parse_corpus(ALLRUN_SCRIPTS, CASE_CORPUS)

    results = format_results(ALLRUN_SCRIPTS, documents[:1], [0.25])

    assert set(results[0]) == {"index", "score", *RESULT_FIELDS[ALLRUN_SCRIPTS]}
    assert results[0]["score"] == 0.25


def test_a_missing_field_gets_a_placeholder():
    results = format_results(ALLRUN_SCRIPTS, [Document(page_content="x")], [None])

    assert results[0]["case_solver"] == "unknown"
    assert results[0]["allrun_script"] == "N/A"


# ---------------------------------------------------------------------------
# GrepRetriever
# ---------------------------------------------------------------------------


def test_grep_finds_a_case_by_its_name(corpus_dir):
    results = GrepRetriever(corpus_dir).retrieve(TUTORIALS_STRUCTURE, "cavity", topk=1)

    assert results[0]["case_name"] == "cavity"


def test_grep_finds_a_case_by_its_solver(corpus_dir):
    results = GrepRetriever(corpus_dir).retrieve(TUTORIALS_STRUCTURE, "simpleFoam", topk=1)

    assert results[0]["case_name"] == "pitzDaily"


def test_grep_splits_camel_case_the_way_the_corpus_was_indexed(corpus_dir):
    """"lidDrivenCavity" in the corpus is stored as "lid driven cavity"."""
    results = GrepRetriever(corpus_dir).retrieve(TUTORIALS_STRUCTURE, "lidDrivenCavity", topk=1)

    assert results[0]["case_category"] == "lidDrivenCavity"


def test_grep_finds_a_command(corpus_dir):
    results = GrepRetriever(corpus_dir).retrieve(COMMAND_HELP, "blockMesh", topk=1)

    assert results[0]["command"] == "blockMesh"
    assert "Usage: blockMesh" in results[0]["help_text"]


def test_grep_ranks_the_better_match_first(corpus_dir):
    results = GrepRetriever(corpus_dir).retrieve(TUTORIALS_STRUCTURE, "cavity icoFoam", topk=2)

    assert results[0]["case_name"] == "cavity"
    assert results[0]["score"] < results[1]["score"]


def test_grep_weighs_the_specific_term_over_the_common_ones(corpus_dir):
    """"cavity icoFoam" must not tie every icoFoam case: "cavity" is what identifies it."""
    results = GrepRetriever(corpus_dir).retrieve(ALLRUN_SCRIPTS, "cavity icoFoam", topk=2)

    assert results[0]["case_name"] == "cavity"
    assert results[0]["score"] == 0.0
    assert results[1]["score"] > 0.0


def test_grep_scores_are_distances_so_smaller_is_closer(corpus_dir):
    results = GrepRetriever(corpus_dir).retrieve(COMMAND_HELP, "blockMesh", topk=2)

    assert results[0]["score"] == 0.0
    assert all(0.0 <= r["score"] <= 1.0 for r in results)


def test_grep_returns_fewer_results_rather_than_irrelevant_ones(corpus_dir):
    results = GrepRetriever(corpus_dir).retrieve(COMMAND_HELP, "blockMesh", topk=5)

    # snappyHexMesh shares the token "mesh", so it is a weak but real match; nothing else is.
    assert len(results) == 2


def test_grep_raises_when_nothing_matches_at_all(corpus_dir):
    with pytest.raises(ValueError, match="No documents found"):
        GrepRetriever(corpus_dir).retrieve(COMMAND_HELP, "zzzz", topk=1)


def test_grep_rejects_an_unknown_database(corpus_dir):
    with pytest.raises(ValueError, match="Unknown database"):
        GrepRetriever(corpus_dir).retrieve("openfoam_nonsense", "cavity")


def test_grep_reports_a_missing_corpus_file(tmp_path):
    with pytest.raises(CorpusUnavailableError, match="not found"):
        GrepRetriever(tmp_path).retrieve(TUTORIALS_STRUCTURE, "cavity")


def test_grep_reports_an_unfetched_lfs_pointer(tmp_path):
    """Searching a pointer file would silently find nothing; say why instead."""
    (tmp_path / RAW_FILES[TUTORIALS_STRUCTURE]).write_bytes(
        b"version https://git-lfs.github.com/spec/v1\n"
        b"oid sha256:" + b"a" * 64 + b"\nsize 1234\n"
    )

    with pytest.raises(CorpusUnavailableError, match="git lfs pull"):
        GrepRetriever(tmp_path).retrieve(TUTORIALS_STRUCTURE, "cavity")


def test_grep_parses_each_corpus_once(corpus_dir):
    retriever = GrepRetriever(corpus_dir)
    retriever.retrieve(TUTORIALS_STRUCTURE, "cavity")
    loaded = retriever.documents(TUTORIALS_STRUCTURE)

    assert retriever.documents(TUTORIALS_STRUCTURE) is loaded


def test_grep_needs_no_embedding_model(corpus_dir, monkeypatch):
    """The whole point: retrieval without torch."""
    import foamagent.utils as utils

    monkeypatch.setattr(
        utils, "get_embedding_model", lambda *a, **k: pytest.fail("grep loaded an embedding model")
    )
    monkeypatch.setattr(
        utils, "get_faiss_dbs", lambda *a, **k: pytest.fail("grep loaded a FAISS index")
    )

    assert GrepRetriever(corpus_dir).retrieve(TUTORIALS_STRUCTURE, "cavity")


# ---------------------------------------------------------------------------
# FaissRetriever
# ---------------------------------------------------------------------------


class _FakeVectorStore:
    def __init__(self, documents, scores):
        self.documents = documents
        self.scores = scores
        self.queries = []

    def similarity_search_with_score(self, query, k):
        self.queries.append(query)
        return list(zip(self.documents, self.scores))[:k]

    def similarity_search(self, query, k):
        self.queries.append(query)
        return self.documents[:k]


def _fake_documents():
    return parse_corpus(TUTORIALS_STRUCTURE, CASE_CORPUS)


def test_faiss_formats_results_the_same_way_as_grep(corpus_dir):
    store = _FakeVectorStore(_fake_documents(), [0.1, 0.9])
    faiss_results = FaissRetriever({TUTORIALS_STRUCTURE: store}).retrieve(
        TUTORIALS_STRUCTURE, "cavity", topk=1
    )
    grep_results = GrepRetriever(corpus_dir).retrieve(TUTORIALS_STRUCTURE, "cavity", topk=1)

    assert set(faiss_results[0]) == set(grep_results[0])
    assert faiss_results[0]["case_name"] == grep_results[0]["case_name"]


def test_faiss_tokenizes_the_query():
    store = _FakeVectorStore(_fake_documents(), [0.1, 0.9])

    FaissRetriever({TUTORIALS_STRUCTURE: store}).retrieve(TUTORIALS_STRUCTURE, "lidDrivenCavity")

    assert store.queries == ["lid driven cavity"]


def test_faiss_falls_back_to_the_unscored_search():
    class UnscoredStore(_FakeVectorStore):
        def similarity_search_with_score(self, query, k):
            raise NotImplementedError

    store = UnscoredStore(_fake_documents(), [])
    results = FaissRetriever({TUTORIALS_STRUCTURE: store}).retrieve(TUTORIALS_STRUCTURE, "cavity")

    assert results[0]["score"] is None


def test_faiss_reports_an_index_that_was_not_loaded():
    with pytest.raises(ValueError, match="is not loaded"):
        FaissRetriever({}).retrieve(TUTORIALS_STRUCTURE, "cavity")


# ---------------------------------------------------------------------------
# Backend selection
# ---------------------------------------------------------------------------


def test_faiss_is_the_default(monkeypatch):
    monkeypatch.delenv("FOAMAGENT_RETRIEVAL_BACKEND", raising=False)

    assert get_retriever().name == DEFAULT_BACKEND == "faiss"


def test_the_backend_can_be_switched_by_environment(monkeypatch):
    monkeypatch.setenv("FOAMAGENT_RETRIEVAL_BACKEND", "grep")

    assert isinstance(get_retriever(), GrepRetriever)


def test_an_unknown_backend_falls_back_to_the_default(monkeypatch):
    monkeypatch.setenv("FOAMAGENT_RETRIEVAL_BACKEND", "elasticsearch")

    assert get_retriever().name == DEFAULT_BACKEND


def test_the_retriever_is_reused_between_calls(monkeypatch):
    monkeypatch.setenv("FOAMAGENT_RETRIEVAL_BACKEND", "grep")

    assert get_retriever() is get_retriever()


def test_an_explicit_backend_does_not_disturb_the_cached_one(monkeypatch):
    monkeypatch.setenv("FOAMAGENT_RETRIEVAL_BACKEND", "grep")
    cached = get_retriever()

    assert get_retriever("faiss").name == "faiss"
    assert get_retriever() is cached
