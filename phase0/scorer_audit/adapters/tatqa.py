from __future__ import annotations

import json
import random
import sys
import contextlib
import io
from collections import defaultdict
from pathlib import Path
from typing import Any

from ..extractors import get_extractor
from ..types import AnswerValue, GoldItem, PredictionItem


def load_gold(path: str | Path) -> list[GoldItem]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    items: list[GoldItem] = []
    for context in data:
        for question in context["questions"]:
            items.append(
                GoldItem(
                    uid=question["uid"],
                    answer=AnswerValue.from_parts(question.get("answer"), question.get("scale", "")),
                    answer_type=question.get("answer_type", ""),
                    metadata={
                        "question": question.get("question", ""),
                        "derivation": question.get("derivation", ""),
                        "answer_from": question.get("answer_from", ""),
                    },
                )
            )
    return items


def load_predictions(path: str | Path, *, extractor: str = "official_file") -> dict[str, PredictionItem]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    predictions: dict[str, PredictionItem] = {}
    for uid, value in data.items():
        answer, scale = value if isinstance(value, list) and len(value) == 2 else (None, "")
        predictions[uid] = PredictionItem(
            uid=uid,
            answer=AnswerValue.from_parts(answer, scale),
            extractor=extractor,
        )
    return predictions


def predictions_from_raw(
    raw_path: str | Path,
    extractor_name: str,
) -> tuple[dict[str, PredictionItem], list[dict[str, Any]]]:
    extractor = get_extractor(extractor_name)
    predictions: dict[str, PredictionItem] = {}
    records: list[dict[str, Any]] = []
    with Path(raw_path).open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            record = json.loads(line)
            result = extractor(record.get("raw", ""))
            uid = record["uid"]
            predictions[uid] = PredictionItem(
                uid=uid,
                answer=result.answer,
                raw=record.get("raw", ""),
                extractor=extractor_name,
                metadata={
                    "condition": record.get("cond", ""),
                    "request_hash": record.get("request_hash", ""),
                    "status": result.status,
                    "error": result.error,
                },
            )
            records.append(
                {
                    "uid": uid,
                    "line_number": line_number,
                    "extractor": extractor_name,
                    **result.to_json(),
                }
            )
    return predictions, records


def write_official_predictions(predictions: dict[str, PredictionItem], path: str | Path) -> None:
    payload: dict[str, list[Any]] = {}
    for uid, prediction in predictions.items():
        spans = list(prediction.answer.spans)
        answer: Any
        if not spans:
            answer = None
        elif len(spans) == 1:
            answer = spans[0]
        else:
            answer = spans
        payload[uid] = [answer, prediction.answer.scale]
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def stratified_sample(items: list[GoldItem], n: int, seed: int = 0) -> list[GoldItem]:
    if n <= 0 or n >= len(items):
        return list(items)
    buckets: dict[tuple[str, bool], list[GoldItem]] = defaultdict(list)
    for item in items:
        buckets[(item.answer_type, bool(item.answer.scale))].append(item)
    rng = random.Random(seed)
    for bucket in buckets.values():
        rng.shuffle(bucket)
    keys = sorted(buckets)
    selected: list[GoldItem] = []
    while len(selected) < n:
        progressed = False
        for key in keys:
            if buckets[key] and len(selected) < n:
                selected.append(buckets[key].pop())
                progressed = True
        if not progressed:
            break
    return selected


def run_official_evaluation(
    gold_path: str | Path,
    prediction_path: str | Path,
    tatqa_repo: str | Path,
    selected_uids: set[str] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Run the unmodified official scorer and return its item-level details."""
    repo = str(Path(tatqa_repo).resolve())
    if repo not in sys.path:
        sys.path.insert(0, repo)
    try:
        import tatqa_metric as metric
    except ImportError as exc:
        raise RuntimeError(f"cannot import tatqa_metric from {repo}") from exc

    gold_data = json.loads(Path(gold_path).read_text(encoding="utf-8"))
    predictions = json.loads(Path(prediction_path).read_text(encoding="utf-8"))
    scorer = metric.TaTQAEmAndF1()
    for context in gold_data:
        for question in context["questions"]:
            if selected_uids is not None and question["uid"] not in selected_uids:
                continue
            prediction, scale = predictions.get(question["uid"], (None, None))
            scorer(ground_truth=question, prediction=prediction, pred_scale=scale)
    with contextlib.redirect_stdout(io.StringIO()):
        em, f1, scale, operation = scorer.get_overall_metric()
    summary = {
        "em": em,
        "f1": f1,
        "scale": scale,
        "operation": operation,
        "n": scorer._count,
        "tatqa_repo": repo,
    }
    return summary, list(scorer._details)
