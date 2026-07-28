"""Matching administrative names between datasets that disagree about spelling.

This is the step that quietly decides whether a geospatial join is any good.
A statistics office writes "Bengaluru Urban"; the boundary file says
"BANGALORE URBAN"; a field spreadsheet says "Bangalore (Urban)". All three are
the same district, and a naive equality join silently drops two of them.

The approach here is deliberately conservative and explainable:

  1. Normalise aggressively (case, punctuation, articles, common suffixes).
  2. Accept an exact match on the normalised form.
  3. Otherwise fall back to edit distance, but only within a tight threshold
     and only when the best candidate is clearly better than the runner-up.

Anything below that bar is reported as unmatched rather than guessed at. In
this kind of work a wrong join is far more expensive than a missing row,
because it looks like data.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

__all__ = ["normalise", "edit_distance", "similarity", "Matcher", "MatchResult"]

# Dropped wholesale — they carry no distinguishing information in admin names.
_NOISE_WORDS = frozenset(
    {
        "district",
        "dist",
        "taluk",
        "taluka",
        "tehsil",
        "block",
        "mandal",
        "county",
        "province",
        "region",
        "division",
        "subdivision",
        "the",
        "of",
        "and",
    }
)

# Apostrophes are elided rather than split on: "Mary's" and "Marys" are the
# same place, but splitting would leave a stray "s" token.
_ELIDED = re.compile(r"['’ʼ]")
_PUNCTUATION = re.compile(r"[^\w\s]", re.UNICODE)
_WHITESPACE = re.compile(r"\s+")


def normalise(name: str) -> str:
    """Reduce a place name to a comparable key.

    Strips accents, case, punctuation and structural noise words, then
    collapses whitespace.

    >>> normalise("Bengaluru Urban District")
    'bengaluru urban'
    >>> normalise("  BANGALORE  (Urban) ")
    'bangalore urban'
    """
    decomposed = unicodedata.normalize("NFKD", name)
    ascii_only = "".join(ch for ch in decomposed if not unicodedata.combining(ch))

    lowered = _ELIDED.sub("", ascii_only.lower())
    depunctuated = _PUNCTUATION.sub(" ", lowered)
    collapsed = _WHITESPACE.sub(" ", depunctuated).strip()

    words = [w for w in collapsed.split(" ") if w and w not in _NOISE_WORDS]
    return " ".join(words) if words else collapsed


def edit_distance(a: str, b: str, cap: int | None = None) -> int:
    """Levenshtein distance, with early exit once `cap` is exceeded.

    The cap matters: comparing one name against thousands of candidates is the
    inner loop of a join, and most pairs are obviously unrelated.
    """
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)

    if len(a) < len(b):
        a, b = b, a

    if cap is not None and len(a) - len(b) > cap:
        return cap + 1

    previous = list(range(len(b) + 1))

    for i, ch_a in enumerate(a, start=1):
        current = [i]
        for j, ch_b in enumerate(b, start=1):
            current.append(
                min(
                    previous[j] + 1,          # deletion
                    current[j - 1] + 1,       # insertion
                    previous[j - 1] + (ch_a != ch_b),  # substitution
                )
            )
        if cap is not None and min(current) > cap:
            return cap + 1
        previous = current

    return previous[-1]


def similarity(a: str, b: str) -> float:
    """Edit distance rescaled to 0.0–1.0, where 1.0 is identical."""
    if not a and not b:
        return 1.0
    longest = max(len(a), len(b))
    return 1.0 - (edit_distance(a, b) / longest)


@dataclass(frozen=True)
class MatchResult:
    """One resolved lookup.

    `method` is "alias", "exact", "fuzzy" or "none"; `score` is 1.0 for alias
    and exact matches. `margin` is how far ahead of the runner-up the winner
    was, which is what makes a fuzzy match trustworthy rather than merely
    closest.
    """

    query: str
    matched: str | None
    method: str
    score: float
    margin: float

    @property
    def ok(self) -> bool:
        return self.matched is not None


class Matcher:
    """Resolves names against a fixed set of canonical names.

    Renames are the case fuzzy matching cannot solve. Mysore → Mysuru scores
    0.67; Madras → Chennai scores near zero. No threshold recovers those
    without also inventing matches elsewhere, so they belong in an explicit
    alias table that a human can review.

    Args:
        canonical: the authoritative names, usually from the boundary file.
        aliases: known variant → canonical mappings, applied before scoring.
        threshold: minimum similarity for a fuzzy match (0–1).
        min_margin: how far the best candidate must beat the second-best.
            Guards against a name sitting equidistant between two real places.
    """

    def __init__(
        self,
        canonical: list[str],
        *,
        aliases: dict[str, str] | None = None,
        threshold: float = 0.85,
        min_margin: float = 0.05,
    ) -> None:
        if not 0 < threshold <= 1:
            raise ValueError("threshold must be in (0, 1]")

        self.threshold = threshold
        self.min_margin = min_margin
        self._canonical = list(canonical)
        self._index: dict[str, str] = {}

        for name in canonical:
            key = normalise(name)
            # First writer wins, so a duplicate spelling can't shadow the
            # canonical one silently.
            self._index.setdefault(key, name)

        # Aliases are normalised on both sides, so the table can be written in
        # whatever casing the source data happens to use.
        self._aliases: dict[str, str] = {}
        for variant, target in (aliases or {}).items():
            resolved = self._index.get(normalise(target))
            if resolved is None:
                raise ValueError(
                    f"alias {variant!r} points at {target!r}, which is not a canonical name"
                )
            self._aliases[normalise(variant)] = resolved

    def __len__(self) -> int:
        return len(self._canonical)

    def match(self, query: str) -> MatchResult:
        key = normalise(query)

        aliased = self._aliases.get(key)
        if aliased is not None:
            return MatchResult(query, aliased, "alias", 1.0, 1.0)

        exact = self._index.get(key)
        if exact is not None:
            return MatchResult(query, exact, "exact", 1.0, 1.0)

        scored = sorted(
            ((similarity(key, candidate), name) for candidate, name in self._index.items()),
            key=lambda pair: pair[0],
            reverse=True,
        )

        if not scored:
            return MatchResult(query, None, "none", 0.0, 0.0)

        best_score, best_name = scored[0]
        runner_up = scored[1][0] if len(scored) > 1 else 0.0
        margin = best_score - runner_up

        if best_score >= self.threshold and margin >= self.min_margin:
            return MatchResult(query, best_name, "fuzzy", round(best_score, 4), round(margin, 4))

        return MatchResult(query, None, "none", round(best_score, 4), round(margin, 4))
