# -*- coding: utf-8 -*-
"""规则引擎：两层嵌套条件树（ADR-5）的校验与求值。

条件树 JSON（PRD 5.4.1，AND/OR 两层嵌套）::

    {"logic": "and", "conditions": [
        {"field": "remain_times", "op": "lte", "value": 4},
        {"logic": "or", "conditions": [...]}
    ]}

求值主体 = 会员 x 份额明细。字段：remain_times / share_type /
order_status / good_name / tag / cs_id / register_days。
（「近 N 天未下单」依赖订单支付时间，ext_order 暂未同步，M2 不支持）
"""
from __future__ import annotations

from typing import Any, Optional

FIELDS: dict[str, frozenset[str]] = {
    "remain_times": frozenset({"eq", "ne", "lte", "gte", "between", "in"}),
    "share_type": frozenset({"eq", "ne", "in"}),
    "order_status": frozenset({"eq", "ne", "in"}),
    "good_name": frozenset({"eq", "contains", "in"}),
    "tag": frozenset({"has"}),
    "cs_id": frozenset({"eq"}),
    "register_days": frozenset({"gte", "lte", "between"}),
}

MAX_DEPTH = 2  # 两层嵌套：根 + 一层子组


class ConditionError(ValueError):
    """条件树结构或取值非法。"""


def validate_tree(node: Any, depth: int = 1) -> None:
    """递归校验条件树结构；非法即抛 ConditionError。"""
    if not isinstance(node, dict):
        raise ConditionError("条件节点必须是对象")
    logic = node.get("logic")
    conditions = node.get("conditions")
    if logic not in ("and", "or"):
        raise ConditionError(f"logic 必须是 and/or，收到 {logic!r}")
    if not isinstance(conditions, list) or not conditions:
        raise ConditionError("conditions 必须是非空数组")
    if depth > MAX_DEPTH:
        raise ConditionError(f"条件嵌套最多 {MAX_DEPTH} 层（PRD 5.4.1）")
    for cond in conditions:
        if not isinstance(cond, dict):
            raise ConditionError("条件项必须是对象")
        if "logic" in cond:
            validate_tree(cond, depth + 1)
        else:
            field = cond.get("field")
            op = cond.get("op")
            if field not in FIELDS:
                raise ConditionError(f"不支持的条件字段: {field!r}（可选: {sorted(FIELDS)}）")
            if op not in FIELDS[field]:
                raise ConditionError(f"字段 {field} 不支持操作符 {op!r}（可选: {sorted(FIELDS[field])}）")
            if "value" not in cond:
                raise ConditionError(f"条件 {field} {op} 缺少 value")
            _check_value(field, op, cond["value"])


def _check_value(field: str, op: str, value: Any) -> None:
    if op == "between":
        if not (isinstance(value, list) and len(value) == 2):
            raise ConditionError("between 的 value 必须是 [min, max]")
        return
    if op == "in":
        if not isinstance(value, list) or not value:
            raise ConditionError("in 的 value 必须是非空数组")
        return
    if field in ("remain_times", "order_status", "cs_id", "register_days"):
        if not isinstance(value, (int, float)):
            raise ConditionError(f"字段 {field} 的 value 必须是数值")

def _as_int(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return None


def _match(op: str, actual: Any, expect: Any) -> bool:
    """单条件匹配；actual 为 None（数据缺失）一律不命中。"""
    if actual is None:
        return False
    if op == "eq":
        return actual == expect or str(actual) == str(expect)
    if op == "ne":
        return not (actual == expect or str(actual) == str(expect))
    if op == "lte":
        return actual <= expect
    if op == "gte":
        return actual >= expect
    if op == "between":
        return expect[0] <= actual <= expect[1]
    if op == "in":
        return any(actual == v or str(actual) == str(v) for v in expect)
    if op == "contains":
        return str(expect) in str(actual)
    if op == "has":
        return True  # 由调用方传入已解析的 tag 布尔值
    raise ConditionError(f"未知操作符: {op}")


def evaluate_tree(node: dict, ctx: dict[str, Any]) -> bool:
    """对 (会员 x 份额) 上下文求值。

    ctx 可用键：remain_times / share_type / order_status / good_name /
    cs_id / register_days / tag_keys(set[str])。
    """
    logic = node.get("logic")
    results = []
    for cond in node.get("conditions") or []:
        if "logic" in cond:
            results.append(evaluate_tree(cond, ctx))
            continue
        field = cond["field"]
        op = cond["op"]
        value = cond.get("value")
        if field == "tag":
            results.append(isinstance(ctx.get("tag_keys"), set) and str(value) in ctx["tag_keys"])
        elif field == "register_days":
            results.append(_match(op, ctx.get("register_days"), value))
        else:
            actual = _as_int(ctx.get(field)) if field in ("remain_times", "order_status", "cs_id") else ctx.get(field)
            results.append(_match(op, actual, value))
    if not results:
        return False
    return all(results) if logic == "and" else any(results)
