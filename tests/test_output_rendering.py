from datetime import date
from pathlib import Path

from pipeline.output.email import _gap_card_html
from pipeline.output.inbox import write_daily_inbox


def _gap_item():
    return {
        "type": "theoretical",
        "score": {
            "total": 8.3,
            "novelty": 8,
            "actionability": 9,
            "theoretical_support": 8.0,
            "novelty_reason": "novel",
            "actionability_reason": "actionable",
            "theoretical_support_reason": "grounded",
            "passes_email_threshold": True,
            "email_gate": "theoretical_high_novelty",
            "email_gate_reason": "theoretical gate",
        },
        "gap": {
            "_id": "TH-1",
            "hypothesis": "用证据充分性评分改进金融 RAG 检索",
            "field_boundary_alignment": {
                "field_id": "financial_nlp",
                "mechanism_family": "Evidence-Grounded Financial Retrieval",
                "open_bottleneck": "Realistic query retrieval",
                "good_transfer_target": "Subclaim-level retrieval",
                "bad_target_avoided": "generic RAG over SEC filings",
                "why_aligned": "聚焦金融 RAG 的证据支撑边界",
            },
            "ai_anchor": {"paper_id": "ai1", "concept": "evidence sufficiency scoring"},
            "fin_anchor": {"description": "financial RAG evidence retrieval"},
        },
    }


def _engineering_gap_item():
    item = _gap_item()
    item["type"] = "engineering"
    item["gap"].update({
        "_id": "ENG-1",
        "hypothesis": "用反馈修复 <因子公式> 并进行执行验证",
        "experimental_roadmap": {
            "data": {
                "sources": ["CRSP", "Compustat"],
                "sample": "US equities",
                "period_frequency": "1990-2024 monthly",
                "split_protocol": "train 1990-2005, test 2015-2024",
                "leakage_controls": ["point-in-time fundamentals"],
            },
            "method": ["解析 DSL 表达式", "执行点时校验", "回测修复后的公式"],
            "metrics": {
                "primary": [
                    {"name": "repair success rate", "success_criterion": "higher than rule repair"},
                    {"name": "OOS RankIC", "success_criterion": "positive after costs"},
                ],
                "secondary": [
                    {"name": "turnover", "purpose": "implementation cost diagnostic"},
                ],
            },
            "baselines": [
                {
                    "name": "Prior repair work",
                    "type": "prior_work",
                    "purpose": "external comparison",
                    "citation": "Author et al. (2025)",
                    "url": "https://arxiv.org/abs/2501.00001",
                },
                {
                    "name": "Genetic programming",
                    "type": "standard_baseline",
                    "purpose": "same search budget",
                    "citation": "grammar search",
                    "url": "",
                },
            ],
            "ablations": [
                {"name": "remove point-in-time checker", "tests_component": "validity checks"},
                {"name": "remove repair feedback", "tests_component": "feedback loop"},
            ],
            "compute_profile": {
                "tier": "medium",
                "requirements": ["cpu", "llm_api"],
                "estimated_runtime": "1-2 weeks",
                "main_bottleneck": "data cleaning",
                "summary": "Backtests run on CPU.",
                "fallback": "Use price-only factors.",
            },
            "estimated_effort": "3 months / 1 person",
            "key_risks": ["Point-in-time leakage", "Repair changes economic intent"],
        },
    })
    return item


def test_inbox_renders_field_boundary_alignment(tmp_path: Path):
    payload = {
        "stats": {"cost_usd": 0.0},
        "theoretical": [_gap_item()["gap"]],
        "engineering": [],
        "accepted": [_gap_item()],
        "email_ready": [_gap_item()],
        "mapping_actions": [],
        "mapping_drafts": [],
    }

    path = write_daily_inbox(date(2026, 5, 22), payload, out_dir=tmp_path)
    text = path.read_text()

    assert "Fin field boundary" in text
    assert "financial_nlp" in text
    assert "Evidence-Grounded Financial Retrieval" in text
    assert "email_gate" in text


def test_email_card_renders_field_boundary_alignment():
    html = _gap_card_html(_gap_item())

    assert "Field: <b>financial_nlp</b>" in html
    assert "Evidence-Grounded Financial Retrieval" in html
    assert "Gate: theoretical_high_novelty" in html


def test_email_engineering_card_renders_structured_experiment_panels():
    html = _gap_card_html(_engineering_gap_item())

    assert "Experimental setup" in html
    assert ">Dataset<" in html
    assert ">Metrics<" in html
    assert "Decision use" in html
    assert "Baselines &amp; Ablations" in html
    assert "Comparator / variant" in html
    assert "Ablations" in html
    assert "Feasibility" in html
    assert "Watch-outs" in html
    assert "https://arxiv.org/abs/2501.00001" in html
    assert "Author et al. (2025)" in html
    assert "Method outline" not in html
    assert "primary=[" not in html
    assert "用反馈修复 &lt;因子公式&gt;" in html


def test_inbox_renders_engineering_roadmap_tables_and_baseline_link(tmp_path: Path):
    engineering = _engineering_gap_item()
    payload = {
        "stats": {"cost_usd": 0.0},
        "theoretical": [],
        "engineering": [engineering["gap"]],
        "accepted": [engineering],
        "email_ready": [engineering],
        "mapping_actions": [],
        "mapping_drafts": [],
    }

    path = write_daily_inbox(date(2026, 5, 25), payload, out_dir=tmp_path)
    text = path.read_text()

    assert "| Sources | CRSP; Compustat |" in text
    assert "| Primary | repair success rate | higher than rule repair |" in text
    assert "[Author et al. (2025)](https://arxiv.org/abs/2501.00001)" in text


def test_inbox_reports_folded_theoretical_duplicate(tmp_path: Path):
    suppressed = _gap_item()
    suppressed["_email_suppressed_by"] = "ENG-1"
    payload = {
        "stats": {"cost_usd": 0.0},
        "theoretical": [suppressed["gap"]],
        "engineering": [],
        "accepted": [suppressed],
        "email_ready": [],
        "duplicates_suppressed": [suppressed],
        "mapping_actions": [],
        "mapping_drafts": [],
    }

    path = write_daily_inbox(date(2026, 5, 23), payload, out_dir=tmp_path)
    text = path.read_text()

    assert "Theoretical email duplicates suppressed: 1" in text
    assert "Folded Theoretical Duplicates" in text
    assert "`TH-1` folded into `ENG-1`" in text


def test_inbox_reports_adversarial_risk_audit(tmp_path: Path):
    payload = {
        "stats": {"cost_usd": 0.0},
        "theoretical": [],
        "engineering": [],
        "accepted": [],
        "email_ready": [],
        "mapping_actions": [],
        "mapping_drafts": [],
        "risk_audit": {
            "enabled": True,
            "input_candidates": 2,
            "retained": 1,
            "revised": 0,
            "rejected": 1,
            "decisions": [
                {
                    "candidate_idx": 1,
                    "verdict": "pass",
                    "one_liner": "valid proposal",
                    "failure_classes": ["none"],
                    "strongest_objection": "testable residual risk",
                    "required_revision": "",
                    "revised_one_liner": "",
                },
                {
                    "candidate_idx": 2,
                    "verdict": "reject",
                    "one_liner": "generic trading agent",
                    "failure_classes": ["boundary", "mechanism_transfer"],
                    "strongest_objection": "falls into an unconstrained trading target",
                    "required_revision": "",
                    "revised_one_liner": "",
                },
            ],
        },
    }

    path = write_daily_inbox(date(2026, 5, 23), payload, out_dir=tmp_path)
    text = path.read_text()

    assert "Adversarial research audit: **on**" in text
    assert "Adversarial Research Audit (full ledger)" in text
    assert "Candidate 1 — PASS" in text
    assert "Candidate 2 — REJECT" in text
    assert "boundary, mechanism_transfer" in text
    assert "falls into an unconstrained trading target" in text
