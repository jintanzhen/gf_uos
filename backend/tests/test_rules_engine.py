# -*- coding: utf-8 -*-
"""规则引擎单测：条件树求值 / 模板渲染 / 分流稳定性。"""
import pytest

from app.rules.evaluator import ConditionError, evaluate_tree, validate_tree
from app.rules.renderer import render
from app.rules.scanner import assign_group


def test_and_or_nesting():
    tree = {"logic": "and", "conditions": [
        {"field": "remain_times", "op": "lte", "value": 4},
        {"logic": "or", "conditions": [
            {"field": "share_type", "op": "eq", "value": "shucai"},
            {"field": "good_name", "op": "contains", "value": "蔬菜"},
        ]},
    ]}
    validate_tree(tree)
    hit_shucai = {"remain_times": 4, "share_type": "doufu",
                  "good_name": "有机蔬菜份额", "tag_keys": set()}
    miss = {"remain_times": 9, "share_type": "doufu",
            "good_name": "豆腐份额", "tag_keys": set()}
    assert evaluate_tree(tree, hit_shucai) is True
    assert evaluate_tree(tree, miss) is False


def test_missing_data_not_matched():
    tree = {"logic": "and", "conditions": [{"field": "remain_times", "op": "lte", "value": 4}]}
    assert evaluate_tree(tree, {"remain_times": None, "tag_keys": set()}) is False


def test_validate_errors():
    with pytest.raises(ConditionError):
        validate_tree({"logic": "and", "conditions": [{"field": "bad", "op": "eq", "value": 1}]})
    with pytest.raises(ConditionError):
        validate_tree({"logic": "and", "conditions": [{"field": "remain_times", "op": "like", "value": 1}]})
    # 三层嵌套拒绝
    deep = {"logic": "and", "conditions": [{"logic": "or", "conditions": [
        {"logic": "and", "conditions": [{"field": "remain_times", "op": "eq", "value": 1}]}]}]}
    with pytest.raises(ConditionError):
        validate_tree(deep)


def test_register_days_and_tag():
    tree = {"logic": "and", "conditions": [
        {"field": "register_days", "op": "gte", "value": 90},
        {"field": "tag", "op": "has", "value": "vip"},
    ]}
    assert evaluate_tree(tree, {"register_days": 100, "tag_keys": {"vip"}}) is True
    assert evaluate_tree(tree, {"register_days": 10, "tag_keys": {"vip"}}) is False
    assert evaluate_tree(tree, {"register_days": 100, "tag_keys": set()}) is False


class _M:
    nickname = None
    real_name = "王女士"


class _S:
    share_type = "shucai"
    good_name = "春季蔬菜份额"
    remain_times = 4
    total_cnt = 12
    cycle_desc = "每周三配送"


class _C:
    name = "车厘子"
    qrcode_url = "https://img/q.png"


def test_render_all_variables():
    template = "{会员昵称}您好，我是{客服名}。您的{份额类型}（{商品名}）还剩{剩余次数}/{总次数}次，{配送周期}，{续订权益}"
    text, missing = render(template, member=_M(), share=_S(), cs=_C(), benefit_text="续订立减30元")
    assert "王女士您好" in text
    assert "车厘子" in text and "蔬菜份额" in text and "4/12" in text
    assert "每周三配送" in text and "续订立减30元" in text
    assert missing == []


def test_render_missing_warns_not_blocks():
    text, missing = render("{商品名}{客服二维码}", member=_M(), share=_S(), cs=None)
    assert "春季蔬菜份额" in text  # 有值变量正常渲染
    assert set(missing) == {"客服二维码"}


def test_assign_group_stable():
    """BR-11：同 member+rule 分组永久不变；ratio=0 全实验组，100 全对照组。"""
    g1 = assign_group(12345, 7, 20)
    for _ in range(20):
        assert assign_group(12345, 7, 20) == g1
    assert assign_group(1, 1, 0) == "exp"
    assert assign_group(1, 1, 100) == "ctrl"
