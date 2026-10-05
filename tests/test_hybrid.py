"""QNT-312: BM25 + RRF parity with equity-data-agent's shared.retrieval (QNT-262)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "lambda" / "retrieval_service"))

from hybrid import RRF_K, bm25_ranking, reciprocal_rank_fusion  # pyright: ignore[reportMissingImports]


def test_rrf_k_matches_original() -> None:
    assert RRF_K == 60


def test_rrf_rewards_docs_in_both_lists() -> None:
    fused = reciprocal_rank_fusion([["a", "b"], ["b", "c"]])
    assert [doc_id for doc_id, _ in fused] == ["b", "a", "c"]
    assert fused[0][1] == 1 / 62 + 1 / 61


def test_rrf_ties_broken_by_id() -> None:
    fused = reciprocal_rank_fusion([["z"], ["a"]])
    assert [doc_id for doc_id, _ in fused] == ["a", "z"]


def test_bm25_ranks_exact_term_first_and_drops_zero_scores() -> None:
    corpus = {
        "1": "Apple signs chip deal with Intel",
        "2": "Apple reports record iPhone sales",
        "3": "Nvidia data center revenue grows",
        "4": "Memory prices fall again",
    }
    ranking = bm25_ranking(corpus, "Intel chip deal", limit=20)
    assert ranking == ["1"]


def test_bm25_tokenizer_is_case_insensitive_word_split() -> None:
    corpus = {"1": "SK-Hynix HBM supply", "2": "unrelated text here", "3": "more filler words"}
    assert bm25_ranking(corpus, "sk hynix", limit=20) == ["1"]


def test_bm25_respects_limit_and_empty_inputs() -> None:
    corpus = {str(i): f"deal number {i}" for i in range(10)}
    assert len(bm25_ranking(corpus, "deal", limit=3)) <= 3
    assert bm25_ranking({}, "deal", limit=3) == []
    assert bm25_ranking(corpus, "   ", limit=3) == []
