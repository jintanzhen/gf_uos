# -*- coding: utf-8 -*-
"""绿手指有机农园（https://www.zhlsz.cn）可复用鉴权客户端。

鉴权机制（经抓包确认）：
1. GET  /api/User/getVierificationCode  -> {img: base64 png, uuid}
2. POST /api/user/login  {userName, password, verificationCode, UUID}
   -> {status, code, message, data: {token, userName, ...}}
   token 为 JWT（HS256，有效期 2 小时，iss=ZH, aud=Lsz）
3. 后续所有请求加请求头  Authorization: Bearer <token>
4. 无 Cookie/Session 依赖，纯无状态 JWT。

用法示例：
    from zhlsz_client import ZhlszClient

    client = ZhlszClient()            # 自动从 .env 读配置，惰性登录
    data = client.get_page("memberinfo", page=1, rows=10)
    resp = client.post("/api/user/GetCurrentUserInfo")
    resp = client.get("/api/View6MonthOrderCount/GetInfo")
"""
from __future__ import annotations

import base64
import json
import os
import time
from typing import Any, Dict, List, Optional

import requests
from dotenv import load_dotenv

try:
    import ddddocr
except ImportError:  # pragma: no cover
    ddddocr = None

load_dotenv()

MAX_CAPTCHA_RETRY = 5
RELOGIN_ON_UNAUTHORIZED = True


class ZhlszAuthError(RuntimeError):
    """登录/鉴权相关异常。"""


class ZhlszClient:
    """封装登录、凭证持有与带鉴权请求的客户端。

    - 凭证（JWT token）在实例内持久持有，token 过期前（提前 60s）自动刷新
    - 收到 401 时自动重登一次并重试请求
    - 验证码用 ddddocr 本地 OCR 识别，识别失败自动换图重试
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        account: Optional[str] = None,
        password: Optional[str] = None,
    ) -> None:
        self.base_url = (base_url or os.getenv("ZHLSZ_BASE_URL", "https://www.zhlsz.cn")).rstrip("/")
        self.account = account or os.getenv("ZHLSZ_ACCOUNT")
        self.password = password or os.getenv("ZHLSZ_PASSWORD")
        if not self.account or not self.password:
            raise ZhlszAuthError("缺少账号/密码：请配置 .env（ZHLSZ_ACCOUNT / ZHLSZ_PASSWORD）或传参")

        self.session = requests.Session()
        self._token: Optional[str] = None
        self._token_expire_at: float = 0.0  # unix 秒
        self._ocr: Optional[Any] = None
        self._common_headers = {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "lang": "zh-cn",
            "Referer": self.base_url + "/",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        }

    # ------------------------------------------------------------------ 鉴权

    def _get_ocr(self):
        if self._ocr is None:
            if ddddocr is None:
                raise ZhlszAuthError("未安装 ddddocr（uv pip install ddddocr），无法自动识别验证码")
            self._ocr = ddddocr.DdddOcr(show_ad=False)
        return self._ocr

    def _get_captcha(self) -> tuple[str, str]:
        """获取验证码并 OCR 识别，返回 (验证码文本, uuid)。识别质量差自动换图重试。"""
        ocr = self._get_ocr()
        last_error: Optional[Exception] = None
        for attempt in range(1, MAX_CAPTCHA_RETRY + 1):
            resp = self.session.get(f"{self.base_url}/api/User/getVierificationCode",
                                    headers=self._common_headers, timeout=15)
            resp.raise_for_status()
            payload = resp.json()
            png = base64.b64decode(payload["img"])
            text = ocr.classification(png).strip()
            if len(text) == 4 and text.isascii() and text.isalnum():
                return text, payload["uuid"]
            last_error = ValueError(f"验证码识别结果不合规: {text!r}")
        raise ZhlszAuthError(f"验证码连续 {MAX_CAPTCHA_RETRY} 次识别失败，最后一次: {last_error}")

    def login(self, force: bool = False) -> str:
        """登录获取 JWT。已持有未过期 token 时直接复用（force=True 强制重登）。"""
        if self._token and not force and time.time() < self._token_expire_at - 60:
            return self._token

        for attempt in range(1, MAX_CAPTCHA_RETRY + 1):
            code, uuid = self._get_captcha()
            resp = self.session.post(
                f"{self.base_url}/api/user/login",
                headers={**self._common_headers, "Content-Type": "application/json;charset=UTF-8"},
                json={
                    "userName": self.account,
                    "password": self.password,
                    "verificationCode": code,
                    "UUID": uuid,
                },
                timeout=15,
            )
            resp.raise_for_status()
            result = resp.json()
            token = (result.get("data") or {}).get("token")
            if result.get("status") and token:
                self._set_token(token)
                return token
            # code=320 等视为验证码/凭证可重试错误；其余直接终止
            if result.get("code") not in ("320", None):
                raise ZhlszAuthError(f"登录被拒绝: code={result.get('code')}, message={result.get('message')}")
        raise ZhlszAuthError(f"连续 {MAX_CAPTCHA_RETRY} 次登录失败")

    def _set_token(self, token: str) -> None:
        """保存 token 并解析 JWT payload 中的 exp（秒级 unix 时间）。"""
        self._token = token
        try:
            payload_b64 = token.split(".")[1]
            payload_b64 += "=" * (-len(payload_b64) % 4)  # 补齐 base64url padding
            payload = __import__("json").loads(base64.urlsafe_b64decode(payload_b64))
            exp = payload.get("exp")
            self._token_expire_at = float(exp) if exp else time.time() + 7200
        except Exception:
            self._token_expire_at = time.time() + 7200  # 解析失败按 2 小时兜底

    def _auth_headers(self) -> Dict[str, str]:
        return {**self._common_headers, "Authorization": f"Bearer {self.login()}"}

    # ------------------------------------------------------------------ 请求

    def request(self, method: str, path: str, *, retry_on_unauthorized: bool = True,
                **kwargs: Any) -> requests.Response:
        """带鉴权的通用请求。path 以 / 开头（如 /api/memberinfo/getPageData）。"""
        if not path.startswith("/"):
            path = "/" + path
        resp = self.session.request(method, self.base_url + path,
                                    headers=self._auth_headers(), timeout=30, **kwargs)
        if resp.status_code == 401 and retry_on_unauthorized and RELOGIN_ON_UNAUTHORIZED:
            self.login(force=True)  # token 失效，强制重登后重试一次
            resp = self.session.request(method, self.base_url + path,
                                        headers=self._auth_headers(), timeout=30, **kwargs)
        return resp

    def get(self, path: str, params: Optional[Dict[str, Any]] = None, **kwargs: Any) -> requests.Response:
        return self.request("GET", path, params=params, **kwargs)

    def post(self, path: str, json: Any = None, **kwargs: Any) -> requests.Response:
        return self.request("POST", path, json=json, **kwargs)

    # -------------------------------------------------------------- 业务便捷方法

    def get_page(self, table: str, page: int = 1, rows: int = 20,
                 sort: Optional[str] = None, order: str = "desc",
                 wheres: Optional[List[Dict[str, Any]]] = None, **extra: Any) -> Dict[str, Any]:
        """通用分页查询：POST /api/<table>/getPageData。

        wheres 为条件数组，元素形如 {"name": "OrderStatus", "value": "1"}，支持模糊：
        {"name": "RealName", "value": "张"}（服务端按列名生成 where）。
        返回 {status, total, rows, summary, ...}。
        """
        body: Dict[str, Any] = {
            "page": page,
            "rows": rows,
            "order": order,
            # 服务端要求 wheres 为 JSON 字符串（浏览器抓包为 "[]" 或 "[{...}]"）
            "wheres": json.dumps(wheres or [], ensure_ascii=False),
        }
        if sort:
            body["sort"] = sort
        body.update(extra)
        resp = self.post(f"/api/{table}/getPageData", json=body)
        resp.raise_for_status()
        return resp.json()

    def get_dict(self, dic_nos: List[str]) -> Dict[str, Any]:
        """批量获取数据字典：POST /api/Sys_Dictionary/GetVueDictionary。"""
        resp = self.post("/api/Sys_Dictionary/GetVueDictionary", json=dic_nos)
        resp.raise_for_status()
        return {item.get("dicNo"): item for item in resp.json()}

    def get_current_user(self) -> Dict[str, Any]:
        """当前登录用户信息。"""
        resp = self.post("/api/user/GetCurrentUserInfo")
        resp.raise_for_status()
        return resp.json().get("data") or {}


if __name__ == "__main__":
    import io
    import sys
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    client = ZhlszClient()
    print("当前用户:", client.get_current_user())
    data = client.get_page("memberinfo", page=1, rows=3)
    print(f"memberinfo total={data.get('total')}, 本页行数={len(data.get('rows') or [])}")
