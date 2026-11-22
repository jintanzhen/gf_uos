---
name: fix-member-cs-binding
overview: 修复会员匹配客服全空的 bug：以源系统 MemberInfo.Staff（负责员工，存姓名）为主口径重建客服绑定——member 表新增 staff_name 列（迁移 0005 + MEMBER_MAP），一次性全量回填 staff_name，sync_binding 改为三口径匹配（负责员工姓名 > StaffInfo.MemberList > 手机号），重跑绑定后约 4,218 个会员点亮归属客服。
todos:
  - id: migrate-staff-name
    content: Member 模型加 staff_name 列 + MEMBER_MAP 扩展 + 迁移 0005（沿用 server_default 防坑模式）
    status: completed
  - id: sync-member-staff
    content: sync_member 赋值段写入 staff_name，增量同步可持续维护
    status: completed
    dependencies:
      - migrate-staff-name
  - id: rework-binding-match
    content: 重构 sync_binding 三口径匹配（负责员工姓名为主，MemberList/手机号回退，source 记录口径，按优先级去重保证唯一归属）
    status: completed
    dependencies:
      - migrate-staff-name
  - id: backfill-staff
    content: 一次性回填脚本 backfill_staff.py：全量拉 MemberInfo 更新 staff_name 并重跑绑定，输出前后对比
    status: completed
    dependencies:
      - sync-member-staff
      - rework-binding-match
  - id: tests-regression
    content: 补 test_sync 用例（三口径优先级/回退/去重）并全量回归测试套件
    status: completed
    dependencies:
      - rework-binding-match
  - id: verify-e2e
    content: 实网验证：绑定数≈4218、前端会员中心归属客服点亮、PRD 变更记录与记忆更新
    status: completed
    dependencies:
      - backfill-staff
---

## 用户需求
继续 Green-OS 运营支持系统 M4 阶段开发，本期实现**标签体系**（PRD F2-03 + F2-04），分群（F2-05）明确不在本次范围。

## 已确认口径
- **静默标签**：距最近一次下单（ext_order 支付/创建时间）超过 **30 天**未下单即打标，每日自动重算
- **人工标签**：预置词表（价格敏感/只收微信/勿扰/新客待跟进）下拉 + 允许自定义输入 + 支持到期时间（如“勿扰至5月”）+ 删标签留痕

## 核心功能
1. **系统标签自动计算（F2-03）**：四类标签每日 03:30 自动重算 + 支持运营手动触发——
   - `share_low`（剩≤4次）：名下生效份额剩余次数 ≤ 4
   - `silent_30d`（静默）：30 天无任何下单记录
   - `high_value`（高价值）：累计消费 Top 20% 会员
   - `new_member`（新会员）：注册 ≤ 7 天
2. **人工标签（F2-04）**：客服给自己名下会员打标（服务端校验归属），运营/超管可对全部会员打标；标签可设到期时间；删除留审计痕迹
3. **规则条件引用标签**：规则引擎已支持 `标签 has` 条件（scanner/evaluator 就绪），本次补齐规则编辑器中标签值下拉选择（从已有标签词表读取），系统标签生成后即可被规则命中
4. **会员 360 展示**：详情抽屉展示系统标签（灰）+ 人工标签（蓝，含到期时间），客服/运营可在此打标与删标

## 验收标准
- 系统标签实网重算幂等，manual 标签不受重算影响
- 客服越权给他人会员打标 → 403；删除标签写审计日志
- 规则条件选“拥有标签”后值控件为下拉选择，扫描命中带标签会员
- 测试全绿（基线 51/51 + 新增用例）


## Tech Stack
- 后端：FastAPI + SQLAlchemy + SQLite（复用现有架构，无新依赖）
- 前端：Vue3 + TypeScript + Element Plus（复用现有页面）
- 无需数据库迁移（Tag 模型已就绪：member_id/tag_type/tag_key/tag_value/expire_at/created_by）

## Implementation Approach
- **系统标签计算**（新建 `backend/app/tags/service.py`）：四类标签一次性重算——剩余次数与新会员用单查 SQL 集合判定；静默用 `ext_order` 按会员 max(pay_time, created_at) 聚合（注意 UTC↔本地偏移换算，复用 attribution.py 的 `_to_utc()` 先例）；高价值按 ext_order.total_price 汇总取前 20% 分位。落库策略：**只删 sys 类标签后批量重插**（绝对不动 manual），幂等且实现简单（26k 会员量级单次重算 <2s）
- **标签 API**（新建 `backend/app/api/tags.py`）：人工标签新增/删除（写 audit_log）、标签 key 词表查询（sys 词表常量 + manual 去重 distinct）、运营手动触发系统标签重算；挂载到 main.py
- **会员详情增强**：`api/members.py` 两个详情端点响应增加 `tags` 数组（过滤已过期），复用现有 require_cs/require_ops 权限注入
- **调度**：`scheduler/jobs.py` 增加 daily_system_tags@03:30 cron（归因回补 03:10 之后，避免与同步竞争）
- **前端**：`api/tags.ts` 新建；MembersView 360 抽屉加标签展示与打标 UI（el-select allow-create + 日期选择）；ConditionValue 的 tag 字段值控件从自由文本改为标签下拉（词表接口）
- **性能**：重算为批量集合运算 + bulk insert，避开逐会员查询（防 N+1）；规则扫描 tag_map 已有缓存模式，零改动

## Architecture Design
```
scheduler/jobs.py (daily 03:30) ──▶ tags/service.py::recompute_system_tags
                                         │ 只重写 sys 类标签
api/tags.py ◀── 前端 api/tags.ts          ▼
  POST /ops/tags/recompute            tag 表 (sys|manual)
  GET  /ops/tags/keys（词表）              ▲
  POST /{member_id}/tags（打标）      scanner.py tag_map（已有，过滤过期）
  DELETE /tags/{tag_id}（删标+审计）   evaluator.py has 操作（已有）
  ▲
api/members.py 详情响应 +tags 字段 ──▶ MembersView 360 抽屉展示/打标
```

## Directory Structure Summary
```
backend/
├── app/
│   ├── tags/
│   │   ├── __init__.py            # [NEW] 空
│   │   └── service.py             # [NEW] 四类系统标签计算与幂等重算（核心服务）
│   ├── api/
│   │   └── tags.py                # [NEW] 标签 API：打标/删标/词表/手动重算
│   ├── api/members.py             # [MODIFY] 详情响应加 tags 数组
│   ├── scheduler/jobs.py          # [MODIFY] 注册 daily_system_tags@03:30
│   └── main.py                    # [MODIFY] 挂载 tags router
├── tests/
│   └── test_tags.py               # [NEW] 系统标签四口径+幂等+人工标签权限+删标留痕
frontend/
├── src/api/tags.ts                # [NEW] 标签 API 封装
├── src/views/MembersView.vue      # [MODIFY] 360 抽屉标签展示+打标/删标 UI
└── src/views/ConditionValue.vue   # [MODIFY] tag 值控件改为词表下拉
```

## Key Code Structures
```python
# backend/app/tags/service.py（核心签名）
SYS_TAG_KEYS = ("share_low", "silent_30d", "high_value", "new_member")
SILENT_DAYS = 30
HIGH_VALUE_TOP_PCT = 0.20

def recompute_system_tags(db: Session, now: datetime | None = None) -> dict:
    """重算四类系统标签（只动 tag_type='sys'，manual 不受影响）。幂等。
    返回 {"share_low": n, "silent_30d": n, "high_value": n, "new_member": n}"""

# backend/app/api/tags.py（端点）
# POST /api/ops/tags/recompute            运营手动触发重算
# GET  /api/ops/tags/keys                 词表（SYS 常量 + manual distinct）
# POST /api/{role}/members/{mid}/tags     打标（cs 校验归属，写 audit）
# DELETE /api/{role}/tags/{tag_id}        删标（写 audit）
	

## Agent Extensions
### SubAgent
- **code-explorer**
  - Purpose：执行期快速核对 attribution.py 的 `_to_utc()` 时区换算实现、main.py router 挂载模式与 audit_log 写入函数签名，避免实现时口径偏差
  - Expected outcome：获得可直接复用的工具函数签名与挂载代码样例
### Skill
- **agent-browser**
  - Purpose：实网浏览器验收——登录运营账号验证 360 抽屉标签展示/打标、规则编辑器标签下拉
  - Expected outcome：页面真实渲染截图级验证，确认端到端可用
