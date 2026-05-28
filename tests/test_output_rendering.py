import base64
from datetime import date
from pathlib import Path

from pipeline.output import email as email_mod
from pipeline.output.email import _brief_attachments, _gap_card_html
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
            "email_gate": "theoretical_discussion_only",
            "email_gate_reason": "inbox discussion only",
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
            "first_experiment": {
                "question": "Does verifier feedback reduce invalid formulas?",
                "minimal_setup": "100 formula candidates; no-verifier baseline; remove feedback ablation",
                "go_criterion": "invalid rate decreases by 30%",
                "stop_criterion": "improvement below 10%",
                "estimated_runtime": "1-2 days",
            },
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
    item["_brief_path"] = "briefs/2026-05-25-ENG-1.md"
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
    assert "Gate: theoretical_discussion_only" in html


def test_frontier_extension_renders_as_proposed_new_cell():
    item = _gap_item()
    item["gap"]["opportunity_mode"] = "frontier_extension"
    item["gap"]["proposed_cell"] = {
        "new_failure_mode": "agent hides audit violations behind successful output",
        "ai_intervention_class": "adversarial process monitoring",
        "experiment_anchor_sketch": "tool traces; hidden-violation recall; static auditor",
        "why_existing_cells_insufficient": "current cell checks accidental trace errors only",
    }

    html = _gap_card_html(item)

    assert "FRONTIER EXTENSION" in html
    assert "Proposed new transfer cell" in html
    assert "hidden-violation recall" in html
    assert "human review required" in html


def test_inbox_renders_frontier_extension_for_manual_review(tmp_path: Path):
    item = _gap_item()
    item["gap"]["opportunity_mode"] = "frontier_extension"
    item["gap"]["proposed_cell"] = {
        "new_failure_mode": "hidden audit evasion",
        "ai_intervention_class": "adversarial monitoring",
        "experiment_anchor_sketch": "trace audit recall",
        "why_existing_cells_insufficient": "uncovered strategic failure",
    }
    payload = {
        "stats": {"cost_usd": 0.0},
        "theoretical": [item["gap"]],
        "engineering": [],
        "accepted": [item],
        "email_ready": [item],
        "mapping_actions": [],
        "mapping_drafts": [],
    }

    path = write_daily_inbox(date(2026, 5, 27), payload, out_dir=tmp_path)
    text = path.read_text()

    assert "frontier_extension" in text
    assert "Proposed new transfer cell (not active)" in text
    assert "hidden audit evasion" in text


def test_email_engineering_card_renders_structured_experiment_panels():
    html = _gap_card_html(_engineering_gap_item())

    assert "Experimental setup" in html
    assert "First Experiment" in html
    assert "The smallest go/no-go test to run now" in html
    assert "invalid rate decreases by 30%" in html
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


def test_email_attaches_brief_instead_of_linking_to_unpublished_github_path(
        monkeypatch, tmp_path: Path):
    briefs = tmp_path / "briefs"
    briefs.mkdir()
    markdown = "# Deep brief\n\n中文机制说明\n"
    (briefs / "2026-05-25-ENG-1.md").write_text(markdown, encoding="utf-8")
    engineering = _engineering_gap_item()
    monkeypatch.setattr(email_mod, "PROJECT_ROOT", tmp_path)

    attachments = _brief_attachments({"email_ready": [engineering]})
    html = _gap_card_html(engineering)

    assert attachments == [{
        "filename": "2026-05-25-ENG-1.md",
        "content": base64.b64encode(markdown.encode("utf-8")).decode("ascii"),
        "content_type": "text/markdown; charset=utf-8",
    }]
    assert base64.b64decode(attachments[0]["content"]).decode("utf-8") == markdown
    assert "Attached markdown" in html
    assert "https://github.com" not in html


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
    assert "**First Experiment (go/no-go)**" in text
    assert "| Go | invalid rate decreases by 30% |" in text
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


def test_inbox_reports_rejected_self_check_reasons(tmp_path: Path):
    rejected = {
        "type": "engineering",
        "gap": {"_id": "ENG-1", "hypothesis": "用验证器修复因子公式"},
        "check": {
            "overall_verdict": "reject",
            "verdict_summary": "roadmap 不完整",
            "checks": {
                "F_data_concrete": {"pass": False, "reason": "dataset split missing"},
                "I_baselines_sufficient": {"pass": False, "reason": "only one baseline"},
                "G_method_detail": {"pass": True, "reason": ""},
            },
        },
    }
    downgraded = {
        "type": "engineering",
        "gap": {"_id": "ENG-2", "hypothesis": "用检索停止规则改进金融 RAG"},
        "check": {
            "overall_verdict": "downgrade",
            "verdict_summary": "缺最小实验",
            "checks": {
                "Q_first_experiment_go_no_go": {
                    "pass": False,
                    "reason": "stop criterion missing",
                },
            },
        },
        "recheck": {
            "overall_verdict": "reject",
            "verdict_summary": "理论证据不足",
            "checks": {
                "E_evidence_for_gap": {"pass": False, "reason": "weak fin evidence"},
            },
        },
    }
    payload = {
        "stats": {"cost_usd": 0.0, "historical_ai_mechanisms": 12},
        "theoretical": [],
        "engineering": [],
        "accepted": [],
        "rejected": [rejected],
        "downgraded": [downgraded],
        "email_ready": [],
        "mapping_actions": [],
        "mapping_drafts": [],
    }

    path = write_daily_inbox(date(2026, 5, 28), payload, out_dir=tmp_path)
    text = path.read_text()

    assert "Historical AI mechanisms retrieved: 12" in text
    assert "Rejected / Downgraded Self-check Ledger" in text
    assert "[ENG-1] (engineering) — rejected" in text
    assert "`F_data_concrete` | dataset split missing" in text
    assert "`I_baselines_sufficient` | only one baseline" in text
    assert "[ENG-2] (engineering) — downgraded" in text
    assert "Downgrade recheck: `reject`" in text
    assert "`E_evidence_for_gap` | weak fin evidence" in text
