from datetime import date
from pathlib import Path

from pipeline.analyze import brief


def _item(gap_id: str, gap_type: str) -> dict:
    return {
        "type": gap_type,
        "gap": {"_id": gap_id, "hypothesis": f"hypothesis {gap_id}"},
    }


def test_theoretical_email_ready_gap_does_not_generate_deep_brief(monkeypatch):
    calls: list[str] = []

    def fake_generate(*args, **kwargs):
        calls.append(args[0]["gap"]["_id"])
        return "# generated"

    monkeypatch.setattr(brief, "generate_brief", fake_generate)

    paths = brief.generate_and_save_briefs(
        date(2026, 5, 23),
        [_item("TH-1", "theoretical")],
        {},
        {},
        [],
        client=object(),
    )

    assert paths == []
    assert calls == []


def test_engineering_email_ready_gap_generates_deep_brief(monkeypatch, tmp_path: Path):
    calls: list[str] = []

    def fake_generate(item, *args, **kwargs):
        calls.append(item["gap"]["_id"])
        return "# generated"

    def fake_write(d, item, markdown):
        path = tmp_path / f"{d.isoformat()}-{item['gap']['_id']}.md"
        path.write_text(markdown)
        return path

    monkeypatch.setattr(brief, "generate_brief", fake_generate)
    monkeypatch.setattr(brief, "write_brief", fake_write)
    monkeypatch.setattr(brief, "PROJECT_ROOT", tmp_path)

    item = _item("ENG-1", "engineering")
    paths = brief.generate_and_save_briefs(
        date(2026, 5, 23),
        [item],
        {},
        {},
        [],
        client=object(),
    )

    assert calls == ["ENG-1"]
    assert len(paths) == 1
    assert item["_brief_path"] == "2026-05-23-ENG-1.md"
