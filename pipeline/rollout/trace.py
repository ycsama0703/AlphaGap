"""Rollout observability layer — the supporting infra for GPU/local-LLM experiments.

Every LLM call is logged as a structured JSONL record; each run gets a manifest + live progress file.
Provider-agnostic (the local ollama engine on luyao4's 5080, or any OpenAI-compatible API). Files live
under <repo>/runs/<run_id>/ (gitignored). Designed so traces are queryable (see expctl) and
AUTO-GRADABLE (decisions/tool-calls recorded structurally, not as opaque text), so agent-gap validation
needs no human labels.

Usage:
    from pipeline.rollout.trace import Run
    run = Run("my-exp", params={...})          # provider from LLM_PROVIDER env (default local)
    for i, q in enumerate(items):
        run.progress(phase="rollout", done=i, total=len(items))
        ans = run.chat([{"role": "user", "content": q}], step=f"q{i}")
    run.finish(verdict="...", metrics={...})
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
RUNS = ROOT / "runs"


def _load_env() -> None:
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())


def _git_commit() -> str:
    try:
        return subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"],
                                       text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return "unknown"


def make_client(provider: str | None = None):
    """Return (OpenAI client, model) for the provider (env LLM_PROVIDER if None).
    'local'/'ollama' → the local GPU engine; 'deepseek' → the API. Easy to extend."""
    from openai import OpenAI
    _load_env()
    provider = (provider or os.getenv("LLM_PROVIDER", "local")).strip().lower()
    if provider in ("local", "ollama"):
        return (OpenAI(base_url=os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1"),
                       api_key=os.getenv("OLLAMA_API_KEY", "ollama")),
                os.getenv("OLLAMA_MODEL", "qwen2.5:7b-instruct"), provider)
    if provider == "deepseek":
        return (OpenAI(base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
                       api_key=os.getenv("DEEPSEEK_API_KEY")),
                os.getenv("DEEPSEEK_MODEL_DEFAULT", "deepseek-v4-flash"), provider)
    if provider == "openrouter":   # the strong "deep" model (gpt-chat-latest) — cross-model check
        return (OpenAI(base_url=os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
                       api_key=os.getenv("OPENROUTER_API_KEY")),
                os.getenv("ROLLOUT_OPENROUTER_MODEL") or os.getenv("OPENROUTER_MODEL_OPUS", "openai/gpt-chat-latest"),
                provider)
    raise ValueError(f"rollout.make_client: unsupported provider {provider!r}")


class Run:
    def __init__(self, exp: str, params: dict | None = None, provider: str | None = None):
        self.client, self.model, self.provider = make_client(provider)
        ts = time.strftime("%Y%m%d-%H%M%S")
        self.run_id = f"{exp}-{ts}"
        self.dir = RUNS / self.run_id
        self.dir.mkdir(parents=True, exist_ok=True)
        self.n = 0
        self._t0 = time.time()
        self._manifest = {
            "run_id": self.run_id, "exp": exp, "provider": self.provider, "model": self.model,
            "params": params or {}, "git_commit": _git_commit(),
            "started_at": ts, "status": "running",
        }
        self._write_manifest()

    def _write_manifest(self):
        (self.dir / "manifest.json").write_text(
            json.dumps(self._manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    def progress(self, **kw):
        (self.dir / "progress.json").write_text(
            json.dumps({"ts": round(time.time(), 1), **kw}, ensure_ascii=False), encoding="utf-8")

    def chat(self, messages, *, step: str = "", **kw) -> str:
        t = time.time()
        r = self.client.chat.completions.create(model=self.model, messages=messages, **kw)
        dt = int((time.time() - t) * 1000)
        msg = r.choices[0].message.content or ""
        u = getattr(r, "usage", None)
        rec = {
            "run_id": self.run_id, "n": self.n, "step": step, "ts": round(time.time(), 3),
            "provider": self.provider, "model": self.model, "params": kw,
            "messages": messages, "response": msg,
            "prompt_tokens": getattr(u, "prompt_tokens", None),
            "completion_tokens": getattr(u, "completion_tokens", None),
            "latency_ms": dt,
        }
        with (self.dir / "trace.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        self.n += 1
        return msg

    def finish(self, verdict=None, metrics: dict | None = None, status: str = "done"):
        self._manifest.update({
            "status": status, "verdict": verdict, "metrics": metrics or {},
            "n_calls": self.n, "elapsed_s": round(time.time() - self._t0, 1),
            "ended_at": time.strftime("%Y%m%d-%H%M%S"),
        })
        self._write_manifest()
        return self._manifest
