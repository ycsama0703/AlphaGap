# luyao4 使用方法与规则

**luyao4 = 实验室共享 GPU 服务器**，AlphaGap 的跑实验 / 跑 daily pipeline 主机。换 session 先读此文，别再翻记忆。
**最后核实**：2026-06-23。

---

## 0. 铁律（违反会出事 / 被实验室罚）

1. **禁止用 ssh/scp 传数据**（实验室规定）。ssh **只能跑命令**。代码/数据进 luyao4 只有两条路：
   - **GitHub commit + 在 luyao4 上 `git pull`**（传代码/小文件）
   - **luyao4 自己从公网拉**（findata / HuggingFace / arXiv 等——脚本在服务器上 `httpx.get` 自取）
2. **本机存储紧张**——大数据(推文/embedding/windows)**只落在 luyao4**，不要拉回本地。
3. **共享机**：东西放 `/home/ycliu0703/` 下；GPU 按需用，跑完确认释放（`nvidia-smi`）。
4. **commit/push 只在用户明确要求时做**。git co-author 固定：
   `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`

---

## 1. 连接

ssh alias 已配好（`~/.ssh/config`）：
```
Host luyao4
    HostName 192.168.6.204
    User ycliu0703
    ProxyJump kv.run        # 经 kv.run 跳板，不能直连
```
直接 `ssh luyao4 '<命令>'` 即可。用户要交互登录时让其在 prompt 里打 `! ssh luyao4`。

| 项 | 值 |
|---|---|
| user / host | `ycliu0703` @ `luyao4` (192.168.6.204) |
| home | `/home/ycliu0703` |
| 仓库 | `/home/ycliu0703/workspace/projects/alphagap` |
| GPU | NVIDIA RTX 5080, 16 GB |

---

## 2. Python 环境

**项目 venv（带 torch+cuda，必须用这个，不是系统 python3）**：
```
/home/ycliu0703/workspace/projects/alphagap/.venv/bin/python
```
- torch 2.12.0+cu130, `cuda.is_available()=True`
- 有：httpx, numpy, sentence-transformers
- **没有 pyarrow** → 存盘用 `.npz`，别用 parquet
- 系统 `python3` 没装 torch → 直接跑会 `ModuleNotFoundError: torch`

---

## 3. findata 访问（luyao4 上自取，不经本地）

```python
import re, pathlib, httpx
BASE = "https://kv.run:5000"
pat = re.search(r"lm_pat_live_[A-Za-z0-9_]+",
                (pathlib.Path.home()/".lumid/credentials.toml").read_text()).group(0)
H = {"Authorization": f"Bearer {pat}"}
r = httpx.get(f"{BASE}/fundamentals/AAPL/history",
              params={"statement":"income","period":"quarter","limit":200},
              headers=H, timeout=60, verify=False)   # verify=False: 自签证书
```
- PAT 在 `~/.lumid/credentials.toml`（格式 `lm_pat_live_...`），已复制到 luyao4，直接读。
- 能力目录见 `knowledge/FINDATA_CATALOG.md`，字段验证见 `knowledge/FINDATA_VERIFICATION.md`。
- 长拉取会 `read timed out` → 加 retry + backoff（见 socialenc/fetch_kol.py 的 `get()`）。

---

## 4. 后台跑实验（标准姿势）

ssh 会话断开不杀进程，用 `setsid` + 日志落盘 + 轮询日志：
```bash
ssh luyao4 'cd ~/workspace/projects/alphagap/experiments/<exp> && \
  setsid bash -c "~/workspace/projects/alphagap/.venv/bin/python -u job.py > job.log 2>&1" < /dev/null & echo LAUNCHED'
# 之后轮询（注意：刚启动那几秒 log 可能还没创建，sleep 后再读）
ssh luyao4 'grep -vi warning ~/workspace/projects/alphagap/experiments/<exp>/job.log | tail -30'
```
- 写脚本到 luyao4：用 `cat > path << "PYEOF" ... PYEOF` heredoc（写代码文本不算"传数据"）。先 `mkdir -p` 目录再 heredoc，否则 `No such file or directory`。
- 写完先语法检查：`python3 -c "import ast; ast.parse(open('job.py').read()); print('SYNTAX_OK')"`。
- 跑完查 GPU 释放：`nvidia-smi --query-gpu=memory.used --format=csv,noheader`。

实验目录惯例：`~/workspace/projects/alphagap/experiments/<name>/`，数据落 `<name>/data/*.npz|*.jsonl`。

---

## 5. daily pipeline 的 cron

luyao4 上跑 AlphaGap 找-gap daily（每天 07:00）：
```
0 7 * * * cd /home/ycliu0703/workspace/projects/alphagap && \
  /home/ycliu0703/workspace/projects/alphagap/.venv/bin/python -m pipeline.main daily --no-commit \
  >> /home/ycliu0703/workspace/projects/alphagap/logs/daily.log 2>&1
```

**硬规则**：
1. **cron 不会自动 `git pull`**。每次本地 push 后，必须手动同步 luyao4 才会生效：
   ```bash
   ssh luyao4 'cd ~/workspace/projects/alphagap && git pull --ff-only origin main'
   ```
2. 邮件突然停了 → **先查 `ssh luyao4 'crontab -l'`**。LQA showcase 部署会覆盖 crontab、抹掉这条 `0 7` job（见记忆 `project_alphagap_luyao4_cron.md`）。
3. git remote: `origin = https://github.com/ycsama0703/AlphaGap.git`，主分支 `main`。

---

## 6. 现有实验资产（luyao4 上，别重拉）

`experiments/socialenc/`：KOL 推特数据已拉好——**459,472 推文 / 17 标的**（`data/*.jsonl`），MiniLM embedding（`data/*.npz`），windows（57673 个，K=24）。编码 gap 已 KILL（bag 打赢 fancy）。
`experiments/worldmodel/`：涌现会计世界模型 probe（已 KILL-flat）。
