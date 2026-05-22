---
status: active
last_reviewed: 2026-05-22
---

# Fin Field Notes

This directory is a human-maintained Fin domain boundary model. It is adjacent
to AlphaGap, not a generated daily artifact.

Purpose:

- Capture the user's research interests and field boundaries.
- Tell agents what is mature, what remains open, and what transfer targets are
  low-value.
- Provide stable context for AI->Fin gap generation after human review.
- Represent fields at the mechanism level. Paper and benchmark names should be
  evidence for boundaries, not the organizing concepts.

Source policy:

- `recent_boundary` sources define current frontier and should be 2025H2 or
  2026 whenever possible.
- `canonical_background` sources can be older, but only define baseline methods,
  mature tasks, and historical context.
- Do not use pre-2025 survey claims as current frontier unless a newer source
  confirms them.

Current fields:

- `financial_llm_agents.md`
- `factor_investing.md`
- `asset_pricing_ml.md`
- `financial_nlp.md`
- `portfolio_optimization.md`

Update policy:

- Daily pipeline may propose updates in drafts later.
- Official field notes should only change after human review.
- The most important sections to review manually are `Open Bottlenecks`,
  `Bad Or Overcrowded Transfer Targets`, and mechanism-level gap construction
  rules.
