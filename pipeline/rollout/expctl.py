"""expctl — query experiment runs (CLI, output over ssh stdout; no web server, no file transfer).

  python -m pipeline.rollout.expctl list                 # all runs: status / verdict / cost / when
  python -m pipeline.rollout.expctl show <run_id>        # manifest + trace summary
  python -m pipeline.rollout.expctl progress <run_id>    # live progress of a running experiment
  python -m pipeline.rollout.expctl trace <run_id> [k]   # last k trace records (default 5)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

RUNS = Path(__file__).resolve().parent.parent.parent / "runs"


def _load(p):
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}


def _runs():
    return sorted([d for d in RUNS.glob("*") if (d / "manifest.json").exists()],
                  key=lambda d: d.name)


def cmd_list():
    rows = [_load(d / "manifest.json") for d in _runs()]
    if not rows:
        print("(no runs yet)"); return
    print(f"{'run_id':40} {'prov':8} {'status':8} {'verdict':14} {'calls':>5} {'elapsed':>8}")
    for m in rows:
        print(f"{m.get('run_id',''):40} {str(m.get('provider','')):8} {str(m.get('status','')):8} "
              f"{str(m.get('verdict') or ''):14} {str(m.get('n_calls') or ''):>5} "
              f"{str(m.get('elapsed_s') or ''):>8}")


def _find(run_id):
    d = RUNS / run_id
    if d.exists():
        return d
    hits = [x for x in _runs() if run_id in x.name]
    return hits[-1] if hits else None


def cmd_show(run_id):
    d = _find(run_id)
    if not d:
        print(f"no run matching {run_id!r}"); return
    m = _load(d / "manifest.json")
    print(json.dumps(m, indent=2, ensure_ascii=False))
    tf = d / "trace.jsonl"
    if tf.exists():
        recs = [json.loads(l) for l in tf.read_text().splitlines() if l.strip()]
        pt = sum(r.get("prompt_tokens") or 0 for r in recs)
        ct = sum(r.get("completion_tokens") or 0 for r in recs)
        lat = [r.get("latency_ms") or 0 for r in recs]
        print(f"\ntrace: {len(recs)} calls | prompt_tok={pt} completion_tok={ct} "
              f"| avg_latency={int(sum(lat)/len(lat)) if lat else 0}ms")


def cmd_progress(run_id):
    d = _find(run_id)
    if not d:
        print(f"no run matching {run_id!r}"); return
    print(json.dumps(_load(d / "progress.json"), indent=2, ensure_ascii=False))


def cmd_trace(run_id, k=5):
    d = _find(run_id)
    if not d or not (d / "trace.jsonl").exists():
        print("no trace"); return
    recs = [json.loads(l) for l in (d / "trace.jsonl").read_text().splitlines() if l.strip()]
    for r in recs[-int(k):]:
        print(f"--- step={r.get('step')} n={r.get('n')} lat={r.get('latency_ms')}ms ---")
        print("  Q:", str(r.get('messages', [{}])[-1].get('content', ''))[:100])
        print("  A:", str(r.get('response', ''))[:160])


def main():
    a = sys.argv[1:]
    if not a or a[0] == "list":
        cmd_list()
    elif a[0] == "show" and len(a) > 1:
        cmd_show(a[1])
    elif a[0] == "progress" and len(a) > 1:
        cmd_progress(a[1])
    elif a[0] == "trace" and len(a) > 1:
        cmd_trace(a[1], a[2] if len(a) > 2 else 5)
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
