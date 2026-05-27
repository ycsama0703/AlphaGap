from pipeline.analyze.gaps import (
    _only_reviewed_theoretical_gaps,
    _only_upgraded_engineering_gaps,
    select_email_experiments,
    suppress_theoretical_email_duplicates,
)
from pipeline.analyze import gaps as gaps_mod


def _item(gap_id: str, gap_type: str, hypothesis: str, *,
          field: str = "factor_investing",
          family: str = "Formulaic Alpha Search",
          upgraded_from: str | None = None) -> dict:
    gap = {
        "_id": gap_id,
        "hypothesis": hypothesis,
        "field_boundary_alignment": {
            "field_id": field,
            "mechanism_family": family,
        },
        "ai_anchor": {"concept": hypothesis},
        "fin_anchor": {"description": "factor expression search"},
    }
    if upgraded_from:
        gap["upgraded_from_theoretical"] = upgraded_from
    return {"type": gap_type, "gap": gap, "score": {"passes_email_threshold": True}}


def test_explicit_engineering_upgrade_suppresses_theoretical_email_gap():
    engineering = _item(
        "ENG-1", "engineering", "用验证反馈改进因子搜索", upgraded_from="TH-1",
    )
    theoretical = _item("TH-1", "theoretical", "用验证反馈改进因子搜索")

    kept, suppressed = suppress_theoretical_email_duplicates([engineering, theoretical])

    assert kept == [engineering]
    assert suppressed == [theoretical]
    assert theoretical["_email_suppressed_by"] == "ENG-1"
    assert "explicit engineering upgrade" in theoretical["_email_suppressed_reason"]


def test_overlapping_same_boundary_gap_is_suppressed_without_upgrade_marker():
    engineering = _item(
        "ENG-1",
        "engineering",
        "用密集per-step credit assignment改进因子搜索中关键表达式与填充步骤的信用分配，提升搜索效率",
    )
    theoretical = _item(
        "TH-1",
        "theoretical",
        "用未来KL散度密集优势信号改进因子搜索中关键表达式与填充步骤的信用分配",
    )

    kept, suppressed = suppress_theoretical_email_duplicates([engineering, theoretical])

    assert kept == [engineering]
    assert suppressed == [theoretical]
    assert "overlapping transfer hypothesis" in theoretical["_email_suppressed_reason"]


def test_same_field_but_different_mechanism_family_is_kept():
    engineering = _item("ENG-1", "engineering", "用验证反馈改进因子搜索")
    theoretical = _item(
        "TH-1",
        "theoretical",
        "用拥挤度监控诊断因子衰减",
        family="Factor Decay And Crowding Diagnosis",
    )

    kept, suppressed = suppress_theoretical_email_duplicates([engineering, theoretical])

    assert kept == [engineering, theoretical]
    assert suppressed == []


def test_daily_email_includes_only_runnable_engineering_experiments():
    theory = _item("TH-1", "theoretical", "novel discussion")
    engineering = _item("ENG-1", "engineering", "runnable experiment")
    low_score = _item("ENG-2", "engineering", "not ready")
    low_score["score"]["passes_email_threshold"] = False

    assert select_email_experiments([theory, low_score, engineering]) == [engineering]


def test_adversarial_mode_drops_theory_without_reviewed_candidate_source():
    candidates = [{"idx": 3}]
    gaps = [
        {"_id": "TH-1", "source_candidate_idx": 3},
        {"_id": "TH-2", "source_candidate_idx": 9},
    ]

    assert _only_reviewed_theoretical_gaps(gaps, candidates) == [gaps[0]]


def test_adversarial_mode_allows_only_engineering_upgrades_of_theory():
    theories = [{"_id": "TH-1"}]
    engineering = [
        {"_id": "ENG-1", "upgraded_from_theoretical": "TH-1"},
        {"_id": "ENG-2"},
    ]

    assert _only_upgraded_engineering_gaps(engineering, theories) == [engineering[0]]


def test_all_rejected_adversarial_candidates_skip_expansion(monkeypatch):
    context = {
        "_valid_ai_ids": set(),
        "_valid_fin_ids": set(),
        "_mappings_brief": [],
        "ai_recent_papers": [],
    }
    monkeypatch.setattr(gaps_mod, "build_gap_context", lambda *args, **kwargs: context)
    monkeypatch.setattr(gaps_mod, "enumerate_candidates", lambda *args, **kwargs: [{"idx": 1}])
    monkeypatch.setattr(
        gaps_mod.risk_audit_mod,
        "audit_candidates",
        lambda *args, **kwargs: ([], {"enabled": True, "fallback": False, "decisions": []}),
    )
    monkeypatch.setattr(
        gaps_mod,
        "generate_theoretical_gaps",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not expand")),
    )

    class Client:
        def estimate_cost_usd(self):
            return 0.0

    result = gaps_mod.run_gap_pipeline(adversarial_review=True, client=Client())

    assert result["theoretical"] == []
    assert result["engineering"] == []
    assert result["email_ready"] == []
