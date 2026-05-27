import json
import sqlite3
from datetime import date, datetime

from pipeline import db, ingest, mechanism_lib, transfer_cells
from pipeline.analyze.uptake import measure_fin_uptake
from pipeline.conf_backfill import ingest_records, replay_evidence_snapshot
from pipeline.fetchers.arxiv import PaperRecord
from pipeline.fetchers.openreview import _extract_arxiv_id, _normalize_decision
from pipeline.mechanism_maintenance import (
    audit_library,
    build_progress,
    clone_database,
    format_progress,
    reset_rebuildable_library,
)


def _init_db(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test")
    monkeypatch.setenv("RESEND_API_KEY", "test")
    monkeypatch.setenv("EMAIL_FROM", "test@example.com")
    monkeypatch.setenv("EMAIL_TO", "test@example.com")
    monkeypatch.setenv("ALPHAGAP_DB_PATH", str(tmp_path / "test.sqlite"))
    db.init_schema()


def _paper(paper_id, *, source="hf_daily", title="Mechanism Paper"):
    return {
        "id": paper_id,
        "source": source,
        "arxiv_id": paper_id if not paper_id.startswith("openreview:") else None,
        "title": title,
        "abstract": "A financial transformer mechanism with useful evidence.",
        "authors": [],
        "publication_date": date(2026, 5, 25),
        "arxiv_categories": ["cs.LG"],
        "url": f"https://arxiv.org/abs/{paper_id}",
        "raw_meta": {},
    }


def _openreview_record(title, *, arxiv_id=None, note_id="note-1", decision="oral"):
    return PaperRecord(
        id=arxiv_id or f"openreview:{note_id}",
        source="openreview",
        arxiv_id=arxiv_id,
        title=title,
        abstract="Conference evidence.",
        authors=[],
        publication_date=date(2026, 5, 1),
        arxiv_categories=[],
        url=f"https://openreview.net/forum?id={note_id}",
        raw_meta={
            "openreview_id": note_id,
            "venue": "ICLR 2026",
            "venue_short": "ICLR",
            "venue_year": 2026,
            "decision": decision,
            "review_scores": [8, 7],
        },
    )


def test_daily_ingest_writes_trigger_observation_without_replacing_parent(monkeypatch, tmp_path):
    _init_db(monkeypatch, tmp_path)
    paper = _paper("2605.00001")

    ingest.persist_papers([paper])
    ingest.persist_papers([paper])

    with db.connect() as conn:
        rows = conn.execute(
            "SELECT role, eligible_for_daily_trigger FROM paper_sources WHERE paper_id = ?",
            (paper["id"],),
        ).fetchall()
    assert [(r["role"], r["eligible_for_daily_trigger"]) for r in rows] == [("trigger", 1)]


def test_conference_evidence_preserves_existing_trigger_and_signals(monkeypatch, tmp_path):
    _init_db(monkeypatch, tmp_path)
    paper = _paper("2605.00002", title="Shared Paper")
    with db.connect() as conn:
        db.upsert_paper(conn, paper)
        db.upsert_signals(conn, paper["id"], {"is_hf_daily": True, "priority_score": 4.0})

    stats = ingest_records([_openreview_record("Shared Paper", arxiv_id=paper["id"])])

    with db.connect() as conn:
        visible = conn.execute(
            f"SELECT COUNT(*) FROM papers p WHERE p.id = ? AND {db.TRIGGER_ELIGIBILITY_GUARD}",
            (paper["id"],),
        ).fetchone()[0]
        observations = conn.execute(
            "SELECT source, eligible_for_daily_trigger FROM paper_sources WHERE paper_id = ? ORDER BY source",
            (paper["id"],),
        ).fetchall()
        signals = json.loads(conn.execute(
            "SELECT signals_json FROM paper_signals WHERE paper_id = ?", (paper["id"],)
        ).fetchone()[0])

    assert stats["matched_existing"] == 1
    assert visible == 1
    assert [(r["source"], r["eligible_for_daily_trigger"]) for r in observations] == [
        ("hf_daily", 1),
        ("openreview", 0),
    ]
    assert signals["is_hf_daily"] is True
    assert signals["openreview_decision"] == "oral"


def test_conference_record_without_arxiv_id_merges_unique_trigger_title(monkeypatch, tmp_path):
    _init_db(monkeypatch, tmp_path)
    with db.connect() as conn:
        db.upsert_paper(conn, _paper("2605.00003", title="Exact Unique Mechanism Title"))

    ingest_records([_openreview_record("Exact Unique Mechanism Title", note_id="note-title")])

    with db.connect() as conn:
        mapped = db.find_paper_by_external_id(conn, "openreview", "note-title")
        count = conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
    assert mapped == "2605.00003"
    assert count == 1


def test_later_trigger_merges_unique_existing_evidence_title(monkeypatch, tmp_path):
    _init_db(monkeypatch, tmp_path)
    ingest_records([_openreview_record("Evidence Appears First", note_id="first")])

    ingest.persist_papers([_paper("2605.00033", title="Evidence Appears First")])

    with db.connect() as conn:
        count = conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
        mapped = db.find_paper_by_external_id(conn, "arxiv", "2605.00033")
        visible = conn.execute(
            f"SELECT COUNT(*) FROM papers p WHERE p.id = ? AND {db.TRIGGER_ELIGIBILITY_GUARD}",
            ("openreview:first",),
        ).fetchone()[0]
    assert count == 1
    assert mapped == "openreview:first"
    assert visible == 1


def test_daily_pending_queue_excludes_evidence_unless_explicitly_requested(monkeypatch, tmp_path):
    _init_db(monkeypatch, tmp_path)
    with db.connect() as conn:
        for paper_id, source, eligible in [
            ("2605.00004", "hf_daily", 1),
            ("openreview:evidence", "openreview", 0),
        ]:
            db.upsert_paper(conn, _paper(paper_id, source=source))
            db.upsert_signals(conn, paper_id, {"priority_score": 9.0, "candidate": True})
            db.upsert_paper_source(
                conn,
                paper_id=paper_id,
                source=source,
                source_record_id=paper_id,
                role="trigger" if eligible else "evidence",
                eligible_for_daily_trigger=eligible,
            )
        daily = db.fetch_pending_for_l1(conn, include_evidence=False)
        backfill = db.fetch_pending_for_l1(conn, include_evidence=True)
        evidence = db.fetch_pending_for_l1(conn, include_evidence=True, evidence_only=True)

    assert [r["id"] for r in daily] == ["2605.00004"]
    assert {r["id"] for r in backfill} == {"2605.00004", "openreview:evidence"}
    assert [r["id"] for r in evidence] == ["openreview:evidence"]


def test_maturity_counts_strongest_observation_once_per_paper(monkeypatch, tmp_path):
    _init_db(monkeypatch, tmp_path)
    with db.connect() as conn:
        db.upsert_paper(conn, _paper("2605.00005"))
        conn.execute(
            """
            INSERT INTO mechanism_families
                (family_id, representative_one_liner, created_at, last_updated, canonical_status)
            VALUES ('fam-1', 'test family', '2026-05-26', '2026-05-26', 'auto_draft')
            """
        )
        conn.execute(
            """
            INSERT INTO mechanism_memberships
                (paper_id, family_id, confidence, assigned_at, assigned_by, membership_status)
            VALUES ('2605.00005', 'fam-1', 1.0, '2026-05-26', 'test', 'accepted')
            """
        )
        db.upsert_paper_source(
            conn, paper_id="2605.00005", source="arxiv", source_record_id="a",
            role="trigger", eligible_for_daily_trigger=1,
        )
        db.upsert_paper_source(
            conn, paper_id="2605.00005", source="hf_daily", source_record_id="h",
            role="trigger", eligible_for_daily_trigger=1,
        )
        db.upsert_paper_source(
            conn, paper_id="2605.00005", source="openreview", source_record_id="o",
            role="evidence", eligible_for_daily_trigger=0, venue="ICLR 2026", decision="oral",
        )
        maturity = mechanism_lib.compute_maturity("fam-1", conn)

    assert maturity["member_count"] == 1
    assert maturity["total_weight"] == 3.0
    assert maturity["venue_breakdown"] == {"ICLR Oral": 1}
    assert maturity["observation_breakdown"] == {"arxiv": 1, "hf_daily": 1, "ICLR Oral": 1}


def test_fin_extractions_do_not_enter_ai_family_assignment(monkeypatch, tmp_path):
    _init_db(monkeypatch, tmp_path)
    with db.connect() as conn:
        db.upsert_paper(conn, _paper("2605.00006"))
        db.upsert_extraction_l1(conn, "2605.00006", {
            "side": "fin",
            "mechanism_description": {"one_liner": "a financial-only mechanism"},
        })

    monkeypatch.setattr(mechanism_lib, "LLMClient", lambda: object())
    stats = mechanism_lib.assign_pending()

    assert stats["processed"] == 0


def test_evidence_only_family_assignment_does_not_select_trigger_extraction(monkeypatch, tmp_path):
    _init_db(monkeypatch, tmp_path)
    with db.connect() as conn:
        for paper_id, source, role in [
            ("2605.trigger", "hf_daily", "trigger"),
            ("openreview:evidence-ai", "openreview", "evidence"),
        ]:
            db.upsert_paper(conn, _paper(paper_id, source=source))
            db.upsert_extraction_l1(conn, paper_id, {
                "side": "ai",
                "mechanism_description": {"one_liner": paper_id},
            })
            db.upsert_paper_source(
                conn,
                paper_id=paper_id,
                source=source,
                source_record_id=paper_id,
                role=role,
                eligible_for_daily_trigger=1 if role == "trigger" else 0,
            )

    selected = []

    class FakeClient:
        total_tokens = (0, 0)

        def estimate_cost_usd(self):
            return 0.0

    def fake_assign(paper_id, mech, *, llm=None, top_k=5):
        selected.append(paper_id)
        return {"action": "new_family"}

    monkeypatch.setattr(mechanism_lib, "LLMClient", FakeClient)
    monkeypatch.setattr(mechanism_lib, "assign_paper", fake_assign)

    stats = mechanism_lib.assign_pending(evidence_only=True)

    assert stats["processed"] == 1
    assert selected == ["openreview:evidence-ai"]


def test_transfer_screen_excludes_non_transferable_evidence_without_family(monkeypatch, tmp_path):
    _init_db(monkeypatch, tmp_path)
    with db.connect() as conn:
        db.upsert_paper(conn, _paper("openreview:protein", source="openreview"))
        db.upsert_extraction_l1(conn, "openreview:protein", {
            "side": "ai",
            "mechanism_description": {"one_liner": "generate protein structures"},
        })

    class FakeClient:
        def chat_json(self, system, user, **kwargs):
            assert "screening AI research evidence" in system
            assert kwargs["reasoning"] is True
            return {
                "relevance_status": "not_relevant",
                "relevant_fin_fields": [],
                "transferable_one_liner": None,
                "transfer_problem": None,
                "shared_approach": None,
                "rationale": "protein generation has no stated finance bottleneck bridge",
            }

    result = mechanism_lib.assign_paper(
        "openreview:protein",
        {"one_liner": "generate protein structures"},
        llm=FakeClient(),
    )

    with db.connect() as conn:
        reviews = conn.execute(
            "SELECT relevance_status FROM mechanism_transfer_reviews"
        ).fetchall()
        families = conn.execute("SELECT COUNT(*) FROM mechanism_families").fetchone()[0]
    assert result["action"] == "screen-not_relevant"
    assert [r["relevance_status"] for r in reviews] == ["not_relevant"]
    assert families == 0


def test_transfer_screen_bootstraps_family_from_projection_not_paper_brand(monkeypatch, tmp_path):
    _init_db(monkeypatch, tmp_path)
    with db.connect() as conn:
        db.upsert_paper(conn, _paper("openreview:repair", source="openreview"))
        db.upsert_extraction_l1(conn, "openreview:repair", {
            "side": "ai",
            "mechanism_description": {"one_liner": "FIPO repairs programs"},
        })

    class FakeClient:
        def chat_json(self, system, user, **kwargs):
            return {
                "relevance_status": "transferable",
                "relevant_fin_fields": ["factor_investing"],
                "transferable_one_liner": "Verifier-guided repair of executable structured outputs",
                "transfer_problem": "generated expressions fail execution checks",
                "shared_approach": "execute, diagnose, and revise invalid outputs",
                "rationale": "maps to executable factor validity",
            }

    result = mechanism_lib.assign_paper(
        "openreview:repair",
        {"one_liner": "FIPO repairs programs"},
        llm=FakeClient(),
    )

    with db.connect() as conn:
        family = conn.execute(
            "SELECT representative_one_liner, what_problem FROM mechanism_families"
        ).fetchone()
        fields = conn.execute(
            "SELECT relevant_fin_fields_json FROM mechanism_transfer_reviews"
        ).fetchone()[0]
    assert result["action"] == "bootstrap-new_family"
    assert family["representative_one_liner"] == "Verifier-guided repair of executable structured outputs"
    assert "FIPO" not in family["representative_one_liner"]
    assert json.loads(fields) == ["factor_investing"]


def test_screened_out_evidence_is_not_reprocessed_by_batch_assignment(monkeypatch, tmp_path):
    _init_db(monkeypatch, tmp_path)
    with db.connect() as conn:
        db.upsert_paper(conn, _paper("openreview:screened", source="openreview"))
        db.upsert_extraction_l1(conn, "openreview:screened", {
            "side": "ai",
            "mechanism_description": {"one_liner": "domain-only generator"},
        })
        db.upsert_paper_source(
            conn, paper_id="openreview:screened", source="openreview",
            source_record_id="screened", role="evidence", eligible_for_daily_trigger=0,
        )

    calls = []

    class FakeClient:
        total_tokens = (0, 0)

        def chat_json(self, system, user, **kwargs):
            calls.append(user)
            return {
                "relevance_status": "not_relevant",
                "rationale": "no finance bridge",
            }

        def estimate_cost_usd(self):
            return 0.0

    monkeypatch.setattr(mechanism_lib, "LLMClient", FakeClient)

    first = mechanism_lib.assign_pending(evidence_only=True)
    second = mechanism_lib.assign_pending(evidence_only=True)

    assert first["processed"] == 1
    assert first["screened_out"] == 1
    assert first["assigned"] == 0
    assert second["processed"] == 0
    assert len(calls) == 1


def test_seed_fin_transfer_cells_is_idempotent_and_experiment_anchored(monkeypatch, tmp_path):
    _init_db(monkeypatch, tmp_path)

    first = transfer_cells.seed_cells()
    second = transfer_cells.seed_cells()

    with db.connect() as conn:
        count = conn.execute("SELECT COUNT(*) FROM fin_transfer_cells").fetchone()[0]
        anchor = json.loads(conn.execute(
            "SELECT experiment_anchor_json FROM fin_transfer_cells WHERE cell_id = 'factor.executable_repair'"
        ).fetchone()[0])
    assert first == {"cells_total": 30, "inserted": 30, "updated": 0}
    assert second == {"cells_total": 30, "inserted": 0, "updated": 30}
    assert count == 30
    assert anchor["failure_mode"]


def test_init_schema_migrates_existing_single_cell_decision_table(monkeypatch, tmp_path):
    monkeypatch.setenv("ALPHAGAP_DB_PATH", str(tmp_path / "legacy.sqlite"))
    with sqlite3.connect(tmp_path / "legacy.sqlite") as conn:
        conn.execute(
            """
            CREATE TABLE ai_evidence_decisions (
                paper_id TEXT PRIMARY KEY,
                verdict TEXT NOT NULL,
                selected_cell_id TEXT,
                candidate_cell_ids_json TEXT,
                bridge_claim TEXT,
                experiment_fit_json TEXT,
                proposed_extension_json TEXT,
                rationale TEXT,
                assessed_at TEXT NOT NULL,
                assessed_by TEXT NOT NULL
            )
            """
        )

    db.init_schema()

    with db.connect() as conn:
        columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(ai_evidence_decisions)")
        }
    assert "supported_cell_ids_json" in columns


def test_evidence_auditor_links_only_to_existing_cell_with_complete_experiment_fit(monkeypatch, tmp_path):
    _init_db(monkeypatch, tmp_path)
    transfer_cells.seed_cells()
    with db.connect() as conn:
        db.upsert_paper(conn, _paper("openreview:verifier", source="openreview"))

    class FakeClient:
        def chat_json(self, system, user, **kwargs):
            if "conservative confirmation reviewer" in system:
                return {
                    "accepted_cell_ids": ["factor.executable_repair"],
                    "rationale": "same verifier operation",
                }
            assert "must never create or activate a new cell" in system
            assert "factor.executable_repair" in user
            assert kwargs["reasoning"] is True
            return {
                "verdict": "support",
                "selected_cell_id": "factor.executable_repair",
                "confidence": 0.91,
                "bridge_claim": "Execution feedback repairs invalid factor expressions.",
                "experiment_fit": {
                    "data_object": "symbolic factors",
                    "primary_metric": "valid investable expression rate",
                    "baseline": "unguided generation",
                    "failure_mode": "invalid or temporally leaked formulas",
                },
                "rationale": "Concrete verifier intervention for executable factors.",
            }

    result = transfer_cells.audit_evidence(
        "openreview:verifier",
        {"one_liner": "Verifier detects invalid programs and repairs them."},
        llm=FakeClient(),
        allow_automatic_support=True,
    )

    with db.connect() as conn:
        decision = conn.execute(
            "SELECT verdict, selected_cell_id FROM ai_evidence_decisions"
        ).fetchone()
        link = conn.execute(
            "SELECT verdict, confidence FROM ai_evidence_links"
        ).fetchone()
        auto_families = conn.execute("SELECT COUNT(*) FROM mechanism_families").fetchone()[0]
    assert result["action"] == "support"
    assert (decision["verdict"], decision["selected_cell_id"]) == (
        "support", "factor.executable_repair",
    )
    assert link["verdict"] == "support"
    assert link["confidence"] == 0.91
    assert auto_families == 0


def test_incomplete_evidence_fit_cannot_be_automatic_support(monkeypatch, tmp_path):
    _init_db(monkeypatch, tmp_path)
    transfer_cells.seed_cells()
    with db.connect() as conn:
        db.upsert_paper(conn, _paper("openreview:analogy", source="openreview"))

    class FakeClient:
        def chat_json(self, *args, **kwargs):
            return {
                "verdict": "support",
                "selected_cell_id": "pricing.cross_asset_relations",
                "confidence": 0.9,
                "bridge_claim": "Maybe relevant.",
                "experiment_fit": {"data_object": "assets"},
                "rationale": "No concrete evaluation bridge.",
            }

    result = transfer_cells.audit_evidence(
        "openreview:analogy",
        {"one_liner": "align biological signals"},
        llm=FakeClient(),
    )

    with db.connect() as conn:
        decision = conn.execute("SELECT verdict FROM ai_evidence_decisions").fetchone()[0]
        link = conn.execute("SELECT verdict FROM ai_evidence_links").fetchone()[0]
    assert result["action"] == "candidate_extension"
    assert decision == "candidate_extension"
    assert link == "candidate"


def test_evidence_auditor_persists_multiple_independent_support_cells(monkeypatch, tmp_path):
    _init_db(monkeypatch, tmp_path)
    transfer_cells.seed_cells()
    with db.connect() as conn:
        db.upsert_paper(conn, _paper("openreview:adaptive-compute", source="openreview"))

    class FakeClient:
        def chat_json(self, *args, **kwargs):
            if "conservative confirmation reviewer" in args[0]:
                return {
                    "accepted_cell_ids": [
                        "factor.budgeted_search",
                        "agent.adaptive_retrieval_budget",
                    ],
                    "rationale": "both use the same adaptive allocation operation",
                }
            return {
                "verdict": "support",
                "supported_cells": [
                    {
                        "cell_id": "factor.budgeted_search",
                        "confidence": 0.92,
                        "bridge_claim": "Allocate more search calls to promising factor hypotheses.",
                        "experiment_fit": {
                            "data_object": "factor search traces",
                            "primary_metric": "discoveries per dollar",
                            "baseline": "fixed candidate budget",
                            "failure_mode": "wasted search budget",
                        },
                    },
                    {
                        "cell_id": "agent.adaptive_retrieval_budget",
                        "confidence": 0.88,
                        "bridge_claim": "Allocate retrieval depth by question difficulty.",
                        "experiment_fit": {
                            "data_object": "financial evidence questions",
                            "primary_metric": "supported answers per dollar",
                            "baseline": "fixed retrieval depth",
                            "failure_mode": "unnecessary retrieval compute",
                        },
                    },
                ],
                "rationale": "The same allocation operation fits two distinct anchors.",
            }

    result = transfer_cells.audit_evidence(
        "openreview:adaptive-compute",
        {"one_liner": "Adaptive test-time compute allocation."},
        llm=FakeClient(),
        allow_automatic_support=True,
    )

    with db.connect() as conn:
        decision = conn.execute(
            "SELECT selected_cell_id, supported_cell_ids_json FROM ai_evidence_decisions"
        ).fetchone()
        links = conn.execute(
            "SELECT cell_id FROM ai_evidence_links ORDER BY cell_id"
        ).fetchall()
    assert result["cell_ids"] == ["factor.budgeted_search", "agent.adaptive_retrieval_budget"]
    assert decision["selected_cell_id"] == "factor.budgeted_search"
    assert json.loads(decision["supported_cell_ids_json"]) == result["cell_ids"]
    assert [row["cell_id"] for row in links] == [
        "agent.adaptive_retrieval_budget",
        "factor.budgeted_search",
    ]


def test_unconfirmed_support_is_retained_as_candidate_without_link(monkeypatch, tmp_path):
    _init_db(monkeypatch, tmp_path)
    transfer_cells.seed_cells()
    with db.connect() as conn:
        db.upsert_paper(conn, _paper("openreview:near-match", source="openreview"))

    class FakeClient:
        def chat_json(self, system, user, **kwargs):
            if "conservative confirmation reviewer" in system:
                return {"accepted_cell_ids": [], "rationale": "nearby but different operation"}
            return {
                "verdict": "support",
                "supported_cells": [{
                    "cell_id": "agent.trace_audit",
                    "confidence": 0.91,
                    "bridge_claim": "Process supervision audits traces.",
                    "experiment_fit": {
                        "data_object": "agent traces",
                        "primary_metric": "error detection",
                        "baseline": "no checker",
                        "failure_mode": "invalid trace",
                    },
                }],
                "rationale": "proposed support",
            }

    result = transfer_cells.audit_evidence(
        "openreview:near-match",
        {"one_liner": "Improve agent planning with process supervision."},
        llm=FakeClient(),
    )

    with db.connect() as conn:
        decision = conn.execute("SELECT verdict FROM ai_evidence_decisions").fetchone()[0]
        links = conn.execute("SELECT COUNT(*) FROM ai_evidence_links").fetchone()[0]
    assert result["action"] == "candidate_extension"
    assert decision == "candidate_extension"
    assert links == 0


def test_confirmed_support_is_candidate_by_default_until_gate_signoff(monkeypatch, tmp_path):
    _init_db(monkeypatch, tmp_path)
    transfer_cells.seed_cells()
    with db.connect() as conn:
        db.upsert_paper(conn, _paper("openreview:staged", source="openreview"))

    class FakeClient:
        def chat_json(self, system, user, **kwargs):
            if "conservative confirmation reviewer" in system:
                return {"accepted_cell_ids": ["factor.executable_repair"], "rationale": "confirmed"}
            return {
                "verdict": "support",
                "supported_cells": [{
                    "cell_id": "factor.executable_repair",
                    "confidence": 0.9,
                    "bridge_claim": "Repair invalid factors.",
                    "experiment_fit": {
                        "data_object": "factor expressions",
                        "primary_metric": "valid expression rate",
                        "baseline": "unguided generation",
                        "failure_mode": "invalid formulas",
                    },
                }],
                "rationale": "same repair operation",
            }

    result = transfer_cells.audit_evidence(
        "openreview:staged",
        {"one_liner": "repair executable expressions"},
        llm=FakeClient(),
    )

    with db.connect() as conn:
        decision = conn.execute(
            "SELECT verdict, supported_cell_ids_json, candidate_cell_ids_json FROM ai_evidence_decisions"
        ).fetchone()
        link = conn.execute("SELECT verdict FROM ai_evidence_links").fetchone()[0]
    assert result["action"] == "candidate_extension"
    assert decision["verdict"] == "candidate_extension"
    assert json.loads(decision["supported_cell_ids_json"]) == []
    assert json.loads(decision["candidate_cell_ids_json"]) == ["factor.executable_repair"]
    assert link == "candidate"


def test_transfer_cell_evaluation_asset_has_representative_boundary_cases():
    cases = transfer_cells.load_evaluation_cases()

    assert len(cases) == 50
    assert sum(c["expected_verdict"] == "support" for c in cases) == 9
    assert sum(c["expected_verdict"] == "candidate_extension" for c in cases) == 22
    assert sum(c["expected_verdict"] == "reject" for c in cases) == 19
    assert all(c.get("difficulty") for c in cases)


def test_evaluate_benchmark_does_not_persist_decisions(monkeypatch, tmp_path):
    _init_db(monkeypatch, tmp_path)
    with db.connect() as conn:
        for paper_id, title in [("ai:support", "Support"), ("ai:reject", "Reject")]:
            db.upsert_paper(conn, _paper(paper_id, title=title))
            db.upsert_extraction_l1(conn, paper_id, {
                "side": "ai",
                "mechanism_description": {"one_liner": title},
            })

    class FakeClient:
        total_tokens = (20, 4)

        def chat_json(self, system, user, **kwargs):
            if "conservative confirmation reviewer" in system:
                return {
                    "accepted_cell_ids": ["factor.executable_repair"],
                    "rationale": "confirmed",
                }
            if "ai:support" in user:
                return {
                    "verdict": "support",
                    "selected_cell_id": "factor.executable_repair",
                    "confidence": 0.9,
                    "experiment_fit": {
                        "data_object": "factor expressions",
                        "primary_metric": "execution validity",
                        "baseline": "generation",
                        "failure_mode": "invalid expression",
                    },
                    "rationale": "direct match",
                }
            return {
                "verdict": "reject",
                "confidence": 0.9,
                "rationale": "not transferable",
            }

        def estimate_cost_usd(self):
            return 0.001

    cases = [
        {
            "paper_id": "ai:support",
            "title": "Support",
            "expected_verdict": "support",
            "expected_cell_id": "factor.executable_repair",
            "rationale": "test",
        },
        {
            "paper_id": "ai:reject",
            "title": "Reject",
            "expected_verdict": "reject",
            "rationale": "test",
        },
    ]
    result = transfer_cells.evaluate_benchmark(cases=cases, llm=FakeClient())

    with db.connect() as conn:
        decisions = conn.execute("SELECT COUNT(*) FROM ai_evidence_decisions").fetchone()[0]
        links = conn.execute("SELECT COUNT(*) FROM ai_evidence_links").fetchone()[0]
    assert result["evaluated"] == 2
    assert result["verdict_accuracy"] == 1.0
    assert result["support_cell_recall"] == 1.0
    assert result["automatic_support_precision"] == 1.0
    assert decisions == 0
    assert links == 0


def test_fin_uptake_ignores_evidence_only_observations(monkeypatch, tmp_path):
    _init_db(monkeypatch, tmp_path)
    with db.connect() as conn:
        db.upsert_paper(conn, _paper("openreview:fin", source="openreview", title="Transformer adoption"))
        db.upsert_extraction_l1(conn, "openreview:fin", {
            "side": "fin",
            "mechanism_description": {"one_liner": "transformer adoption"},
        })
        db.upsert_paper_source(
            conn, paper_id="openreview:fin", source="openreview", source_record_id="fin",
            role="evidence", eligible_for_daily_trigger=0,
        )

    result = measure_fin_uptake(["transformer"], end_date=date(2026, 5, 26))
    assert result["transformer"]["count"] == 0


def test_openreview_pending_label_and_arxiv_field_parsing():
    assert _normalize_decision("Submitted to ICLR 2027") == "pending"
    assert _extract_arxiv_id({"pdf": {"value": "https://arxiv.org/pdf/2605.12345v2"}}) == "2605.12345"


def test_reset_removes_rebuildable_evidence_but_retains_trigger_paper(monkeypatch, tmp_path):
    _init_db(monkeypatch, tmp_path)
    trigger = _paper("2605.00007", title="Shared Mechanism")
    ingest.persist_papers([trigger])
    ingest_records([_openreview_record("Shared Mechanism", arxiv_id=trigger["id"], note_id="shared")])
    ingest_records([_openreview_record("Evidence Only", note_id="only")])
    with db.connect() as conn:
        conn.execute(
            """
            INSERT INTO mechanism_families
                (family_id, representative_one_liner, created_at, last_updated, canonical_status)
            VALUES ('reset-family', 'mechanism', '2026-05-26', '2026-05-26', 'auto_draft')
            """
        )
        conn.execute(
            """
            INSERT INTO mechanism_memberships
                (paper_id, family_id, confidence, assigned_at, assigned_by, membership_status)
            VALUES (?, 'reset-family', 1.0, '2026-05-26', 'test', 'accepted')
            """,
            (trigger["id"],),
        )
        conn.execute(
            """
            INSERT INTO mechanism_transfer_reviews
                (paper_id, relevance_status, assessed_at, assessed_by)
            VALUES ('openreview:only', 'not_relevant', '2026-05-26', 'test')
            """
        )

    result = reset_rebuildable_library()

    with db.connect() as conn:
        remaining_papers = {r["id"] for r in conn.execute("SELECT id FROM papers").fetchall()}
        observations = conn.execute(
            "SELECT source, eligible_for_daily_trigger FROM paper_sources WHERE paper_id = ?",
            (trigger["id"],),
        ).fetchall()
        families = conn.execute("SELECT COUNT(*) FROM mechanism_families").fetchone()[0]
        transfer_reviews = conn.execute(
            "SELECT COUNT(*) FROM mechanism_transfer_reviews"
        ).fetchone()[0]
    assert result["deleted_evidence_only_papers"] == 1
    assert remaining_papers == {trigger["id"]}
    assert [(r["source"], r["eligible_for_daily_trigger"]) for r in observations] == [
        ("hf_daily", 1)
    ]
    assert families == 0
    assert result["deleted_transfer_reviews"] == 1
    assert transfer_reviews == 0


def test_reset_refuses_to_delete_human_confirmed_family(monkeypatch, tmp_path):
    _init_db(monkeypatch, tmp_path)
    with db.connect() as conn:
        conn.execute(
            """
            INSERT INTO mechanism_families
                (family_id, representative_one_liner, created_at, last_updated, canonical_status)
            VALUES ('reviewed', 'human mechanism', '2026-05-26', '2026-05-26', 'human_confirmed')
            """
        )

    try:
        reset_rebuildable_library()
    except RuntimeError as exc:
        assert "human review" in str(exc)
    else:
        raise AssertionError("reset should refuse human-confirmed family deletion")


def test_audit_reports_non_ai_memberships_and_cross_source_duplicate(monkeypatch, tmp_path):
    _init_db(monkeypatch, tmp_path)
    with db.connect() as conn:
        db.upsert_paper(conn, _paper("2605.00008", title="Duplicate Work"))
        db.upsert_paper(conn, _paper("openreview:duplicate", source="openreview", title="Duplicate Work"))
        db.upsert_extraction_l1(conn, "2605.00008", {
            "side": "fin",
            "mechanism_description": {"one_liner": "not ai"},
        })
        conn.execute(
            """
            INSERT INTO mechanism_families
                (family_id, representative_one_liner, created_at, last_updated, canonical_status)
            VALUES ('audit-family', 'mechanism', '2026-05-26', '2026-05-26', 'auto_draft')
            """
        )
        conn.execute(
            """
            INSERT INTO mechanism_memberships
                (paper_id, family_id, confidence, assigned_at, assigned_by, membership_status)
            VALUES ('2605.00008', 'audit-family', 1.0, '2026-05-26', 'test', 'accepted')
            """
        )

    report = audit_library()

    assert report["accepted_non_ai_memberships"] == {"fin": 1}
    assert report["exact_title_cross_source_duplicates"]["count"] == 1


def test_clone_database_copies_without_changing_source(monkeypatch, tmp_path):
    _init_db(monkeypatch, tmp_path)
    ingest.persist_papers([_paper("2605.00009")])
    source = tmp_path / "test.sqlite"
    clone = tmp_path / "validation.sqlite"

    copied = clone_database(source, clone)

    assert copied == clone
    with sqlite3.connect(clone) as conn:
        assert conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0] == 1


def test_build_progress_reports_eta_and_ascii_bar(monkeypatch, tmp_path):
    _init_db(monkeypatch, tmp_path)
    with db.connect() as conn:
        for idx in range(2):
            paper_id = f"openreview:progress-{idx}"
            db.upsert_paper(conn, _paper(paper_id, source="openreview"))
            conn.execute(
                """
                INSERT INTO mechanism_transfer_reviews
                    (paper_id, relevance_status, assessed_at, assessed_by)
                VALUES (?, ?, ?, 'test')
                """,
                (
                    paper_id,
                    "transferable" if idx == 0 else "not_relevant",
                    f"2026-05-26T21:0{idx}:00",
                ),
            )

    report = build_progress(total=4, now=datetime(2026, 5, 26, 21, 2, 0))
    rendered = format_progress(report, width=10)

    assert report["done"] == 2
    assert report["remaining"] == 2
    assert report["percent"] == 50.0
    assert report["rate_per_hour"] == 60.0
    assert report["estimated_completion"] == "2026-05-26T21:04:00"
    assert "[#####-----] 2/4 (50.0%)" in rendered


def test_snapshot_replay_reuses_evidence_metadata_and_new_dedupe(monkeypatch, tmp_path):
    _init_db(monkeypatch, tmp_path)
    ingest_records([_openreview_record("Replay Shared Work", note_id="saved")])
    with db.connect() as conn:
        db.upsert_extraction_l1(conn, "openreview:saved", {
            "side": "ai",
            "method_primary": ["retrieval"],
            "mechanism_description": {"one_liner": "restored mechanism"},
        })
    snapshot = tmp_path / "snapshot.sqlite"
    clone_database(tmp_path / "test.sqlite", snapshot)

    target = tmp_path / "target.sqlite"
    monkeypatch.setenv("ALPHAGAP_DB_PATH", str(target))
    db.init_schema()
    with db.connect() as conn:
        db.upsert_paper(conn, _paper("2605.replay", title="Replay Shared Work"))

    result = replay_evidence_snapshot(snapshot)

    with db.connect() as conn:
        papers = conn.execute("SELECT id FROM papers").fetchall()
        observation = conn.execute(
            "SELECT paper_id, decision, review_scores FROM paper_sources WHERE source = 'openreview'"
        ).fetchone()
        extraction = conn.execute(
            "SELECT side, mechanism_description_json FROM paper_extractions WHERE paper_id = ?",
            ("2605.replay",),
        ).fetchone()
    assert result["fetch_total"] == 1
    assert len(papers) == 1
    assert observation["paper_id"] == "2605.replay"
    assert observation["decision"] == "oral"
    assert json.loads(observation["review_scores"]) == [8, 7]
    assert result["extractions"]["restored"] == 1
    assert extraction["side"] == "ai"
    assert json.loads(extraction["mechanism_description_json"])["one_liner"] == "restored mechanism"
