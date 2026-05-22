"""Rendering helpers for engineering gap compute requirements."""
from __future__ import annotations


def compute_profile_summary(profile: dict | None) -> str:
    if not isinstance(profile, dict) or not profile:
        return ""

    tier = profile.get("tier") or "?"
    requirements = profile.get("requirements") or []
    if isinstance(requirements, str):
        requirements = [requirements]
    req = ", ".join(str(x) for x in requirements if str(x).strip())
    runtime = profile.get("estimated_runtime") or ""
    bottleneck = profile.get("main_bottleneck") or ""

    parts = [f"tier={tier}"]
    if req:
        parts.append(req)
    if runtime:
        parts.append(str(runtime))
    if bottleneck:
        parts.append(f"bottleneck: {bottleneck}")
    return " · ".join(parts)
