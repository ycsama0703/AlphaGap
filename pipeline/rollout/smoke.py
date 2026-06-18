"""Rollout smoke test — a few traced calls through the configured provider.
Proves drop-in provider + trace logging + manifest/progress end-to-end.

On luyao4:  LLM_PROVIDER=local python -m pipeline.rollout.smoke
Locally:    LLM_PROVIDER=deepseek python -m pipeline.rollout.smoke   (to test the trace logic)
"""
from __future__ import annotations

from pipeline.rollout.trace import Run

QS = [
    "Propose ONE cross-sectional equity alpha factor in a single line.",
    "Name one way a factor backtest can overfit, in one sentence.",
    "What distinguishes momentum from short-term reversal? One sentence.",
]


def main():
    run = Run("rollout-smoke", params={"task": "factor-qa", "n": len(QS)})
    print(f"run_id={run.run_id} provider={run.provider} model={run.model}")
    for i, q in enumerate(QS):
        run.progress(phase="rollout", done=i, total=len(QS))
        a = run.chat([{"role": "user", "content": q}], step=f"q{i}", max_tokens=120)
        print(f"  [{i}] {a.strip()[:90]}")
    run.progress(phase="done", done=len(QS), total=len(QS))
    m = run.finish(verdict="smoke_ok", metrics={"calls": run.n})
    print(f"DONE calls={m['n_calls']} elapsed={m['elapsed_s']}s -> {run.dir}")


if __name__ == "__main__":
    main()
