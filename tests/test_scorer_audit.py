from __future__ import annotations

import json
import random

import pytest

from phase0.scorer_audit.blind_audit import _randomized_candidates, assert_reviewer_blind
from phase0.scorer_audit.engine import audit, decision_changes, summarize_audit
from phase0.scorer_audit.exact_tatqa import (
    EXACT_POLICY_ORDER,
    audit_exact,
    compare_official_rows,
    score_exact_item,
    summarize_exact,
)
from phase0.scorer_audit.judge_agreement import cohen_kappa
from phase0.scorer_audit.extractors import (
    extract_free_regex,
    extract_free_surface,
    extract_free_typed,
    extract_labeled,
    extract_schema,
)
from phase0.scorer_audit.policies import canonicalize
from phase0.scorer_audit.types import AnswerValue, GoldItem, PredictionItem
from phase0.openrouter_batch import (
    base_model_slug,
    build_batch_payload,
    completion_from_batch_result,
)
from phase0.tatqa_run import _existing_successes, build_request_body, stratified_items
from phase0.tatqa_run import load_dev
from phase0.tatqa_blind_judge import build_judge_body


def test_json_condition_uses_real_schema() -> None:
    body = build_request_body("model", "prompt", "json")
    assert body["response_format"]["type"] == "json_schema"
    schema = body["response_format"]["json_schema"]
    assert schema["strict"] is True
    assert schema["schema"]["properties"]["answer"]["type"] == "array"
    assert body["reasoning"] == {"effort": "high", "exclude": True}
    assert body["provider"]["require_parameters"] is True
    pinned = build_request_body("model", "prompt", "json", provider="DeepInfra")
    assert pinned["provider"] == {
        "require_parameters": True,
        "order": ["DeepInfra"],
        "allow_fallbacks": False,
    }
    assert "response_format" not in build_request_body("model", "prompt", "free")
    compatible = build_request_body(
        "model",
        "prompt",
        "free",
        drop_parameters=("temperature", "seed"),
    )
    assert "temperature" not in compatible
    assert "seed" not in compatible


def test_extractors_preserve_answer_types_and_surfaces() -> None:
    structured = extract_schema('{"answer":["2018","2019"],"scale":""}')
    assert structured.status == "ok"
    assert structured.answer.spans == ("2018", "2019")

    typed = extract_free_regex("After checking the table, the final answer is (134) million.")
    assert typed.answer.spans == ("(134)",)
    assert typed.answer.scale == "million"

    focused = extract_free_regex(
        "The debt ratio in 2018 was approximately 27.5% (92,364 divided by 336,032)."
    )
    assert focused.answer.spans == ("27.5%",)
    assert focused.answer.scale == "percent"

    revised = extract_free_regex("The answer is 100. On reflection, final answer: 120 million.")
    assert revised.answer.spans == ("120",)
    assert revised.answer.scale == "million"

    surface = extract_free_surface("The answer is 12%.")
    assert surface.answer.spans == ("12%",)
    assert surface.answer.scale == ""
    assert extract_free_typed("Only one year (2019) exceeded the threshold.").answer.spans == ("1",)
    assert extract_free_typed("There are seven services in total.").answer.spans == ("7",)
    labeled = extract_labeled("ANSWER: [1, 2]\nSCALE: million")
    assert labeled.answer.spans == ("1", "2")
    assert labeled.answer.scale == "million"


def test_permission_boundaries_are_cumulative() -> None:
    accounting = AnswerValue.from_parts("(134)")
    assert canonicalize(accounting, "p1_syntax").value == "(134)"
    assert canonicalize(accounting, "p2_scale").value == "(134)"
    assert canonicalize(accounting, "p3_numeric").value == "-134"
    assert canonicalize(accounting, "p4_round2").value == "-134"

    structured_scale = AnswerValue.from_parts("1", "million")
    assert "scale:million" in canonicalize(structured_scale, "p1_syntax").value
    assert canonicalize(structured_scale, "p2_scale").value == "1000000"

    percent = AnswerValue.from_parts("12%", "percent")
    assert canonicalize(percent, "p2_scale").value.startswith("12%")
    assert canonicalize(percent, "p3_numeric").value == "0.12"


def test_syntax_does_not_preserve_textual_hyphens_as_numeric_signs() -> None:
    answer = AnswerValue.from_parts("The cost-plus contract.")
    assert canonicalize(answer, "p1_syntax").value == "cost plus contract"
    assert canonicalize(AnswerValue.from_parts("-12.5%"), "p1_syntax").value == "-12.5%"


def test_transition_decomposition_matches_delta_em() -> None:
    gold = [
        GoldItem("a", AnswerValue.from_parts("-134"), "arithmetic"),
        GoldItem("b", AnswerValue.from_parts("10"), "count"),
    ]
    predictions = {
        "a": PredictionItem("a", AnswerValue.from_parts("(134)")),
        "b": PredictionItem("b", AnswerValue.from_parts("10")),
    }
    policies = ("p1_syntax", "p3_numeric")
    rows = audit(gold, predictions, policies, mode="fixed_gold")
    summary = summarize_audit(rows, policies)
    transition = summary["transitions"][0]
    assert transition["n01"] == 1
    assert transition["n10"] == 0
    assert transition["delta_em"] == 0.5
    assert summary["scores"]["p3_numeric"]["em"] == 1.0
    changes = decision_changes(rows, policies)
    assert [(change["uid"], change["transition"]) for change in changes] == [("a", "0->1")]


def test_stratified_sampling_is_deterministic_and_balanced() -> None:
    items = [
        {
            "uid": f"{answer_type}-{scale}-{index}",
            "answer_type": answer_type,
            "gold_scale": scale,
        }
        for answer_type in ("span", "arithmetic")
        for scale in ("", "million")
        for index in range(5)
    ]
    first = stratified_items(items, 8, 7)
    second = stratified_items(items, 8, 7)
    assert [item["uid"] for item in first] == [item["uid"] for item in second]
    strata = {(item["answer_type"], bool(item["gold_scale"])) for item in first}
    assert len(strata) == 4


def test_load_dev_replaces_an_incomplete_download(monkeypatch, tmp_path) -> None:
    path = tmp_path / "dev.json"
    path.write_text("", encoding="utf-8")

    class Response:
        content = b'[{"table": {}, "paragraphs": [], "questions": []}]'

        def raise_for_status(self) -> None:
            return None

        def json(self):
            return json.loads(self.content)

    monkeypatch.setattr("phase0.tatqa_run.requests.get", lambda *args, **kwargs: Response())
    assert load_dev(path)[0]["questions"] == []
    assert json.loads(path.read_text(encoding="utf-8"))[0]["table"] == {}


def test_resume_treats_truncation_as_terminal(tmp_path) -> None:
    path = tmp_path / "raw.jsonl"
    path.write_text(
        '\n'.join(
            [
                '{"uid":"ok","status":"ok","raw":"answer","run_fingerprint":"run"}',
                '{"uid":"cut","status":"truncated","raw":"","run_fingerprint":"run"}',
                '{"uid":"retry","status":"error","raw":"","run_fingerprint":"run","error":"HTTP 429"}',
            ]
        ),
        encoding="utf-8",
    )
    assert _existing_successes(path, "run") == {"ok", "cut"}


def test_openrouter_batch_payload_uses_base_model_and_preserves_request_body() -> None:
    body = build_request_body(
        "anthropic/claude-sonnet-5",
        "prompt",
        "json",
        provider="Anthropic",
    )
    payload = build_batch_payload(
        "anthropic/claude-sonnet-5:batch",
        {"item-1": body},
    )
    assert base_model_slug("anthropic/claude-sonnet-5:batch") == "anthropic/claude-sonnet-5"
    assert payload["model"] == "anthropic/claude-sonnet-5"
    assert payload["requests"][0]["custom_id"] == "item-1"
    request_body = payload["requests"][0]["body"]
    assert request_body["model"] == "anthropic/claude-sonnet-5"
    assert request_body["provider"]["order"] == ["Anthropic"]
    assert request_body["response_format"]["type"] == "json_schema"


def test_openrouter_batch_result_matches_realtime_record_shape() -> None:
    result = {
        "custom_id": "item-1",
        "response": {
            "status_code": 200,
            "body": {
                "id": "generation-1",
                "model": "provider/model",
                "provider": "Provider",
                "usage": {"prompt_tokens": 10, "completion_tokens": 2},
                "choices": [
                    {
                        "message": {"content": "answer"},
                        "finish_reason": "stop",
                        "native_finish_reason": "stop",
                    }
                ],
            },
        },
    }
    status, raw, usage, error, meta = completion_from_batch_result(result)
    assert (status, raw, error) == ("ok", "answer", "")
    assert usage["prompt_tokens"] == 10
    assert meta["provider"] == "Provider"


def test_exact_tatqa_path_keeps_syntax_and_semantic_permissions_separate() -> None:
    gold = GoldItem("signed", AnswerValue.from_parts("-134"), "arithmetic")
    prediction = PredictionItem("signed", AnswerValue.from_parts("(134)"))
    p1 = score_exact_item(gold, prediction, "exact_p1_syntax")
    p3 = score_exact_item(gold, prediction, "exact_p3_numeric")
    assert p1["pred_canonical"] == "(134)"
    assert p1["gold_canonical"] == "-134"
    assert p1["correct"] is False
    assert p3["pred_canonical"] == "-134.0"
    assert p3["gold_canonical"] == "-134.0"
    assert p3["correct"] is True

    scaled_gold = GoldItem("scale", AnswerValue.from_parts("1", "million"), "arithmetic")
    scaled_prediction = PredictionItem("scale", AnswerValue.from_parts("1000000"))
    assert score_exact_item(scaled_gold, scaled_prediction, "exact_p1_syntax")["correct"] is False
    assert score_exact_item(scaled_gold, scaled_prediction, "exact_p2_scale")["correct"] is True


def test_exact_tatqa_summary_and_official_comparison_are_itemwise() -> None:
    gold = [
        GoldItem("a", AnswerValue.from_parts("25", "percent"), "arithmetic"),
        GoldItem("b", AnswerValue.from_parts("2"), "count"),
    ]
    predictions = {
        "a": PredictionItem("a", AnswerValue.from_parts("0.25")),
        "b": PredictionItem("b", AnswerValue.from_parts("two")),
    }
    rows = audit_exact(gold, predictions)
    summary = summarize_exact(rows)
    assert tuple(summary["scores"]) == EXACT_POLICY_ORDER
    assert summary["scores"]["exact_official"]["em"] == 0.5
    official_rows = [
        {"uid": "a", "em": 1.0, "f1": 1.0},
        {"uid": "b", "em": 0.0, "f1": 0.0},
    ]
    verification = compare_official_rows(rows, official_rows)
    assert verification["itemwise_exact"] is True
    official_rows[1]["em"] = 1.0
    assert compare_official_rows(rows, official_rows)["n_mismatches"] == 1


def test_blind_audit_candidate_order_is_seeded_and_leaks_are_rejected(tmp_path) -> None:
    first = _randomized_candidates("raw", "official", "low", "high", random.Random(9))
    second = _randomized_candidates("raw", "official", "low", "high", random.Random(9))
    assert first == second
    assert {first[0]["candidate_a"], first[0]["candidate_b"]} == {"raw", "official"}

    reviewer = tmp_path / "reviewer"
    reviewer.mkdir()
    packet = reviewer / "packet.jsonl"
    packet.write_text('{"blind_id":"B0001","question":"safe"}\n', encoding="utf-8")
    assert assert_reviewer_blind(reviewer)["violations"] == 0
    packet.write_text(
        '{"blind_id":"B0001","uid":"276f39d7-5428-46cf-b808-7dd9eefab430"}\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="leaks private labels"):
        assert_reviewer_blind(reviewer)
    packet.write_text('{"blind_id":"B0001","condition":"hidden"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="private keys"):
        assert_reviewer_blind(reviewer)


def test_judge_agreement_kappa() -> None:
    assert cohen_kappa(["yes", "yes", "no", "no"], ["yes", "yes", "no", "no"]) == 1.0
    assert cohen_kappa(["yes", "yes", "no", "no"], ["yes", "no", "yes", "no"]) == 0.0
    assert cohen_kappa([], []) is None


def test_blind_judge_request_is_strict_and_provider_pinned() -> None:
    body = build_judge_body(
        "openai/gpt-5.6-terra-pro",
        "OpenAI",
        "pass1",
        {"blind_id": "B0001", "model_response": "The answer is 3."},
        seed=1,
        max_tokens=2000,
        reasoning_effort="medium",
    )
    assert body["provider"] == {
        "require_parameters": True,
        "order": ["OpenAI"],
        "allow_fallbacks": False,
    }
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["strict"] is True
    assert body["reasoning"] == {"effort": "medium", "exclude": True}
