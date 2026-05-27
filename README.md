# AlphaGap

> AI × Fin gap detection · 每日扫描两侧前沿，自动产出可执行的研究 gap

---

## What this is

AlphaGap 每天读取新的高相关论文，把新的 AI 机制翻译为金融中可验证的失败模式，并通过邮件推送最多两个可立即开展的实验方案。理论型跨界想法留在 inbox 人工讨论，不让知识维护工作挤占实验推进。

**项目本质不是论文管理工具，而是研究判断沉淀系统**——核心资产是 `mappings/` + `briefs/` 两份持续生长的 markdown 知识库，DB 和论文都是可再生的派生数据。

---

## Current state (as of 2026-05-22)

### Deployed
- **服务器**：`luyao4` (`/home/ycliu0703/workspace/projects/alphagap`)
- **GitHub**: <https://github.com/ycsama0703/AlphaGap>
- **Cron**: 每天 WIB 07:00 (= 北京 08:00) 自动触发 `python -m pipeline.main daily --no-commit`
- **日志**: `logs/daily.log`

### DB 状态
- ~2700 papers backfilled (HF Daily 90 天)
- L1 extraction: **正在 reextract 加 mechanism_description 字段**（本地，~2530 篇，~30 分钟）
- ~2150 papers have S2 citation snapshots

### 信号源
- ✅ **HF Daily Papers** (AI 主源，工作正常)
- ❌ **arXiv API**（持续 429 rate-limited，目前未投产）
- ⏳ **SSRN** / **S2 search**（未实现）

### 进行中（2026-05-22）：Mechanism-Level 升级 Phase

这是 gap detection 核心质量改造，从 "tag 级 shallow pattern matching" → "mechanism family 动态聚类"。

**已完成的 4 步**：
- ✅ **Step A**: L1 抽取深化 — 加 `mechanism_description.{one_liner, what_problem, contrast, prerequisites}` 4 子字段。LLM 现在用功能描述（"用未来 KL 散度作为 per-token advantage 信号"），不只品牌名（"FIPO"）。
- ✅ **Step C**: Prompt 03 重写为 mechanism-level 动态聚类 — 不再聚合 tag 字符串，LLM 从 100 篇 paper 的 mechanism_description 里动态聚成 5-10 个 mechanism families，每个 family 带 representative_one_liner / what_problem / shared_approach / contrast_to_prior / member_papers / citation_velocity。
- ✅ **Step D**: 品牌名禁令 — prompts 04/05 hypothesis 必须功能层描述；self-check 06 加 check M 拦截品牌嫁接（`hypothesis` 不允许出现 FIPO / CEPO / Reflexion 这种 paper 自创名）。

**进行中**：
- 🚧 **Step B**: Backfill 2530 篇用新 L1 重抽。运行中，~30 min，~$1.5 一次性成本。

**待做**：
- ⏳ **Step E**: 端到端测试 + 发邮件验收新 mechanism trends + gap 输出
- ⏳ **Step F (可选)**: `uptake.py` 升级到 mechanism 级（用 mechanism description 而非 keyword 匹配 Fin 论文）
- ⏳ 服务器 git pull + 同步本地 backfill 的 mechanism 抽取结果（或服务器自己重抽）

### 已知问题（持续）
1. **arXiv 429** —— 致命：Fin 侧 q-fin 论文几乎抓不到，Fin trends 持续单薄。fix：换 OAI-PMH 接口 + 加 polite User-Agent
2. **Server git push 未配置** —— 用 `--no-commit` 绕过，inbox.md 只在服务器本地
3. **Mappings 表为空** —— 还没有 human-approved 的 mappings 沉淀
4. **Weekly report 未实现** —— `pipeline/main.py` 里 `run_weekly` 是 stub
5. **Logs 无 rotation** —— 跑半年后需要手动 truncate

### 如何从这里捡起

当 backfill 跑完（看 `db stats` 里 `l1_done` ≈ 2530）：

```bash
cd ~/Desktop/alphagap

# 1. 验证 mechanism 字段抽出来了
.venv/bin/python -c "
import sqlite3, json
conn = sqlite3.connect('db/alphagap.sqlite')
row = conn.execute('SELECT mechanism_description_json FROM paper_extractions WHERE mechanism_description_json IS NOT NULL LIMIT 1').fetchone()
print(json.dumps(json.loads(row[0]), indent=2, ensure_ascii=False))
"

# 2. 跑一次 daily pipeline 看新 trends + gap 输出
.venv/bin/python -m pipeline.main daily --no-commit 2>&1 | tail -15

# 3. 检查邮件 / inbox / brief，重点看：
#    - Mechanism Trends 是否真的是 35-80 字的功能描述（而非 "agent" 这种 tag）
#    - Gap hypothesis 是否不再出现 paper 品牌名
#    - structural_mapping 字段是否正确填充

# 4. 服务器同步（确认本地效果好之后）
ssh luyao4
cd ~/workspace/projects/alphagap && git pull
# 服务器 DB 需要单独 reextract（数据不互通）：
.venv/bin/python -c "
import sqlite3; conn = sqlite3.connect('db/alphagap.sqlite')
conn.execute('DELETE FROM paper_extractions'); conn.commit()
print('cleared')
"
.venv/bin/python -u -m pipeline.ingest --no-arxiv --no-hf --max-l1 5000 --max-l2 0 2>&1 | tail -5
```

下次 cron（明早 7:00 WIB）就会用新 mechanism-level 逻辑出邮件。

---

## Quick navigation

| 想找什么 | 看哪 |
|---|---|
| 项目原理与设计动机 | 本 README 下面几节 |
| Prompt 内容 | `prompts/01..09_*.md` |
| 每日 pipeline 流程 | `pipeline/main.py` `run_daily()` |
| DB 表结构 | `pipeline/db.py` SCHEMA 常量 |
| 白名单 / 关键词 | `whitelist.yaml` |
| 部署配置 | `deploy/cron.example` + 本 README "Deployment" 节 |
| 历史决策（为什么这么设计） | 见下方 "Design decisions" 节 |

---

## Architecture

### 单日流程（pipeline/main.py: run_daily）

```
Step 1   Ingest                  fetchers/* → filter → SQLite
            ↓                    (今日 HF Daily 新论文 + L1 extract)
Step 2   Gap pipeline            analyze/gaps.py:run_gap_pipeline
            ↓
         ├─ Candidate pool       Prompt 04A (6-8 → refine top 4)
         ├─ Risk audit (可选)    Prompt 04B (ADVERSARIAL_GAP_REVIEW=true)
         ├─ Theoretical gaps     Prompt 04 (screening/discussion only)
         ├─ Engineering gaps     Prompt 05 (最多 2 个 go/no-go 实验)
         ├─ Self-check           Prompt 06 (结构 + 实证风险 checklist)
         └─ Scoring              Prompt 07 (novelty + actionability)
            ↓
Step 2.5 Enrich gaps             从 DB 查 anchor papers 完整信息
            ↓
Step 3   Deep briefs             Prompt 09 (仅对 email-ready engineering gap)
            ↓                    → briefs/YYYY-MM-DD-GAPID.md
Step 4   Inbox markdown          inbox/YYYY-MM-DD.md (讨论/审计用)
            ↓
Step 5   Email                   Resend HTML → runnable experiments only
```

模型路由：论文 L1/L2 批量抽取以及独立运行的 mapping maintenance 使用
`DEEPSEEK_MODEL_DEFAULT`；Candidate pool、Risk audit、Theoretical/Engineering
gaps、Self-check 与 Scoring 使用 `DEEPSEEK_MODEL_REASONING`；只有筛选通过的
工程实验在生成 Deep brief 时使用 `DEEPSEEK_MODEL_BRIEF`。默认 DeepSeek 配置
下，daily 主链均为 `deepseek-v4-flash`，`deepseek-v4-pro` 仅承担少量 deep
brief 深写任务。

Daily 主流程不再执行 Semantic Scholar 全库 citation snapshot、Prompt 03
趋势聚类或 mapping 更新建议。这些均不是产出实验的前置条件；需要维护时可
单独运行相应命令。

Gap generation 有两个研究通道：`grounded_transfer` 使用人工维护的 active
transfer cell，可升级为工程实验与 deep brief；`frontier_extension` 使用
`knowledge/ai_innovation_playbook.md` 识别现有 taxonomy 未覆盖的新金融
control point，仅作为理论型人工讨论项展示，批准为新 cell 前不会自动工程化。

### 文件树（重要的）

```
alphagap/
├── prompts/                       LLM 角色定义，每个文件一个独立任务
│   ├── 01_concept_extract_l1.md   必抽：method_primary / domain / tags / side
│   ├── 02_concept_extract_l2.md   高优先级加抽：building_blocks / claims / benchmarks
│   ├── 03_trend_summary.md        rising/falling/new/stable_hot 分类
│   ├── 04A_gap_enumerate.md       mechanism-level 候选池
│   ├── 04B_gap_risk_audit.md      可选对抗审计 gate
│   ├── 04_gap_theoretical.md      conceptual hypothesis（无实验路线）
│   ├── 05_gap_engineering.md      含完整实验路线（data/method/metrics/baselines/...）
│   ├── 06_gap_self_check.md       11 项 checklist → accept/reject/downgrade/retry
│   ├── 07_gap_scoring.md          novelty + actionability 各 1-10
│   ├── 08_mapping_update.md       status_change / add_mapping / add_evidence 提议
│   └── 09_gap_deep_brief.md       8 章节 markdown brief（自包含，可直接交给 agent）
│
├── pipeline/                      代码
│   ├── config.py                  load_settings / load_whitelist / load_prompt
│   ├── db.py                      SQLite schema + upserts + queries
│   ├── llm_client.py              DeepSeek 客户端（OpenAI 兼容接口）+ token 计费
│   ├── filter.py                  候选信号 (HF / q-fin / 作者 / 机构 / 关键词)
│   ├── ingest.py                  端到端 ingest: fetch → filter → persist → L1/L2
│   ├── main.py                    每日 cron 入口
│   │
│   ├── fetchers/
│   │   ├── arxiv.py               arXiv Atom API（含 retry，但 429 限制严）
│   │   ├── hf_daily.py            HuggingFace Daily Papers API
│   │   ├── semantic_scholar.py    S2 batch citation lookup
│   │   └── ssrn.py                STUB（未实现）
│   │
│   ├── extract/
│   │   └── concepts.py            Prompt 01/02 + prompt md 解析器 + render_template
│   │
│   ├── analyze/
│   │   ├── citations.py           可选 S2 snapshot + concept-level velocity 维护
│   │   ├── context.py             从 DB 取 top papers / mappings 给 prompts
│   │   ├── trends.py              Prompt 03 + 概念频率聚合（AI 90d / Fin 180d）
│   │   ├── gaps.py                Prompt 04/05 + orchestrator (run_gap_pipeline)
│   │   ├── risk_audit.py          Prompt 04B 对抗审计（可选）
│   │   ├── self_check.py          Prompt 06 + downgrade helper
│   │   ├── scoring.py             Prompt 07 + EMAIL_THRESHOLD=8
│   │   ├── enrich.py              用 DB 给 gap 的 anchor papers 加 title/url/affil
│   │   ├── brief.py               Prompt 09 + 写 briefs/YYYY-MM-DD-GAPID.md
│   │   └── mapping_update.py      Prompt 08 + 动作合法性校验
│   │
│   └── output/
│       ├── inbox.py               写 inbox/YYYY-MM-DD.md (审批用，全量 audit)
│       ├── email.py               Resend HTML 邮件
│       └── report.py              STUB（weekly 未实现）
│
├── whitelist.yaml                 机构/作者/关键词白名单 + 阈值
├── db/alphagap.sqlite             SQLite（gitignored）
├── mappings/                      AI↔Fin 知识映射（核心资产，手动审批）
├── briefs/                        每个高分 gap 的 deep brief md
├── inbox/                         每日 audit + 待审批 actions
├── logs/                          运行日志
└── deploy/cron.example            crontab 模板
```

---

## Design decisions（为什么这么设计）

### 1. 两类 gap 严格区分
- **理论型 (theoretical)**: 偏 conceptual hypothesis，用于人工讨论或升级筛选，不进入每日邮件。
- **工程型 (engineering)**: 必须自带完整实验路线（first experiment + data + metrics + baselines + ablations）。LLM 想不清楚就降级为理论型。

理由：纯理论 gap 每天能生成无限条没有用，工程型才是真正交给人/AI 执行的研究 task spec。

### 2. 邮件不是 digest，是分流入口
- 邮件只放 score ≥ 8 的工程型 go/no-go 实验，最多两个
- inbox.md 全量 audit（审批层）
- briefs/*.md 每个高分 gap 独立深度文档（onboarding 层）

理由：邮件每天 1 封，太密集人会麻木。分层让"扫描-决策-深入"三个动作分开。

### 3. 非对称观察窗口
- AI 侧 90 天（覆盖一个会议周期）
- Fin 侧 180 天（金融发表节奏慢）

理由：14 天对 AI 都嫌窄，对 Fin 是噪声。两侧 publication cadence 本质不同，必须不对称。

### 4. 边界维护不阻塞实验
- citation snapshot、趋势聚类和 mapping 扩展不是 daily 邮件前置步骤
- 需要复盘领域边界时再独立运行维护任务
- daily 预算优先给新机制翻译、实验设计和 go/no-go 判断

### 5. Mappings 表必须人审
- LLM 提议永远进 `inbox/` 等审批
- 人确认后才动 `mappings/`
- 即使 audit 通过，每条动作也走 git commit 留痕

理由：mappings 是项目唯一不可再生的资产，污染了就完了。

### 6. 资产层级
- **L1**（不可再生）：`mappings/` + `briefs/` markdown + git 历史
- **L2**（派生）：`db/*.sqlite` concepts / reports
- **L3**（缓存）：`db/*.sqlite` papers（丢了重抓）
- **L4**（不存）：PDF / 网页原文

理由：备份和保护策略按层级走，避免误删核心资产。

### 7. DeepSeek 主导 + S2 / HF API 辅助
- DeepSeek-chat (V3.5) 做所有 LLM 推理 (~$0.05/天)
- DeepSeek-reasoner (R1) 是预留，目前未实际触发
- 不引入 embedding（语义相似度 DeepSeek 直接判断已够用）

理由：成本可控，质量稳定。哪天质量不够再混 Claude。

---

## Daily user workflow

### 你需要做的（每天）
1. **8:00 北京时间**收邮件 (`yuncongliu0703@gmail.com`)
2. 邮件里看 score ≥ 8 的 gap，决定值不值得 dive in
3. 想深入：邮件附件直接打开 engineering deep brief；服务器本地也保留在 `briefs/YYYY-MM-DD-GAPID.md`
4. 想完整 audit：`ssh luyao4 cat ~/workspace/projects/alphagap/inbox/YYYY-MM-DD.md`

### Mapping 审批流（手动，目前还没用过）
1. inbox.md 里看 LLM 提议的 `add_mapping` / `status_change` 动作
2. 同意的：手动建/改 `mappings/<id>-<slug>.md` 文件，frontmatter 包含 id / ai_concept / fin_concept / status
3. `git add . && git commit -m "review YYYY-MM-DD" && git push`
4. 服务器下次跑会用最新 mappings 作为 context

### 想现在就触发一次
```bash
ssh luyao4
cd ~/workspace/projects/alphagap
.venv/bin/python -m pipeline.main daily --no-commit
```

---

## Configuration

### `whitelist.yaml`
- **institutions**: ai_industry / ai_academia / fin_industry / fin_academia
- **named_authors_fin**: Fin big-names 个人白名单（不依赖机构匹配）
- **keywords**: ai_side / fin_side 分组，多组 keyword
- **thresholds**: h_index_ai / h_index_fin / llm_relevance（h_index 实际未使用，待 S2 author enrichment）

### `.env`（不进 git，每台机器独立）
```
LLM_PROVIDER=deepseek                         # deepseek | mimo | openrouter | custom
DEEPSEEK_API_KEY=sk-...
DEEPSEEK_MODEL_DEFAULT=deepseek-v4-flash  # 批量抽取与机械更新步骤
DEEPSEEK_MODEL_REASONING=deepseek-v4-flash # daily gap 判断链路
DEEPSEEK_MODEL_BRIEF=deepseek-v4-pro       # 仅筛选通过后的 deep brief
OPENROUTER_API_KEY=                         # 仅 LLM_PROVIDER=openrouter 时读取
OPENROUTER_MODEL_DEFAULT=                   # 例如供应商给出的 model slug
OPENROUTER_MODEL_REASONING=
OPENROUTER_MODEL_BRIEF=
MIMO_API_KEY=                               # 仅 LLM_PROVIDER=mimo 时读取
MIMO_BASE_URL=                              # MiMo dedicated base URL
MIMO_MODEL_DEFAULT=mimo-v2.5-pro
MIMO_MODEL_REASONING=mimo-v2.5-pro
MIMO_MODEL_BRIEF=mimo-v2.5-pro
RESEND_API_KEY=re_...
EMAIL_FROM=onboarding@resend.dev           # Resend 测试地址（不需要域名验证）
EMAIL_TO=yuncongliu0703@gmail.com          # 必须是 Resend 注册账号邮箱
ALPHAGAP_DB_PATH=db/alphagap.sqlite
ADVERSARIAL_GAP_REVIEW=false                # true = 开启候选级对抗审计 gate
```

`LLM_PROVIDER` 默认保持 `deepseek`，因此服务器日常任务不会因新增接口而更换模型。用 OpenRouter 测模型时，将 key 仅放在本机 `.env`，设置 provider 与模型 slug 后可先做最小 JSON 兼容测试：

```bash
.venv/bin/python -m pipeline.llm_client probe \
  --provider openrouter --model '<provider/model-slug>'
```

若测试通过，再触发完整流程：

```bash
LLM_PROVIDER=openrouter LLM_MODEL_DEFAULT='<provider/model-slug>' \
  LLM_MODEL_REASONING='<provider/model-slug>' \
  LLM_MODEL_BRIEF='<provider/model-slug>' \
  .venv/bin/python -m pipeline.main daily --no-commit
```

也可以检索当前可见 model IDs：

```bash
.venv/bin/python -m pipeline.llm_client models --provider openrouter --contains '<keyword>'
```

项目的 prompt 依赖严格 JSON 输出；某个 OpenRouter 模型即便可聊天，也必须先通过 `probe`，再用于真实发信。OpenRouter 返回的 `usage.cost` 会直接记入本次运行的 cost；DeepSeek 仍按本地价格配置估算。

### `prompts/*.md`
每个 prompt md 文件结构必须包含两段：
```markdown
## System Prompt
```
<system text>
```

## User Prompt Template
```
<user text with {placeholders}>
```
```
代码用 `pipeline/extract/concepts.py:parse_prompt()` 解析。

---

## Database schema

详见 `pipeline/db.py` SCHEMA 常量。核心表：

| 表 | 内容 | 层级 |
|---|---|---|
| `papers` | 论文元数据（标题/摘要/作者/分类） | L3 |
| `paper_extractions` | L1/L2 LLM 抽取结果 | L2 |
| `paper_signals` | 候选信号 (HF / q-fin / 关键词 / 作者) + priority_score | L2 |
| `citation_snapshots` | S2 每日 citation 数快照 (paper_id, date, count) | L2 |
| `concepts` | 标准化概念实体（**目前未使用**，trends 直接聚合 JSON） | - |
| `paper_concepts` | paper × concept 多对多（**目前未使用**） | - |
| `daily_runs` | pipeline 执行日志（**目前未使用**） | - |

---

## Cost

| 项 | 频率 | 成本 |
|---|---|---|
| DeepSeek API | 每日 ~50-100 calls | ~$0.05-0.10/天 |
| Resend | 每日 1 封 | 免费（< 3000/月） |
| S2 API | 每日 1 batch | 免费（1 RPS） |
| 服务器 | luyao4 已有 | $0 |
| **合计** | | **~$15-25/年** |

一次性 backfill ~$0.8（已花在 5/20）。

---

## Roadmap

### 立刻（mechanism-level 升级收尾）
- [ ] **Step E**: 本地 backfill 跑完后端到端测试 + 发邮件验收
- [ ] **Step F**: `uptake.py` 升级到 mechanism 级（用 mechanism description 匹配 Fin 论文而非 keyword）
- [ ] **服务器同步**: 同样需要 reextract 一次（或等 cron 自然积累）

### 短期（优先级高）
- [ ] **修 arXiv 429**：换 OAI-PMH 接口 + polite User-Agent → 解锁 Fin 侧抓取
- [ ] **First mapping seed**：手动建 5-10 个 mappings 作为种子，让 LLM 后续 add_mapping 提议有上下文
- [ ] **Mapping 反馈回路**：被 reject 的 gap 留 in-context 例子，让 LLM 学习用户偏好（[Tier 2.4]）

### 中期
- [ ] **Weekly report**：`run_weekly()` 实现，周末邮件汇总 mapping 表变化、本周 gap top 5
- [ ] **Server git push**：服务器配 GitHub SSH key 或 HTTPS token，让 inbox 自动推到 git
- [ ] **Log rotation**：logrotate 配置或 cron 自动 truncate
- [ ] **Mechanism entity table (Phase 2)**：如果 dynamic clustering 不稳定，再考虑建 `mechanisms` 持久化表 + 聚类去重

### 长期
- [ ] **Author h-index enrichment**：S2 author batch API 拉 h-index，激活白名单的 h-index 阈值规则
- [ ] **Embedding-based gap detection**：当 LLM 漏掉语义级 gap 时再加（目前不需要）
- [ ] **Lumid 集成**：把 gap pipeline 作为 Lumid loop 跑（看 [[project_lqa_showcase_step_b]] 那条线）

---

## Local development

```bash
# Mac 本地（开发用）
git clone https://github.com/ycsama0703/AlphaGap.git
cd alphagap
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
# 编辑 .env

.venv/bin/python -m pipeline.db init
.venv/bin/python -m pipeline.main daily --dry-run --no-commit
```

### 单组件调试
```bash
# 只抓 arxiv
.venv/bin/python -m pipeline.fetchers.arxiv cs.LG q-fin.PM

# 只抓 HF Daily
.venv/bin/python -m pipeline.fetchers.hf_daily 2026-05-20

# 测一篇论文的 L1/L2
.venv/bin/python -m pipeline.extract.concepts cs.LG q-fin.PM

# 可选维护：测 trends（不在 daily critical path）
.venv/bin/python -m pipeline.analyze.trends ai --window 90 --end-date 2026-05-20

# 测完整 gap pipeline
.venv/bin/python -m pipeline.analyze.gaps --full --end-date 2026-05-20

# 可选维护：Citation snapshot (S2，不在 daily critical path)
.venv/bin/python -m pipeline.analyze.citations snapshot

# 看 DB 当前状态
.venv/bin/python -m pipeline.db stats
```

---

## Deployment notes

服务器已部署，配置详见上方 "Current state"。

### 重新部署（如果换服务器）
```bash
ssh new-server
cd ~/workspace/projects  # 或类似路径
git clone https://github.com/ycsama0703/AlphaGap.git alphagap
cd alphagap
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
mkdir -p logs

cp .env.example .env
nano .env  # 选择 LLM_PROVIDER，并填对应 provider key、RESEND_API_KEY 等

.venv/bin/python -m pipeline.db init
.venv/bin/python -m pipeline.main daily --dry-run --no-commit  # 验证

# 装 cron（替换路径为实际）
crontab -e
# 加: 0 <hour> * * * cd <project-path> && <venv>/bin/python -m pipeline.main daily --no-commit >> <project-path>/logs/daily.log 2>&1
```

### 时区
- 服务器 luyao4 是 **WIB** (UTC+7)
- Cron `0 7 * * *` = 北京时间 08:00（推荐）

---

## License & Privacy

私有项目。`.env` 含 API key，绝不进 git。`db/` 也不进 git（每台机器独立）。

`mappings/` + `briefs/` + `inbox/` + `prompts/` + `whitelist.yaml` 是 git 跟踪的核心内容。
