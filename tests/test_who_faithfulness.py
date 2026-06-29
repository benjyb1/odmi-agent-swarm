"""Faithfulness evaluation harness.

Decomposes each point into atomic claims and labels every claim against the
cited quote alone as supported / contradicted / not_addressed. A point is
faithful only if every claim is supported. An optional cross-grader (a
different model family) must also agree before a point is counted confirmed.
The grader is injected, so the aggregation logic is tested without any live
model call.
"""
from __future__ import annotations

from who_speech import faithfulness as ff
from who_speech.faithfulness import AtomicClaim, PointGrading
from who_speech.swarm import BriefingPack, BriefingPoint


def _point(point, quote="a verbatim quote"):
    return BriefingPoint(point=point, quote=quote, citation="C", iris_url="U", page=1, confidence=0.8)


def _pack(points):
    return BriefingPack(query="q", points=points, abstained=False, note="")


def _grader_returning(mapping):
    def grader(*, system, user_message, output_schema, usage_context, max_tokens=400):
        for text, grading in mapping.items():
            if text in user_message:
                return grading, {}
        raise AssertionError("no scripted grading for the message")

    return grader


def test_point_faithful_when_all_claims_supported():
    g = PointGrading(claims=[
        AtomicClaim(claim="a", label="supported"),
        AtomicClaim(claim="b", label="supported"),
    ])
    assert ff.point_is_faithful(g) is True


def test_point_unfaithful_when_a_claim_contradicted():
    g = PointGrading(claims=[
        AtomicClaim(claim="a", label="supported"),
        AtomicClaim(claim="b", label="contradicted"),
    ])
    assert ff.point_is_faithful(g) is False


def test_point_unfaithful_when_a_claim_not_addressed():
    g = PointGrading(claims=[AtomicClaim(claim="a", label="not_addressed")])
    assert ff.point_is_faithful(g) is False


def test_point_unfaithful_when_no_claims():
    assert ff.point_is_faithful(PointGrading(claims=[])) is False


def test_evaluate_pack_faithfulness_rate():
    faithful = PointGrading(claims=[AtomicClaim(claim="x", label="supported")])
    unfaithful = PointGrading(claims=[AtomicClaim(claim="y", label="not_addressed")])
    pack = _pack([_point("POINT_A"), _point("POINT_B")])
    grader = _grader_returning({"POINT_A": faithful, "POINT_B": unfaithful})
    result = ff.evaluate_pack(pack, grader=grader)
    assert result.n_points == 2
    assert result.n_confirmed == 1
    assert result.faithfulness_rate == 0.5


def test_cross_grader_must_also_agree():
    faithful = PointGrading(claims=[AtomicClaim(claim="x", label="supported")])
    contradicted = PointGrading(claims=[AtomicClaim(claim="x", label="contradicted")])
    pack = _pack([_point("POINT_A")])
    primary = _grader_returning({"POINT_A": faithful})
    cross = _grader_returning({"POINT_A": contradicted})
    result = ff.evaluate_pack(pack, grader=primary, cross_grader=cross)
    assert result.n_confirmed == 0
