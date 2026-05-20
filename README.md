# AI × Fin Radar

每日抓取 AI 与金融领域前沿论文，自动产出 AI→Fin 迁移的 gap 候选（理论型 + 工程型），通过邮件推送，并把可审批的 mapping 提议落到 git 仓库。

核心资产是 `mappings/` 和 `ideas/` 两份持续生长的 markdown 知识库——项目不是论文管理工具，是研究判断沉淀系统。

## Quick Start

```bash
# 1. 装依赖
pip install -r requirements.txt

# 2. 配置环境
cp .env.example .env
# 编辑 .env 填入 DEEPSEEK_API_KEY、RESEND_API_KEY 等

# 3. 初始化数据库
make init-db

# 4. 跑一次 dry-run（不发邮件、不写 inbox，只 stdout）
make dry-run

# 5. 生产模式跑每日
make daily
```

## 架构

```
fetchers/       数据抓取 (HF Daily / arXiv / SSRN / S2)
   ↓
extract/        概念抽取 (LLM Layer 1/2)
   ↓
db (SQLite)     papers + concepts 持久化
   ↓
analyze/        Trend 总结 → Gap 生成 → 自检 → 评分 → Mapping 更新
   ↓
output/         邮件推送 + inbox markdown patch + 周报
```

## 数据流

- **L1 资产**（不可再生）：`mappings/` + `ideas/` markdown，git 跟踪
- **L2 派生**：`db/radar.sqlite` 的 concepts/reports
- **L3 缓存**：`db/radar.sqlite` 的 papers（丢了可重抓）
- **L4 不存**：PDF / 网页原文

## 配置

- `whitelist.yaml` — 机构/作者/数据源白名单 + 关键词 + 阈值
- `prompts/` — 8 个 LLM prompt 定义
- `.env` — API keys 和路径

## 审批工作流

```
服务器 cron 每日跑 → 写 inbox/yyyy-mm-dd.md → git commit & push
   ↓
你本地 git pull → 编辑 inbox/yyyy-mm-dd.md（accept / reject / modify）
   ↓
将通过的 mapping action apply 到 mappings/ → git commit & push
   ↓
服务器下次跑时读最新 mappings 作为 context
```

## 部署

参考 `deploy/cron.example`（待补）。

## License

私有项目。
