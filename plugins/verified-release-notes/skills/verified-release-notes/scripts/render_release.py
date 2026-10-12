# -*- coding: utf-8 -*-
"""
render_release.py —— 合并 LLM 产物、渲染发版说明、并自动过校验闸门

在整体流程中的位置（第 3 步）：
    parse.py          -> facts.json（结构事实）
    Agent(LLM)        -> llm_overrides.json（语义兜底 + 中文措辞）
    render_release.py -> 本脚本：应用 overrides、渲染 Markdown、调用 verify 校验、落盘

两条输入：
    --facts      parse.py 产出的事实 JSON
    --overrides  可选。Agent 写出的 llm_overrides.json，结构见 references/schemas.md：
                 semantic: {原始标题: {type, include, reason}}  —— 只作用于 type=unknown 的提交
                 wording : {原始标题: 中文措辞}                  —— 作用于全部应收录条目
                 缺省时退化为直接用原始标题渲染（保证任何提交都有条目，不会静默丢失）。

关键约束：
    semantic 修正会改变类型集合，必须据此重算版本号，否则会出现"改了类型却没改版本"。
    渲染后立即调用 verify；--strict 下校验不通过则以非零退出码结束，交由 Agent 回到措辞步骤重写。

    重要：语义修正改变了类型/收录/版本号，必须把"合并后的事实"落盘（--facts-out），
    否则下游若仍拿原始 facts.json 复核，会把已被语义收录的提交误判为 INTERNAL_LEAK。
"""
import argparse
import json
from pathlib import Path

import parse as P
import verify as V

# 渲染顺序与章节标题（改这里即可调整章节体系，需与 verify.ALLOWED_SECTIONS 保持一致）
SECTION_TITLES = [("breaking", "破坏性变更"), ("feat", "新功能"), ("fix", "修复")]


def apply_semantic(facts, overrides):
    """
    LLM 语义兜底：把脚本归为 unknown 的提交，按 semantic 表升级为具体类型。
    参数: facts 事实 dict（原地修改）；overrides 覆盖表
    返回: 被修正的提交列表（供审计"LLM 具体改了什么"）
    说明: 只对 type=='unknown' 的提交生效，避免覆盖脚本已给出的确定性判定。
    """
    semantic = overrides.get("semantic", {})
    fixes = []
    for c in facts["commits"]:
        ov = semantic.get(c["message"])
        if ov and c["type"] == "unknown":
            c["type"] = ov["type"]
            c["include"] = ov.get("include", P.include_of(ov["type"]))
            c["source"] = "llm"
            fixes.append({"message": c["message"], "to": ov["type"],
                          "reason": ov.get("reason", "")})
    # 类型集合变了，必须重算版本号与统计，保证 facts 自洽
    facts["types"] = sorted({c["type"] for c in facts["commits"]})
    facts["next"] = P.suggest_version(facts["prev"], set(facts["types"]))
    facts["counts"]["included"] = sum(1 for c in facts["commits"] if c["include"])
    facts["counts"]["unknown"] = sum(1 for c in facts["commits"] if c["type"] == "unknown")
    return fixes


def wording_of(message, overrides):
    """取 LLM 中文措辞；缺省回退到原始标题，保证条目永不静默丢失。"""
    return overrides.get("wording", {}).get(message, message)


def render(version, commits, overrides):
    """
    按章节渲染 Markdown，条目尾部用 HTML 注释携带 sha 锚点。
    说明: sha 锚点既供 verify 定位/覆盖度校验，也供人工溯源到原始提交。
    """
    lines = ["# Changelog", "", "## %s" % version, ""]
    for key, title in SECTION_TITLES:
        items = [c for c in commits if c["include"] and c["type"] == key]
        if not items:
            continue
        lines.append("### %s" % title)
        for c in items:
            lines.append("- %s <!-- sha:%s -->" % (wording_of(c["message"], overrides), c["sha"]))
        lines.append("")
    return "\n".join(lines)


def load_overrides(path):
    """读取 overrides；未提供路径时返回空覆盖表（渲染回退为原始标题）。"""
    if not path:
        return {"semantic": {}, "wording": {}}
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main():
    ap = argparse.ArgumentParser(description="渲染发版说明并自动校验")
    ap.add_argument("--facts", required=True, help="parse.py 生成的事实 JSON")
    ap.add_argument("--overrides", default=None, help="Agent 写出的 llm_overrides.json（可选）")
    ap.add_argument("--out", required=True, help="渲染结果 Markdown 输出路径")
    ap.add_argument("--report", default=None, help="校验报告 JSON 输出路径（可选）")
    ap.add_argument("--facts-out", default=None,
                    help="合并后事实 JSON 输出路径，默认与 --out 同名（后缀改为 .facts.json）")
    ap.add_argument("--strict", action="store_true", help="校验不通过时以非零退出码结束")
    a = ap.parse_args()

    facts = json.loads(Path(a.facts).read_text(encoding="utf-8"))
    overrides = load_overrides(a.overrides)

    fixes = apply_semantic(facts, overrides)
    md = render(facts["next"], facts["commits"], overrides)
    Path(a.out).write_text(md, encoding="utf-8")

    # 落盘合并后的事实，保证下游 verify / cut_release 与本次渲染用的是同一份基准
    # 默认按 --out 文件名派生（附 .facts.json），避免多版本渲染互相覆盖
    facts_out = Path(a.facts_out) if a.facts_out \
        else Path(a.out).with_suffix(".facts.json")
    facts_out.write_text(json.dumps(facts, ensure_ascii=False, indent=2), encoding="utf-8")

    res = V.verify(md, facts)
    report = {
        "tag": facts["next"],
        "prev": facts["prev"],
        "semantic_fixes": fixes,
        "counts": facts["counts"],
        "verify": res,
    }
    if a.report:
        Path(a.report).write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                  encoding="utf-8")

    print("[%s] prev=%s semantic_fixes=%d verify_ok=%s issues=%d warn=%d"
          % (facts["next"], facts["prev"], len(fixes), res["ok"],
             len(res["issues"]), len(res["warnings"])))
    if not res["ok"]:
        for i in res["issues"]:
            print("  ISSUE %s: %s" % (i["code"], i["detail"]))
    for w in res["warnings"]:
        print("  WARN  %s: %s" % (w["code"], w["detail"]))

    if a.strict and not res["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()