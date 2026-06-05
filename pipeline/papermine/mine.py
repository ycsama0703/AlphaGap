"""L3 paper mining — fetch a paper's FULL TEXT and extract its transferable experiment structure.

The shallow L1/L2 extraction reads only the abstract → one mechanism/paper → shallow gaps. This goes
deeper: download the PDF (embedded claude-paper scripts), parse full text, and mine the EXPERIMENT
STRUCTURE — multiple transferable sub-mechanisms, what the ablations reveal about WHY it works, the
boundary conditions, and the failure modes the authors found. This is the deep fuel for research-gap
generation (depth + mechanism composition + frontier).

Headless: download+parse are deterministic node scripts (lifted from github.com/alaliqing/claude-paper,
MIT); mining is DeepSeek via the AlphaGap LLMClient. Runs without an interactive agent → cron-able.

Usage: from pipeline.papermine.mine import mine_paper; rec = mine_paper("2603.19835")
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
from pathlib import Path

log = logging.getLogger("papermine")
_DIR = Path(__file__).resolve().parent
_NODE = "node"
MAX_BODY = 42000   # chars of body fed to the LLM (drop references/appendix first)


def fetch_fulltext(arxiv_id_or_url: str) -> dict:
    """Download + parse a paper → {title, authors, abstract, content, githubLinks, codeLinks, pageCount}."""
    url = (arxiv_id_or_url if arxiv_id_or_url.startswith("http")
           else f"https://arxiv.org/abs/{arxiv_id_or_url}")
    dl = subprocess.run([_NODE, str(_DIR / "download-pdf.cjs"), url],
                        capture_output=True, text=True, timeout=120)
    pdf_path = dl.stdout.strip().splitlines()[-1] if dl.stdout.strip() else ""
    if dl.returncode != 0 or not pdf_path or not Path(pdf_path).exists():
        raise RuntimeError(f"download failed: {dl.stderr.strip()[:200]}")
    pr = subprocess.run([_NODE, str(_DIR / "parse-pdf.js"), pdf_path],
                        capture_output=True, text=True, timeout=120)
    if pr.returncode != 0:
        raise RuntimeError(f"parse failed: {pr.stderr.strip()[:200]}")
    return json.loads(pr.stdout)


def _body_for_mining(content: str) -> str:
    """Drop the references/bibliography tail (low transfer value), keep method+experiments+ablations."""
    cut = len(content)
    for m in re.finditer(r"\n\s*(References|Bibliography|REFERENCES)\s*\n", content):
        cut = m.start()  # last occurrence wins (refs are near the end)
    return content[:cut][:MAX_BODY]


_MINE_SYSTEM = """你从一篇 AI 论文的【全文】里挖掘可迁移到金融研究的【实验结构】,而不是压成一句话。
abstract 只给一个机制;全文有主实验 + 2-3 个消融/子实验,每个都藏着可迁移的点和"为什么 work"的洞见。
你的产出是后续 AI×Fin 研究 gap 的【深度燃料】,所以要机制级、具体、带论文里的真实数字,绝不编造。

输出严格 JSON:
{
  "main_claim": "论文核心主张(机制级,≤60字,不要品牌名)",
  "transferable_sub_mechanisms": [           // 复数!这是最重要的——一篇论文多个可独立迁移的机制点
    {"mechanism": "机制功能描述(非品牌名)", "evidence": "论文里支撑它的实验/数字",
     "why_transferable": "它为什么可能迁到金融的某类问题(机制层,不指定具体gap)"}
  ],                                          // 抽 2-5 个,主方法 + 消融揭示的子机制都算
  "ablations_why": [                          // 消融揭示的"它为什么 work"——做深迁移的关键
    {"removed": "拿掉了什么组件", "effect": "性能怎么变(带数字)", "reveals": "这说明真正起作用的是什么机制"}
  ],
  "boundary_conditions": ["机制在什么条件下成立/失效(规模、数据、任务结构…)"],
  "failure_modes": ["作者自己发现或承认的失败/局限(机制层)"],
  "key_quant_results": ["主实验的关键量化结果,带 benchmark 名和数字"]
}

规则:
1. transferable_sub_mechanisms 必须 ≥2 个;只有一个说明你没挖透全文(消融里一定还有子机制)
2. 全部机制级、功能化描述,禁止只写品牌方法名(品牌名只可出现在 evidence 里作证据)
3. ablations_why 的 reveals 字段是精华:它告诉下游"这个机制真正依赖什么",决定迁移深不深
4. 数字只填论文真报告过的;摘要/全文没有就留空,绝不编造
5. boundary_conditions / failure_modes 是 frontier gap(格子外新问题)的来源,认真挖"
"""


_CACHE_DDL = """CREATE TABLE IF NOT EXISTS paper_mines (
    arxiv_id TEXT PRIMARY KEY, mined_json TEXT NOT NULL, pages INTEGER,
    fulltext_chars INTEGER, n_sub_mechanisms INTEGER, mined_at TEXT NOT NULL,
    miner_version TEXT NOT NULL DEFAULT 'l3-v1')"""
_MINER_VERSION = "l3-v1"


def get_cached_mine(arxiv_id: str):
    """Return the persisted L3 record for this paper, or None. Defensive (table may not exist yet)."""
    try:
        from pipeline import db
        with db.connect() as c:
            c.execute(_CACHE_DDL)
            row = c.execute("SELECT mined_json FROM paper_mines WHERE arxiv_id=? AND miner_version=?",
                            (arxiv_id, _MINER_VERSION)).fetchone()
        return json.loads(row[0]) if row else None
    except Exception as e:
        log.warning("paper_mines cache read failed: %s", e)
        return None


def save_mine(rec: dict) -> None:
    """Lazy write-back: persist a freshly-mined L3 record so the corpus deepens where it's used."""
    try:
        from datetime import datetime, timezone
        from pipeline import db
        with db.connect() as c:
            c.execute(_CACHE_DDL)
            c.execute("INSERT OR REPLACE INTO paper_mines "
                      "(arxiv_id, mined_json, pages, fulltext_chars, n_sub_mechanisms, mined_at, miner_version) "
                      "VALUES (?,?,?,?,?,?,?)",
                      (rec.get("arxiv_id"), json.dumps(rec, ensure_ascii=False), rec.get("pages"),
                       rec.get("fulltext_chars"), len(rec.get("transferable_sub_mechanisms") or []),
                       datetime.now(timezone.utc).isoformat(), _MINER_VERSION))
            c.commit() if hasattr(c, "commit") else None
    except Exception as e:
        log.warning("paper_mines write-back failed: %s", e)


def mine_paper(arxiv_id_or_url: str, *, client=None, use_cache: bool = True, persist: bool = True) -> dict:
    """Fetch full text → LLM-mine the experiment structure. Cache-aware: returns the persisted L3
    record if present (lazy deepening of the corpus), else mines and writes back. use_cache/persist
    let callers force a fresh mine or skip storage."""
    import sys
    if str(_DIR.parent.parent) not in sys.path:
        sys.path.insert(0, str(_DIR.parent.parent))
    from pipeline.llm_client import LLMClient

    aid = arxiv_id_or_url.split("/")[-1].replace(".pdf", "")
    if use_cache:
        cached = get_cached_mine(aid)
        if cached:
            log.info("paper_mines: cache hit for %s (no re-mine)", aid)
            return cached

    client = client or LLMClient()
    ft = fetch_fulltext(arxiv_id_or_url)
    body = _body_for_mining(ft.get("content", ""))
    user = (f"论文标题: {ft.get('title','')[:120]}\n"
            f"代码仓库: {ft.get('githubLinks', [])[:1]}\n\n"
            f"【论文全文(已去 references)】\n{body}")
    mined = client.chat_json(system=_MINE_SYSTEM, user=user, temperature=0.0,
                             reasoning=True, max_tokens=4096) or {}
    rec = {
        "arxiv_id": aid,
        "pages": ft.get("pageCount"), "fulltext_chars": len(ft.get("content", "")),
        "github": ft.get("githubLinks", []),
        **{k: mined.get(k) for k in ("main_claim", "transferable_sub_mechanisms", "ablations_why",
                                     "boundary_conditions", "failure_modes", "key_quant_results")},
    }
    if persist and (rec.get("transferable_sub_mechanisms")):
        save_mine(rec)
    return rec
