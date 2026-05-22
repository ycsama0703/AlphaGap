from pipeline.output.compute import compute_profile_summary


def test_compute_profile_summary_renders_core_fields():
    summary = compute_profile_summary({
        "tier": "medium",
        "requirements": ["cpu", "llm_api"],
        "estimated_runtime": "1-3 days",
        "main_bottleneck": "LLM verifier API cost",
    })

    assert summary == "tier=medium · cpu, llm_api · 1-3 days · bottleneck: LLM verifier API cost"


def test_compute_profile_summary_handles_missing_profile():
    assert compute_profile_summary(None) == ""
    assert compute_profile_summary({}) == ""
