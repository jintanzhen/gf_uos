# 运营支持系统（Green-OS）

在预设时间点，把统一口径的内容派给会员的专属客服，由客服人工触达会员，并用对照组验证运营动作的真实续订增量。

| 文档 | 说明 |
|---|---|
| [PRD.md](./PRD.md) | 产品需求文档 v0.3.2（决议 D1–D15、R1–R4） |
| [architecture.md](./architecture.md) | 架构设计文档 v0.2（ER/表结构/时序/ADR） |
| [api_inventory.md](./api_inventory.md) | 源系统（绿手指 zhlsz.cn）鉴权与接口清单 |
| [data_model.md](./data_model.md) | 源系统数据模型逆向分析 |

**技术栈**：Python 3.11+ / FastAPI / SQLAlchemy 2.x / Alembic / APScheduler（内嵌调度器） / Vue3 + Element Plus / SQLite（可切 PostgreSQL） / Docker Compose

---

## 目录结构（规划，随 M0 落地）

```
backend/            # FastAPI 后端（内嵌 APScheduler 调度器）
├── app/
│   ├── api/        # 路由（cs / ops / admin 按角色分）
│   ├── services/   # 规则引擎、生成流水线、分流、归因、报表
│   ├── spider/     # 源系统爬取（zhlsz_client.py 改造）+ 字段映射
│   ├── models/     # SQLAlchemy ORM（16 张表）
│   ├── schemas/    # Pydantic 模型
│   ├── scheduler/  # 定时任务：同步 / 扫描 / 过期清理 / 归因回补
│   └── core/       # JWT、角色权限（BR-10 服务端隔离）、审计
├── alembic/        # 数据库迁移
├── tests/
└── data/           # app.db（SQLite，卷挂载）+ backup/
frontend/           # Vue3 + Element Plus（客服工作台 / 运营后台 / 超管）
```

---

## 环境要求

| 组件 | 版本 | 用途 |
|---|---|---|
| Python | 3.11+ | 后端 |
| Node.js | 18+ | 前端构建与开发服务器 |
| Docker Desktop | 可选 | 方式二的容器化运行 |

---

## 方式一：本机开发模式（推荐日常开发，无需 Docker）

### 1. 配置凭证

项目根目录创建 `.env`（不会提交到仓库）：

```ini
ZHLSZ_BASE_URL=https://www.zhlsz.cn
ZHLSZ_ACCOUNT=<源系统账号>
ZHLSZ_PASSWORD=<源系统密码>
```

### 2. 启动后端（PowerShell）

```powershell
cd backend

# 一条命令创建 .venv 并按 uv.lock 精确安装依赖（需已安装 uv：pip install uv / 官网安装）
uv sync

# 初始化数据库（建全部表）
uv run alembic upgrade head

# 创建第一个超管账号（M0 提供 CLI）
uv run python -m app.cli create-admin --name admin

# 启动服务（含 APScheduler 调度器）
uv run uvicorn app.main:app --reload --port 8000
```

后端就绪后可访问：

- API：http://localhost:8000/api
- Swagger 文档：http://localhost:8000/docs

### 3. 启动前端（另开一个终端）

```powershell
cd frontend
npm install
npm run dev
```

浏览器打开 **http://localhost:5173**（Vite 开发服务器，`/api` 已代理到 `localhost:8000`）。

> **重置环境**：删除 `backend/data/app.db` 后重跑 `uv run alembic upgrade head` 即可。
> **注意**：`--reload` 模式下改代码会连调度器一起重启；扫描任务幂等，不影响正确性。生产运行不要带 `--reload`。

---

## 方式二：Docker Compose（模拟生产形态）

```powershell
docker compose up --build -d
```

- 访问 **http://localhost**（nginx：前端静态资源 + `/api` 反向代理到 backend）
- SQLite 数据卷挂载在 `./data/`，容器重建数据不丢
- `.env` 凭证通过 `env_file` 注入，日志中凭证脱敏

停止/查看日志：

```powershell
docker compose down
docker compose logs -f backend
```

---

## 上线后的日常运行流

1. **同步数据**：超管登录 → 超管后台「立即同步」（或等每日定时）→ 爬取客服/会员/归属/份额 → 落库 + 对账报告；
2. **配置规则**：运营登录 → 新建规则（如"蔬菜份额剩 4 次续订提醒"，开 20% 对照组）→ 保存即生效，无需审批；
3. **自动派任务**：每日定时（如 09:30）调度器扫描 → 生成任务，全程无人工干预；
4. **客服执行**：客服登录工作台 → 今日待办（逾期红区/今日/即将到期）→ 一键复制文案 → 人工发送 → 回填结果；
5. **看效果**：运营查看任务总览与实验组 vs 对照组续订率对比（归因窗口默认 30 天）。

## 常用命令速查

| 命令（backend 目录） | 说明 |
|---|---|
| `uv sync` | 按 `uv.lock` 精确重建/更新 `.venv`（新增依赖用 `uv add xxx`） |
| `uv run alembic upgrade head` | 数据库迁移到最新 |
| `uv run alembic revision --autogenerate -m "xxx"` | 生成迁移脚本 |
| `uv run python -m app.cli create-admin --name admin` | 创建超管账号 |
| `uv run python -m app.cli sync --type all` | 手动触发同步（all/staff/member/order/share/binding） |
| `uv run pytest` | 运行测试（幂等/越权/频控/分流稳定/状态机等） |
| `uv run python scripts/verify_t1_t2_t3.py` | PRD T1/T2/T3 实测（分页上限/登录稳定性/手机号质量，需真实凭证） |

## 已实现的 API（M2 完成后）

| 分组 | 端点 |
|---|---|
| 规则（运营） | `POST/GET/PUT/DELETE /api/ops/rules`、`/{id}/toggle`、`/{id}/duplicate`、`/{id}/preview`（命中预览）、`/{id}/run-scan`（手动扫描）、`/{id}/scan-logs` |
| 任务（工作台） | `GET /api/cs/tasks?zone=overdue\|today\|upcoming`（三分区）、`GET /{id}`（详情含渲染文案）、`POST /{id}/copy`（复制留痕）、`POST /{id}/complete`（结果回填，其他必填备注）、`POST /{id}/cancel`、`POST /{id}/reschedule`、`GET /api/cs/summary`（今日小结） |
| 公共池（运营） | `GET /api/ops/pool`、`POST /api/ops/pool/{id}/claim` |
| 黑名单（运营） | `GET/POST /api/ops/blacklist`、`POST /{id}/unblock`（加入黑名单自动取消在途任务，BR-02） |
| 同步（超管） | `POST /api/admin/sync/{type}/run`（后台执行）、`GET /api/admin/sync-logs` |
| 会员 | `GET /api/cs/members`（我的会员）、`GET /api/cs/members/{id}`、`GET /api/ops/members`（全量检索）、`GET /api/ops/members/{id}` |
| 效果看板（M3） | `GET /api/ops/reports/overview`（任务总览）、`GET /experiment/{rule_id}`（实验组 vs 对照组，含 z 检验 p 值）、`GET /rules-ranking`（排行榜）、`GET /cs-performance`（客服绩效）、`POST /recompute`（历史重算，幂等） |

**Web 前端**（Vue3 + Element Plus，`frontend/`）：登录后按角色展示——客服：工作台/今日待办（三分区、复制留痕、完成回填）/会员中心/今日小结；运营：工作台/规则管理（两层嵌套可视化条件构建器、命中预览、手动扫描、扫描日志）/公共池认领与黑名单/效果分析（任务总览、实验效果对比、规则排行榜、客服绩效）；超管另有系统管理（同步日志与手动触发）。开发：`cd frontend && npm run dev`（5173，代理 /api → 8000）；构建：`npm run build`（含 `npx vue-tsc --noEmit` 类型检查）。

调度：每日 02:30 自动同步 → 03:10 续订归因回补（F6-05 三信号）；每分钟 tick 检查规则 exec_time 到期扫描（同规则每日一次，幂等）+ 逾期 3 天自动过期（D4）+ 离职客服任务转公共池（BR-06）。客服归属三口径匹配（v0.3.6）：`MemberInfo.Staff` 负责员工姓名（主）→ `StaffInfo.MemberList` MemID（辅1）→ 手机号（辅2）；历史存量用 `backend/backfill_staff.py` 一次性回填（可重跑，幂等）。

**账号（v0.3.7 一人一号）**：超管 admin/admin123；运营 ops1/ops123；10 个客服由 StaffInfo 同步自动建号（登录名=姓名，如 `瓜娃子`），初始密码统一 `cs123`（`backend/bootstrap_accounts.py` 幂等发放）；改密/停用走超管「系统管理 → 人员管理」（停用立即失效并在下个 tick 转公共池）。验收脚本：`backend/accept_m0.py`、`backend/smoke_m1.py`、`backend/smoke_m2.py`、`backend/smoke_m3.py` 可重跑。

---

## 验证脚本（源系统连通性）

| 脚本 | 用途 |
|---|---|
| `verify_t1_t2_t3.py` | PRD T1–T3 实测：分页上限/QPS、OCR 登录稳定性、手机号质量（可重跑） |

```powershell
.\.venv\Scripts\python.exe -X utf8 verify_t1_t2_t3.py
```
