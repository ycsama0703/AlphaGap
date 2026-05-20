"""Mapping table update — Prompt 08.

Proposes status_change / add_mapping / add_evidence actions.
All actions go to inbox/, NEVER auto-applied to mappings/.
"""
from __future__ import annotations


def propose_mapping_updates(today_papers: list[dict], existing_mappings: list[dict],
                             today_accepted_gaps: list[dict]) -> list[dict]:
    """Returns list of proposed actions (each action is a dict)."""
    raise NotImplementedError
