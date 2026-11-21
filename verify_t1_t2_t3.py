# -*- coding: utf-8 -*-
"""PRD v0.3 遗留问题 T1/T2/T3 实测脚本。

T1 分页上限与限频：探测 getPageData 的 rows 上限 + 连续请求测 QPS/是否被限流
T2 登录稳定性：连续多次走完整登录流程（验证码 OCR），统计成功率与重试次数
T3 手机号质量：全量拉取 memberinfo，检查 Mobile 为空/重复情况

输出：控制台报告（UTF-8）。
"""
from __future__ import annotations

import io
import sys
import time
from concurrent.futures import ThreadPoolExecutor

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from zhlsz_client import ZhlszClient, ZhlszAuthError

PROBE_ROWS = [100, 200, 500, 1000, 2000, 5000, 10000]
QPS_BURST = 15          # 顺序小请求次数
CONCURRENT = 5          # 并发线程数（克制）
LOGIN_ROUNDS = 5        # 登录稳定性轮数
PAGE_DELAY = 0.2        # 全量拉取时的页间隔（秒）


def hr(title: str) -> None:
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)


# ---------------------------------------------------------------- T2 登录稳定性
def verify_login_stability(client: ZhlszClient) -> None:
    hr(f"T2 登录稳定性（{LOGIN_ROUNDS} 轮完整登录，含验证码 OCR）")
    ok, fail, attempts_list, durations = 0, 0, [], []
    for i in range(1, LOGIN_ROUNDS + 1):
        start = time.perf_counter()
        # 通过重置内部状态强制走完整登录（验证码+提交）
        client._token = None
        client._token_expire_at = 0.0
        try:
            client.login(force=True)
            dur = time.perf_counter() - start
            durations.append(dur)
            print(f"  第 {i} 轮: 成功  耗时 {dur:.1f}s")
            ok += 1
        except ZhlszAuthError as e:
            print(f"  第 {i} 轮: 失败  {e}")
            fail += 1
        time.sleep(1)
    print(f"\n  结果: {ok}/{LOGIN_ROUNDS} 成功"
          + (f"，平均耗时 {sum(durations)/len(durations):.1f}s，单轮 {min(durations):.1f}~{max(durations):.1f}s"
             if durations else ""))
    if ok < LOGIN_ROUNDS:
        print("  ⚠️ 存在失败轮次：需调大 MAX_CAPTCHA_RETRY 或检查 OCR")


# ---------------------------------------------------------------- T1 分页上限
def probe_rows_limit(client: ZhlszClient) -> int:
    """探测 rows 上限，返回确认可用的最大单页行数。"""
    hr(f"T1-a 分页上限探测 rows={PROBE_ROWS}")
    usable = 20
    for rows in PROBE_ROWS:
        try:
            start = time.perf_counter()
            data = client.get_page("memberinfo", page=1, rows=rows, sort="MemID", order="asc")
            got = len(data.get("rows") or [])
            dur = time.perf_counter() - start
            verdict = "✅ 足额返回" if got >= rows else (f"⚠️ 截断为 {got}" if got < rows else "空")
            print(f"  rows={rows:>6}: 返回 {got:>6} 行  {dur:.2f}s  {verdict}")
            if got >= rows:
                usable = rows
            else:
                print(f"  → 服务端在 rows={rows} 处截断，可用上限取 {usable}")
                break
        except Exception as e:
            print(f"  rows={rows:>6}: 请求异常 {type(e).__name__}: {e}")
            break
        time.sleep(0.3)
    print(f"\n  结论：确认可用单页行数 = {usable}")
    return usable


# ---------------------------------------------------------------- T1 限频
def probe_qps(client: ZhlszClient) -> None:
    hr(f"T1-b 限频探测：顺序 {QPS_BURST} 次小请求 + {CONCURRENT} 线程并发 1 轮")
    latencies, errors = [], 0
    for i in range(QPS_BURST):
        start = time.perf_counter()
        try:
            resp = client.get_page("memberinfo", page=1, rows=10)
            assert resp.get("status") == 0 or resp.get("rows") is not None
            latencies.append(time.perf_counter() - start)
        except Exception as e:
            errors += 1
            print(f"  顺序第 {i+1} 次: 异常 {type(e).__name__}: {e}")
    if latencies:
        seq_qps = len(latencies) / sum(latencies)
        print(f"  顺序: {len(latencies)}/{QPS_BURST} 成功, "
              f"平均 {sum(latencies)/len(latencies):.2f}s, 等效 QPS≈{seq_qps:.1f}")

    def one(_: int) -> float:
        s = time.perf_counter()
        client.get_page("memberinfo", page=1, rows=10)
        return time.perf_counter() - s

    with ThreadPoolExecutor(max_workers=CONCURRENT) as pool:
        results = list(pool.map(one, range(CONCURRENT)))
    print(f"  并发{CONCURRENT}: 全部成功, 平均 {sum(results)/len(results):.2f}s, "
          f"峰值 {max(results):.2f}s")
    if errors == 0:
        print("  → 未观察到限流/封禁（本账号当前无 QPS 硬限制或阈值高于本次压力）")
    else:
        print("  → ⚠️ 出现异常，存在限流迹象，爬虫需按 ≤2 QPS 保守限频")


# ---------------------------------------------------------------- T3 手机号质量
def verify_phone_quality(client: ZhlszClient, page_size: int) -> None:
    hr(f"T3 全量 memberinfo 手机号质量检查（每页 {page_size} 行）")
    members: dict[int, tuple[str, str]] = {}
    page, total = 1, None
    start = time.perf_counter()
    while True:
        data = client.get_page("memberinfo", page=page, rows=page_size,
                               sort="MemID", order="asc")
        rows = data.get("rows") or []
        if total is None:
            total = data.get("total")
        if not rows:
            break
        for r in rows:
            members[int(r["MemID"])] = (
                (r.get("Mobile") or "").strip(),
                (r.get("AnotherPhone") or "").strip(),
            )
        if len(members) >= (total or 0):
            break
        page += 1
        time.sleep(PAGE_DELAY)

    dur = time.perf_counter() - start
    print(f"  拉取完成: {len(members)}/{total} 名会员, {dur:.0f}s, "
          f"{page} 页 × {page_size} 行")

    empty = [mid for mid, (m, _) in members.items() if not m]
    by_phone: dict[str, list[int]] = {}
    for mid, (m, _) in members.items():
        if m:
            by_phone.setdefault(m, []).append(mid)
    dup = {p: ids for p, ids in by_phone.items() if len(ids) > 1}
    # 手机号与 MemberList 匹配相关的第二手机号
    empty2 = sum(1 for _, (m, a) in members.items() if m and not a)

    print(f"\n  Mobile 为空: {len(empty)} / {len(members)}"
          f"（{len(empty)/len(members)*100:.1f}%）")
    if empty:
        print(f"    样例 MemID: {empty[:10]}")
    print(f"  Mobile 重复: {len(dup)} 个号码被多个会员共用，涉及 "
          f"{sum(len(v) for v in dup.values())} 名会员")
    for p, ids in list(dup.items())[:5]:
        print(f"    {p} -> MemID {ids}")
    print(f"  已填 Mobile 的会员中 AnotherPhone 为空: {empty2}")


def main() -> None:
    client = ZhlszClient()
    print("PRD T1/T2/T3 验证开始，目标:", client.base_url)
    verify_login_stability(client)
    page_size = probe_rows_limit(client)
    probe_qps(client)
    verify_phone_quality(client, page_size)
    hr("验证结束")


if __name__ == "__main__":
    main()
