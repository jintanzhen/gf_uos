---
name: zhlsz-auth-reuse-and-data-api
overview: 用浏览器自动化登录 https://www.zhlsz.cn/（Vue SPA），抓取登录接口与后续 XHR 请求，分析鉴权机制（Cookie/Session 或 JWT），在 e:/code/fene_management_system 下用 Python 实现可复用的登录鉴权封装，验证带鉴权请求可用，并列出系统内主要数据接口清单供用户选择后续抓取目标。
todos:
  - id: browser-login-capture
    content: 用 [skill:agent-browser] 打开 zhlsz.cn 并以 fupenzi/123456 登录，抓取登录接口与后续 XHR 请求（路径、参数、响应、请求头、Cookie）
    status: completed
  - id: analyze-auth
    content: 分析抓包结果，判定鉴权机制（Cookie/SessionId 或 JWT Bearer）及数据接口前缀
    status: completed
    dependencies:
      - browser-login-capture
  - id: verify-auth-python
    content: 初始化 Python 环境（uv venv + requests/python-dotenv），编写 verify_auth.py 用 requests 独立复现登录并带鉴权请求一个真实接口验证
    status: completed
    dependencies:
      - analyze-auth
  - id: build-client
    content: 编写 zhlsz_client.py 可复用鉴权客户端（.env 凭证、自动登录、凭证持有、401 自动重登），并验证调用成功
    status: completed
    dependencies:
      - verify-auth-python
  - id: api-inventory-doc
    content: 整理 api_inventory.md：鉴权机制说明 + 主要数据接口清单，供用户选择后续抓取目标
    status: completed
    dependencies:
      - build-client
---

## 产品概述

针对内部信息管理系统「绿手指有机农园」（https://www.zhlsz.cn/，Vue SPA），通过浏览器登录抓包还原其鉴权体系，并用 Python 代码复用该鉴权，实现脱离浏览器的直接数据接口请求。

## 核心功能

- 自动化登录系统（账号 fupenzi），抓取登录接口的请求路径、参数、响应及后续 XHR 请求
- 分析鉴权机制：确认是 Cookie/SessionId 还是 JWT（Authorization: Bearer），提取凭证
- 用 Python requests 独立复现登录流程，验证不依赖浏览器即可通过鉴权
- 封装可复用的鉴权客户端（自动登录、凭证持有、带鉴权请求、失效重登）
- 调用已发现的数据接口验证鉴权有效性，输出系统内主要数据接口清单供用户选择后续抓取目标

## 技术栈

- 抓包探查：agent-browser 浏览器自动化（打开页面、填表登录、观察网络请求）
- 鉴权复现与封装：Python + requests
- 凭证管理：.env 文件（延续用户既有习惯，避免明文写在代码里）
- 运行环境：Windows + PowerShell；系统 python 为 Microsoft Store stub 不可用，需用 uv 创建项目 .venv 或复用 e:/code/after_sales_analysics_v1.1.0/.venv/Scripts/python.exe（含 requests）

## 实现思路

1. **抓包阶段**：用 agent-browser 打开 zhlsz.cn，执行 JS 渲染后找到登录表单，填入账号密码登录；重点记录：登录接口 URL/方法/请求体（注意是否有密码加密）、响应结构（token 字段 or Set-Cookie）、后续 XHR 请求头（Cookie / Authorization）及数据接口路径前缀。
2. **鉴权分析**：按三种形态分支处理——纯 Cookie/Session（requests.Session 自动携带）、JWT（从登录响应提取 token，后续加 Authorization: Bearer 头）、两者混合（Session + Bearer 同时持有）。
3. **独立验证**：先写一次性验证脚本用 requests 直接复现登录，确认抓包结论正确后再固化封装，避免基于误判写代码。
4. **封装设计**：单一客户端类封装登录态生命周期（登录 → 持凭证 → 请求 → 401/token 失效自动重登一次），对外暴露 get/post 通用方法，保持可扩展（后续用户选定数据接口后仅需追加业务方法）。

## 性能与可靠性

- 登录态复用：模块内仅登录一次并持久持有 Session/token，避免每次请求重复登录
- 失败处理：登录失败/验证码出现/接口 401 均给出明确报错信息；token 失效自动重登一次，仍失败则抛出异常
- 爆炸半径控制：全新工作区（当前为空目录），全部为新建文件，不影响任何既有项目

## 目录结构

```
e:/code/fene_management_system/
├── .env                      # [NEW] 存放 ZHLSZ_BASE_URL / ZHLSZ_ACCOUNT / ZHLSZ_PASSWORD
├── zhlsz_client.py           # [NEW] 可复用鉴权客户端：登录、凭证管理、带鉴权 get/post、失效重登
├── verify_auth.py            # [NEW] 一次性验证脚本：用 requests 独立复现登录并请求一个真实数据接口
├── api_inventory.md          # [NEW] 抓包产出：鉴权机制说明 + 主要数据接口清单（方法/路径/参数/响应示例）
└── requirements.txt          # [NEW] requests、python-dotenv
```

## Agent Extensions

### Skill

- **agent-browser**
- 用途：浏览器自动化登录 zhlsz.cn，执行 JS 渲染 SPA 页面、填写登录表单、观察登录接口与后续 XHR 网络请求
- 预期产出：拿到登录接口路径/参数/响应、鉴权凭证形态（Cookie/Session 或 JWT）、数据接口路径清单