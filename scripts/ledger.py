#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""premise-ledger 内核：登记前提与结论、检测六类缺陷、计算失效级联。

纯标准库，无第三方依赖。所有输出为 JSON。
退出码：0 = 通过 / 成功，1 = 检查不通过，2 = 输入非法。
"""

import argparse
import json
import os
import sys
from collections import deque

SCHEMA_VERSION = "1.0"

PREMISE_ALIVE = ("unverified", "verified")
PREMISE_DEAD = ("refuted", "retracted")

CHECKS = {
    "orphan_claim": "孤儿结论",
    "orphan_input": "孤儿输入",
    "phantom_ref": "幽灵引用",
    "circular": "循环论证",
    "contamination": "污染传播",
    "drift": "前提漂移",
    "export_gate": "交付门禁",
}


def _reconfigure_stdio():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass


def emit(payload, code=0):
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    sys.stdout.flush()
    return code


def fail(msg, code=2):
    return emit({"ok": False, "error": msg}, code)


def _issue(kind, severity, ids, message, fix=""):
    return {
        "type": kind,
        "label": CHECKS.get(kind, kind),
        "severity": severity,
        "ids": ids,
        "message": message,
        "fix": fix,
    }


def _num(raw):
    if raw is None:
        return None
    text = str(raw).strip()
    if text == "":
        return None
    try:
        return int(text)
    except ValueError:
        return float(text)


def _split(raw):
    if not raw:
        return []
    return [x.strip() for x in raw.replace("，", ",").split(",") if x.strip()]


class Ledger:
    def __init__(self, path):
        self.path = path
        self.data = self._load()

    # ---------- 持久化 ----------

    def _load(self):
        if os.path.exists(self.path):
            with open(self.path, encoding="utf-8") as fh:
                data = json.load(fh)
            data.setdefault("version", SCHEMA_VERSION)
            data.setdefault("task", "")
            data.setdefault("nodes", {})
            data.setdefault("seq", {"A": 0, "C": 0})
            data.setdefault("events", [])
            return data
        return {"version": SCHEMA_VERSION, "task": "", "nodes": {}, "seq": {"A": 0, "C": 0}, "events": []}

    def save(self):
        parent = os.path.dirname(os.path.abspath(self.path))
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(self.data, fh, ensure_ascii=False, indent=2)
        return self.path

    def _next_id(self, prefix):
        n = int(self.data["seq"].get(prefix, 0)) + 1
        self.data["seq"][prefix] = n
        return f"{prefix}{n}"

    def _log(self, action, nid, turn=0, reason=""):
        self.data["events"].append({"t": action, "id": nid, "turn": turn, "reason": reason})

    # ---------- 查询 ----------

    def node(self, nid):
        return self.data["nodes"].get(nid)

    def resolve(self, symbol):
        if not symbol:
            return None
        for nid, n in self.data["nodes"].items():
            if n.get("symbol") == symbol:
                return nid
        return None

    def alive(self, nid, _stack=frozenset()):
        n = self.node(nid)
        if n is None or n.get("retracted"):
            return False
        if n["kind"] == "premise":
            return n["status"] in PREMISE_ALIVE
        if nid in _stack:
            return False
        stack = _stack | {nid}
        if n["requires"] and all(self.alive(d, stack) for d in n["requires"]):
            return True
        if n["alts"] and all(self.alive(d, stack) for d in n["alts"]):
            return True
        return False

    def is_strong(self, nid, _stack=frozenset()):
        n = self.node(nid)
        if n is None or n.get("retracted"):
            return False
        if n["kind"] == "premise":
            return n["status"] == "verified"
        return self.claim_status(nid, _stack) == "active"

    def claim_status(self, cid, _stack=frozenset()):
        n = self.node(cid)
        if n is None or n.get("retracted"):
            return "invalidated"
        if cid in _stack:
            return "invalidated"
        stack = _stack | {cid}
        if n["requires"] and all(self.alive(d, stack) for d in n["requires"]):
            strong = all(self.is_strong(d, stack) for d in n["requires"])
            return "active" if strong else "degraded"
        if n["alts"] and all(self.alive(d, stack) for d in n["alts"]):
            return "degraded"
        return "invalidated"

    def is_live(self, nid):
        """该节点是否仍"在账上有效"：已撤回/已作废的条目视为历史，不参与冲突比较。

        用途：前提被更正时走 retract + 重新登记，新旧两条同 symbol 不应被判漂移；
        结论被显式撤回后，也不应继续触发污染告警——否则账本一旦有历史就永久不可交付。
        """
        n = self.node(nid)
        if n is None:
            return False
        if n["kind"] == "premise":
            return n["status"] not in PREMISE_DEAD
        if n.get("retracted"):
            return False
        return self.claim_status(nid) != "invalidated"

    def live_claims(self):
        return [cid for cid, n in self.data["nodes"].items()
                if n["kind"] == "claim" and self.is_live(cid)]

    def deps(self, nid, kind=None):
        out, seen, queue = set(), set(), deque([nid])
        while queue:
            cur = queue.popleft()
            n = self.node(cur)
            if n is None:
                continue
            for d in list(n.get("requires", [])) + list(n.get("alts", [])):
                if d in seen or d not in self.data["nodes"]:
                    continue
                seen.add(d)
                out.add(d)
                queue.append(d)
        if kind:
            out = {i for i in out if self.data["nodes"][i]["kind"] == kind}
        return out

    def find_cycle(self):
        nodes = self.data["nodes"]
        WHITE, GRAY, BLACK = 0, 1, 2
        color = {nid: WHITE for nid in nodes}
        path = []

        def dfs(nid):
            color[nid] = GRAY
            path.append(nid)
            for d in list(nodes[nid].get("requires", [])) + list(nodes[nid].get("alts", [])):
                if d not in nodes:
                    continue
                if color[d] == GRAY:
                    return path[path.index(d):] + [d]
                if color[d] == WHITE:
                    found = dfs(d)
                    if found:
                        return found
            path.pop()
            color[nid] = BLACK
            return None

        for nid in nodes:
            if color[nid] == WHITE:
                found = dfs(nid)
                if found:
                    return found
        return None

    # ---------- 写入 ----------

    def add_premise(self, text, symbol="", value=None, unit="", conf=0.5, src="user", turn=0, note=""):
        nid = self._next_id("A")
        self.data["nodes"][nid] = {
            "id": nid,
            "kind": "premise",
            "text": text,
            "symbol": symbol,
            "value": value,
            "unit": unit,
            "status": "unverified",
            "conf": float(conf),
            "src": src,
            "turn": turn,
            "updated_turn": turn,
            "requires": [],
            "alts": [],
            "inputs": [],
            "unresolved": [],
            "exported": False,
            "retracted": False,
            "evidence": [],
            "note": note,
        }
        self._log("add_premise", nid, turn)
        return nid

    def add_claim(self, text, symbol="", value=None, unit="", inputs=None, requires=None,
                  alts=None, turn=0, exported=False, note=""):
        nid = self._next_id("C")
        req = list(requires or [])
        unresolved = []
        for sym in inputs or []:
            hit = self.resolve(sym)
            if hit and hit not in req:
                req.append(hit)
            elif not hit:
                unresolved.append(sym)
        self.data["nodes"][nid] = {
            "id": nid,
            "kind": "claim",
            "text": text,
            "symbol": symbol,
            "value": value,
            "unit": unit,
            "status": "active",
            "conf": 0.0,
            "src": "derived",
            "turn": turn,
            "updated_turn": turn,
            "requires": req,
            "alts": list(alts or []),
            "inputs": list(inputs or []),
            "unresolved": unresolved,
            "exported": bool(exported),
            "retracted": False,
            "evidence": [],
            "note": note,
        }
        self._log("add_claim", nid, turn)
        return nid

    def verify(self, nid, evidence="", conf=0.95, turn=0):
        n = self.node(nid)
        if n is None:
            return None
        if n["kind"] != "premise":
            return None
        n["status"] = "verified"
        n["conf"] = 1.0
        n["updated_turn"] = turn
        if evidence:
            n["evidence"].append(evidence)
        self._log("verify", nid, turn, evidence)
        return n

    def set_exported(self, nid, exported=True, turn=0):
        n = self.node(nid)
        if n is None:
            return None
        n["exported"] = bool(exported)
        n["updated_turn"] = turn
        self._log("export" if exported else "unexport", nid, turn)
        return n

    def retract(self, nid, reason="", turn=0):
        n = self.node(nid)
        if n is None:
            return None
        before = {c: self.claim_status(c) for c, x in self.data["nodes"].items() if x["kind"] == "claim"}
        if n["kind"] == "premise":
            n["status"] = "retracted"
        else:
            n["retracted"] = True
        n["updated_turn"] = turn
        self._log("retract", nid, turn, reason)
        after = {c: self.claim_status(c) for c, x in self.data["nodes"].items() if x["kind"] == "claim"}
        impact = []
        for cid in before:
            if before[cid] != after[cid]:
                impact.append({"id": cid, "from": before[cid], "to": after[cid]})
        return {"id": nid, "impact": impact, "snapshot": after}

    # ---------- 检查 ----------

    def check(self):
        nodes = self.data["nodes"]
        issues = []

        for cid, c in nodes.items():
            if c["kind"] != "claim" or c.get("retracted"):
                continue
            if not c["requires"] and not c["alts"]:
                issues.append(_issue(
                    "orphan_claim", "error", [cid],
                    f"{cid}「{c['text']}」没有任何依赖，是凭空生成的结论。",
                    "补上它依赖的前提：--depends A1,A2 或 --alts …",
                ))

        for cid, c in nodes.items():
            if c["kind"] != "claim" or c.get("retracted"):
                continue
            for sym in c.get("unresolved", []):
                issues.append(_issue(
                    "orphan_input", "error", [cid],
                    f"{cid} 用了「{sym}」，但账本里没有任何节点提供这个量（静默前提）。",
                    f"先登记一条带 --symbol {sym} 的前提，或删掉这个输入。",
                ))

        for nid, n in nodes.items():
            for d in list(n.get("requires", [])) + list(n.get("alts", [])):
                if d not in nodes:
                    issues.append(_issue(
                        "phantom_ref", "error", [nid],
                        f"{nid} 引用了不存在的 {d}。",
                        "检查编号；编号不会被复用，确认是否登记失败。",
                    ))

        cycle = self.find_cycle()
        if cycle:
            issues.append(_issue(
                "circular", "error", cycle,
                "依赖成环：" + " → ".join(cycle) + "，这是循环论证。",
                "断掉其中一条边，或把被循环依赖的结论降为前提。",
            ))

        for cid, c in nodes.items():
            if c["kind"] != "claim" or c.get("retracted"):
                continue
            dead = [d for d in sorted(self.deps(cid, "premise")) if nodes[d]["status"] in PREMISE_DEAD]
            if not dead:
                continue
            state = self.claim_status(cid)
            if state == "invalidated":
                issues.append(_issue(
                    "contamination", "error", [cid] + dead,
                    f"{cid} 依赖的前提 {', '.join(dead)} 已失效，结论本身也已作废。",
                    "重新推导，或撤回该结论。",
                ))
            else:
                issues.append(_issue(
                    "contamination", "warning", [cid] + dead,
                    f"{cid} 依赖链上的 {', '.join(dead)} 已失效，现由替代支撑维持（状态 {state}）。",
                    "确认替代支撑确实成立；对外引用时须注明降级。",
                ))

        by_symbol = {}
        for nid, n in nodes.items():
            sym = n.get("symbol")
            if sym and self.is_live(nid):
                by_symbol.setdefault(sym, []).append(nid)
        for sym, ids in by_symbol.items():
            variants = {(nodes[i].get("value"), nodes[i].get("text")) for i in ids}
            if len(variants) > 1:
                issues.append(_issue(
                    "drift", "error", ids,
                    f"「{sym}」被赋予了 {len(variants)} 个不同取值或陈述（{', '.join(ids)}），前提漂移。",
                    "保留一个权威取值；若是有意更正，先 retract 旧条目再登记新的。",
                ))

        for cid, c in nodes.items():
            if c["kind"] != "claim" or not c.get("exported") or c.get("retracted"):
                continue
            state = self.claim_status(cid)
            bad = [d for d in sorted(self.deps(cid, "premise")) if nodes[d]["status"] != "verified"]
            if bad or state != "active":
                issues.append(_issue(
                    "export_gate", "error", [cid] + bad,
                    f"{cid} 已标记对外输出，但上游 {len(bad)} 条前提未核实，或自身状态为 {state}，不允许交付。",
                    "先核验上游前提，或撤回对外输出标记。",
                ))

        ok = not any(i["severity"] == "error" for i in issues)
        premises = [n for n in nodes.values() if n["kind"] == "premise"]
        claims = [n for n in nodes.values() if n["kind"] == "claim"]
        states = [self.claim_status(c["id"]) for c in claims]
        return {
            "ok": ok,
            "task": self.data.get("task", ""),
            "issues": issues,
            "stats": {
                "premises": len(premises),
                "premises_verified": sum(1 for p in premises if p["status"] == "verified"),
                "claims": len(claims),
                "claims_active": states.count("active"),
                "claims_degraded": states.count("degraded"),
                "claims_invalidated": states.count("invalidated"),
            },
            "exit_hint": "可以交付" if ok else "不可交付：存在 error 级问题",
        }

    # ---------- 输出 ----------

    def cite(self, cid):
        n = self.node(cid)
        if n is None:
            return None
        state = self.claim_status(cid) if n["kind"] == "claim" else n["status"]
        deps = sorted(self.deps(cid)) if n["kind"] == "claim" else []
        dead = [d for d in deps if self.node(d)["kind"] == "premise"
                and self.node(d)["status"] in PREMISE_DEAD]
        unverified = [d for d in deps if self.node(d)["kind"] == "premise"
                      and self.node(d)["status"] == "unverified"]

        if n["kind"] == "premise":
            usable = state in PREMISE_ALIVE
            level = {"verified": "可用", "unverified": "未核实"}.get(state, "不可用")
            via_alts = False
        else:
            usable = state != "invalidated"
            req_ok = bool(n["requires"]) and all(self.alive(d) for d in n["requires"])
            via_alts = state == "degraded" and not req_ok
            if not usable:
                level = "不可用"
            elif state == "active" and not dead and not unverified:
                level = "可用"
            else:
                level = "降级可用"

        lines = [f"[{cid}] {n['text']}"]
        if n.get("value") is not None:
            lines.append(f"取值：{n['value']} {n.get('unit') or ''}".rstrip())
        lines.append(f"状态：{state}　引用级别：{level}")
        if deps:
            lines.append("依赖：" + "、".join(deps))
        if dead:
            lines.append("已失效前提：" + "、".join(
                f"{d}（{self.node(d)['text']}）" for d in dead))
        if unverified:
            lines.append("未核实前提：" + "、".join(
                f"{d}（{self.node(d)['text']}）" for d in unverified))
        if level == "降级可用":
            weak_claims = [d for d in deps if self.node(d)["kind"] == "claim"
                           and self.claim_status(d) != "active"]
            if dead:
                note = "依赖链上 " + "、".join(dead) + " 已失效，结论由替代支撑维持，引用须注明降级"
            elif unverified:
                note = "上游 " + "、".join(unverified) + " 未核实，引用须注明置信度"
            elif weak_claims:
                note = "上游结论 " + "、".join(weak_claims) + " 处于降级状态，引用须注明降级"
            else:
                note = "结论处于降级状态，引用须注明"
            lines.append("注意：" + note)
        if level == "不可用":
            reasons = []
            if state == "invalidated":
                reasons.append("依赖链已断")
            if dead:
                reasons.append("前提 " + "、".join(dead) + " 已失效且无替代支撑")
            lines.append("不可引用原因：" + "；".join(reasons or [f"状态为 {state}"]))
        return {
            "id": cid,
            "state": state,
            "level": level,
            "usable": usable,
            "via_alts": via_alts,
            "card": "\n".join(lines),
            "deps": deps,
            "dead_deps": dead,
            "unverified_deps": unverified,
        }

    def export(self, fmt="mermaid"):
        nodes = self.data["nodes"]
        if fmt == "mermaid":
            out = ["flowchart LR"]
            for nid, n in nodes.items():
                if n["kind"] == "premise":
                    mark = "ok" if n["status"] == "verified" else ("dead" if n["status"] in PREMISE_DEAD else "warn")
                    tail = {"ok": "已核", "dead": "已废", "warn": "未核"}[mark]
                    out.append(f'  {nid}["{nid} {n["text"]}<br/>{tail}"]:::{mark}')
                else:
                    mark = {"active": "ok", "degraded": "warn", "invalidated": "dead"}[self.claim_status(nid)]
                    out.append(f'  {nid}["{nid} {n["text"]}<br/>{self.claim_status(nid)}"]:::{mark}')
            for nid, n in nodes.items():
                for d in n.get("requires", []):
                    if d in nodes:
                        out.append(f"  {d} --> {nid}")
                for d in n.get("alts", []):
                    if d in nodes:
                        out.append(f"  {d} -.替代.-> {nid}")
            out.extend([
                "  classDef ok fill:#EAF3DE,stroke:#639922,color:#3B6D11",
                "  classDef warn fill:#FAEEDA,stroke:#EF9F27,color:#854F0B",
                "  classDef dead fill:#FCEBEB,stroke:#E24B4A,color:#A32D2D",
            ])
            content = "\n".join(out)
        elif fmt == "md":
            rows = ["| 编号 | 类型 | 陈述 | 取值 | 依赖 | 状态 |", "|---|---|---|---|---|---|"]
            for nid, n in nodes.items():
                state = "失效" if n.get("retracted") else (
                    n["status"] if n["kind"] == "premise" else self.claim_status(nid))
                val = "" if n.get("value") is None else f"{n['value']} {n.get('unit') or ''}".strip()
                rows.append(f"| {nid} | {'前提' if n['kind'] == 'premise' else '结论'} | {n['text']} | {val} | "
                            f"{', '.join(n.get('requires', []) + n.get('alts', []))} | {state} |")
            content = "\n".join(rows)
        else:
            return None
        return {"format": fmt, "content": content}

    def show(self):
        rows = []
        for nid, n in self.data["nodes"].items():
            if n["kind"] == "premise":
                state = n["status"]
            else:
                state = "invalidated" if n.get("retracted") else self.claim_status(nid)
            rows.append({
                "id": nid,
                "kind": n["kind"],
                "text": n["text"],
                "value": n.get("value"),
                "unit": n.get("unit"),
                "state": state,
                "conf": n.get("conf"),
                "requires": n.get("requires", []),
                "alts": n.get("alts", []),
                "exported": n.get("exported", False),
            })
        return {"task": self.data.get("task", ""), "count": len(rows), "nodes": rows}


def main(argv=None):
    _reconfigure_stdio()
    parser = argparse.ArgumentParser(prog="ledger", description="前提-结论账本内核")
    parser.add_argument("--ledger", default=".ledger.json", help="账本文件路径")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_new = sub.add_parser("new", help="新建账本")
    p_new.add_argument("--task", default="")
    p_new.add_argument("--force", action="store_true")

    p_pre = sub.add_parser("add-premise", help="登记一条前提")
    p_pre.add_argument("--text", required=True)
    p_pre.add_argument("--symbol", default="")
    p_pre.add_argument("--value", default=None)
    p_pre.add_argument("--unit", default="")
    p_pre.add_argument("--conf", type=float, default=0.5)
    p_pre.add_argument("--src", default="user")
    p_pre.add_argument("--turn", type=int, default=0)
    p_pre.add_argument("--note", default="")

    p_clm = sub.add_parser("add-claim", help="登记一条结论")
    p_clm.add_argument("--text", required=True)
    p_clm.add_argument("--symbol", default="")
    p_clm.add_argument("--value", default=None)
    p_clm.add_argument("--unit", default="")
    p_clm.add_argument("--inputs", default="", help="消费的符号名，逗号分隔")
    p_clm.add_argument("--depends", default="", help="必需依赖 id，逗号分隔")
    p_clm.add_argument("--alts", default="", help="替代支撑组 id，逗号分隔")
    p_clm.add_argument("--turn", type=int, default=0)
    p_clm.add_argument("--exported", action="store_true")
    p_clm.add_argument("--note", default="")

    p_v = sub.add_parser("verify", help="核验一条前提")
    p_v.add_argument("--id", required=True)
    p_v.add_argument("--evidence", default="")
    p_v.add_argument("--conf", type=float, default=0.95)
    p_v.add_argument("--turn", type=int, default=0)

    p_r = sub.add_parser("retract", help="撤回前提/结论并计算级联")
    p_r.add_argument("--id", required=True)
    p_r.add_argument("--reason", default="")
    p_r.add_argument("--turn", type=int, default=0)

    sub.add_parser("check", help="六类病体检 + 交付门禁")
    p_c = sub.add_parser("cite", help="生成可引用的结论卡片")
    p_c.add_argument("--id", required=True)
    sub.add_parser("show", help="列出账本全部节点")
    p_e = sub.add_parser("export", help="导出依赖图")
    p_e.add_argument("--format", choices=["mermaid", "md"], default="mermaid")

    args = parser.parse_args(argv)

    if args.cmd == "new":
        if os.path.exists(args.ledger) and not args.force:
            return fail(f"账本已存在：{args.ledger}（加 --force 覆盖）")
        led = Ledger(args.ledger)
        led.data = {"version": SCHEMA_VERSION, "task": args.task, "nodes": {},
                    "seq": {"A": 0, "C": 0}, "events": []}
        led.save()
        return emit({"ok": True, "ledger": os.path.abspath(args.ledger), "task": args.task})

    led = Ledger(args.ledger)

    if args.cmd == "add-premise":
        if not (args.text or "").strip():
            return fail("前提陈述不能为空")
        nid = led.add_premise(args.text, args.symbol, _num(args.value), args.unit,
                              args.conf, args.src, args.turn, args.note)
        led.save()
        return emit({"ok": True, "id": nid, "kind": "premise", "status": "unverified",
                     "hint": f"引用它时写 {nid}"})

    if args.cmd == "add-claim":
        if not (args.text or "").strip():
            return fail("结论陈述不能为空")
        nid = led.add_claim(args.text, args.symbol, _num(args.value), args.unit,
                            _split(args.inputs), _split(args.depends), _split(args.alts),
                            args.turn, args.exported, args.note)
        node = led.node(nid)
        led.save()
        payload = {"ok": True, "id": nid, "kind": "claim",
                   "requires": node["requires"], "alts": node["alts"],
                   "status": led.claim_status(nid)}
        if node["unresolved"]:
            payload["warning"] = f"以下输入找不到提供者：{', '.join(node['unresolved'])}（孤儿输入）"
        return emit(payload)

    if args.cmd == "verify":
        if led.node(args.id) is None:
            return fail(f"未知 id：{args.id}")
        if led.node(args.id)["kind"] != "premise":
            return fail(f"{args.id} 是结论，不能直接核验；结论只能由依赖推导")
        led.verify(args.id, args.evidence, args.conf, args.turn)
        led.save()
        return emit({"ok": True, "id": args.id, "status": "verified", "conf": 1.0})

    if args.cmd == "retract":
        if led.node(args.id) is None:
            return fail(f"未知 id：{args.id}")
        result = led.retract(args.id, args.reason, args.turn)
        led.save()
        flagged = [i for i in result["impact"]]
        return emit({
            "ok": True,
            "retracted": args.id,
            "reason": args.reason,
            "changed": flagged,
            "unchanged": sorted(c for c in result["snapshot"] if c not in {x["id"] for x in flagged}),
            "summary": (f"撤销 {args.id}：{len(flagged)} 条结论状态改变，"
                        f"{len(result['snapshot']) - len(flagged)} 条不受影响"),
        })

    if args.cmd == "check":
        result = led.check()
        return emit(result, 0 if result["ok"] else 1)

    if args.cmd == "cite":
        card = led.cite(args.id)
        if card is None:
            return fail(f"未知 id：{args.id}")
        return emit({"ok": True, **card})

    if args.cmd == "show":
        return emit({"ok": True, **led.show()})

    if args.cmd == "export":
        out = led.export(args.format)
        if out is None:
            return fail(f"不支持的格式：{args.format}")
        return emit({"ok": True, **out})

    return fail("未知命令")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as exc:  # 任何未预期异常都必须变成结构化输出
        sys.exit(fail(f"输入非法：{type(exc).__name__}: {exc}"))
