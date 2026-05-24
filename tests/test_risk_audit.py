from pipeline.analyze.risk_audit import audit_candidates


class FakeClient:
    def __init__(self, result=None, error: Exception | None = None):
        self.result = result
        self.error = error
        self.calls = []

    def chat_json(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.result


def _candidate(idx: int, one_liner: str) -> dict:
    return {
        "idx": idx,
        "one_liner": one_liner,
        "field_boundary_alignment": {
            "field_id": "factor_investing",
            "mechanism_family": "Formulaic Alpha Search",
        },
    }


def test_audit_candidates_keeps_pass_revises_candidate_and_drops_reject():
    candidates = [
        _candidate(1, "proposal one"),
        _candidate(2, "proposal two"),
        _candidate(3, "proposal three"),
    ]
    result = {
        "reviews": [
            {
                "candidate_idx": 1,
                "verdict": "pass",
                "failure_class": "none",
                "strongest_objection": "reward signal may be noisy",
            },
            {
                "candidate_idx": 2,
                "verdict": "revise",
                "failure_class": "mechanism_transfer",
                "strongest_objection": "target is too broad",
                "required_revision": "restrict to factor formula search",
                "revised_one_liner": "narrow revised proposal",
            },
            {
                "candidate_idx": 3,
                "verdict": "reject",
                "failure_class": "boundary",
                "strongest_objection": "falls outside the field boundary",
            },
        ]
    }

    client = FakeClient(result)
    retained, summary = audit_candidates(candidates, {}, client=client)

    assert [item["idx"] for item in retained] == [1, 2]
    assert retained[1]["one_liner"] == "narrow revised proposal"
    assert retained[1]["original_one_liner"] == "proposal two"
    assert summary["passed"] == 1
    assert summary["revised"] == 1
    assert summary["rejected"] == 1
    assert summary["retained"] == 2
    assert summary["decisions"][1]["failure_classes"] == ["mechanism_transfer"]
    assert client.calls[0]["max_tokens"] == 12288


def test_audit_candidates_fails_open_when_model_call_fails():
    candidates = [_candidate(1, "proposal one")]

    retained, summary = audit_candidates(
        candidates,
        {},
        client=FakeClient(error=ValueError("invalid response")),
    )

    assert retained == candidates
    assert summary["fallback"] is True
    assert summary["retained"] == 1


def test_audit_candidates_falls_back_for_missing_reviews():
    candidates = [_candidate(1, "proposal one")]

    retained, summary = audit_candidates(candidates, {}, client=FakeClient({}))

    assert retained == candidates
    assert summary["fallback"] is True
    assert summary["coverage"] == 0.0
    assert summary["decisions"][0]["verdict"] == "unreviewed"


def test_audit_candidates_falls_back_for_unknown_candidate_idx():
    candidates = [_candidate(1, "proposal one")]
    result = {
        "reviews": [{
            "candidate_idx": 999,
            "verdict": "reject",
            "failure_classes": ["boundary"],
            "strongest_objection": "not an actual input candidate",
        }]
    }

    retained, summary = audit_candidates(candidates, {}, client=FakeClient(result))

    assert retained == candidates
    assert summary["fallback"] is True
    assert summary["reviewed"] == 0


def test_audit_candidates_normalizes_uppercase_verdict_and_multiple_classes():
    result = {
        "reviews": [{
            "candidate_idx": 1,
            "verdict": " REJECT ",
            "failure_classes": ["boundary", "mechanism_transfer"],
            "strongest_objection": "multiple failures",
        }]
    }

    retained, summary = audit_candidates(
        [_candidate(1, "proposal one")], {}, client=FakeClient(result),
    )

    assert retained == []
    assert summary["fallback"] is False
    assert summary["decisions"][0]["verdict"] == "reject"
    assert summary["decisions"][0]["failure_classes"] == [
        "boundary", "mechanism_transfer",
    ]


def test_audit_candidates_all_rejected_is_a_valid_gate_result():
    result = {
        "reviews": [
            {"candidate_idx": 1, "verdict": "reject", "strongest_objection": "weak"},
            {"candidate_idx": 2, "verdict": "reject", "strongest_objection": "duplicate"},
        ]
    }

    retained, summary = audit_candidates(
        [_candidate(1, "one"), _candidate(2, "two")], {}, client=FakeClient(result),
    )

    assert retained == []
    assert summary["rejected"] == 2
    assert summary["coverage"] == 1.0
    assert summary["fallback"] is False
