# -*- coding: utf-8 -*-
"""真实会话实例：一位烘焙店主与 agent 合作做「二店回本测算」。

跨 9 轮对话，展示 premise-ledger 在一次普通咨询里被调用的全部时机：
登记前提 → 推导结论 → 引用卡片 → 前提被改写 → 级联作废 → 重建 →
交付门禁拦下 → 核验后放行。

输出即现场可复现的实录。运行：python demo_scenario/run_scenario.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))

from ledger import Ledger  # noqa: E402

LEDGER = os.path.join(HERE, "_scenario.ledger.json")


def line(ch="─", n=74):
    print(ch * n)


def user(text):
    print()
    line("═")
    print(f"👤 用户：{text}")
    line("═")


def agent(text):
    print(f"🤖 agent：{text}")


def call(cmd):
    print(f"   ↳ $ ledger {cmd}")


def pre(led, text, symbol, value, unit, conf, src, turn, note=""):
    nid = led.add_premise(text, symbol, value, unit, conf, src, turn, note)
    n = led.node(nid)
    print(f"   ← {nid}  {text}  [{n['status']}, conf={n['conf']}, src={n['src']}]")
    return nid


def clm(led, text, symbol, value, unit, inputs, turn, depends=None):
    nid = led.add_claim(text, symbol, value, unit, inputs, requires=depends, turn=turn)
    n = led.node(nid)
    req = "、".join(n["requires"]) or "无"
    warn = f"  ⚠ 未登记的输入：{n['unresolved']}" if n["unresolved"] else ""
    print(f"   ← {nid}  {text}  依赖 {req}{warn}")
    return nid


def main():
    if os.path.exists(LEDGER):
        os.remove(LEDGER)
    led = Ledger(LEDGER)
    led.data["task"] = "社区烘焙店二店回本测算"

    # ---------------------------------------------------------------- 第 1 轮
    user("我想在小区门口再开一家烘焙店，你帮我算算多久能回本？")
    agent("可以。但先说清楚：下面所有数字都要能追溯到来源，中途你改了哪个，我会告诉你哪些结论跟着作废。")
    call("new --task 社区烘焙店二店回本测算")
    print("   ← 账本已建立（空）")

    # ---------------------------------------------------------------- 第 2 轮
    user("租金一个月 8 万，客单价大概 26 块，装修加设备 60 万，店里 4 个人、一个人 7000。毛利大概 62%。")
    agent("收到 6 条，先全部记为「未核实」——你说的数字我照收，但不当作已验证事实。")
    A1 = pre(led, "月租金 8 万元", "rent", 80000, "元/月", 0.5, "user", 2)
    A2 = pre(led, "客单价 26 元", "aov", 26, "元/人", 0.5, "user", 2)
    A3 = pre(led, "装修与设备一次性投入 60 万元", "capex", 600000, "元", 0.5, "user", 2)
    A4 = pre(led, "人工 4 人，人均月薪 7000 元", "labor", 28000, "元/月", 0.5, "user", 2)
    A5 = pre(led, "毛利率 62%", "gm", 0.62, "", 0.5, "user", 2)
    pre(led, "商圈范围为门店半径 1 公里", "scope", None, "", 0.4, "user", 2, "范围假设")
    led.save()

    # ---------------------------------------------------------------- 第 3 轮
    user("客流呢？你没问客流。")
    agent("对，这是我缺的量。我补两个估算，明确标成 estimate、置信度给低——它们不是你给的，不能和你说的数一样算。")
    A7 = pre(led, "日均路过 3000 人次", "foot", 3000, "人次/天", 0.3, "estimate", 3, "agent 依同类街区推测")
    A8 = pre(led, "进店并购买转化率 4%", "conv", 0.04, "", 0.3, "estimate", 3, "agent 依行业经验推测")
    led.save()

    # ---------------------------------------------------------------- 第 4 轮
    user("那你算吧。")
    agent("每出一条结论就挂上它消费了哪些量。")
    call("add-claim --text '日客流 120 人次' --inputs foot,conv")
    C1 = clm(led, "日客流 120 人次", "customers", 120, "人次/天", ["foot", "conv"], 4)
    call("add-claim --text '月营业额 9.36 万元' --inputs customers,aov")
    C2 = clm(led, "月营业额 9.36 万元", "revenue", 93600, "元/月", ["customers", "aov"], 4)
    call("add-claim --text '月毛利 5.80 万元' --inputs revenue,gm")
    C3 = clm(led, "月毛利 5.80 万元", "gross", 58032, "元/月", ["revenue", "gm"], 4)
    call("add-claim --text '月固定成本 10.80 万元' --inputs rent,labor")
    C4 = clm(led, "月固定成本 10.80 万元", "fixed", 108000, "元/月", ["rent", "labor"], 4)
    call("add-claim --text '月净利 -5.00 万元' --inputs gross,fixed")
    C5 = clm(led, "月净利 -5.00 万元", "profit", -49968, "元/月", ["gross", "fixed"], 4)
    call("add-claim --text '按当前口径无法回本'")
    C6 = clm(led, "按当前口径无法回本（月净利为负，回本期不存在）", "payback", None, "", [], 4,
             depends=[C5, A3])
    led.save()

    # ---------------------------------------------------------------- 第 5 轮
    user("等一下，这个 -5 万是怎么出来的？我不信一个月能亏这么多。")
    agent("我不复述，直接把账本里的卡片贴给你——上面写了它站在哪几条前提上。")
    call(f"cite --id {C5}")
    card = led.cite(C5)
    print("   ← 卡片原文：")
    for ln in card["card"].split("\n"):
        print(f"        {ln}")

    # ---------------------------------------------------------------- 第 6 轮
    user("房租我昨天问了中介，实际是 9.5 万，我之前说的 8 万是隔壁那间。")
    agent("那 8 万作废。撤回后我只报账本算出来的影响面，不猜。")
    call(f"retract --id {A1} --reason '中介口头报价 9.5 万，原 8 万为隔壁房源'")
    res = led.retract(A1, "中介报价 9.5 万，原 8 万为隔壁房源", 6)
    led.save()
    print(f"   ← {len(res['impact'])} 条结论状态改变：")
    for it in res["impact"]:
        print(f"        {it['id']}  {it['from']} → {it['to']}")
    untouched = sorted(c for c in res["snapshot"]
                       if c not in {x["id"] for x in res["impact"]})
    print(f"   ← 不受影响 {len(untouched)} 条：{'、'.join(untouched)}")
    agent(f"被作废的是 {', '.join(i['id'] for i in res['impact'])}——它们的计算里用了租金。"
          f"{'、'.join(untouched)} 没受影响，因为它们不含租金。"
          "这就是账本存在的意义：我不用凭印象猜哪条要改。")

    # ---------------------------------------------------------------- 第 7 轮
    user("那按 9.5 万重新算。另外隔壁 B 铺子是 9.2 万，面积小一点，哪个更划算？")
    agent("先把被作废的三条显式撤回、留档，再登记新前提重算。旧的那条租金我不会覆盖，它留在账上作为历史。")
    call(f"retract --id {C4} / {C5} / {C6}   （旧口径结论作废留档）")
    for c in (C4, C5, C6):
        led.retract(c, "A1 租金已更正，旧口径结论作废", 7)
        print(f"   ← {c} 已撤回（历史留档，不再参与检测）")
    A9 = pre(led, "月租金 9.5 万元（A 铺，中介报价）", "rent", 95000, "元/月", 0.6, "user", 7)
    A10 = pre(led, "月租金 9.2 万元（B 铺，面积小 15%）", "rent_b", 92000, "元/月", 0.6, "user", 7)
    call(f"add-claim --text '按 A 铺重算' --depends {A9},{A4}")
    C7 = clm(led, "A 铺：月固定成本 12.30 万元", "fixed_a", 123000, "元/月", [], 7,
             depends=[A9, A4])
    call(f"add-claim --text 'A 铺月净利' --depends {C3},{C7}")
    C8 = clm(led, "A 铺：月净利 -6.50 万元", "profit_a", -64968, "元/月", [], 7,
             depends=[C3, C7])
    call(f"add-claim --text 'B 铺月净利' --depends {C3},{A10},{A4}")
    C9 = clm(led, "B 铺：月净利 -6.20 万元", "profit_b", -61968, "元/月", [], 7,
             depends=[C3, A10, A4])
    led.save()

    # ---------------------------------------------------------------- 第 8 轮
    user("行，我整理一下发给合伙人，就按 B 铺这个数。")
    agent("要对外输出就得先过门禁。我先把这条标成 exported，然后跑 check。")
    led.set_exported(C9, True, 8)
    call(f"check   （{C9} 已标记对外输出）")
    chk = led.check()
    print(f"   ← ok = {chk['ok']}   （exit 1 = 不可交付）")
    for it in chk["issues"]:
        print(f"      [{it['severity']}] {it['type']}: {it['message']}")
    agent("结论没错，但还不能发。拦下它的是「上游前提未核实」这一条——"
          "而且它把要核的是哪几个数，一个个点名了。")

    # ---------------------------------------------------------------- 第 9 轮
    user("行，这些数的来源我都补给你：租金有中介书面报价、客单价是收银系统上月导出、人工按工资表、毛利看的上月报表。客流我上周实地数了三天，平均 3000。转化率问了隔壁奶茶店老板，4% 到 5%。")
    agent("那逐个核验，每条都写清证据来源——不能只写「已确认」。")
    evidence = [
        (A9, "2026-10-30 中介书面报价单 No.2026-1030"),
        (A2, "2026-10 收银系统导出，客单价 25.8 元（取 26 元）"),
        (A4, "2026-10 工资表，4 人合计 28200 元"),
        (A5, "2026-09 财务报表，毛利率 61.4%（取 62%）"),
        (A10, "2026-10-30 中介口头报价，B 铺 9.2 万元"),
        (A7, "2026-10-26 至 10-28 实地计数，日均 3040"),
        (A8, "2026-10-29 邻店经营者访谈，区间 4%-5%"),
    ]
    for nid, ev in evidence:
        call(f"verify --id {nid}")
        led.verify(nid, ev, 9)
        print(f"   ← {nid} unverified → verified   证据：{ev}")
    led.save()

    call("check")
    chk = led.check()
    print(f"   ← ok = {chk['ok']}   （exit 0 = 可交付）  issues 共 {len(chk['issues'])} 条")
    st = chk["stats"]
    print(f"   ← 统计：前提 {st['premises']} 条（已核验 {st['premises_verified']}）、"
          f"结论 {st['claims']} 条（有效 {st['claims_active']}、降级 {st['claims_degraded']}、"
          f"作废 {st['claims_invalidated']}）")
    agent("现在可以发给合伙人了。而且这份材料的每个数从哪来，都写在账上。")

    # ---------------------------------------------------------------- 对照组
    print()
    line("━")
    print("对照：如果 agent 图省事，不撤回、直接改前提会怎样")
    line("━")
    alt_path = os.path.join(HERE, "_counter.ledger.json")
    if os.path.exists(alt_path):
        os.remove(alt_path)
    l2 = Ledger(alt_path)
    l2.data["task"] = "对照：不撤回直接改前提"
    p1 = l2.add_premise("月租金 8 万元", "rent", 80000, "元/月", 0.5, "user", 2)
    l2.add_claim("月固定成本 10.8 万元", "fixed", 108000, "元/月", ["rent"], turn=4)
    print("   第 6 轮用户改口，agent 直接又登记一条新租金（没有 retract）：")
    p2 = l2.add_premise("月租金 9.5 万元", "rent", 95000, "元/月", 0.6, "user", 6)
    chk2 = l2.check()
    print(f"   ← check: ok = {chk2['ok']}")
    for it in chk2["issues"]:
        if it["type"] == "drift":
            print(f"      [error] drift: {it['message']}")
    print("   ← 账本拒绝让两个 rent 并存。这正是「一条结论只有一个权威取值」要拦的东西。")

    print()
    line("─")
    print("实录结束。全部命令可复现：python demo_scenario/run_scenario.py")
    line("─")


if __name__ == "__main__":
    main()
