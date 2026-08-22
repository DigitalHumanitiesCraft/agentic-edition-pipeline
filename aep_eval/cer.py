"""Character error rate with the fidelity/scope decomposition.

CER = Levenshtein(reference, hypothesis) / len(reference), denominator the
reference, values above 1.0 are reported as they are. The edit operations are
split the way zbz-ocr-tei does it: substitutions, deletions and short
insertions are fidelity (real recognition errors), insertions of at least
`scope_block_min` characters are scope surplus (hypothesis carries text the
reference does not cover). fidelity + scope == total distance.

rapidfuzz provides distance and opcodes from the same minimal alignment; a
pure-Python backtrace would need O(n*m) memory and is out of reach for
documents of several hundred thousand characters.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

SCOPE_BLOCK_MIN = 50


@dataclass(frozen=True)
class CerResult:
    reference_chars: int
    hypothesis_chars: int
    distance: int
    fidelity_distance: int
    scope_insertion_distance: int
    scope_block_min: int

    @property
    def cer(self) -> float:
        return _rate(self.distance, self.reference_chars, self.hypothesis_chars)

    @property
    def cer_fidelity(self) -> float:
        return _rate(
            self.fidelity_distance, self.reference_chars, self.hypothesis_chars
        )

    @property
    def scope_insertion_rate(self) -> float:
        if self.reference_chars == 0:
            return 0.0
        return self.scope_insertion_distance / self.reference_chars

    @property
    def decomposition_consistent(self) -> bool:
        """True when fidelity and scope sum to the minimal edit distance."""
        return self.fidelity_distance + self.scope_insertion_distance == self.distance

    def to_dict(self) -> dict:
        data = asdict(self)
        data.update(
            cer=self.cer,
            cer_fidelity=self.cer_fidelity,
            scope_insertion_rate=self.scope_insertion_rate,
            decomposition_consistent=self.decomposition_consistent,
        )
        return data


def _rate(distance: int, reference_chars: int, hypothesis_chars: int) -> float:
    if reference_chars == 0:
        return 0.0 if hypothesis_chars == 0 else 1.0
    return distance / reference_chars


def _opcodes(reference: str, hypothesis: str) -> list[tuple[str, int, int, int, int]]:
    try:
        from rapidfuzz.distance import Levenshtein
    except ImportError as exc:  # pragma: no cover - environment guard
        raise RuntimeError(
            "rapidfuzz is required for aep_eval (pip install rapidfuzz)"
        ) from exc
    return [
        (op.tag, op.src_start, op.src_end, op.dest_start, op.dest_end)
        for op in Levenshtein.opcodes(reference, hypothesis)
    ]


def levenshtein(reference: str, hypothesis: str) -> int:
    try:
        from rapidfuzz.distance import Levenshtein
    except ImportError as exc:  # pragma: no cover - environment guard
        raise RuntimeError(
            "rapidfuzz is required for aep_eval (pip install rapidfuzz)"
        ) from exc
    return Levenshtein.distance(reference, hypothesis)


def score(
    reference: str, hypothesis: str, scope_block_min: int = SCOPE_BLOCK_MIN
) -> CerResult:
    """Score one normalised pair. Both texts must already carry the profile's
    normalisation; this function knows nothing about profiles."""
    fidelity = 0
    scope = 0
    for tag, i1, i2, j1, j2 in _opcodes(reference, hypothesis):
        ref_len, hyp_len = i2 - i1, j2 - j1
        if tag == "equal":
            continue
        if tag == "replace":
            fidelity += max(ref_len, hyp_len)
        elif tag == "delete":
            fidelity += ref_len
        elif tag == "insert":
            if hyp_len >= scope_block_min:
                scope += hyp_len
            else:
                fidelity += hyp_len
    return CerResult(
        reference_chars=len(reference),
        hypothesis_chars=len(hypothesis),
        distance=levenshtein(reference, hypothesis),
        fidelity_distance=fidelity,
        scope_insertion_distance=scope,
        scope_block_min=scope_block_min,
    )
