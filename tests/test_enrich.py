from pipeline.analyze.enrich import _attach_baseline_links


def test_baseline_links_are_only_attached_from_resolved_papers():
    gap = {
        "experimental_roadmap": {
            "baselines": [
                {
                    "name": "Resolved work",
                    "paper_id": "2501.00001",
                    "citation": "Known paper",
                    "url": "https://untrusted.example/fabricated",
                },
                {
                    "name": "Unresolved work",
                    "paper_id": "missing",
                    "citation": "Unverified paper",
                    "url": "https://untrusted.example/also-fabricated",
                },
            ],
        },
    }

    _attach_baseline_links(
        gap,
        {"2501.00001": {"id": "2501.00001", "url": "https://arxiv.org/abs/2501.00001"}},
    )

    baselines = gap["experimental_roadmap"]["baselines"]
    assert baselines[0]["url"] == "https://arxiv.org/abs/2501.00001"
    assert "url" not in baselines[1]
