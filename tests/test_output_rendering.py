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
