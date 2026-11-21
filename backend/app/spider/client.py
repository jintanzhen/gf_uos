# -*- coding: utf-8 -*-
"""绿手指（zhlsz.cn）爬取客户端：由根目录 zhlsz_client.py 改造为 spider 模块。

在原验证客户端基础上增加（F1-09 爬取健壮性）：
- 限频：请求间最小间隔（默认 0.6s ≈ 1.7 QPS，符合 PRD 保守限频要求）
- 重试：网络异常/5xx 指数退避重试 3 次
- 分页遍历器：iter_page_rows() 自动翻页，支持按 ModifyDate 游标提前停止（增量同步）
"""
from __future__ import annotations

import base64
import json
import logging
import os
import time
from typing import Any, Callable, Dict, Iterator, List, Optional

import requests
from dotenv import load_dotenv

try:
    import ddddocr
except ImportError:  # pragma: no cover
    ddddocr = None

load_dotenv()

logger = logging.getLogger("greenos.spider")

MAX_CAPTCHA_RETRY = 5
DEFAULT_MIN_INTERVAL = 0.6  # 秒，限频间隔（PRD：1~2 QPS 保守值）
HTTP_RETRIES = 3
RETRY_BACKOFF_SECONDS = 2.0


class ZhlszAuthError(RuntimeError):
    """登录/鉴权相关异常。"""


class ZhlszRemoteError(RuntimeError):
    """重试后仍失败的业务/网络异常。"""


class ZhlszClient:
    """封装登录、凭证持有、限频与带鉴权请求的客户端。

    - JWT token 实例内持有，过期前（提前 60s）自动刷新；401 自动重登重试一次
    - 验证码用 ddddocr 本地 OCR，识别失败自动换图重试
    - 所有请求经 _throttle() 限频
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        account: Optional[str] = None,
        password: Optional[str] = None,
        min_interval: float = DEFAULT_MIN_INTERVAL,
    ) -> None:
        self.base_url = (base_url or os.getenv("ZHLSZ_BASE_URL", "https://www.zhlsz.cn")).rstrip("/")
        self.account = account or os.getenv("ZHLSZ_ACCOUNT")
        self.password = password or os.getenv("ZHLSZ_PASSWORD")
        if not self.account or not self.password:
            raise ZhlszAuthError("缺少账号/密码：请配置 .env（ZHLSZ_ACCOUNT / ZHLSZ_PASSWORD）或传参")

        self.min_interval = min_interval
        self._last_request_at = 0.0

        self.session = requests.Session()
        self._token: Optional[str] = None
        self._token_expire_at: float = 0.0
        self._ocr: Optional[Any] = None
        self._common_headers = {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "lang": "zh-cn",
            "Referer": self.base_url + "/",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        }

    # ------------------------------------------------------------------ 限频

    def _throttle(self) -> None:
        elapsed = time.time() - self._last_request_at
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self._last_request_at = time.time()

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
        for _attempt in range(1, MAX_CAPTCHA_RETRY + 1):
            self._throttle()
            resp = self.session.get(
                f"{self.base_url}/api/User/getVierificationCode",
                headers=self._common_headers, timeout=15,
            )
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
            self._throttle()
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
                logger.info("zhlsz login ok (attempt=%d)", attempt)
                return token
            if result.get("code") not in ("320", None):
                raise ZhlszAuthError(
                    f"登录被拒绝: code={result.get('code')}, message={result.get('message')}"
                )
        raise ZhlszAuthError(f"连续 {MAX_CAPTCHA_RETRY} 次登录失败")

    def _set_token(self, token: str) -> None:
        self._token = token
        try:
            payload_b64 = token.split(".")[1]
            payload_b64 += "=" * (-len(payload_b64) % 4)
            payload = json.loads(base64.urlsafe_b64decode(payload_b64))
            exp = payload.get("exp")
            self._token_expire_at = float(exp) if exp else time.time() + 7200
        except Exception:
            self._token_expire_at = time.time() + 7200

    def _auth_headers(self) -> Dict[str, str]:
        return {**self._common_headers, "Authorization": f"Bearer {self.login()}"}

    # ------------------------------------------------------------------ 请求

    def request(self, method: str, path: str, *, retry_on_unauthorized: bool = True,
                **kwargs: Any) -> requests.Response:
        """带鉴权、限频、重试的通用请求。path 以 / 开头。"""
        if not path.startswith("/"):
            path = "/" + path

        last_exc: Optional[Exception] = None
        for attempt in range(1, HTTP_RETRIES + 1):
            self._throttle()
            try:
                resp = self.session.request(
                    method, self.base_url + path,
                    headers=self._auth_headers(), timeout=60, **kwargs,
                )
            except requests.RequestException as exc:
                last_exc = exc
                logger.warning("request %s %s failed (attempt %d/%d): %s",
                               method, path, attempt, HTTP_RETRIES, exc)
                time.sleep(RETRY_BACKOFF_SECONDS * (2 ** (attempt - 1)))
                continue
            if resp.status_code == 401 and retry_on_unauthorized:
                self.login(force=True)
                continue  # 重登后下一轮重试
            if resp.status_code >= 500:
                last_exc = ZhlszRemoteError(f"{method} {path} -> HTTP {resp.status_code}")
                logger.warning("server error %s %s (attempt %d/%d)",
                               method, path, attempt, HTTP_RETRIES)
                time.sleep(RETRY_BACKOFF_SECONDS * (2 ** (attempt - 1)))
                continue
            return resp
        raise ZhlszRemoteError(f"{method} {path} 重试 {HTTP_RETRIES} 次后仍失败: {last_exc}")

    def get(self, path: str, params: Optional[Dict[str, Any]] = None, **kwargs: Any) -> requests.Response:
        return self.request("GET", path, params=params, **kwargs)

    def post(self, path: str, json: Any = None, **kwargs: Any) -> requests.Response:
        return self.request("POST", path, json=json, **kwargs)

    # -------------------------------------------------------------- 业务便捷方法

    def get_page(self, table: str, page: int = 1, rows: int = 20,
                 sort: Optional[str] = None, order: str = "desc",
                 wheres: Optional[List[Dict[str, Any]]] = None, **extra: Any) -> Dict[str, Any]:
        """通用分页查询：POST /api/<table>/getPageData。返回 {status, total, rows, ...}。"""
        body: Dict[str, Any] = {
            "page": page,
            "rows": rows,
            "order": order,
            "wheres": json.dumps(wheres or [], ensure_ascii=False),
        }
        if sort:
            body["sort"] = sort
        body.update(extra)
        resp = self.post(f"/api/{table}/getPageData", json=body)
        resp.raise_for_status()
        return resp.json()

    def iter_page_rows(
        self,
        table: str,
        *,
        page_size: int = 5000,
        sort: Optional[str] = None,
        order: str = "desc",
        wheres: Optional[List[Dict[str, Any]]] = None,
        stop_when: Optional[Callable[[Dict[str, Any]], bool]] = None,
        max_rows: Optional[int] = None,
    ) -> Iterator[Dict[str, Any]]:
        """自动翻页遍历器（断点续传友好的拉取层）。

        stop_when: 回调 fn(row) -> bool，为 True 时停止拉取后续页（用于 ModifyDate 游标增量）。
        max_rows: 保险丝，超过即停止并告警。
        """
        first = self.get_page(table, page=1, rows=page_size, sort=sort, order=order, wheres=wheres)
        total = int(first.get("total") or 0)
        rows: List[Dict[str, Any]] = first.get("rows") or []
        logger.info("pull %s: total=%d page_size=%d", table, total, page_size)

        yielded = 0
        page = 1
        while True:
            for row in rows:
                if stop_when is not None and stop_when(row):
                    logger.info("pull %s: stop_when hit after %d rows (incremental)", table, yielded)
                    return
                yield row
                yielded += 1
                if max_rows is not None and yielded >= max_rows:
                    logger.warning("pull %s: max_rows=%d reached", table, max_rows)
                    return
            if not rows:
                return
            if len(rows) < page_size and page > 1:
                return  # 已到末页
            page += 1
            if page * page_size > total + page_size:  # 超出总数兜底
                return
            data = self.get_page(table, page=page, rows=page_size, sort=sort, order=order, wheres=wheres)
            rows = data.get("rows") or []

    def get_dict(self, dic_nos: List[str]) -> Dict[str, Any]:
        """批量获取数据字典：POST /api/Sys_Dictionary/GetVueDictionary。"""
        resp = self.post("/api/Sys_Dictionary/GetVueDictionary", json=dic_nos)
        resp.raise_for_status()
        return {item.get("dicNo"): item for item in resp.json()}

    def get_current_user(self) -> Dict[str, Any]:
        resp = self.post("/api/user/GetCurrentUserInfo")
        resp.raise_for_status()
        return resp.json().get("data") or {}
