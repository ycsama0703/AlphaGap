from pipeline.analyze.context import (
    fin_field_for_prompt,
    load_fin_field_notes,
    mapping_brief,
    mapping_for_prompt,
    paper_for_prompt,
    select_fin_field_notes,
)
from pipeline.analyze import gaps as gaps_mod


def test_paper_for_prompt_includes_normalized_mechanism():
    paper = {
        "id": "2603.19835",
        "title": "FIPO",
        "abstract": "abstract",
        "method_primary": ["FIPO"],
        "mechanism": {
            "one_liner": "  用未来 KL 散度作为 token 级 credit signal  ",
            "what_problem": "稀疏奖励无法定位关键步骤",
            "contrast": "比 trajectory-level reward 更密集",
            "prerequisites": "可采样未来轨迹",
        },
        "domain": ["policy optimization"],
        "tags": ["credit assignment"],
        "affiliation_top": "Example Lab",
        "priority_score": 9.2,
    }

    result = paper_for_prompt(paper)

    assert result["mechanism"] == {
        "one_liner": "用未来 KL 散度作为 token 级 credit signal",
        "what_problem": "稀疏奖励无法定位关键步骤",
        "contrast": "比 trajectory-level reward 更密集",
        "prerequisites": "可采样未来轨迹",
    }


def test_paper_for_prompt_defaults_empty_mechanism_fields():
    result = paper_for_prompt({
        "id": "p1",
        "title": "Paper",
        "abstract": "",
    })

    assert result["mechanism"] == {
        "one_liner": "",
        "what_problem": "",
        "contrast": "",
        "prerequisites": "",
    }


def test_mapping_projection_supports_mechanism_schema():
    mapping = {
        "id": "M0001",
        "status": "open_gap",
        "ai_mechanism": "dense step-level credit assignment",
        "ai_problem": "sparse trajectory reward",
        "fin_structure": "multi-step factor construction pipeline",
        "fin_problem": "factor decay is only diagnosed globally",
        "bridge": "treat construction steps as decision steps",
        "evidence_ai_papers": ["2603.19835"],
    }

    prompt_mapping = mapping_for_prompt(mapping)
    brief = mapping_brief(mapping)

    assert prompt_mapping["ai_concept"] == "dense step-level credit assignment"
    assert prompt_mapping["fin_concept"] == "multi-step factor construction pipeline"
    assert prompt_mapping["bridge"] == "treat construction steps as decision steps"
    assert brief["ai_mechanism"] == "dense step-level credit assignment"
    assert brief["fin_structure"] == "multi-step factor construction pipeline"


def test_fin_field_for_prompt_extracts_mechanism_boundaries():
    body = """
# Field

## Mechanism Families

### Evidence-Sufficient Agentic Retrieval

Mechanism: the agent searches until evidence is sufficient.

Current boundary: frontier is iterative retrieval with stopping rules.

Gap relevance: transfer evidence sufficiency classifiers.

## Mechanism-Level Frontier

The frontier is workflow reliability, not plausible prose.

## Mature Mechanisms

- Generic ReAct loops are baseline.

## Open Bottlenecks

1. **Evidence sufficiency**
   Agents need a stopping rule.

## Good AI Transfer Targets

- Citation validators that check subclaims.

## Bad Or Overcrowded Transfer Targets

- LLM agent directly trades stocks without constraints.

## Gap Construction Rules

- Start from a mechanism family above, not from a benchmark name.
"""

    result = fin_field_for_prompt(
        {"id": "financial_llm_agents", "name": "Financial LLM Agents"},
        body,
    )

    assert result["id"] == "financial_llm_agents"
    assert result["mechanism_families"] == [{
        "name": "Evidence-Sufficient Agentic Retrieval",
        "mechanism": "the agent searches until evidence is sufficient.",
        "current_boundary": "frontier is iterative retrieval with stopping rules.",
        "gap_relevance": "transfer evidence sufficiency classifiers.",
    }]
    assert result["open_bottlenecks"] == [{
        "name": "Evidence sufficiency",
        "description": "Agents need a stopping rule.",
    }]
    assert result["good_transfer_targets"] == ["Citation validators that check subclaims."]
    assert result["gap_construction_rules"] == [
        "Start from a mechanism family above, not from a benchmark name."
    ]


def test_load_fin_field_notes_skips_readme_and_inactive(tmp_path):
    (tmp_path / "README.md").write_text("---\nstatus: active\n---\n# Readme\n", encoding="utf-8")
    (tmp_path / "inactive.md").write_text(
        "---\nid: old\nname: Old\nstatus: archived\n---\n# Old\n",
        encoding="utf-8",
    )
    (tmp_path / "field.md").write_text(
        """---
id: f1
name: Field One
status: active
last_reviewed: 2026-05-22
---

# Field One

## Mechanism Families

### Routing

Mechanism: choose tools.

Current boundary: finance-specific routing.

Gap relevance: schema compression.
""",
        encoding="utf-8",
    )

    notes = load_fin_field_notes(tmp_path)

    assert len(notes) == 1
    assert notes[0]["id"] == "f1"
    assert notes[0]["mechanism_families"][0]["name"] == "Routing"


def test_select_fin_field_notes_prefers_relevant_topics():
    notes = [
        {
            "id": "factor_investing",
            "name": "Factor Investing",
            "related_keywords": ["factor investing", "alpha mining"],
            "canonical_tasks": ["formulaic alpha mining"],
            "mechanism_families": [{"name": "Formulaic Alpha Search"}],
            "open_bottlenecks": [{"name": "Redundancy control", "description": ""}],
            "good_transfer_targets": [],
            "bad_transfer_targets": [],
            "frontier": "",
        },
        {
            "id": "financial_nlp",
            "name": "Financial NLP",
            "related_keywords": ["financial RAG", "XBRL", "financial sentiment"],
            "canonical_tasks": ["financial report question answering"],
            "mechanism_families": [{"name": "Evidence-Grounded Financial Retrieval"}],
            "open_bottlenecks": [{"name": "Schema alignment", "description": ""}],
            "good_transfer_targets": [],
            "bad_transfer_targets": [],
            "frontier": "",
        },
        {
            "id": "portfolio_optimization",
            "name": "Portfolio Optimization",
            "related_keywords": ["portfolio optimization"],
            "canonical_tasks": ["risk budgeting"],
            "mechanism_families": [{"name": "Constrained Allocation"}],
            "open_bottlenecks": [],
            "good_transfer_targets": [],
            "bad_transfer_targets": [],
            "frontier": "",
        },
    ]
    papers = [{
        "title": "Financial RAG for XBRL report question answering",
        "abstract_short": "retrieval over financial reports with schema alignment",
        "method_primary": [],
        "domain": ["financial NLP"],
        "tags": ["RAG", "XBRL"],
        "mechanism": {},
    }]

    selected = select_fin_field_notes(notes, [], papers, {}, {}, max_fields=2)

    assert [n["id"] for n in selected][0] == "financial_nlp"
    assert len(selected) == 2


def test_select_fin_field_notes_falls_back_to_original_order_when_no_match():
    notes = [{"id": f"f{i}", "name": f"Field {i}"} for i in range(4)]

    selected = select_fin_field_notes(notes, [], [], {}, {}, max_fields=2)

    assert [n["id"] for n in selected] == ["f0", "f1"]


def test_build_gap_context_uses_selected_fin_fields(monkeypatch):
    def fake_papers(side, end, *, top_n, window_days):
        if side == "fin":
            return [{
                "id": "fin1",
                "title": "Financial RAG for XBRL reports",
                "abstract": "schema alignment for financial report question answering",
                "method_primary": [],
                "mechanism": {},
                "domain": ["financial NLP"],
                "tags": ["RAG", "XBRL"],
                "priority_score": 8,
            }]
        return [{
            "id": "ai1",
            "title": "Retriever repair",
            "abstract": "query expansion and evidence retrieval",
            "method_primary": [],
            "mechanism": {},
            "domain": ["retrieval"],
            "tags": ["RAG"],
            "priority_score": 8,
        }]

    notes = [
        {
            "id": "factor_investing",
            "name": "Factor Investing",
            "related_keywords": ["alpha mining"],
            "canonical_tasks": [],
            "mechanism_families": [{"name": "Formulaic Alpha Search"}],
            "open_bottlenecks": [],
            "good_transfer_targets": [],
            "bad_transfer_targets": [],
            "frontier": "",
        },
        {
            "id": "financial_nlp",
            "name": "Financial NLP",
            "related_keywords": ["financial RAG", "XBRL"],
            "canonical_tasks": ["financial report question answering"],
            "mechanism_families": [{"name": "Evidence-Grounded Financial Retrieval"}],
            "open_bottlenecks": [],
            "good_transfer_targets": [],
            "bad_transfer_targets": [],
            "frontier": "",
        },
        {"id": "portfolio_optimization", "name": "Portfolio Optimization"},
        {"id": "asset_pricing_ml", "name": "Asset Pricing ML"},
    ]

    monkeypatch.setattr(gaps_mod.ctx_builder, "get_top_papers", fake_papers)
    monkeypatch.setattr(gaps_mod.ctx_builder, "load_existing_mappings", lambda: [])
    monkeypatch.setattr(gaps_mod.ctx_builder, "load_fin_field_notes", lambda: notes)
    monkeypatch.setattr(gaps_mod.trends_mod, "summarize_trends", lambda *args, **kwargs: {})
    monkeypatch.setattr(gaps_mod.uptake_mod, "extract_ai_concepts_for_uptake", lambda *args, **kwargs: [])
    monkeypatch.setattr(gaps_mod.uptake_mod, "measure_fin_uptake", lambda *args, **kwargs: {})

    ctx = gaps_mod.build_gap_context(client=object())

    assert [f["id"] for f in ctx["fin_field_boundaries"]][0] == "financial_nlp"
    assert len(ctx["fin_field_boundaries"]) == 3
    assert len(ctx["fin_field_boundaries_all"]) == 4


def test_select_top_candidates_diversifies_by_field():
    candidates = []
    for i in range(1, 6):
        candidates.append({
            "idx": i,
            "ai_category": f"cat{i}",
            "fin_uptake_status": "open_gap",
            "field_boundary_alignment": {
                "field_id": "factor_investing",
                "mechanism_family": "Formulaic Alpha Search",
            },
        })
    candidates.append({
        "idx": 6,
        "ai_category": "cat6",
        "fin_uptake_status": "open_gap",
        "field_boundary_alignment": {
            "field_id": "financial_nlp",
            "mechanism_family": "Evidence-Grounded Financial Retrieval",
        },
    })

    selected = gaps_mod.select_top_candidates(candidates, top_n=6)

    assert sum(
        c["field_boundary_alignment"]["field_id"] == "factor_investing"
        for c in selected
    ) == 3
    assert any(c["field_boundary_alignment"]["field_id"] == "financial_nlp" for c in selected)


def test_candidate_enumeration_uses_reasoning_model():
    calls = []

    class FakeClient:
        def chat_json(self, **kwargs):
            calls.append(kwargs)
            return {"candidates": [{"ai_anchor_paper_id": "ai1"}]}

    ctx = {
        "ai_recent_papers": [],
        "fin_recent_papers": [],
        "ai_trends": {},
        "fin_trends": {},
        "existing_mappings": [],
        "fin_field_boundaries": [],
        "fin_uptake": {},
        "_valid_ai_ids": {"ai1"},
    }

    candidates = gaps_mod.enumerate_candidates(ctx, client=FakeClient())

    assert len(candidates) == 1
    assert calls[0]["reasoning"] is True


def test_generated_theoretical_gap_inherits_candidate_field_alignment():
    class FakeClient:
        def chat_json(self, **kwargs):
            return {
                "gaps": [{
                    "source_candidate_idx": 7,
                    "hypothesis": "用证据充分性评分改进金融 RAG 检索",
                    "ai_anchor": {"paper_id": "ai1", "concept": "evidence sufficiency scoring"},
                    "fin_anchor": {"description": "financial RAG", "evidence_paper_ids": []},
                }]
            }

    ctx = {
        "ai_recent_papers": [],
        "fin_recent_papers": [],
        "ai_trends": {},
        "fin_trends": {},
        "existing_mappings": [],
        "fin_field_boundaries": [],
        "fin_uptake": {},
    }
    candidates = [{
        "idx": 7,
        "field_boundary_alignment": {
            "field_id": "financial_nlp",
            "mechanism_family": "Evidence-Grounded Financial Retrieval",
            "open_bottleneck": "Realistic query retrieval",
            "why_aligned": "聚焦金融 RAG 证据检索边界",
        },
    }]

    gaps = gaps_mod.generate_theoretical_gaps(ctx, client=FakeClient(), candidates=candidates)

    assert gaps[0]["field_boundary_alignment"]["field_id"] == "financial_nlp"
    assert gaps[0]["field_boundary_alignment"]["mechanism_family"] == "Evidence-Grounded Financial Retrieval"


def test_generated_theoretical_gap_inherits_candidate_risk_audit():
    class FakeClient:
        def chat_json(self, **kwargs):
            return {"gaps": [{"source_candidate_idx": 7, "hypothesis": "narrow gap"}]}

    ctx = {
        "ai_recent_papers": [],
        "fin_recent_papers": [],
        "ai_trends": {},
        "fin_trends": {},
        "existing_mappings": [],
        "fin_field_boundaries": [],
        "fin_uptake": {},
    }
    audit = {
        "verdict": "revise",
        "strongest_objection": "too broad",
        "required_revision": "restrict task",
    }

    gaps = gaps_mod.generate_theoretical_gaps(
        ctx,
        client=FakeClient(),
        candidates=[{"idx": 7, "risk_audit": audit}],
    )

    assert gaps[0]["risk_audit"] == audit
    assert gaps[0]["_origin"]["candidate_idx"] == 7
    assert gaps[0]["_origin"]["audit_verdict"] == "revise"


def test_theoretical_expansion_retries_candidates_individually_after_batch_failure():
    calls = []

    class FakeClient:
        def chat_json(self, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                raise ValueError("truncated json")
            return {
                "gaps": [{
                    "source_candidate_idx": len(calls) - 1,
                    "hypothesis": "recovered gap",
                }]
            }

    ctx = {
        "ai_recent_papers": [],
        "fin_recent_papers": [],
        "ai_trends": {},
        "fin_trends": {},
        "existing_mappings": [],
        "fin_field_boundaries": [],
        "fin_uptake": {},
    }

    gaps = gaps_mod.generate_theoretical_gaps(
        ctx,
        client=FakeClient(),
        candidates=[{"idx": 1}, {"idx": 2}],
    )

    assert [gap["source_candidate_idx"] for gap in gaps] == [1, 2]
    assert [gap["_id"] for gap in gaps] == ["TH-1", "TH-2"]
    assert len(calls) == 3
    assert all(call["max_tokens"] == gaps_mod.THEORETICAL_EXPANSION_MAX_TOKENS for call in calls)
    assert all(call["reasoning"] is True for call in calls)


def test_theoretical_expansion_keeps_successful_recovery_when_one_candidate_fails():
    class FakeClient:
        def __init__(self):
            self.calls = 0

        def chat_json(self, **kwargs):
            self.calls += 1
            if self.calls <= 2:
                raise ValueError("truncated json")
            return {"gaps": [{"source_candidate_idx": 2, "hypothesis": "survivor"}]}

    ctx = {
        "ai_recent_papers": [],
        "fin_recent_papers": [],
        "ai_trends": {},
        "fin_trends": {},
        "existing_mappings": [],
        "fin_field_boundaries": [],
        "fin_uptake": {},
    }

    gaps = gaps_mod.generate_theoretical_gaps(
        ctx,
        client=FakeClient(),
        candidates=[{"idx": 1}, {"idx": 2}],
    )

    assert len(gaps) == 1
    assert gaps[0]["source_candidate_idx"] == 2


def test_engineering_gap_inherits_theoretical_audit_origin():
    class FakeClient:
        def chat_json(self, **kwargs):
            return {"gaps": [{
                "_id": "ENG-1",
                "upgraded_from_theoretical": "TH-1",
                "hypothesis": "engineering upgrade",
            }]}

    ctx = {
        "ai_recent_papers": [],
        "fin_recent_papers": [],
        "ai_trends": {},
        "fin_trends": {},
        "existing_mappings": [],
        "fin_field_boundaries": [],
        "fin_uptake": {},
    }
    theoretical = [{
        "_id": "TH-1",
        "_origin": {"candidate_idx": 7, "audit_verdict": "revise"},
        "risk_audit": {"verdict": "revise"},
    }]

    gaps = gaps_mod.generate_engineering_gaps(ctx, theoretical, client=FakeClient())

    assert gaps[0]["_origin"]["candidate_idx"] == 7
    assert gaps[0]["_origin"]["theoretical_gap_id"] == "TH-1"
    assert gaps[0]["risk_audit"]["verdict"] == "revise"


def test_engineering_expansion_retries_theories_individually_after_batch_failure():
    calls = []

    class FakeClient:
        def chat_json(self, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                raise ValueError("truncated json")
            source = "TH-1" if len(calls) == 2 else "TH-2"
            return {"gaps": [{
                "_id": "ENG-1",
                "upgraded_from_theoretical": source,
                "hypothesis": f"upgrade {source}",
            }]}

    ctx = {
        "ai_recent_papers": [],
        "fin_recent_papers": [],
        "ai_trends": {},
        "fin_trends": {},
        "existing_mappings": [],
        "fin_field_boundaries": [],
        "fin_uptake": {},
    }
    theories = [{"_id": "TH-1"}, {"_id": "TH-2"}]

    gaps = gaps_mod.generate_engineering_gaps(
        ctx,
        theories,
        client=FakeClient(),
        adversarial_mode=True,
    )

    assert [gap["_id"] for gap in gaps] == ["ENG-1", "ENG-2"]
    assert [gap["upgraded_from_theoretical"] for gap in gaps] == ["TH-1", "TH-2"]
    assert len(calls) == 3
    assert all(call["max_tokens"] == gaps_mod.ENGINEERING_EXPANSION_MAX_TOKENS for call in calls)
    assert all(call["reasoning"] is True for call in calls)


def test_engineering_expansion_keeps_successful_recovery_when_one_theory_fails():
    class FakeClient:
        def __init__(self):
            self.calls = 0

        def chat_json(self, **kwargs):
            self.calls += 1
            if self.calls <= 2:
                raise ValueError("truncated json")
            return {"gaps": [{
                "upgraded_from_theoretical": "TH-2",
                "hypothesis": "surviving experiment",
            }]}

    ctx = {
        "ai_recent_papers": [],
        "fin_recent_papers": [],
        "ai_trends": {},
        "fin_trends": {},
        "existing_mappings": [],
        "fin_field_boundaries": [],
        "fin_uptake": {},
    }

    gaps = gaps_mod.generate_engineering_gaps(
        ctx,
        [{"_id": "TH-1"}, {"_id": "TH-2"}],
        client=FakeClient(),
        adversarial_mode=True,
    )

    assert len(gaps) == 1
    assert gaps[0]["_id"] == "ENG-1"
    assert gaps[0]["upgraded_from_theoretical"] == "TH-2"
