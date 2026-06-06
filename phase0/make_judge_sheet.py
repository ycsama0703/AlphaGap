"""Generate phase0/out/judge_sheet.md — the self-contained, model-neutral evidence-sufficiency task.

v2: adds two EXPLICIT rulings that resolve the edge cases two judges split on in the v1 round
(κ=0.538). Give the SAME sheet to several FRESH, blind model chats (Claude / GPT / DeepSeek); ingest
each reply into its own column (suff_A/B/C) via ingest_labels.py; stats.py computes inter-judge κ.

  python -m phase0.make_judge_sheet
"""
from __future__ import annotations

import csv
from pathlib import Path

_OUT = Path(__file__).resolve().parent / "out"

RUBRIC = """# 证据充分性判定任务 (v2)

> 把【整份文件】发给一个**全新的模型对话**(全新的 GPT / Claude / DeepSeek——不要用参与过本研究的会话,以保证独立判断)。

你是一名「证据充分性审计员」。下面有 60 条编号条目,每条包含:
- 一个【主张】:关于某公司某季度财报电话会上,管理层把这一季的主要驱动/原因归结为什么;
- 该主张所【引用的证据】(通常是电话会原话,或注明"无直接证据")。

你的唯一任务:逐条判断【引用的证据是否足以支撑该主张】,三选一:`sufficient` / `insufficient` / `unknown`。

## 判定标准
- **sufficient(充分)**:引用的原话明确陈述了该主张本身。若主张含因果归因(把增长归因于 X),原话需明确指向 X。
- **insufficient(不足)**:没有证据 / 未找到记录;或原话被截断、不完整;或主张断言了原话里并未出现的具体内容。
- **unknown**:确实无法判断,尽量少用。

## 两条必须遵守的明确规则(优先于上面的直觉)
- **规则 A —— 具体业务增长 = 充分。** 若原话给出某业务/板块的**具体增长数字或明确加速**
  (例如 "AWS grew 28%"、"Azure surpassed $75 billion, up 34%"、"Cloud accelerated… up 48%"、"sales growth of 5.2%"、
  "box office of $6.5 billion"),而主张说"该业务/板块是本季的驱动/增长来源",**一律判 sufficient**——因为这是可核验的具体证据。
- **规则 B —— 空泛套话 = 不足。** 若原话只是**没有具体业务、没有数字、不可证伪的定性套话**
  (例如 "exceptional execution"、"discipline and focus"、"disciplined execution of our strategic priorities"、
  "constructively discontent"、"meeting demand and reducing emissions" 这类),即使原话字面提到,也**一律判 insufficient**——
  因为它无法核验任何具体驱动。

原则:只看"引用的证据能不能撑住这条主张",**不要用你自己的外部知识去补证据**,也不要管主张本身是否重要。

**输出:严格只输出 60 行,每行 `序号: sufficient|insufficient|unknown`,从 0 到 59,不要任何解释或表头。**

---
"""


def main():
    rows = list(csv.DictReader((_OUT / "annotation.csv").open(encoding="utf-8")))
    qual = [r for r in rows if r["kind"] == "qualitative"]
    L = [RUBRIC]
    for i, r in enumerate(qual):
        L.append(f"{i}. [{r['task_id']}] 主张: {r['claim_text']}")
        L.append(f"   证据: {r['agent_evidence_ref']}\n")
    (_OUT / "judge_sheet.md").write_text("\n".join(L), encoding="utf-8")
    print(f"wrote phase0/out/judge_sheet.md (v2, {len(qual)} items)")


if __name__ == "__main__":
    main()
