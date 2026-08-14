from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


AnswerData = str | int | float | list[str | int | float] | None


def _spans(value: AnswerData) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, list):
        return tuple(str(v) for v in value)
    return (str(value),)


@dataclass(frozen=True)
class AnswerValue:
    spans: tuple[str, ...]
    scale: str = ""

    @classmethod
    def from_parts(cls, answer: AnswerData, scale: Any = "") -> "AnswerValue":
        return cls(_spans(answer), str(scale or "").strip().lower())

    def to_json(self) -> dict[str, Any]:
        return {"answer": list(self.spans), "scale": self.scale}


@dataclass(frozen=True)
class GoldItem:
    uid: str
    answer: AnswerValue
    answer_type: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PredictionItem:
    uid: str
    answer: AnswerValue
    raw: str = ""
    extractor: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TraceEvent:
    operation: str
    before: str
    after: str
    changed: bool
    detail: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CanonicalAnswer:
    value: str
    trace: tuple[TraceEvent, ...] = ()

    def to_json(self) -> dict[str, Any]:
        return {"value": self.value, "trace": [event.to_json() for event in self.trace]}


@dataclass(frozen=True)
class ExtractionResult:
    answer: AnswerValue
    status: str = "ok"
    error: str = ""

    def to_json(self) -> dict[str, Any]:
        return {"status": self.status, "error": self.error, **self.answer.to_json()}
