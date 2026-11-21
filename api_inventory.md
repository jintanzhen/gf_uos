# 绿手指有机农园（zhlsz.cn）鉴权机制与数据接口清单

> 抓包时间：2026-11-15；账号：fupenzi（覆盆子）。系统为 Vue SPA（前端代号 `vol`）+ Kestrel(.NET) 后端。

## 一、鉴权机制（已确认：JWT Bearer，无 Cookie/Session 依赖）

### 登录流程（两步）

| 步骤 | 请求 | 说明 |
|---|---|---|
| 1 | `GET /api/User/getVierificationCode` | 返回 `{"img": "<base64 PNG>", "uuid": "<GUID>"}`，图形验证码 4 位字母数字 |
| 2 | `POST /api/user/login` | 请求体：`{"userName": "fupenzi", "password": "123456", "verificationCode": "QZrN", "UUID": "<第1步的uuid>"}` |

登录响应：

```json
{"status": true, "code": "310", "message": "登陆成功",
 "data": {"token": "eyJhbGciOi...", "userName": "覆盆子", "accessToken": null}}
```

- token 为 **JWT（HS256）**，有效期 **2 小时**（`exp - iat = 7200s`），`iss=ZH`、`aud=Lsz`，`jti` 为用户 ID。
- 后续所有请求只需加头：`Authorization: Bearer <token>`，**不需要 Cookie**。
- 验证码不区分大小写（抓包中输入 `Tnsj` 成功）。
- 登录失败返回 `status:false` + `code`（320 类为验证码错误，可换图重试）。

### 其他认证相关接口

| 接口 | 方法 | 说明 |
|---|---|---|
| `/api/user/GetCurrentUserInfo` | POST | 当前用户信息（userName/userTrueName 等） |
| `/api/menu/getTreeMenu` | GET | 菜单树 + 每个页面对应的数据表名与权限 |
| `/hub/message/negotiate?userName=fupenzi` | POST | SignalR 实时消息（可忽略） |

## 二、通用数据接口模式（VolPro/VOL 框架风格）

### 分页查询（核心）

```
POST /api/<TableName>/getPageData
Body: {"page": 1, "rows": 10, "sort": "CreateDate", "order": "desc", "wheres": "[]"}
```

- `wheres` 为 JSON 字符串（注意是字符串化的数组），元素形如
  `{"name": "RealName", "value": "张"}`（相等/模糊由服务端按列生成）。
- 响应：`{"status": 0, "msg": null, "total": 25906, "rows": [...], "summary": null, "extra": null}`
- `<TableName>` 大小写不敏感（`memberinfo`/`MemberInfo` 均可）。

### 数据字典

```
POST /api/Sys_Dictionary/GetVueDictionary
Body: ["MemberSelect", "OrderStatus", "WarehouseBaseSelector", ...]
```

返回各下拉框选项（如 `MemberSelect` 含全部会员 key/value）。

## 三、首页统计接口（GET，无需参数）

| 接口 | 说明 |
|---|---|
| `/api/ViewOrderCountByPlatform/GetList` | 各平台订单数 |
| `/api/View6MonthOrderCount/GetInfo` | 近 6 个月订单量趋势 |
| `/api/View6MonthOrderPrice/GetInfo` | 近 6 个月订单金额趋势 |
| `/api/ViewTop10OrderCountByMember/GetInfo` | 会员订单数 Top10 |
| `/api/ViewTop10PriceByMember/GetInfo` | 会员消费金额 Top10 |
| `/api/ViewShipCountByDay/GetInfo` | 每日配送量 |

## 四、业务数据表清单（42 个页面，均支持 `POST /api/<表名>/getPageData`）

### 订单类

| 菜单 | 表名 | 权限 |
|---|---|---|
| 待审订单 | `OrderInfoToAduited` | Search,Export,审单 |
| 已审订单信息 | `OrderInfoAduited` | Search,Export,暂停/恢复 |
| 已暂停订单 | `OrderInfoPaused` | Search,Export |
| 异常订单 | `OrderInfoProblem` | Search,Export |
| 完结订单 | `OrderInfoCompleted` | Search,Export,归档 |
| 普通散单订单 | `OrderInfoSandan` | Search |
| 完整订单信息 | `OrderInfo` | Search,Export,同步 |
| 归档订单 | `orderinfo_archive` | Search,Export |
| 明细管理 | `OrderDetail` | Search,Export |
| 归档明细 | `orderdetail_archive` | Search |
| 订单日志 | `GreenLog` | Search |

### 配送类

| 菜单 | 表名 | 权限 |
|---|---|---|
| 待审配送单 | `ShipInfoToAduited` | Search,Export,审配 |
| 配送中配送单 | `ShipInfoOnShip` | Search,Export |
| 已审配送单 | `ShipInfoAduited` | Search,Export |
| 已暂停配送单 | `ShipInfoPaused` | Search,Export |
| 完整配送记录 | `ShipInfo` | Search,Export |
| 归档配送单 | `shipinfo_archive` | Search,Export |
| 打包管理/明细 | `BagInfo` / `BagDetail` | Search,Export |
| 拣菜管理/明细 | `JianCaiInfo` / `JianCaiDetail` | Search,Export |
| 预检批次/明细/统计 | `ShipPreCheckBatch` / `ShipPreCheckDetail` / `ShipPreCheckStat` | Search,Export |

### 会员类

| 菜单 | 表名 | 权限 |
|---|---|---|
| 会员信息 | `memberinfo` | 全套（含账户变动） |
| 账户变动 | `account` | Search |
| 纸箱变动 | `AccountForBox` | Search,Export |
| 减配变动 | `AccountForJianpei` | Search,Export |
| 补送运费记录 | `FreightRecord` | Search,Export |
| 忌口管理 | `UnlikeInfo` | 全套 |
| 会员忌口汇总 | `ViewUnlikeList` | Search,Export |
| 会员日志 | `MemberLog` | Search |
| 客服管理 | `StaffInfo` | 全套 |
| 自提点管理 | `addressinfoSelfFetchPoint` | 全套 |
| 地址管理 | `addressinfo` | 全套 |

### 商品/聚水潭类

| 菜单 | 表名 | 权限 |
|---|---|---|
| 商品信息 | `jstGood` | 全套，Sync |
| 聚水潭订单 | `JstOrder` | Search,Export |
| 每日菜品库存 | `DailyCaipinStock` | 全套 |
| 菜品管理 | `CaipinInfo` | 全套 |
| 菜品预计 | `YujiInfo` | 全套 |

### 系统类

| 菜单 | 表名 |
|---|---|
| 日志管理 | `Sys_Log` |
| 接口日志 | `ApiLog` |

## 五、已验证结论

- 用 Python requests 完整复现登录（验证码用 ddddocr OCR 自动识别）并通过 Bearer token 请求成功：
  - `POST /api/user/GetCurrentUserInfo` → 200
  - `POST /api/memberinfo/getPageData` → 200，`total=25906`（41 个字段/行）
- 可复用代码见 `zhlsz_client.py`（`.env` 存凭证，token 过期前自动刷新、401 自动重登）。
- 未测：写操作（Add/Update/审单等）仅查询验证过；`rows` 参数服务端可能存在上限。
