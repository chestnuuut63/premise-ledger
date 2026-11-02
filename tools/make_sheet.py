#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成人工基线测评材料。

产出两份：
  results/human_baseline_sheet.md  打印给同学填（不含答案）
  results/human_filled.csv         填完的数字表，交给 evaluate.py --human
答案单独放在 results/ANSWER_KEY.md，做测试时不要打开。
"""

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "results")


def main():
    with open(os.path.join(ROOT, "dataset", "dialogues.json"), encoding="utf-8") as fh:
        data = json.load(fh)
    dialogues = data["dialogues"]
    os.makedirs(OUT, exist_ok=True)

    lines = [
        "# 人工基线测评表",
        "",
        "**说明**：下面是 10 段真实风格的多轮对话。每段里有 0–2 处「站不住」的地方",
        "（前提被悄悄改掉、结论没有依据、互相循环论证、引用了不存在的东西等）。",
        "",
        "请像平时审稿一样读，**不许使用任何工具**，把你认为有问题的地方写下来：",
        "指出哪一句、为什么站不住。完全看不出来就写「没发现」。",
        "",
        "每段请记一下用时（秒）。全部做完大约需要 25–40 分钟，中途不要看答案。",
        "",
        "---",
        "",
    ]

    for i, d in enumerate(dialogues, 1):
        lines.append(f"## {i}. {d['id']} {d['title']}（{d['domain']}）")
        lines.append("")
        for t in d["turns"]:
            who = "**用户**" if t["who"] == "用户" else "助手"
            lines.append(f"{t['n']}. {who}：{t['text']}")
        lines.append("")
        lines.append("你发现的问题：")
        lines.append("")
        lines.append("1. ")
        lines.append("2. ")
        lines.append("")
        lines.append("用时：______ 秒")
        lines.append("")
        lines.append("---")
        lines.append("")

    lines.extend([
        "## 汇总",
        "",
        "全部做完后，打开 `ANSWER_KEY.md` 对照，把每段的数字填进 `human_filled.csv`：",
        "",
        "```",
        "id,hit,false_alarm,seconds",
        "D01,1,0,180",
        "...",
        "```",
        "",
        "- `hit`：你写的问题里，和答案对上的条数",
        "- `false_alarm`：你写了但答案里没有的条数（自行判断是否合理也算误报）",
        "",
        "然后运行：`python evaluate.py --human results/human_filled.csv`",
        "",
    ])

    sheet_path = os.path.join(OUT, "human_baseline_sheet.md")
    with open(sheet_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))

    with open(os.path.join(OUT, "human_filled.csv"), "w", encoding="utf-8") as fh:
        fh.write("id,hit,false_alarm,seconds\n")
        for d in dialogues:
            fh.write(f"{d['id']},0,0,0\n")

    key = ["# 答案键（测评时不要打开）", ""]
    for d in dialogues:
        key.append(f"## {d['id']} {d['title']}")
        key.append("")
        if not d.get("planted"):
            key.append("- 本段无埋点")
        for p in d.get("planted", []):
            key.append(f"- **{p['type']}** {'/'.join(p['ids'])}：{p['note']}")
        key.append("")
    with open(os.path.join(OUT, "ANSWER_KEY.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(key))

    print(f"测评表：{sheet_path}")
    print(f"填空表：{os.path.join(OUT, 'human_filled.csv')}")
    print(f"答案键：{os.path.join(OUT, 'ANSWER_KEY.md')}（做测试时不要打开）")
    print(f"共 {len(dialogues)} 段，{sum(len(d.get('planted', [])) for d in dialogues)} 处埋点")


if __name__ == "__main__":
    main()
