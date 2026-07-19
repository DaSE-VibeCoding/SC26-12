from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MetricDefinition:
    metric_id: str
    label: str
    short_label: str
    kind: str
    aliases: tuple[str, ...]


# Longer, more specific labels are matched before shorter labels in parser.py.
METRICS: tuple[MetricDefinition, ...] = (
    MetricDefinition(
        "deducted_roe",
        "扣除非经常性损益后的加权平均净资产收益率（%）",
        "扣非加权平均ROE",
        "percent",
        (
            "扣除非经常性损益后的加权平均净资产收益率",
            "扣除非经常损益后的加权平均净资产收益率",
        ),
    ),
    MetricDefinition(
        "deducted_eps",
        "扣除非经常性损益后的基本每股收益（元／股）",
        "扣非基本每股收益",
        "eps",
        (
            "扣除非经常性损益后的基本每股收益",
            "扣除非经常损益后的基本每股收益",
        ),
    ),
    MetricDefinition(
        "deducted_net_profit",
        "归属于上市公司股东的扣除非经常性损益的净利润",
        "扣非归母净利润",
        "amount",
        (
            "归属于上市公司股东的扣除非经常性损益的净利润",
            "归属于母公司股东的扣除非经常性损益的净利润",
            "归属于母公司所有者的扣除非经常性损益的净利润",
            "扣除非经常性损益后归属于母公司股东的净利润",
        ),
    ),
    MetricDefinition(
        "operating_cash_flow",
        "经营活动产生的现金流量净额",
        "经营现金流净额",
        "amount",
        ("经营活动产生的现金流量净额", "经营活动现金流量净额"),
    ),
    MetricDefinition(
        "net_assets",
        "归属于上市公司股东的净资产",
        "归母净资产",
        "amount",
        (
            "归属于上市公司股东的净资产",
            "归属于母公司股东的净资产",
            "归属于母公司所有者的净资产",
            "归属于上市公司股东的所有者权益",
        ),
    ),
    MetricDefinition(
        "net_profit",
        "归属于上市公司股东的净利润",
        "归母净利润",
        "amount",
        (
            "归属于上市公司股东的净利润",
            "归属于母公司股东的净利润",
            "归属于母公司所有者的净利润",
        ),
    ),
    MetricDefinition(
        "diluted_eps",
        "稀释每股收益（元／股）",
        "稀释每股收益",
        "eps",
        ("稀释每股收益",),
    ),
    MetricDefinition(
        "basic_eps",
        "基本每股收益（元／股）",
        "基本每股收益",
        "eps",
        ("基本每股收益",),
    ),
    MetricDefinition(
        "roe",
        "加权平均净资产收益率（%）",
        "加权平均ROE",
        "percent",
        ("加权平均净资产收益率",),
    ),
    MetricDefinition(
        "profit_total",
        "利润总额",
        "利润总额",
        "amount",
        ("利润总额",),
    ),
    MetricDefinition(
        "total_assets",
        "总资产",
        "总资产",
        "amount",
        ("资产总额", "总资产"),
    ),
    MetricDefinition(
        "share_capital",
        "股本",
        "股本",
        "amount",
        ("股本", "实收资本（或股本）", "实收资本或股本"),
    ),
    MetricDefinition(
        "revenue",
        "营业收入",
        "营业收入",
        "amount",
        ("营业收入", "营业总收入"),
    ),
)

METRIC_BY_ID = {metric.metric_id: metric for metric in METRICS}

SUPPORTED_YEAR_MIN = 2021
SUPPORTED_YEAR_MAX = 2026

# Annual-report templates do not use one uniform heading.  Some issuers use
# “近三年主要会计数据和财务指标”, while Shenzhen-style reports commonly use
# “主要会计数据和财务指标”.  The latter is the stable common substring.
SUMMARY_HEADING = "主要会计数据和财务指标"

UNIT_MULTIPLIERS = {
    "元": 1,
    "千元": 1_000,
    "万元": 10_000,
    "百万元": 1_000_000,
    "亿元": 100_000_000,
}
