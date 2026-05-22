from pipeline.analyze.mapping_update import propose_mapping_updates


class FakeClient:
    def __init__(self, result):
        self.result = result

    def chat_json(self, **kwargs):
        return self.result


def test_propose_mapping_updates_drops_add_mapping_when_draft_exists():
    result = {
        "actions": [{
            "type": "add_mapping",
            "from_gap_id": "ENG-1",
            "ai_concept": "dense credit assignment",
            "fin_concept": "factor attribution",
            "initial_status": "open_gap",
            "reason": "accepted gap",
        }]
    }

    actions = propose_mapping_updates(
        today_papers=[],
        existing_mappings=[],
        today_accepted_gaps=[{
            "_mapping_draft_path": "mappings/drafts/2026-05-22-ENG-1.md",
            "gap": {"_id": "ENG-1"},
        }],
        client=FakeClient(result),
    )

    assert actions == []
