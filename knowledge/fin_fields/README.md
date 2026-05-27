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
- `transfer_cells.yaml`: active, experiment-anchored AI-to-Fin transfer cells
- `../ai_innovation_playbook.md`: one-time calibration of reusable AI innovation
  patterns used to identify credible new finance control points

Transfer cell policy:

- A transfer cell is the formal unit for grounded engineering gap generation.
- Each active cell must specify a finance field, an open bottleneck, a reusable
  AI intervention class, and an experiment anchor with data object, primary
  metric, baseline, and failure mode.
- AI papers provide evidence for existing cells. Automated ingestion must not
  create active cells from paper analogies.
- One AI intervention may support multiple active cells only when it supplies
  a separately complete experiment fit for each cell; there is no forced
  single-cell winner.
- Automatic `support` requires a second conservative confirmation review of
  each proposed link. An unconfirmed proposed support is retained only as a
  candidate extension for human review.
- Until the acceptance threshold below is met, `python -m pipeline.transfer_cells link`
  stages confirmed mappings as candidate links only. The explicit
  `--allow-auto-support` flag enables support persistence after human sign-off.
- A theoretical `frontier_extension` may propose a new cell when an AI
  innovation pattern exposes a concrete finance failure not covered by active
  cells. It must specify the missing failure, intervention, experiment anchor
  sketch, and why the current taxonomy is insufficient.
- A `frontier_extension` remains a human-review discussion item: it does not
  produce an engineering brief or mapping draft until reviewed and added to
  `transfer_cells.yaml`.
- `transfer_cell_eval.yaml` is the curated boundary acceptance set. Run
  `python -m pipeline.transfer_cells evaluate`; evaluation never writes
  evidence decisions or links.
- Do not bulk-link AI evidence unless the acceptance set reaches at least
  0.90 automatic-support precision, 0.80 support-cell recall, and zero
  automatic support on clear negative cases.

Update policy:

- Daily pipeline may propose updates in drafts later.
- Official field notes should only change after human review.
- The most important sections to review manually are `Open Bottlenecks`,
  `Bad Or Overcrowded Transfer Targets`, and mechanism-level gap construction
  rules.
- Review changes to `transfer_cells.yaml` before seeding the taxonomy with
  `python -m pipeline.transfer_cells seed`.
