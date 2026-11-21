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

## 需求概述

修复“会员的匹配客服都是空的”bug：源系统“会员信息”中的 **负责员工（MemberInfo.Staff）** 字段才是客服归属的权威口径，应据此重建会员-客服绑定关系。

## 问题根因（实网已核实）

- 现行 `sync_binding` 仅用 `StaffInfo.MemberList`（MemID 串）+ 手机号双口径匹配，当前生效绑定仅 9 条，导致前端“归属客服”全空。
- 源系统 `MemberInfo.Staff` 存的是员工**姓名**（如 瓜娃子/覆盆子），此前未纳入同步。
- 全量扫描 26,071 个会员：**4,218 个有非空负责员工，100% 命中 StaffInfo.StaffName 名单**（10 个客服），本地 operator 表 `Operator.name == StaffInfo.StaffName` 可直接对齐。

## 修复目标

1. member 表落库“负责员工”姓名（`staff_name` 列），同步管线纳入该字段
2. 绑定匹配改为三口径：**负责员工姓名（主）→ StaffInfo.MemberList（辅1）→ 手机号（辅2）**，并按优先级记录 source
3. 一次性回填历史存量（增量游标拿不到未变更的老行），重跑绑定后约 4,218 个会员点亮归属客服
4. 无 Staff 值的 21,853 个会员源系统本就无归属，继续走公共池（属正常，非 bug）
5. 前端会员中心/详情无需改动（cs_name 来自 is_current binding join，自动点亮）

## 技术方案

### 技术栈

沿用现有项目栈：FastAPI + SQLAlchemy 2.x + Alembic（迁移 0005）+ Vue3 前端零改动。

### 实现思路

1. **模型与映射**（遵循 M3 迁移 0004 的既有模式）：

- `Member` 增加 `staff_name: Mapped[Optional[str]]`（String(50)，index）
- `MEMBER_MAP` 增加 `"Staff": "staff_name"`
- `sync_member` 赋值段补 `member.staff_name = data.get("staff_name")`（负责员工变更会 bump ModifyDate，增量游标可持续维护）

2. **绑定匹配重构**（`sync_binding`）：

- 预载 `Operator.name → id` 映射（active 且 ext_cs_id 非空，与现有 operators 过滤一致）
- 口径 a：`member.staff_name == Operator.name`（主，source="MemberInfo.Staff"）
- 口径 b/c：保留现有 MemberList MemID 匹配与手机号匹配（source="StaffInfo"/"Mobile"），按 a→b→c 优先级取第一个命中
- 统计字段新增 `matched_by_staff`；保留全量置零再重建的 R1 语义（`is_current=False` → 重新点亮）
- 一个会员被多口径命中时以负责员工为准（R1 唯一归属，按口径优先级去重）

3. **一次性回填脚本**（`backend/backfill_staff.py`，对齐 smoke 脚本风格）：

- 全量分页拉 MemberInfo（rows=500，约 53 页），仅 UPDATE `staff_name` 有变化的行（UPSERT 幂等，不动游标）
- 回填后自动调用 `sync_binding`，打印前后绑定数对比（预期 9 → ~4,218）
- 写 sync_log（sync_type="binding"，detail 记录回填口径）

4. **性能**：绑定匹配基于内存 dict（26k 会员 id/mobile/staff_name 预载），O(N)；回填 53 次 API 请求，分钟级，一次性成本可接受

### 性能与可靠性

- 匹配全程内存 dict 查找，无 N+1
- BR-08：回填/绑定失败各自独立事务与 sync_log，不阻断
- BR-01：绑定变化只影响后续扫描生成任务的 cs 归属/公共池落点，不重排已生成任务

### 验证

- 单测：补 `test_sync.py` 用例（staff 姓名匹配优先级、MemberList 回退、无 Staff 走 MemberList/手机号、口径去重唯一归属）
- 实网：回填脚本 + 重跑绑定 → 核对 `total_current ≈ 4218`、各客服绑定数与源分布一致；前端会员中心抽查 cs_name 点亮
- 回归：smoke_m2/smoke_m3 全量测试套件