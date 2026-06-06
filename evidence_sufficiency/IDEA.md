# Evidence Sufficiency for Finance Agents — 研究纲领 (IDEA)

> ## 🛑 STOPPED (2026-06-06) — 不继续
> **死因(机制级)**:gap 的核心 ground truth 是"证据充分性"这个**主观判断**标签。主观标签构念效度不稳——
> 60 题易样本上跨模型 κ=0.74–0.96(虚高),但**规模化(467 难案例)后,即便最一致的好裁判(Qwen/o3/Gemini)
> Fleiss 也只 ~0.35–0.47**。benchmark 标签 ≈0.4 立不住;唯一活下来的是"LLM-judge 不可靠/双峰"这种**负面框架**,
> 而负面/方法学结果在"需创新+正向"的 AI×fin venue **发不了**。
> P1 结论:(b) benchmark 能区分 agent(57pp)✅,但 (a) 规模化可靠标注 ❌。
> 反思见 `~/.xp/findings/reflections.jsonl`(gap_id=`agent-evidence-sufficiency-benchmark`);
> 新规则【标签客观性】已蒸馏进 `knowledge/FAILURE_PREMORTEM.md` #5 + prompts 05/07。
> **保留**:`phase0/` + `evidence_sufficiency/` 代码作资产(下次做"客观标签的 agent 评测"可直接复用)。
> 现象本身(agent 答对但无据)是真的,只是**无法被可靠标注成 benchmark**。
>
> --- 以下为原纲领,存档 ---

> **一句话主线**:金融 agent "答案对" ≠ "证据足";我们**定义并测量**这条被忽视的轴,发现
> **前沿 LLM 对它的判断是双峰分裂的**,并提出一个**带明确标准的审计机制**把"高置信无据"压下去。
>
> **定位**:AI 是主角(benchmark + 可靠性机制 + 实证发现),金融是高风险场景。
> 目标 venue:NeurIPS D&B / ICLR / ACL。**不碰收益预测**。
>
> 锚定论文:ForeSci (arXiv 2606.00644) —— 证据-决策脱耦 + 时间切片。
> 状态:Phase-0 已通过(~$0.15),进入"扩大试验"阶段。最后更新见 git。

---

## ① 现状问题 (status quo)
- 金融 agent(调 filings/transcripts/财报数据的 LLM agent)目前**只按最终答案正确率评测**
  (FinToolBench / ToolBench / GAIA)。
- 但金融是高风险、强合规场景:**"答对" ≠ "结论有充分证据支撑"**。agent 可能蒙对、靠参数记忆、
  或把"前瞻机会 / 套话"当成原因——**答案对、证据却不足**。
- **空白**:
  1. 没有评测衡量 **claim 级证据充分性**;
  2. 连"怎么算证据够"都**没有公认、可操作的定义**——而**裸用 LLM 当裁判判这个并不可靠**(见 ②F2)。

## ② 发现关键点 (Phase-0 已实证)
- **F1 — 现象真实且大**:即便 agent 数值答对,**30–42% 的定性"原因/驱动"主张证据不足**
  (无证据 / 引文截断 / 拿空泛表态当驱动)。
- **F2 — 判断双峰分裂(核心发现)**:10 个前沿模型判"够不够",分成
  **宽松营(Gemini/Claude/GPT/Qwen/o3,Fleiss κ=0.74)** 与 **严格营(DeepSeek-pro/Grok/Mistral/Llama/R1,κ=0.60)**,
  两营之间只有 **0.51**;且**推理档、厂商都解释不了**(o3 推理却宽松,R1 推理却最严)。
  → **裸用 LLM-judge 不可靠**。
- **F3 — 可操作化**:一旦把"严格度"用规则钉死,一致性回到 **0.74–0.96** → 这条轴**定标准后可可靠标注**。

## ③ 机制创新 (三块贡献)
- **M1 Benchmark**:时间切片、可核验的**金融 agent 证据充分性基准**——不只测答案对错,测
  **每个 claim 有没有最小充分证据集**,带失效分类;数值真值自动判 + 定性 claim 充分性标注。
- **M2 操作化定义 + 双峰性实证**:给"证据充分性"一个**明确操作化定义**(钉死严格度)+
  **跨模型双峰性**的系统刻画(解释 naive LLM-judge 为何失败)。把 F2/F3 升华成方法贡献。
- **M3 CESA 审计器**:一个**独立**的"claim → 证据充分性"审计器——拆解 claim、判每条是否有充分证据、
  不足则**拒答 / 降级 / 标不确定**,在固定标准下运行。

## ④ 解决问题 (payoff)
- 给金融 agent 领域**第一个可靠测"证据充分性"的工具 + 标准**;
- 量化出**当前 agent 普遍存在"答对但无据"的大缺口**;
- **CESA 在几乎不掉正确率的前提下显著降低"高置信无据"输出** → agent 更可信(高风险场景刚需);
- 全程**正向结果可达 + 自动可判 + 防泄漏**(forward-only / 时间切片),符合可发表条件。

---

## 贡献清单
1. 一个面向**证据充分性**的金融 agent benchmark(新评测轴);
2. **跨前沿模型双峰性**的实证发现 + 一个**可操作的充分性定义**;
3. **CESA** 审计机制 + 它能在不掉正确率下压低无据输出的证据。

## 和 prior work 的区别
- vs FinToolBench / ToolBench / GAIA:它们测**能力 / 最终正确率**,我们测 **claim 级证据充分性**;
- vs ForeSci(锚点):它揭示"证据-决策脱耦",我们**做成可测基准 + 干预机制 + 跨模型双峰刻画**;
- vs Reflexion / SelfCheckGPT / citation 验证:它们查一致性 / 引用存在,我们查**充分性**(够不够,而非有没有 / 对不对)。

---

## 状态条 (诚实区分)
- ✅ **已实证(Phase-0,~$0.15)**:F1 现象、F2 双峰、F3 可操作化;findata 可支撑;harness 跑通。
- 🔜 **待做(扩大试验)**:M1 benchmark 上规模(~300–500 题、多 agent)、人工 gold 校验 LLM 共识、
  **M3 CESA 的真实效果**(目前是假设,数字未验)。

> 一句话现状:**"值不值得做"已验证(值,且白捡一个双峰发现);现在缺的是把 benchmark 做大 + 把 CESA 真做出来证明有效。**

---

## 扩大试验计划 (合成 MECH-1+2 pilot)

**关键设计 —— 用双峰发现来定标注策略(成败点)**:
1. 写死操作化 rubric(Phase-0 v2 的 A/B 规则 + soft-causal 边界),**明确选"宽松营标准"为 ground truth**;
2. 标签 = N 模型在该 rubric 下的共识 + **人工 gold 子集校验**;
3. **双峰性本身作为测量结果报告**。

**规模**:任务 41 → 300–500(100+ 公司、4 年、多类 claim);受测 agent 1 → 3–4 种;裁判固定 panel + ~200 claim 人工 gold;新增 CESA。

**分阶段 + go/no-go**:
- **P1 扩 benchmark**(~1 周):300 题×3 agent + panel 在 rubric 下打标。GO:营内 κ≥0.7 且 agent 间失败率可区分。
- **P2 人工校验**(~2–3 天):~200 claim gold,验 LLM 共识 vs 人 κ。GO:κ≥0.7。
- **P3 CESA**(~1 周):建审计器 + 评测。GO:高置信无据 ↓≥30%、任务正确率掉 ≤5%。
- **P4 写作**。

**成本**:agent 跑 ~$50(便宜模型)–$500(前沿);panel 打标 ~$5–15;真成本是人工 gold ~200 条(1–2 天)。合计 ~$100–600 API + 1–2 天人力。

**建议起点**:先做 P1 最小版(扩到 ~150 题 + 加 1 个 agent 配置 + 固定 rubric 重跑 panel),确认两个前提成立再投人工 gold 和 CESA。

---

## 资产指针 (artifacts)
- **Phase-0 harness**(扩大试验的种子):`../phase0/`
  - `build_tasks.py` 造题(findata,数值真值自动判) · `agent.py` PIT ReAct agent ·
    `run_judge_api.py` 任意模型当盲判 · `make_judge_sheet.py` 判题表 · `ingest_labels.py` 录标签 ·
    `stats.py` 2×2 / Cohen / Fleiss / 留一 / 判词
  - 运行产物 `phase0/out/`(gitignore):`annotation.csv`(60 定性 claim × 10 裁判)、`judges.json`、各 `*_labels.txt`
- **数据**:findata(老师 Lumid API),客户端 `~/.xp/skills/a3f48236-.../lumid-findata/skills/client.py`,US 股,LUMID_PAT 鉴权
- **Phase-0 关键数字**:G1 = 42% 答对但证据不足;宽松营 κ=0.74 / 严格营 κ=0.60 / 全 10 家 0.51
- **记忆**:`project_evidence_sufficiency_research_line`(背景全程)
