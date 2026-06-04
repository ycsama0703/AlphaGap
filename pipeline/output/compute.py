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
    runtime = profile.get("run_wallclock") or profile.get("estimated_runtime") or ""
    api = profile.get("api_cost_usd")
    bottleneck = profile.get("main_bottleneck") or ""
    native = profile.get("findata_native")
    build = profile.get("data_build") or ""

    parts = []
    if api is not None:
        parts.append(f"API ~${api}")
    parts.append(f"compute={tier}")
    if req:
        parts.append(req)
    if runtime:
        parts.append(str(runtime))
    if native is True:
        parts.append("data: findata-native")
    elif native is False:
        parts.append(f"data: needs build ({build})" if build else "data: needs external build")
    if bottleneck:
        parts.append(f"bottleneck: {bottleneck}")
    return " · ".join(parts)
