"""QNT-312: BM25 + reciprocal rank fusion -- the keyword half of hybrid retrieval.

Ported from equity-data-agent's ``shared.retrieval`` (QNT-262) with the same constants and
tie-breaking, so the AWS hybrid leg reproduces the original's: rank_bm25 BM25Okapi over a
lowercase ``\\w+`` tokenizer, zero-score docs dropped, RRF with k=60. Pure functions -- no
AWS clients -- so tests import this module without the handler's env/boto3 setup.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

from rank_bm25 import BM25Okapi

# Cormack et al. RRF default, same as the original -- not tuned per corpus.
RRF_K = 60

_TOKEN_RE = re.compile(r"\w+")


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def reciprocal_rank_fusion(
    rankings: Sequence[Sequence[str]], *, k: int = RRF_K
) -> list[tuple[str, float]]:
    """Fuse best-first id lists; score = sum(1 / (k + rank)), ties broken by id."""
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, doc_id in enumerate(ranking, start=1):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))


def bm25_ranking(corpus: Mapping[str, str], query: str, *, limit: int) -> list[str]:
    """Rank ``corpus`` ({id: text}) by BM25 against ``query``; up to ``limit`` ids, best-first."""
    if not corpus or not query.strip():
        return []
    ids = list(corpus)
    bm25 = BM25Okapi([_tokenize(corpus[i]) for i in ids])
    scores = bm25.get_scores(_tokenize(query))
    ranked = sorted(zip(ids, scores, strict=True), key=lambda kv: (-kv[1], kv[0]))
    # A doc sharing no query term isn't a lexical hit -- don't pad the fusion list with it.
    return [doc_id for doc_id, score in ranked[:limit] if score > 0.0]
