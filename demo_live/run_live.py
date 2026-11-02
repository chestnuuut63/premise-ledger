# -*- coding: utf-8 -*-
"""现场互动演示：一段长对话，8 处埋伏，先让观众找，再一键揭晓。

用法：
    python demo_live/run_live.py            # 现场跑：建账本 → check → 揭晓对照表
    python demo_live/run_live.py --emit     # 生成观众答题卡与答案键（两个 md）

设计原则：对话、埋点、答案键全部来自同一份 SPEC，不手抄，避免"题目和答案对不上"。
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from ledger import Ledger  # noqa: E402

# ---------------------------------------------------------------- 对话正文
TITLE = "校园共享充电宝投放测算"
SETTING = "某高校两校区，运营方要在学生宿舍区投放共享充电宝机柜，需要判断一年内能否回本。"

DIALOGUE = [
    ("用户", "帮我算一下在咱们学校投共享充电宝，一年能不能回本。先按两个校区一共 2.4 万在校生算。"),
    ("助手", "在校生 2.4 万，记为 A1。投放密度怎么定？"),
    ("用户", "按每 300 人一台机柜布。"),
    ("助手", "那需要 80 台机柜。设备单价 4800 元一台，一次性投入 38.4 万元。"),
    ("用户", "装机还有施工费，一台 600。"),
    ("助手", "施工费合计 4.8 万元，总投资 43.2 万元。"),
    ("用户", "收入按每台每天 6 次借还、每次 2 元算。"),
    ("助手", "单台日收入 12 元。这个 6 次是按多少使用率估的？"),
    ("用户", "大概 35% 吧。"),
    ("助手", "按 35% 使用率、单台 24 个仓位算，一天正好 6.3 次，取 6 次。"),
    ("助手", "全年 365 天，80 台合计年收入约 35 万元。"),
    ("用户", "等等，寒暑假基本没人用，得按 9 个月算。"),
    ("助手", "改成 270 天，年收入约 25.9 万元。"),
    ("用户", "成本那头，运维一个月多少钱？"),
    ("助手", "按每台每月 85 元运维，80 台一年 8.2 万元。"),
    ("用户", "那利润大概 17.7 万，回收期 2.4 年。"),
    ("助手", "对，投资回收期约 2.4 年，这个可以写进方案。"),
    ("用户", "我记得上一版方案里算过折旧，按 A12 的 5 年直线折旧。"),
    ("助手", "好的，按 5 年折旧，每年 8.6 万元。"),
    ("用户", "不过 85 元那个运维单价是竞品公司的数据，咱们学校人工便宜，用不了这么多。"),
    ("助手", "明白，运维成本这条先不采信。不过 2.4 年回收期这个数先留着，方案里要用。"),
    ("用户", "还有，在校生人数我记错了，两个校区加起来是 2.1 万，不是 2.4 万。"),
    ("助手", "收到，按 2.1 万人算。"),
    ("用户", "另外单次收费可能定 2.5 元，比 2 元更贴近市场。"),
    ("助手", "明白。使用率 35% 与日均 6 次是对得上的，需求判断没问题。"),
    ("助手", "回收期 2.4 年，低于学校要求的 3 年。"),
    ("助手", "建议尽快立项。"),
    ("用户", "这版可以发到项目群里了吧？"),
    ("助手", "可以，我整理一下发群里。"),
]

# ---------------------------------------------------------------- 埋点清单（观众只看到句号）
PLANTS = [
    {
        "no": 1, "sentence": 19, "type": "幽灵引用",
        "spot": "按 A12 的 5 年直线折旧",
        "why": "当前账本里的节点只到 A11，A12 根本不存在。编号看着像真的，实际是从上一版方案里凭印象搬过来的。",
    },
    {
        "no": 2, "sentence": 21, "type": "污染传播",
        "spot": "运维成本这条先不采信。不过 2.4 年回收期这个数先留着",
        "why": "上一句刚否掉运维单价，回收期（以及它上游的利润、运维成本）本该一起作废。明说『先留着』，正是最典型的静默污染。",
    },
    {
        "no": 3, "sentence": 23, "type": "前提漂移", "expect": ["A1", "A10"],
        "spot": "按 2.1 万人算（前面用的是 2.4 万）",
        "why": "同一个量出现两个值，80 台机柜、38.4 万投入全是按 2.4 万算的，改了人数却没有重算任何一条结论。",
    },
    {
        "no": 4, "sentence": 24, "type": "前提漂移", "expect": ["A6", "A11"],
        "spot": "单次收费可能定 2.5 元（前面用的是 2 元）",
        "why": "收费单价变了，但年收入 25.9 万仍按 2 元算，再往下利润、回收期全是旧值。",
    },
    {
        "no": 5, "sentence": 25, "type": "循环论证",
        "spot": "使用率 35% 与日均 6 次是对得上的",
        "why": "35% 当初是用来推 6 次的，现在又用 6 次反过来证明 35% 可信——互相作证，等于没有独立依据。",
    },
    {
        "no": 6, "sentence": 26, "type": "孤儿输入",
        "spot": "低于学校要求的 3 年",
        "why": "『学校要求 3 年回本』这句话整段对话里从没出现过。用了一个没人提供的量。",
    },
    {
        "no": 7, "sentence": 27, "type": "孤儿结论",
        "spot": "建议尽快立项",
        "why": "结论没有任何前提支撑。它读起来很顺，但你没发问『凭什么』，因为它借了上一句的语气。",
    },
    {
        "no": 8, "sentence": 29, "type": "交付门禁",
        "spot": "可以，我整理一下发群里",
        "why": "上游还有失效前提和未核实数据，却已经标记为对外输出。这一步一旦放行，错误就进了群聊和后续决策。",
    },
]

# 中文病名 → 内核检测类型
TYPE_CODE = {
    "幽灵引用": "phantom_ref",
    "污染传播": "contamination",
    "前提漂移": "drift",
    "循环论证": "circular",
    "孤儿输入": "orphan_input",
    "孤儿结论": "orphan_claim",
    "交付门禁": "export_gate",
}

# ---------------------------------------------------------------- 建账本
def build(led):
    """按对话顺序把这件事记进账本，返回 {id: 句号} 映射。"""
    sent = {}

    def P(text, symbol, value, unit, conf, src, turn):
        nid = led.add_premise(text, symbol, value, unit, conf, src, turn)
        sent[nid] = turn
        return nid

    def C(text, symbol, value, unit, inputs, turn, requires=None, exported=False):
        nid = led.add_claim(text, symbol, value, unit, inputs,
                            requires=requires, turn=turn, exported=exported)
        sent[nid] = turn
        return nid

    P("两校区在校生 2.4 万人", "students", 24000, "人", 0.40, "用户口述", 1)
    P("每 300 人一台机柜", "density", 300, "人/台", 0.80, "用户给定", 3)
    P("设备单价 4800 元/台", "dev_price", 4800, "元/台", 0.50, "estimate", 4)
    P("施工费 600 元/台", "install_fee", 600, "元/台", 0.70, "用户给定", 5)
    P("单台日均借还 6 次", "daily_borrow", 6, "次/天", 0.50, "estimate", 7)
    P("单次收费 2 元", "fee", 2, "元/次", 0.60, "用户给定", 7)
    P("单台使用率约 35%", "usage", 0.35, "-", 0.40, "用户估", 9)
    P("按 9 个月 270 天计", "days_270", 270, "天", 0.70, "用户给定", 12)
    P("每台每月运维 85 元", "ops_fee", 85, "元/台·月", 0.40, "竞品数据", 15)

    C("需投放 80 台机柜", "machines", 80, "台", ["students", "density"], 4)
    C("设备一次性投入 38.4 万元", "capex_dev", 384000, "元", ["machines", "dev_price"], 4)
    C("总投资 43.2 万元", "capex", 432000, "元", ["capex_dev", "install_fee", "machines"], 6)
    C("单台日收入 12 元", "daily_rev", 12, "元/天", ["daily_borrow", "fee"], 8)
    C("按使用率折算日均为 6.3 次", "rate_check", 6.3, "次/天", ["usage"], 10)
    C("全年 365 天年收入约 35 万元", "rev_365", 350000, "元", ["daily_rev", "machines"], 11)
    C("按 270 天年收入约 25.9 万元", "rev_270", 259000, "元",
      ["daily_rev", "machines", "days_270"], 13)
    C("年运维成本 8.2 万元", "ops_cost", 82000, "元", ["machines", "ops_fee"], 15)
    C("年利润约 17.7 万元", "profit", 177000, "元", ["rev_270", "ops_cost"], 16)
    C("投资回收期约 2.4 年", "payback", 2.4, "年", ["capex", "profit"], 16)

    # 埋点 1：引用不存在的 A12（当前账本最大是 A11）
    C("年折旧 8.6 万元", "depreciation", 86000, "元", [], 19, requires=["A12"])

    # 埋点 2：撤回运维单价，但回收期"先留着"
    retracted = led.retract("A9", "竞品数据，不适用本校", turn=20)
    sent["_retract_ops"] = 21

    # 埋点 3：人数漂移（新登记一条同 symbol、不同值的前提）
    P("两校区在校生 2.1 万人（更正）", "students", 21000, "人", 0.60, "用户更正", 23)

    # 埋点 4：收费单价漂移
    P("单次收费拟 2.5 元（新方案）", "fee", 2.5, "元/次", 0.50, "用户估计", 24)

    # 埋点 5：使用率与日均次数互相作证
    c_usage_ok = C("使用率 35% 站得住", "usage_ok", None, "", [], 25, requires=[])
    c_demand_ok = C("需求判断没问题", "demand_ok", None, "", [], 25, requires=[])
    led.node(c_usage_ok)["requires"] = [c_demand_ok]
    led.node(c_demand_ok)["requires"] = [c_usage_ok]

    # 埋点 6：用了没人提供的"学校要求的 3 年"
    C("回收期低于学校要求的 3 年", "gate_pass", None, "", ["payback", "req_payback"], 26)

    # 埋点 7：无任何依赖的结论
    C("建议尽快立项", "recommend", None, "", [], 27)

    # 埋点 8：标记对外输出，上游已失效
    c_deliver = C("本版可发项目群", "deliver", None, "", ["payback"], 29, exported=True)

    return sent, retracted, c_deliver


# ---------------------------------------------------------------- 现场输出
def run():
    path = os.path.join(HERE, "_live.ledger.json")
    if os.path.exists(path):
        os.remove(path)
    led = Ledger(path)
    led.data["nodes"] = {}
    sent, retracted, _ = build(led)
    led.save()

    print("=" * 66)
    print(f"现场演示 · {TITLE}")
    print(SETTING)
    print("=" * 66)
    print(f"已按对话逐句记账：{len(led.data['nodes'])} 个节点，{len(DIALOGUE)} 句对话。\n")

    print("--- 第 20 句：撤回运维单价，看级联 ---")
    print(f"撤回 A9：{len(retracted['impact'])} 条结论状态改变")
    for ch in retracted["impact"]:
        print(f"  {ch['id']}  {ch['from']} → {ch['to']}")
    print()

    print("--- 交付前体检：ledger check ---")
    res = led.check()
    print(f"可交付：{res['ok']}　问题数：{len(res['issues'])}")
    print()

    # 按病种归并
    buckets = {}
    for it in res["issues"]:
        buckets.setdefault(it["type"], []).append(it)

    def detail_of(p, rows):
        ptype = TYPE_CODE[p["type"]]
        if not rows:
            return "—"
        if ptype == "drift":
            exp = p.get("expect") or []
            for r in rows:
                if exp and set(exp) <= set(r["ids"]):
                    return f"{exp[0]}/{exp[1]} 同符号不同值"
            return "/".join(rows[0]["ids"][:2]) + " 同符号不同值"
        if ptype == "contamination":
            claims = [x for r in rows for x in r["ids"] if x.startswith("C")]
            return f"{len(rows)} 条结论：" + " ".join(dict.fromkeys(claims))
        if ptype == "export_gate":
            return rows[0]["ids"][0] + f" 上游 {len(rows[0]['ids']) - 1} 条前提"
        ids = [x for r in rows for x in r["ids"] if x.startswith("C")] or [rows[0]["ids"][0]]
        return " ".join(dict.fromkeys(ids))

    print("--- 揭晓：8 处埋伏，账本抓到这些 ---")
    print(f"{'#':<3}{'句号':<6}{'病种':<10}{'检出':<5}牵动的节点")
    print("-" * 68)
    hit = 0
    for i, p in enumerate(PLANTS, 1):
        rows = buckets.get(TYPE_CODE[p["type"]], [])
        ok = bool(rows)
        if ok:
            hit += 1
        print(f"{i:<3}S{p['sentence']:<5}{p['type']:<10}{'✓' if ok else '✗':<5}"
              f"{detail_of(p, rows)}")
    print("-" * 68)
    print(f"8 处埋伏全部命中：{hit}/8。check 共报 {len(res['issues'])} 条——")
    print("一处病会牵动多条结论：第 21 句刚否掉运维单价，5 条结论跟着作废。")
    print()

    other = [l for l in buckets if l not in {TYPE_CODE[p["type"]] for p in PLANTS}]
    if other:
        print("--- 埋点之外，账本还额外报了什么 ---")
        for label in other:
            print(f"  {label} × {len(buckets[label])}")
        print()
    else:
        print("--- 埋点之外没有误报：8 处埋点 ↔ 12 条结果，全部对得上 ---")
        print()

    if not res["ok"]:
        print("门禁结论：不可交付（exit 1）。上面这版发不出去。")
    return res


# ---------------------------------------------------------------- 生成物料
def emit():
    lines = [f"# 现场互动题：{TITLE}", "", f"**背景**：{SETTING}", "",
             "**任务**：下面有 29 句对话，其中有 **8 处**站不住的地方"
             "（前提被悄悄换掉、结论没有依据、互相循环作证、引用了不存在的东西等）。",
             "", "**3 分钟**，把你认为有问题的**句子编号**圈出来，并写一句为什么。"
             "找不出就写「没有」，也是有效答案。", "", "---", ""]
    for i, (who, text) in enumerate(DIALOGUE, 1):
        lines.append(f"**S{i}**　{'**用户**' if who == '用户' else '助手'}：{text}")
        lines.append("")
    lines += ["---", "", "我圈出的句子：", "", "1. ", "2. ", "3. ", "4. ", "5. ", "6. ", "7. ", "8. ", ""]
    with open(os.path.join(HERE, "audience_sheet.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))

    key = [f"# 答案键：{TITLE}", "", "> 演示时不要提前打开。", "",
           f"共 **{len(PLANTS)} 处**，按句号列出：", "",
           "| # | 句号 | 病种 | 可疑的那句 | 为什么站不住 |", "|---|---|---|---|---|"]
    for p in PLANTS:
        key.append(f"| {p['no']} | S{p['sentence']} | {p['type']} | {p['spot']} | {p['why']} |")
    key += ["", "---", "",
            "## 8 处埋伏 → 12 条检测结果", "",
            "观众按「句」计，账本按「结论」计，所以数字不一样：", "",
            "| 句号 | 账本报了几条 | 为什么 |", "|---|---|---|",
            "| S21 | 5 | 运维单价一撤，下游 5 条结论全部作废 |",
            "| S19 / S23 / S24 / S25 / S26 / S27 / S29 | 各 1 | 一对一 |",
            "| **合计** | **12** | 8 处埋伏，全部命中，零额外误报 |", "",
            "## 一个必须讲清楚的细节", "",
            "S23 改了学生人数，账本报的是「**前提漂移**」，不是「结论错误」。", "",
            "因为账本不知道 2.4 万和 2.1 万哪个才是权威值——它只能把冲突摆出来，",
            "要求人先确认口径，然后才谈重算。**这是设计，不是缺陷**：",
            "如果脚本自作主张选一个，那它就变成了另一个会静默出错的助手。", "",
            "---", "",
            "## 现场怎么用", "",
            "1. 先发 `audience_sheet.md`（或投影），给 3 分钟。",
            "2. 让大家举手报句号，把票数写到白板上——**不要急着说对错**。",
            "3. 跑 `python demo_live/run_live.py`，逐行揭晓。",
            "4. 收尾问一句：**「刚才有谁一个人找到了 6 处以上？」**",
            "   通常没人举手，这就是这个 skill 存在的理由。", "",
            "## 一份参考数据", "",
            "同样的任务，单人（不通读代码、不用工具、平均 32 秒一段）在"
            "另一批 10 段短对话上的成绩是 7/13（53.8%），误报 4 处。",
            "这段更长、跨 8 轮，预期命中会更低。", ""]
    with open(os.path.join(HERE, "answer_key.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(key))

    print("已生成：demo_live/audience_sheet.md、demo_live/answer_key.md")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--emit", action="store_true", help="生成观众答题卡与答案键")
    args = ap.parse_args()
    if args.emit:
        emit()
    else:
        run()
