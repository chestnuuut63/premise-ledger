#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RSI：让账本自己发现「该记哪些字段」

可编辑表面（genome）是六个字段的开关：
    deps        依赖边（谁靠谁）
    alts        替代支撑边
    symbol      符号表（同一个量能否被认出是同一个量）
    inputs      输入清单
    unresolved  未解析输入 → 孤儿输入
    exported    对外标记 → 交付门禁

回路按课程第 5 讲的双层结构搭：
    内层  在训练折上用公开分数 r_pub 挑候选（单点变异）
    外层  在留出折上用私有分数 r_priv 决定是否接受（argmax incumbent）

两条护栏也照做：
    信号解耦  挑候选只看训练折；能不能上位只看留出折
    固定预算  总评估次数封顶，不许多跑取胜

与 openai 式「让模型改自己代码」的差别写在 README 里：这里把可编辑表面
限定为字段开关，是受限自我重写（bounded RSI），不是任意代码重写。

用法：
    python rsi/run_rsi.py                 # 两折交叉，出报告
    python rsi/run_rsi.py --budget 120    # 改评估预算
"""
from __future__ import annotations

import argparse
import itertools
import json
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from ledger import Ledger  # noqa: E402

FIELDS = ["deps", "alts", "symbol", "inputs", "unresolved", "exported"]
TOP_K = 3

FIELD_LABEL = {
    "deps": "依赖边",
    "alts": "替代支撑边",
    "symbol": "符号表",
    "inputs": "输入清单",
    "unresolved": "未解析输入",
    "exported": "对外标记",
}


def load_dialogues(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)["dialogues"]


def build_with(spec, genome):
    """按基因组构建账本。

    刻意复刻 evaluate.py 的字段清空语义，这样 A/B/C 三组能被本脚本复现，
    否则两套数字对不上，实验就没有基准。
    """
    led = Ledger(os.path.join(os.sep, "__no_such_ledger__.json"))
    nodes = {}

    for p in spec["ledger"]["premises"]:
        nodes[p["id"]] = {
            "id": p["id"],
            "kind": "premise",
            "text": p["text"],
            "symbol": p.get("symbol", "") if "symbol" in genome else "",
            "value": p.get("value"),
            "unit": p.get("unit", ""),
            "status": p.get("status", "unverified"),
            "conf": p.get("conf", 0.5),
            "src": p.get("src", "user"),
            "turn": 0,
            "updated_turn": 0,
            "requires": list(p.get("requires", [])) if "deps" in genome else [],
            "alts": list(p.get("alts", [])) if "alts" in genome else [],
            "inputs": [],
            "unresolved": [],
            "exported": False,
            "retracted": bool(p.get("retracted", False)),
            "evidence": [],
            "note": "",
        }

    for c in spec["ledger"]["claims"]:
        nodes[c["id"]] = {
            "id": c["id"],
            "kind": "claim",
            "text": c["text"],
            "symbol": c.get("symbol", "") if "symbol" in genome else "",
            "value": c.get("value"),
            "unit": c.get("unit", ""),
            "status": "active",
            "conf": 0.0,
            "src": "derived",
            "turn": 0,
            "updated_turn": 0,
            "requires": list(c.get("requires", [])) if "deps" in genome else [],
            "alts": list(c.get("alts", [])) if "alts" in genome else [],
            "inputs": list(c.get("inputs", [])) if "inputs" in genome else [],
            "unresolved": list(c.get("unresolved", [])) if "unresolved" in genome else [],
            "exported": bool(c.get("exported", False)) if "exported" in genome else False,
            "retracted": bool(c.get("retracted", False)),
            "evidence": [],
            "note": "",
        }

    led.data["nodes"] = nodes
    return led


def score_one(dialogue, genome):
    led = build_with(dialogue, genome)
    issues = led.check()["issues"]
    detected = [(i["type"], set(i["ids"])) for i in issues]

    planted = dialogue.get("planted", [])
    used = set()
    tp = 0
    for p in planted:
        for idx, (t, ids) in enumerate(detected):
            if idx in used:
                continue
            if t == p["type"] and (set(p["ids"]) & ids):
                used.add(idx)
                tp += 1
                break
    fp = len(detected) - len(used)
    return tp, len(planted) - tp, fp


def evaluate(genome, dialogues):
    tp = fn = fp = 0
    for d in dialogues:
        a, b, c = score_one(d, genome)
        tp += a
        fn += b
        fp += c
    total = tp + fn
    recall = 100.0 * tp / total if total else 0.0
    precision = 100.0 * tp / (tp + fp) if (tp + fp) else 100.0
    fitness = recall - 4.0 * fp
    return {
        "genome": sorted(genome),
        "tp": tp, "fn": fn, "fp": fp, "total": total,
        "recall": round(recall, 1),
        "precision": round(precision, 1),
        "fitness": round(fitness, 1),
    }


def neighbors(genome):
    for f in FIELDS:
        g = set(genome)
        g.symmetric_difference_update({f})
        yield frozenset(g)


def run_fold(train, holdout, budget, seed=0, verbose=True):
    rng = random.Random(seed)
    incumbent = frozenset()
    pub = evaluate(incumbent, train)
    priv = evaluate(incumbent, holdout)
    spent = 2

    log = [{
        "round": 0, "move": "起点（纯文本，不记任何字段）",
        "genome": sorted(incumbent), "pub": pub["recall"], "priv": priv["recall"],
        "accepted": True, "note": "",
    }]

    rnd = 0
    while spent < budget:
        rnd += 1

        # 内层：只看公开信号，按训练折表现排序，提交前 TOP_K 个候选。
        # 不要求「严格变好」——训练折抓满之后就没有增量了，但留出折可能还有。
        scored_pub = []
        for cand in neighbors(incumbent):
            if spent >= budget:
                break
            pub_c = evaluate(cand, train)
            spent += 1
            scored_pub.append((cand, pub_c))
        if not scored_pub:
            break
        scored_pub.sort(key=lambda x: (x[1]["fitness"], x[1]["recall"]), reverse=True)
        admitted = scored_pub[:TOP_K]

        # 外层：私有信号做 argmax，只有赢过现任者才上位
        scored = []
        for cand, pub_c in admitted:
            if spent >= budget:
                break
            priv_c = evaluate(cand, holdout)
            spent += 1
            scored.append((cand, pub_c, priv_c))
        if not scored:
            break

        best, best_pub, best_priv = max(
            scored, key=lambda x: (x[2]["fitness"], x[2]["recall"]))

        added = sorted(set(best) - set(incumbent))
        removed = sorted(set(incumbent) - set(best))
        move = []
        if added:
            move.append("+" + "+".join(FIELD_LABEL[f] for f in added))
        if removed:
            move.append("-" + "+".join(FIELD_LABEL[f] for f in removed))
        move_s = " ".join(move) or "原地"

        accepted = (best_priv["fitness"], best_priv["recall"]) > (priv["fitness"], priv["recall"])
        log.append({
            "round": rnd, "move": move_s,
            "genome": sorted(best), "pub": best_pub["recall"], "priv": best_priv["recall"],
            "accepted": accepted,
            "note": "" if accepted else f"提交的 {len(admitted)} 个候选，私有分数均未超越现任者",
        })
        if not accepted:
            break
        incumbent, pub, priv = best, best_pub, best_priv

    return {"log": log, "final": incumbent, "pub": pub, "priv": priv, "spent": spent}


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default=os.path.join(ROOT, "dataset", "dialogues.json"))
    ap.add_argument("--budget", type=int, default=80, help="每折总评估次数上限")
    ap.add_argument("--out", default=os.path.join(ROOT, "results"))
    args = ap.parse_args(argv)

    dialogues = load_dialogues(args.dataset)
    ids = [d["id"] for d in dialogues]
    fold_a = [d for d in dialogues if d["id"] <= "D05"]
    fold_b = [d for d in dialogues if d["id"] > "D05"]

    print("=" * 66)
    print("RSI：让账本自己发现该记哪些字段")
    print("=" * 66)
    print(f"数据：{len(dialogues)} 段对话 / "
          f"{sum(len(d.get('planted', [])) for d in dialogues)} 处埋点")
    print(f"训练折 {[d['id'] for d in fold_a]}  留出折 {[d['id'] for d in fold_b]}")
    print(f"可编辑表面：{len(FIELDS)} 个字段开关，空间 {2 ** len(FIELDS)} 种组合")
    print(f"预算：每折 {args.budget} 次评估（含起点与接受判定）")
    print()

    # 基准复现：确认构建器与 evaluate.py 口径一致
    print("【基准复现】用本脚本的构建器重放三种表示方式")
    for name, g in (("A 纯文本", frozenset()),
                    ("B 内联声明", frozenset({"deps"})),
                    ("C 完整账本", frozenset(FIELDS))):
        r = evaluate(g, dialogues)
        print(f"  {name:<10} {r['tp']:>2}/{r['total']:<2}  检出 {r['recall']:>5.1f}%  "
              f"误报 {r['fp']:>2}  精确 {r['precision']:>5.1f}%")
    print()

    results = []
    for tag, train, hold in (("折 1", fold_a, fold_b), ("折 2", fold_b, fold_a)):
        print(f"【{tag}】训练 {[d['id'] for d in train]} → 留出 {[d['id'] for d in hold]}")
        r = run_fold(train, hold, args.budget)
        for row in r["log"]:
            mark = "接受" if row["accepted"] else "拒绝"
            print(f"  r{row['round']:<2} {row['move']:<28} "
                  f"公开 {row['pub']:>5.1f}%  私有 {row['priv']:>5.1f}%  {mark}"
                  + (f"  ({row['note']})" if row["note"] else ""))
        print(f"  → 终局：{' + '.join(FIELD_LABEL[f] for f in sorted(r['final'])) or '（空）'}")
        print(f"     公开 {r['pub']['recall']:.1f}% / 私有 {r['priv']['recall']:.1f}%，"
              f"评估 {r['spent']} 次")
        print()
        results.append({"fold": tag, **r, "final": sorted(r["final"])})

    os.makedirs(args.out, exist_ok=True)
    payload = {
        "budget": args.budget,
        "fields": FIELDS,
        "folds": results,
    }
    with open(os.path.join(args.out, "rsi_results.json"), "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)

    print("=" * 66)
    print("一句话结论")
    print("=" * 66)
    gains = [r["priv"]["recall"] for r in results]
    base = evaluate(frozenset(), dialogues)["recall"]
    print(f"从「什么都不记」({base:.1f}%) 出发，两折分别自推到 "
          f"{gains[0]:.1f}% 与 {gains[1]:.1f}%；"
          f"内层只用训练折筛候选，留出折只决定谁上位。")

    if all("alts" not in r["final"] for r in results):
        print()
        print("有一处值得记下：两折都没有采纳「替代支撑边」。")
        print("它不改变检出率，只改变结论的状态（invalidated 还是 degraded），")
        print("而评分函数只看检出率——所以搜索认为它没用。")
        print("评分函数看不见的价值，自我改进也发现不了。")

    ceiling = evaluate(frozenset(FIELDS), dialogues)
    print()
    print(f"参照：人工设计的完整账本（六个字段全记）同样是 "
          f"{ceiling['recall']:.1f}%，说明这个评测集上已经饱和，")
    print("自我改进的价值不在提分，而在「用更少的字段达到同样效果」。")
    print(f"结果写入 {os.path.join('results', 'rsi_results.json')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
