from datetime import date

import yaml

from pipeline.analyze.context import load_existing_mappings
from pipeline.analyze.mapping_draft import (
    draft_from_gap_item,
    generate_and_save_mapping_drafts,
    render_mapping_draft,
)


def _gap_item():
    return {
        "type": "engineering",
        "score": {"total": 8.5, "novelty": 9, "actionability": 8, "theoretical_support": 8.2},
        "gap": {
            "_id": "ENG-1",
            "hypothesis": "用密集步骤级信用分配定位因子构建流程失效点",
            "motivation": "motivation",
            "structural_mapping": {
                "ai_data_structure": "token sequence with hidden state evolution",
                "fin_data_structure": "multi-step factor construction pipeline",
                "match_status": "partial",
                "bridge_required": "将因子构建步骤视作离散决策步骤",
                "mismatch_severity": "low",
            },
            "research_context": {
                "ai_frontier": "用未来分布变化构造密集 credit signal",
                "fin_current_state": "因子归因仍停留在整体统计层面",
            },
            "field_boundary_alignment": {
                "field_id": "factor_investing",
                "mechanism_family": "Factor Decay And Crowding Diagnosis",
                "open_bottleneck": "Factor decay diagnosis",
                "why_aligned": "聚焦因子流程失效诊断",
            },
            "anchor_papers": {
                "ai": [{"id": "2603.19835", "title": "AI paper"}],
                "fin": [],
            },
        },
    }


def test_draft_from_gap_item_extracts_mapping_fields():
    draft = draft_from_gap_item(date(2026, 5, 22), _gap_item())

    assert draft["status"] == "open_gap"
    assert draft["source_gap_id"] == "ENG-1"
    assert draft["ai_mechanism"] == "用未来分布变化构造密集 credit signal"
    assert draft["fin_structure"] == "multi-step factor construction pipeline"
    assert draft["bridge"] == "将因子构建步骤视作离散决策步骤"
    assert draft["field_id"] == "factor_investing"
    assert draft["field_mechanism_family"] == "Factor Decay And Crowding Diagnosis"
    assert draft["field_open_bottleneck"] == "Factor decay diagnosis"
    assert draft["evidence_ai_papers"] == ["2603.19835"]
    assert draft["score_theoretical_support"] == 8.2


def test_render_mapping_draft_has_yaml_frontmatter():
    draft = draft_from_gap_item(date(2026, 5, 22), _gap_item())
    rendered = render_mapping_draft(draft)
    frontmatter = rendered.split("---", 2)[1]
    parsed = yaml.safe_load(frontmatter)

    assert parsed["source_gap_id"] == "ENG-1"
    assert parsed["status"] == "open_gap"
    assert parsed["field_id"] == "factor_investing"
    assert parsed["evidence_ai_papers"] == ["2603.19835"]


def test_generate_drafts_under_drafts_dir_and_loader_ignores_them(tmp_path):
    mappings_dir = tmp_path / "mappings"
    drafts_dir = mappings_dir / "drafts"

    drafts = generate_and_save_mapping_drafts(
        date(2026, 5, 22),
        [_gap_item()],
        out_dir=drafts_dir,
    )

    assert drafts[0]["_path"].endswith("mappings/drafts/2026-05-22-ENG-1.md")
    assert (drafts_dir / "2026-05-22-ENG-1.md").exists()
    assert load_existing_mappings(mappings_dir) == []
