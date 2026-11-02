#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""三段样例对话，用来验证账本内核的行为是否符合预期。

样例一：一次完整的建模对话，从登记到交付门禁，再到前提被撤回后的级联。
样例二：带替代支撑的精确级联——撤回同一前提，结论降级而不死。
样例三：一次把六类病全犯一遍，看 check 能不能全部抓到。

用法：python examples/demo.py
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LEDGER = os.path.join(ROOT, "scripts", "ledger.py")
OUT = os.path.join(HERE, "_out")


def fresh(name):
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, name)
    if os.path.exists(path):
        os.remove(path)
    return path


def banner(text):
    print("\n" + "=" * 72)
    print(text)
    print("=" * 72)


def step(path, *args):
    proc = subprocess.run(
        [sys.executable, LEDGER, "--ledger", path, *args],
        capture_output=True, text=True, encoding="utf-8",
    )
    body = (proc.stdout or "").strip()
    if proc.stderr.strip():
        body += "\n" + proc.stderr.strip()
    print("\n$ ledger " + " ".join(args))
    print(body)
    print(f"[exit={proc.returncode}]")
    return proc.returncode, body


def demo_one():
    banner("样例一 · 某市供水规模测算：登记 → 门禁 → 核验 → 撤回 → 级联")
    led = fresh("demo1.json")

    step(led, "new", "--task", "某市供水规模测算")
    step(led, "add-premise", "--text", "人均综合用水 150 L/(人·天)",
         "--symbol", "percapita", "--value", "150", "--unit", "L/(人·天)",
         "--conf", "0.9", "--src", "spec", "--turn", "1")
    step(led, "add-premise", "--text", "常住人口 800 万",
         "--symbol", "population", "--value", "8000000", "--unit", "人",
         "--conf", "0.4", "--src", "用户口述", "--turn", "2")
    step(led, "add-premise", "--text", "管网漏损率 10%",
         "--symbol", "loss", "--value", "0.1", "--unit", "-",
         "--conf", "0.6", "--src", "estimate", "--turn", "2")
    step(led, "add-claim", "--text", "日需水量 ≈120 万吨",
         "--symbol", "demand", "--value", "1200000", "--unit", "吨/天",
         "--inputs", "percapita,population", "--turn", "3")
    step(led, "add-claim", "--text", "年供水量 ≈4.9 亿吨",
         "--symbol", "supply", "--value", "490000000", "--unit", "吨/年",
         "--inputs", "demand,loss", "--turn", "4", "--exported")

    print("\n--- 交付前体检：应当被门禁拦下（A2 未核验）---")
    step(led, "check")

    print("\n--- 这张卡片就是 agent 可以引用的话 ---")
    step(led, "cite", "--id", "C2")

    print("\n--- 三条前提逐一核验之后，门禁应当放行 ---")
    step(led, "verify", "--id", "A2", "--evidence", "《2025 统计年鉴》表 3-1", "--turn", "6")
    step(led, "verify", "--id", "A1", "--evidence", "《室外给水设计标准》GB 50013", "--turn", "6")
    step(led, "verify", "--id", "A3", "--evidence", "供水公司 2025 年漏损报告", "--turn", "7")
    step(led, "check")

    print("\n--- 第 9 轮用户改了口径：A2 作废，看级联 ---")
    step(led, "retract", "--id", "A2", "--reason", "人口口径改为常住半年以上", "--turn", "9")
    step(led, "check")
    step(led, "export", "--format", "md")


def demo_two():
    banner("样例二 · 有替代支撑时，同一个撤回不该把结论全杀死")
    led = fresh("demo2.json")

    step(led, "new", "--task", "供水测算（含备用人口来源）")
    step(led, "add-premise", "--text", "人均综合用水 150 L/(人·天)", "--symbol", "percapita",
         "--value", "150", "--unit", "L/(人·天)", "--conf", "0.9", "--src", "spec", "--turn", "1")
    step(led, "add-premise", "--text", "常住人口 800 万（口述）", "--symbol", "population",
         "--value", "8000000", "--unit", "人", "--conf", "0.4", "--src", "用户口述", "--turn", "2")
    step(led, "add-premise", "--text", "物业实测服务人口 780 万", "--symbol", "population_measured",
         "--value", "7800000", "--unit", "人", "--conf", "0.9", "--src", "measured", "--turn", "5")
    step(led, "add-premise", "--text", "管网漏损率 10%", "--symbol", "loss",
         "--value", "0.1", "--unit", "-", "--conf", "0.6", "--src", "estimate", "--turn", "2")

    print("\n--- C1 的必需依赖是 A1+A2，但另有替代组 A1+A4 ---")
    step(led, "add-claim", "--text", "日需水量 ≈120 万吨", "--symbol", "demand",
         "--value", "1200000", "--unit", "吨/天",
         "--inputs", "percapita,population", "--alts", "A1,A4", "--turn", "3")
    step(led, "add-claim", "--text", "年供水量 ≈4.9 亿吨", "--symbol", "supply",
         "--value", "490000000", "--unit", "吨/年",
         "--inputs", "demand,loss", "--turn", "4")

    print("\n--- 四条前提全部核验：C1、C2 应当是 active ---")
    step(led, "verify", "--id", "A1", "--evidence", "设计标准", "--turn", "5")
    step(led, "verify", "--id", "A2", "--evidence", "统计年鉴", "--turn", "5")
    step(led, "verify", "--id", "A3", "--evidence", "漏损报告", "--turn", "5")
    step(led, "verify", "--id", "A4", "--evidence", "物业 2025 年度报表", "--turn", "5")
    step(led, "check")

    print("\n--- 撤回 A2：C1 走替代支撑降级存活，不被杀死 ---")
    step(led, "retract", "--id", "A2", "--reason", "口述数据不可靠", "--turn", "7")
    step(led, "check")
    step(led, "cite", "--id", "C2")


def demo_three():
    banner("样例三 · 把六类病全犯一遍，看 check 能不能一网打尽")
    led = fresh("demo3.json")

    step(led, "new", "--task", "病态账本（测试用例）")
    step(led, "add-premise", "--text", "常住人口 800 万", "--symbol", "population",
         "--value", "8000000", "--unit", "人", "--turn", "1")
    step(led, "add-premise", "--text", "常住人口 900 万", "--symbol", "population",
         "--value", "9000000", "--unit", "人", "--turn", "4")
    step(led, "add-premise", "--text", "漏损率 10%", "--symbol", "loss",
         "--value", "0.1", "--unit", "-", "--turn", "2")

    step(led, "add-claim", "--text", "这个结论没有任何前提支撑")
    step(led, "add-claim", "--text", "用了一个没人提供的量", "--inputs", "ghost_symbol")
    step(led, "add-claim", "--text", "引用了不存在的条目", "--depends", "A99")
    step(led, "add-claim", "--text", "甲结论靠乙结论", "--symbol", "cyc_a", "--depends", "C5")
    step(led, "add-claim", "--text", "乙结论靠甲结论", "--symbol", "cyc_b", "--depends", "C4")
    step(led, "add-claim", "--text", "依赖漏损率的结论", "--symbol", "with_loss",
         "--inputs", "loss")

    print("\n--- 让一条前提失效，制造污染传播 ---")
    step(led, "retract", "--id", "A3", "--reason", "数据源撤销", "--turn", "8")

    print("\n--- 全量体检：应当同时抓到六类 ---")
    code, body = step(led, "check")
    print("\n捕获到的病种：")
    for label in ["孤儿结论", "孤儿输入", "幽灵引用", "循环论证", "污染传播", "前提漂移"]:
        print(f"  {'命中' if label in body else '漏检'}  {label}")


def main():
    print(f"内核：{LEDGER}")
    print(f"解释器：{sys.executable}")
    demo_one()
    demo_two()
    demo_three()
    print("\n全部样例执行完毕。")


if __name__ == "__main__":
    main()
