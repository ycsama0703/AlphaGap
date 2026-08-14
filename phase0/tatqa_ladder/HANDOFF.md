# 交接 — TAT-QA 评分器权限阶梯实验

> 写给接手的 agent（建议用 Claude Code CLI 跑，因为需要外网 + 本地凭证）。
> **本文件只写「怎么跑」。先读研究说明再动手：**
>
> 1. **`briefs/2026-08-14-MECH-AI-1-scorer-permissions.md`** — 这是什么研究、假设是什么、
>    为什么这么设计、预注册判据、分阶段计划。**不读这份就不知道在干嘛。**
> 2. `knowledge/LIT_GATE_LOG.md` §4 方向 C + §C-6 — 撞车情况、可复用基线、已确立的事实
> 3. `knowledge/FAILURE_PREMORTEM.md` — 19 条前提体检，判 kill 前必查
>
> **最后更新**：2026-08-14
>
> **当前状态**：Phase 0.5 ✅；Phase 1A numeric pilot（200题）✅；exact 归因统一 ✅；双模型 blinded
> LLM audit ✅；三生成模型同题比较（DeepSeek / Claude / MiniMax）✅。Claude 与 MiniMax 的正式
> Batch 均为 200 free + 200 JSON、零 generation error/truncation，且 exact_official 与官方 scorer
> 800/800 逐题一致。第四个模型 Luna 已在 luyao4 生成，因 `kv.run:10020` 暂时离线尚未回收分析。
> 现阶段主结果是跨模型格式效应异质性与 scorer-policy inference flip；数值排名反转仅 0.5pp、`p=1`，
> 不能作为强 reversal 结论。详见研究说明 §12.7。

---

## 0. 一句话

测量 **benchmark 评分器的语义授权** 对报告成绩的贡献有多大——用 TAT-QA，因为它的官方评分器
提供了构造 P0–P3 权限阶梯所需的真实语义操作，而 27 个榜单条目没有一个审计过它。

**决定成败的那个问题**：生成式 LLM 的 SCA（语义强制归因）是否显著大于抽取式模型的 **−1.80pp**？
是 → 论文成立；否 → 这条线到此为止，不要恋战。

---

## 1. 已经确立的事实（不用重做）

### 1.1 官方评分器的语义授权（读过源码，已确认）

`tatqa_utils.py`：

| 级别 | 函数 | 行为 |
|---|---|---|
| P1 | `lower` / `white_space_fix` / `remove_articles` / `remove_punc` | 标准归一化 |
| P2 | `word_scale_handle` | `1 million` → ×1,000,000 |
| P2 | `scale_to_num` | scale 串 → 乘数（`percent → 0.01`） |
| P3 | `negative_num_handle` | **会计括号 `(134)` → `-134`** |
| P3 | `percent_num_handle` | `12%` → ×0.01 |
| P3 | `to_number` | 上述三者复合 |

`tatqa_metric.py` 的 `get_answer_str` 另有两条：
`round(ans_num, 2)`（两位四舍五入）+ **把 (值, scale) 相乘成单一规范数**。

死代码一处：`_align_bags` 里 `_match_numbers_if_present` 定义了但从不调用
（DROP 原版要求数字匹配才给 F1，TAT-QA 主动关掉）。

### 1.2 抽取式基线消融结果（legacy 复现，见 `RESULT_tagop_dev.txt`）

dev + 官方 `sample_prediction.json`（TagOp），**预测完全冻结，只改评分器**：

| 条件 | EM | ΔEM |
|---|---|---|
| 官方完整实现 | 45.92 | — |
| −scale 乘算 | **48.80** | **+2.88** |
| −两位四舍五入 | 44.78 | −1.14 |
| −负号插入 / −百分比 / −单位词 | 45.92 / 45.98 / 45.98 | ~0 |
| **P1 纯语法** | **47.72** | **+1.80** |
| P0 原始串比较 | 47.24 | +1.32 |

**结论与原假设方向相反**：语义授权在**扣分**，不是虚增。机制是 scale 乘算把「算对数」
和「判对量纲」耦合进单一 EM：107/1668 (6.4%) 预测 scale 错配，其中 **23 例值本身正确**，
全靠这次乘法被判错。

**权限对抽取式模型半休眠**——TagOp 1,668 条预测里触发数：百分号 42 / 单位词 33 / 会计括号 17。
这正是为什么要换生成式模型：LLM 写自由文本会大量触发。

> **解释边界**：上表可以原样复现，但旧 `tatqa_ladder.py` 的 P0/P1 仍先经过官方
> `get_answer_str/to_number`，所以“原始串/纯语法”标签是 provisional。新平台将这份结果保留为 legacy
> baseline，并用真正的 P0/P1 重新审计；不得把旧净 EM 差直接写成 scorer 制造的假阳性或假阴性。

---

## 2. 现在怎么跑（按顺序）

### Step 0 — Phase 0.5 无付费自检

```bash
cd ~/Desktop/alphagap
pytest -q tests/test_scorer_audit.py

# 分层抽样、prompt 和请求体检查；不读 key、不写 run 目录、不调用 API
python3 phase0/tatqa_run.py --n 200 --answer-types arithmetic count --dry-run
```

当前自检覆盖：真实 JSON schema 请求体、free/json 多答案支持、会计括号、scale、百分比、纯语法边界、
逐题转移恒等式和分层抽样确定性。

### Step 1 — Phase 1A：生成 100–200 题冻结输出

第一轮建议只跑 arithmetic/count，避免在尚未验证 free span parser 前混入 918 道 span/multi-span：

```bash
python3 phase0/tatqa_run.py \
  --n 200 \
  --answer-types arithmetic count \
  --run-id tatqa_pilot_numeric_v1
```

- 模型默认 `deepseek/deepseek-v4-flash-0731`（可用 `--model` 改）。
- key 从 `.env` 的 `OPENROUTER_API_KEY` 或环境变量读取。
- `free` 是无 response format 的自然语言生成；`json` 使用真正的 `response_format=json_schema`。
- 抽样按 `answer_type × gold scale 是否非空` 分层，seed 写入 manifest。
- 只有 `status=ok` 且 run fingerprint 一致的 uid 才算断点完成；API error 下次会重试。
- 不同模型、prompt、schema 或 sample 不能共用 run id，防止污染。
- 输出到 `phase0/tatqa_out/<run-id>/`：
  - `manifest.json`：模型、数据、prompt、schema、sample 的哈希；
  - `raw_{free,json}.jsonl`：冻结原文、usage、status、request hash；
  - `preds_free_free_regex.json` / `preds_free_free_surface.json`：两种离线 free 抽取；
  - `preds_json_schema.json`：schema field 抽取；
  - `extraction_*.jsonl`：逐题抽取状态。

本轮已完成；固定参数还包括 `--provider DeepInfra --max-tokens 2000 --reasoning-effort high`。
同一 run-id 重跑只补 transient error，不重复调用成功或 truncated 样本。

### Step 1.5 — 离线 extractor replay（已完成）

```bash
# 无模型调用：digit regex + number-word typed regex
python3 -m phase0.scorer_audit.cli extract-tatqa \
  --raw phase0/tatqa_out/tatqa_pilot_numeric_v1/raw_free.jsonl \
  --extractor free_typed \
  --predictions phase0/tatqa_out/tatqa_pilot_numeric_v1/preds_free_typed.json

# 付费但不重新生成答案：LLM 只抽取冻结 free response
python3 phase0/tatqa_extract_llm.py \
  --run-dir phase0/tatqa_out/tatqa_pilot_numeric_v1 \
  --gold phase0/tatqa_out/tatqa_dataset_dev.json \
  --provider DeepInfra \
  --max-tokens 2000 \
  --reasoning-effort low \
  --output-mode labeled \
  --tag llm_labeled_low2000
```

关键结果：free surface / regex / typed / labeled-LLM / schema-LLM 的官方 EM 分别为
`0.0 / 39.5 / 52.0 / 67.5 / 25.0`；直接 JSON generation 为 `76.5`。

### Step 1.6 — 三模型扩展与 luyao4 部署（已完成；Luna 待回收）

部署隔离目录：

```text
/home/ycliu0703/workspace/runs/alphagap-tatqa-audit
```

luyao4 主仓库有大量既有未提交改动，因此使用 detached git worktree，未在主工作树执行 `git pull`。
Batch runner 支持提交后临时 404、原子下载、journal 恢复和 `--attach-batch` 跨机器恢复。正式 run：

| 模型 | Run ID | 传输/provider | generation |
|---|---|---|---:|
| Claude Sonnet 5 | `tatqa_numeric_claude_sonnet5_batch_v1` | Batch / Anthropic | free 200/200 + JSON 200/200 |
| GPT-5.6 Luna Pro | `tatqa_numeric_gpt56_luna_pro_v1` | realtime / OpenAI | 远端输出待回收 |
| MiniMax M3 | `tatqa_numeric_minimax_m3_batch_v1` | Batch / Together | free 200/200 + JSON 200/200 |

Claude/MiniMax 的四个 batch 已直接向 OpenRouter 查询为 `completed`，合计 800/800 success。因 Batch 结果
不返回 `usage.cost`，按提交时冻结价和实际 token 重算，生成费用约 `$0.52856 + $0.06287 = $0.59143`。
统一 labeled extractor 仍用 `deepseek/deepseek-v4-flash-0731` / DeepInfra / low / 2000 tokens：Claude
200/200 ok，MiniMax 199/200 ok + 1 truncated，费用 `$0.00936 + $0.00885 = $0.01821`。

三模型报告：

```bash
python3 phase0/tatqa_multimodel_report.py \
  --model-run deepseek=phase0/tatqa_out/tatqa_pilot_numeric_v1 \
  --model-run claude=phase0/tatqa_out/tatqa_numeric_claude_sonnet5_batch_v1 \
  --model-run minimax=phase0/tatqa_out/tatqa_numeric_minimax_m3_batch_v1 \
  --output phase0/tatqa_out/tatqa_multimodel_3model_v1.json
```

关键 exact EM：DeepSeek free/JSON=`67.5/76.5`，Claude=`74.5/80.5`，MiniMax=`75.0/59.5`。
free 排名在 P1 与 Official 间发生 Claude/MiniMax 0.5pp 的严格数值反转，但两侧逐题 McNemar 均
`p=1`，只可称 descriptive reversal。更可靠的结果是格式效应跨模型变号，以及 DeepSeek/Claude 的
显著性判断随 scorer policy 改变。完整数值与解释见研究说明 §12.7。

**两个条件是有意设计的**，对应文献里一个未调和的矛盾：

| 条件 | 做法 | 对应 |
|---|---|---|
| `free` | 自由文本作答，冻结后分别用 typed regex / surface-preserving extractor replay | Let Me Speak Freely (2408.02442)：格式约束**损害**推理 |
| `json` | 强制 JSON schema 直出 `{answer, scale}` | JSONSchemaBench (2501.10868)：约束解码**提升** ≤4%，含 GSM8K |

同模型、同题、temperature=0。

### Step 2 — 精确复现官方 scorer

```bash
cd /tmp && git clone https://github.com/NExTplusplus/tat-qa.git
cd ~/Desktop/alphagap
python3 -m phase0.scorer_audit.cli reproduce-tatqa \
  --gold /tmp/tat-qa/dataset_raw/tatqa_dataset_dev.json \
  --predictions /tmp/tat-qa/sample_prediction.json \
  --tatqa-repo /tmp/tat-qa \
  --out-dir phase0/tatqa_out/tagop_official_reproduction
```

预期严格复现 `EM 45.92 / F1 58.88 / Scale 90.95`，同时写出官方逐题 details。官方复现和自研权限
引擎分开，不能用 `p4_round2` 冒充官方 scorer。

### Step 3 — Exact 离线权限 replay（主结果）

同一 TAT-QA matcher 内只切换权限开关；以 free labeled-LLM 条件为例：

```bash
python3 -m phase0.scorer_audit.cli audit-tatqa-exact \
  --gold phase0/tatqa_out/tatqa_dataset_dev.json \
  --predictions phase0/tatqa_out/tatqa_pilot_numeric_v1/preds_free_llm_labeled_low2000.json \
  --selection phase0/tatqa_out/tatqa_pilot_numeric_v1/selection.json \
  --tatqa-repo /private/tmp/tat-qa-inspect \
  --out-dir phase0/tatqa_out/tatqa_pilot_numeric_v1/exact_free_llm_labeled_low2000
```

`--tatqa-repo` 会同时调用未修改官方 scorer；只要 `exact_official` 与官方逐题 EM/F1 有一个 mismatch，命令即
失败。完整 TagOp dev 已验证 1,668/1,668 逐题一致，并复现 `45.92 / 58.88`。

Exact policies 累积开启：`exact_p1_syntax → exact_p2_scale → exact_p3_numeric → exact_p4_round2 →
exact_official`。每个目录包含：

- `exact_summary.json`：每级 EM/F1、effective operation、转移矩阵与官方逐题验证；
- `exact_items.jsonl`：每题×每政策的规范值、trace 和判定；
- `exact_decision_changes.jsonl`：只保留 `0→1 / 1→0`，供人工盲审。

旧 `audit-tatqa --mode fixed_gold/symmetric` 仍可用于诊断和历史复现，但不再用于主归因。

旧 `tatqa_ladder/tatqa_ladder.py` 只用于复现 legacy TagOp 表，不再作为新实验主入口。

### Step 4 — 生成并执行逐题盲审

```bash
python3 -m phase0.scorer_audit.cli make-tatqa-blind-audit \
  --run-dir phase0/tatqa_out/tatqa_pilot_numeric_v1 \
  --gold phase0/tatqa_out/tatqa_dataset_dev.json \
  --out-dir phase0/tatqa_out/tatqa_pilot_numeric_v1/blind_audit_v1 \
  --seed 20260814 \
  --controls-per-cell 20
```

当前包包含：34 条 P1↔Official 直接变判、80 条稳定对照（每个隐藏条件各 20 stable-correct + 20
stable-wrong）和 36 条相邻权限机制变判。目录严格分开：

- `reviewer/pass1_intent.jsonl` + `pass1_labels.csv`：不显示 gold、条件或判分，先冻结模型意图；
- `reviewer/pass2_adjudication.jsonl` + `pass2_labels.csv`：显示 gold 和逐题随机化 Candidate A/B；
- `reviewer/mechanism_edges.jsonl` + `mechanism_labels.csv`：审 35 个 `0→1` 和 1 个 `1→0` 相邻边；
- `reviewer/CODEBOOK.md`：标签定义和顺序；
- `private/`：UID、条件、政策和自动判定映射。**人工标签冻结前不要打开，也不要发给 reviewer。**

公开 reviewer 包已自动检查 UUID、条件/政策字符串和私有字段泄漏；当前 `violations=0`。自然语言与 JSON
表面形式本身仍可能提示条件，因此这是 condition-blind protocol，不宣称视觉上完全不可识别。

#### Step 4.1 — 双模型 blinded LLM audit（已完成）

两个 judge 均只读取 `reviewer/`，在输出冻结后才由独立脚本读取 `private/` 解盲：

```bash
python3 phase0/tatqa_blind_judge.py \
  --reviewer-dir phase0/tatqa_out/tatqa_pilot_numeric_v1/blind_audit_v1/reviewer \
  --output-dir phase0/tatqa_out/tatqa_pilot_numeric_v1/blind_audit_v1/judges/gpt56_terra_pro_v1 \
  --model openai/gpt-5.6-terra-pro --provider OpenAI \
  --reasoning-effort medium --max-tokens 2000

python3 phase0/tatqa_blind_judge.py \
  --reviewer-dir phase0/tatqa_out/tatqa_pilot_numeric_v1/blind_audit_v1/reviewer \
  --output-dir phase0/tatqa_out/tatqa_pilot_numeric_v1/blind_audit_v1/judges/gemini37_flash_v1 \
  --model google/gemini-3.7-flash --provider Google \
  --reasoning-effort medium --max-tokens 2000
```

两边均为 264/264 schema-valid、零截断、provider 无漂移；记录费用 `$2.3537 + $0.3142 = $2.6678`。
一致性和解盲：

```bash
python3 phase0/tatqa_judge_agreement.py \
  --reviewer-dir phase0/tatqa_out/tatqa_pilot_numeric_v1/blind_audit_v1/reviewer \
  --judge-a-dir phase0/tatqa_out/tatqa_pilot_numeric_v1/blind_audit_v1/judges/gpt56_terra_pro_v1 \
  --judge-b-dir phase0/tatqa_out/tatqa_pilot_numeric_v1/blind_audit_v1/judges/gemini37_flash_v1 \
  --out-dir phase0/tatqa_out/tatqa_pilot_numeric_v1/blind_audit_v1/judges/agreement_v1

python3 phase0/tatqa_judge_unblind.py \
  --reviewer-dir phase0/tatqa_out/tatqa_pilot_numeric_v1/blind_audit_v1/reviewer \
  --private-dir phase0/tatqa_out/tatqa_pilot_numeric_v1/blind_audit_v1/private \
  --judge-a-dir phase0/tatqa_out/tatqa_pilot_numeric_v1/blind_audit_v1/judges/gpt56_terra_pro_v1 \
  --judge-b-dir phase0/tatqa_out/tatqa_pilot_numeric_v1/blind_audit_v1/judges/gemini37_flash_v1 \
  --out-dir phase0/tatqa_out/tatqa_pilot_numeric_v1/blind_audit_v1/judges/unblinded_v1
```

核心结果：34/34 直接变判题上，两 judge 一致认为 extraction exact 且 P1/Official 两候选都语义正确；
36 条 mechanism edge 上，34 条一致认为 decision change 不应发生、2 条分歧且来自同一数值案例。
`core_adjudication_queue.jsonl` 另含一个 “fewer rights” stable-control 分歧，因此核心待裁决共 3 条/2 UID。
这仍是 **LLM-as-a-judge audit**，不能写成人工盲审；无人工校验时须作为 limitation。

### Step 5 — 三个必答的分析

1. **权限触发率**：同时报告 raw substring、effective operation 和 decision-changing trigger；只有后两者
   能进入机制解释。
2. **free vs json 的 EM 差**，以及**这个差里有多少是评分器造成的**（两个条件各跑完整阶梯，
   比较各自的 P1→官方 落差）。这是调和那个矛盾的直接证据。
3. **完整阶梯下 SCA**：生成式的 P1→官方 落差 vs 抽取式的 −1.80pp。**这条是成败判据。**

---

## 3. 已知坑

**free extractor 自由度**：新平台同时输出 `free_regex`（把单位移入 typed scale，但保留括号/%）和
`free_surface`（保留最终答案表面、scale 留空）。两者都从同一份 raw output 离线重放，不重复调用模型。

**scale 乘算的方向容易搞反**：关掉它 EM 会**上升**，因为不再强制 scale 正确。
写作时说清楚这是「解耦」不是「放宽容差」。

**`eps_surprise_pct` 式的空字段**：检查 gold 里 `scale=""` 的占比（train 6457/13215 ≈ 49%）。
scale 相关的结论要按 `scale != ""` 的子集单独报一遍。

---

## 4. 什么情况下该停

对照 `knowledge/FAILURE_PREMORTEM.md`：

- **#16 天花板**：human 84.1 EM，SOTA TAT-LLM-70B 81.4 —— 未到顶，暂时安全。但如果
  DeepSeek V4 在 dev 上直接打到 85+，说明这个 benchmark 对现代模型已饱和，效应会被压扁。
- **#7 承重区分点**：本线的承重主张是「没人审计过评分器的语义授权」。
  写作前必须补做 `evaluation contamination` / `semantic-equivalence canonicalization` /
  `structured-output scoring` 三条线的系统检索（见 `LIT_GATE_LOG.md` §7 待查）。
- **#12 VERIFY THE KILL**：如果生成式 SCA 也接近 0，别急着宣布死亡——先检查是不是
  typed/surface 两种 extractor 的 effective trigger 都接近 0；不能只凭其中一个 extractor 宣布死亡。

---

## 5. 文件地图

```
phase0/
  tatqa_run.py                  # 生成层：真 JSON schema、分层抽样、manifest、可靠续跑
  scorer_audit/
    types.py                    # 统一 gold/prediction/trace 数据对象
    extractors.py               # schema / free_regex / free_surface
    policies.py                 # 旧的通用 P0/P1 + P2/P3 + round2 诊断策略
    engine.py                   # 旧 fixed-gold/symmetric replay、逐题转移
    exact_tatqa.py              # 单路径 exact TAT-QA 权限 scorer（主归因）
    blind_audit.py              # 去标识、随机化、双阶段盲审包生成与泄漏检查
    judge_agreement.py          # 双 judge agreement / Cohen's kappa / 分歧包
    judge_unblind.py            # 标签冻结后的 condition/policy 解盲报告
    cli.py                      # extract/audit/official reproduce 命令
    adapters/tatqa.py           # TAT-QA gold/pred/raw adapter
  preflight_findata.py          # findata 凭证/连通性预检（另一条线，暂搁置）
  tatqa_out/<run-id>/           # 冻结生成、抽取结果、audit 报告
  tatqa_ladder/
    HANDOFF.md                  # 本文件
    tatqa_ladder.py             # Step 3 消融脚本
    RESULT_tagop_dev.txt        # 抽取式基线完整结果
    phase0_sca.py               # 早期分析：evidence_sufficiency 容差扫描
    phase0_sca2.py              # 早期分析：P1/P2 归因（发现符号插入现象）
tests/
  test_scorer_audit.py          # Phase 0.5 权限边界与请求体测试
knowledge/
  LIT_GATE_LOG.md               # §4 方向C + §C-6：完整背景、撞车情况、可复用基线
  FAILURE_PREMORTEM.md          # 19 条前提体检
  PUBLISHABLE_SHAPES.md         # 什么形状的论文能中
```

---

## 6. 环境说明

这条线**必须在本地跑**（Claude Code CLI 或直接终端），不要在 Cowork 沙箱里跑：
沙箱的代理白名单不放行 LLM API（openrouter / deepseek 均 403），
且看不到 `~/.lumid`、`~/.xp` 等挂载目录之外的路径。

沙箱能做的是：读本地数据、跑分析脚本、拉 github/pypi、web 检索。
Step 2/3/4 的纯分析部分沙箱可以做，**只有 Step 1 必须本地**。
