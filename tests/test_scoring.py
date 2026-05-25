from pipeline.analyze.scoring import (
    _component_average,
    _support_components,
    email_gate_result,
    mapping_novelty_cap,
    score_gap,
)


def test_mapping_novelty_cap_for_mature_mapping():
    gap = {
        "hypothesis": "Use dense step-level credit assignment for factor pipeline attribution",
        "ai_anchor": {"concept": "dense step-level credit assignment"},
        "fin_anchor": {"description": "factor construction pipeline attribution"},
        "structural_mapping": {
            "ai_data_structure": "step sequence with credit signals",
            "fin_data_structure": "multi-step factor construction pipeline",
            "bridge_required": "treat factor construction steps as decision steps",
        },
    }
    mappings = [{
        "id": "M0001",
        "status": "mature",
        "ai_mechanism": "dense step-level credit assignment",
        "fin_structure": "multi-step factor construction pipeline",
        "bridge": "treat factor construction steps as decision steps",
    }]

    cap = mapping_novelty_cap(gap, mappings)

    assert cap["mapping_id"] == "M0001"
    assert cap["status"] == "mature"
    assert cap["cap"] == 4


def test_mapping_novelty_cap_for_open_gap_mapping():
    gap = {
        "hypothesis": "Use verifier feedback loops to reduce OOS overfitting in alpha search",
        "ai_anchor": {"concept": "verifier feedback loop"},
        "fin_anchor": {"description": "alpha search OOS overfitting"},
    }
    mappings = [{
        "id": "M0002",
        "status": "open_gap",
        "ai_mechanism": "verifier feedback loop",
        "fin_structure": "alpha search OOS overfitting",
    }]

    cap = mapping_novelty_cap(gap, mappings)

    assert cap["mapping_id"] == "M0002"
    assert cap["cap"] == 8


def test_mapping_novelty_cap_ignores_unrelated_mapping():
    gap = {
        "hypothesis": "Use latent recursive communication for multi-agent portfolio allocation",
        "ai_anchor": {"concept": "latent recursive communication"},
    }
    mappings = [{
        "id": "M0003",
        "status": "mature",
        "ai_mechanism": "sparse representation probing",
        "fin_structure": "factor decay diagnostics",
    }]

    assert mapping_novelty_cap(gap, mappings) is None


def test_support_components_are_clamped_and_averaged():
    components = _support_components({
        "structural_homology": 8,
        "failure_mode_match": 9,
        "assumption_transferability": 7,
        "identifiable_prediction": 8,
        "theoretical_anchors": 12,
    })

    assert components == {
        "structural_homology": 8,
        "failure_mode_match": 9,
        "assumption_transferability": 7,
        "identifiable_prediction": 8,
        "theoretical_anchors": 10,
    }
    assert _component_average(components) == 8.4


def test_missing_support_components_default_low():
    components = _support_components({})

    assert all(value == 1 for value in components.values())
    assert _component_average(components) == 1.0


def test_engineering_email_gate_uses_total_threshold():
    result = email_gate_result(
        "engineering",
        novelty=8,
        actionability=8,
        theoretical_support=5.0,
        total=8.0,
    )

    assert result["passes"] is True
    assert result["gate"] == "engineering_total"


def test_theoretical_email_gate_allows_high_novelty_conceptual_gap():
    result = email_gate_result(
        "theoretical",
        novelty=9,
        actionability=4,
        theoretical_support=5.4,
        total=6.5,
    )

    assert result["passes"] is True
    assert result["gate"] == "theoretical_high_novelty"


def test_theoretical_email_gate_rejects_low_support():
    result = email_gate_result(
        "theoretical",
        novelty=9,
        actionability=4,
        theoretical_support=4.8,
        total=6.5,
    )

    assert result["passes"] is False


def test_scoring_uses_reasoning_model():
    class FakeClient:
        def __init__(self):
            self.kwargs = None

        def chat_json(self, **kwargs):
            self.kwargs = kwargs
            return {
                "novelty": 8,
                "actionability": 8,
                "theoretical_support_components": {},
            }

    client = FakeClient()
    score_gap({}, "engineering", [], client=client)

    assert client.kwargs["reasoning"] is True
