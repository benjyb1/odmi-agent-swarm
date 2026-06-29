"""Faithfulness evaluation for finished briefing packs.

The swarm's quote-gate and verifier guard each point as it is built. This
harness is the independent audit afterwards: it decomposes every point into
atomic claims and labels each against the cited quote alone
(supported / contradicted / not_addressed), then reports a faithfulness rate.
It is what lets the handover state a number for "how often a published point
is actually supported by its source", rather than asking WHO to take that on
trust.

The grader is a model call injected as a callable with the same shape as
``who_speech.llm.structured``, so the aggregation is unit-tested without a live
model, and a second grader from a different model family can be passed to
guard against a single grader's blind spots (the cross-family check).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from who_speech import llm, prompts

if False:  # typing only; avoids importing swarm at module load
    from who_speech.swarm import BriefingPack

Label = Literal["supported", "contradicted", "not_addressed"]

# A grader has the signature of who_speech.llm.structured.
Grader = Callable[..., tuple["PointGrading", dict]]


class AtomicClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claim: str
    label: Label
    reason: str = ""


class PointGrading(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claims: list[AtomicClaim] = Field(default_factory=list)


@dataclass
class PointResult:
    point: str
    quote: str
    grading: PointGrading
    faithful: bool
    cross_faithful: Optional[bool]

    @property
    def confirmed(self) -> bool:
        """Faithful by the primary grader, and by the cross-grader if present."""
        return self.faithful and (self.cross_faithful is not False)


@dataclass
class PackFaithfulness:
    query: str
    results: list[PointResult]

    @property
    def n_points(self) -> int:
        return len(self.results)

    @property
    def n_confirmed(self) -> int:
        return sum(1 for r in self.results if r.confirmed)

    @property
    def faithfulness_rate(self) -> Optional[float]:
        return self.n_confirmed / self.n_points if self.results else None

    @property
    def claim_label_counts(self) -> dict[str, int]:
        counts = {"supported": 0, "contradicted": 0, "not_addressed": 0}
        for r in self.results:
            for c in r.grading.claims:
                counts[c.label] = counts.get(c.label, 0) + 1
        return counts


def point_is_faithful(grading: PointGrading) -> bool:
    """True iff the point has at least one claim and every claim is supported."""
    return bool(grading.claims) and all(c.label == "supported" for c in grading.claims)


def grade_point(point: str, quote: str, *, grader: Grader = llm.structured) -> PointGrading:
    user = f'Speaking point: {point}\n\nCited verbatim quote:\n"{quote}"'
    grading, _ = grader(
        system=prompts.FAITHFULNESS_SYSTEM,
        user_message=user,
        output_schema=PointGrading,
        usage_context="who_speech:faithfulness",
        max_tokens=800,
    )
    return grading


def evaluate_pack(
    pack: "BriefingPack",
    *,
    grader: Grader = llm.structured,
    cross_grader: Optional[Grader] = None,
) -> PackFaithfulness:
    """Grade every point in the pack, optionally with a cross-family second grader."""
    results: list[PointResult] = []
    for p in pack.points:
        grading = grade_point(p.point, p.quote, grader=grader)
        faithful = point_is_faithful(grading)
        cross_faithful: Optional[bool] = None
        if cross_grader is not None:
            cross_faithful = point_is_faithful(grade_point(p.point, p.quote, grader=cross_grader))
        results.append(
            PointResult(
                point=p.point, quote=p.quote, grading=grading,
                faithful=faithful, cross_faithful=cross_faithful,
            )
        )
    return PackFaithfulness(query=pack.query, results=results)
