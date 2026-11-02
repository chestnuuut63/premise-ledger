#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""三组表示消融评测。

同一批对话，只改变「怎么记账」，看能抓出多少问题：

  A 纯文本      —— 只能从对话里认出"有哪些结论"，拿不到任何依赖边
  B 内联声明    —— 结论边上标了 [依赖 A1,A2]，但没有符号表、没有版本、没有交付门禁
  C 完整账本    —— 全部字段齐全（本项目的方案）

这不是"比模型聪明"，而是"比记账方式"：三段全部是确定性脚本，任何人跑都得到同样数字。

用法：python evaluate.py [--dataset dataset/dialogues.json] [--out results]
"""

import argparse
import copy
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "scripts"))

from ledger import Ledger  # noqa: E402

ARM_LABELS = {
    "A": "A 纯文本",
    "B": "B 内联声明",
    "C": "C 完整账本",
}

TYPE_ORDER = ["orphan_claim", "orphan_input", "phantom_ref", "circular", "contamination", "drift", "export_gate"]
TYPE_LABELS = {
    "orphan_claim": "孤儿结论",
    "orphan_input": "孤儿输入",
    "phantom_ref": "幽灵引用",
    "circular": "循环论证",
    "contamination": "污染传播",
    "drift": "前提漂移",
    "export_gate": "交付门禁",
}


def make_premise(p, arm):
    return {
        "id": p["id"],
        "kind": "premise",
        "text": p["text"],
        "symbol": "" if arm in ("A", "B") else p.get("symbol", ""),
        "value": p.get("value"),
        "unit": p.get("unit", ""),
        "status": p.get("status", "unverified"),
        "conf": p.get("conf", 0.5),
        "src": p.get("src", "user"),
        "turn": 0,
        "updated_turn": 0,
        "requires": [],
        "alts": [],
        "inputs": [],
        "unresolved": [],
        "exported": False,
        "retracted": False,
        "evidence": [],
        "note": "",
    }


def make_claim(c, arm):
    return {
        "id": c["id"],
        "kind": "claim",
        "text": c["text"],
        "symbol": "" if arm in ("A", "B") else c.get("symbol", ""),
        "value": c.get("value"),
        "unit": c.get("unit", ""),
        "status": "active",
        "conf": 0.0,
        "src": "derived",
        "turn": 0,
        "updated_turn": 0,
        "requires": [] if arm == "A" else list(c.get("requires", [])),
        "alts": [] if arm in ("A", "B") else list(c.get("alts", [])),
        "inputs": [] if arm in ("A", "B") else list(c.get("inputs", [])),
        "unresolved": [] if arm in ("A", "B") else list(c.get("unresolved", [])),
        "exported": False if arm in ("A", "B") else bool(c.get("exported", False)),
        "retracted": False,
        "evidence": [],
        "note": "",
    }


def build(spec, arm):
    led = Ledger(os.path.join(os.sep, "__no_such_ledger__.json"))
    led.data["nodes"] = {}
    for p in spec["ledger"]["premises"]:
        led.data["nodes"][p["id"]] = make_premise(p, arm)
    for c in spec["ledger"]["claims"]:
        led.data["nodes"][c["id"]] = make_claim(c, arm)
    return led


def repair(spec):
    """把埋点逐项"治好"，得到一个应当完全健康的账本，用于阴性对照。

    如果检测器在健康账本上也报错，那就是误报——这部分不依赖埋点清单，
    因此不受"自己出题自己考"的影响。
    """
    s = copy.deepcopy(spec["ledger"])
    premise_ids = [p["id"] for p in s["premises"]]
    claim_ids = {c["id"] for c in s["claims"]}
    known = set(premise_ids) | claim_ids

    # 幽灵引用：删掉不存在的依赖
    for c in s["claims"]:
        c["requires"] = [d for d in c.get("requires", []) if d in known]
        c["alts"] = [d for d in c.get("alts", []) if d in known]

    # 循环论证：断掉回指的那条边
    def reaches(start, target, seen):
        if start in seen:
            return False
        seen.add(start)
        for c in s["claims"]:
            if c["id"] == start:
                for d in c.get("requires", []):
                    if d == target or reaches(d, target, seen):
                        return True
        return False

    for c in s["claims"]:
        c["requires"] = [d for d in c["requires"]
                         if not (d in claim_ids and reaches(d, c["id"], set()))]

    # 孤儿结论：挂到第一条前提上
    for c in s["claims"]:
        if not c["requires"] and not c.get("alts") and premise_ids:
            c["requires"] = [premise_ids[0]]

    # 孤儿输入：删掉没人提供的符号
    symbols = {p.get("symbol") for p in s["premises"] if p.get("symbol")}
    for c in s["claims"]:
        c["inputs"] = [x for x in c.get("inputs", []) if x in symbols]
        c["unresolved"] = []

    # 前提漂移：同一符号统一成先出现的那条
    seen_symbol = {}
    for p in s["premises"]:
        sym = p.get("symbol")
        if not sym:
            continue
        if sym in seen_symbol:
            p["value"] = seen_symbol[sym]["value"]
            p["text"] = seen_symbol[sym]["text"]
        else:
            seen_symbol[sym] = p

    # 污染传播 / 交付门禁：把所有前提视为已核实
    for p in s["premises"]:
        p["status"] = "verified"
        p["conf"] = 1.0

    return s


def negative_control(dialogues):
    rows = []
    total_issues = 0
    for d in dialogues:
        fixed = {"ledger": repair(d)}
        led = build(fixed, "C")
        issues = led.check()["issues"]
        total_issues += len(issues)
        rows.append({"dialogue": d["id"], "issues": len(issues),
                     "types": [i["type"] for i in issues]})
    return {"total_issues": total_issues, "rows": rows}


def detect(led):
    result = led.check()
    return [(i["type"], set(i["ids"])) for i in result["issues"]]


def score(planted, detected):
    used = set()
    tp, fn = [], []
    for p in planted:
        hit = None
        for idx, (t, ids) in enumerate(detected):
            if idx in used:
                continue
            if t == p["type"] and (set(p["ids"]) & ids):
                hit = idx
                break
        if hit is None:
            fn.append(p)
        else:
            used.add(hit)
            tp.append(p)
    fp = [d for idx, d in enumerate(detected) if idx not in used]
    return tp, fp, fn


def pct(a, b):
    return 0.0 if b == 0 else 100.0 * a / b


def run_arm(dialogues, arm):
    tp_n = fp_n = fn_n = 0
    per_type = {t: {"planted": 0, "hit": 0} for t in TYPE_ORDER}
    missed, false_alarms, details = [], [], []

    for d in dialogues:
        led = build(d, arm)
        detected = detect(led)
        planted = d.get("planted", [])
        tp, fp, fn = score(planted, detected)
        tp_n += len(tp)
        fp_n += len(fp)
        fn_n += len(fn)
        for p in planted:
            per_type[p["type"]]["planted"] += 1
        for p in tp:
            per_type[p["type"]]["hit"] += 1
        for p in fn:
            missed.append({"dialogue": d["id"], "type": p["type"], "ids": p["ids"]})
        for t, ids in fp:
            false_alarms.append({"dialogue": d["id"], "type": t, "ids": sorted(ids)})
        details.append({
            "dialogue": d["id"],
            "planted": len(planted),
            "hit": len(tp),
            "false_alarms": len(fp),
        })

    return {
        "arm": arm,
        "label": ARM_LABELS[arm],
        "detected": tp_n,
        "planted": tp_n + fn_n,
        "false_alarms": fp_n,
        "recall": pct(tp_n, tp_n + fn_n),
        "precision": pct(tp_n, tp_n + fp_n) if (tp_n + fp_n) else 100.0,
        "per_type": {t: {"planted": v["planted"], "hit": v["hit"],
                         "recall": pct(v["hit"], v["planted"])} for t, v in per_type.items()},
        "missed": missed,
        "false_alarm_list": false_alarms,
        "details": details,
    }


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default=os.path.join(HERE, "dataset", "dialogues.json"))
    ap.add_argument("--out", default=os.path.join(HERE, "results"))
    ap.add_argument("--human", default=None, help="人工基线填好的 CSV（id,hit,false_alarm,seconds）")
    args = ap.parse_args(argv)

    with open(args.dataset, encoding="utf-8") as fh:
        data = json.load(fh)
    dialogues = data["dialogues"]

    total_plants = sum(len(d.get("planted", [])) for d in dialogues)
    print(f"数据集：{len(dialogues)} 段对话，{total_plants} 处埋点")
    print()

    results = {arm: run_arm(dialogues, arm) for arm in ("A", "B", "C")}

    human = None
    if args.human and os.path.exists(args.human):
        import csv
        hits = fa = secs = 0
        with open(args.human, encoding="utf-8-sig") as fh:
            for row in csv.DictReader(fh):
                hits += int(row.get("hit") or 0)
                fa += int(row.get("false_alarm") or 0)
                secs += int(row.get("seconds") or 0)
        if hits or fa:
            human = {
                "label": "H 人工（无工具）",
                "detected": hits,
                "planted": total_plants,
                "false_alarms": fa,
                "recall": pct(hits, total_plants),
                "precision": pct(hits, hits + fa) if (hits + fa) else 100.0,
                "seconds": secs,
            }

    print("## 总表")
    print()
    print("| 记账方式 | 抓到 / 埋点 | 检出率 | 误报 | 精确率 |")
    print("|---|---|---|---|---|")
    for arm in ("A", "B", "C"):
        r = results[arm]
        print(f"| {r['label']} | {r['detected']} / {r['planted']} | {r['recall']:.1f}% | "
              f"{r['false_alarms']} | {r['precision']:.1f}% |")
    if human:
        print(f"| {human['label']} | {human['detected']} / {human['planted']} | "
              f"{human['recall']:.1f}% | {human['false_alarms']} | {human['precision']:.1f}% |")

    print()
    print("## 分项检出率")
    print()
    header = "| 病种 | 埋点数 | " + " | ".join(ARM_LABELS[a] for a in ("A", "B", "C")) + " |"
    print(header)
    print("|---|---|---|---|---|")
    for t in TYPE_ORDER:
        row = [TYPE_LABELS[t], str(results["C"]["per_type"][t]["planted"])]
        for a in ("A", "B", "C"):
            v = results[a]["per_type"][t]
            row.append(f"{v['hit']}/{v['planted']}")
        print("| " + " | ".join(row) + " |")

    print()
    print("## C 组未命中")
    print()
    if results["C"]["missed"]:
        for m in results["C"]["missed"]:
            print(f"- {m['dialogue']} {TYPE_LABELS[m['type']]} {m['ids']}")
    else:
        print("- 无")

    print()
    print("## B 组漏掉了什么")
    print()
    b_missed = {}
    for m in results["B"]["missed"]:
        b_missed.setdefault(m["type"], 0)
        b_missed[m["type"]] += 1
    for t, n in b_missed.items():
        print(f"- {TYPE_LABELS[t]}：漏 {n} 处")
    if not b_missed:
        print("- 无")

    print()
    print(f"## 阴性对照（把 {total_plants} 处埋点全部治好后再检测）")
    print()
    nc = negative_control(dialogues)
    if nc["total_issues"] == 0:
        print(f"- {len(dialogues)} 段健康账本，误报 0 处 —— 检测器不会在没病时乱报警。")
    else:
        print(f"- 共 {nc['total_issues']} 处误报，需要修正：")
        for r in nc["rows"]:
            if r["issues"]:
                print(f"  - {r['dialogue']}: {r['types']}")

    os.makedirs(args.out, exist_ok=True)
    out_path = os.path.join(args.out, "eval_results.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump({
            "dataset": args.dataset,
            "dialogues": len(dialogues),
            "total_plants": total_plants,
            "arms": results,
            "negative_control": nc,
        }, fh, ensure_ascii=False, indent=2)
    print()
    try:
        shown = os.path.relpath(out_path).replace(os.sep, "/")
    except ValueError:
        shown = out_path
    print(f"详细结果已写入 {shown}")

    a, b, c = results["A"], results["B"], results["C"]
    print()
    print(f"一句话结论：同样 {len(dialogues)} 段对话，检出率从 "
          f"{a['recall']:.1f}%（纯文本）→ {b['recall']:.1f}%（内联声明）→ {c['recall']:.1f}%（完整账本）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
