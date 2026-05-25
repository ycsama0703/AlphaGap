from pipeline.analyze.self_check import check_gap, downgrade_to_theoretical
from pipeline.config import load_prompt


def test_engineering_empirical_validity_check_is_part_of_prompt():
    prompt = load_prompt("06_gap_self_check")

    assert "P. empirical_validity_risk" in prompt
    assert "look-ahead leakage" in prompt
    assert "survivorship bias" in prompt
    assert "baseline" in prompt


def test_downgrade_preserves_audit_origin_and_boundary():
    gap = {
        "_id": "ENG-1",
        "_origin": {"candidate_idx": 7, "audit_verdict": "revise"},
        "risk_audit": {"verdict": "revise"},
        "field_boundary_alignment": {"field_id": "factor_investing"},
        "structural_mapping": {"match_status": "partial"},
        "hypothesis": "test",
    }

    downgraded = downgrade_to_theoretical(gap)

    assert downgraded["_origin"]["candidate_idx"] == 7
    assert downgraded["risk_audit"]["verdict"] == "revise"
    assert downgraded["field_boundary_alignment"]["field_id"] == "factor_investing"
    assert downgraded["structural_mapping"]["match_status"] == "partial"


def test_self_check_uses_reasoning_model():
    class FakeClient:
        def __init__(self):
            self.kwargs = None

        def chat_json(self, **kwargs):
            self.kwargs = kwargs
            return {"overall_verdict": "accept"}

    client = FakeClient()
    check_gap({}, "theoretical", set(), set(), [], client=client)

    assert client.kwargs["reasoning"] is True
