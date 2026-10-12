# -*- coding: utf-8 -*-
"""
parse.py —— 把"不规范的中文提交"结构化为事实 JSON（确定性解析层）

定位（本技能三条铁律之一：结构归脚本、措辞归 LLM、发版前必过校验）：
    本模块只做"确定性、可复核"的部分：判定每条提交的类型与是否用户可见，
    并据 prev tag 推导下一个语义化版本号。措辞润色交给宿主 Agent（LLM 层），
    校验交给 verify.py。这样即使措辞出问题，覆盖度/类型/版本号这些硬事实仍可被校验。

对外主要函数：
    classify(message) -> str                单条提交的类型判定
    include_of(ctype) -> bool               该类型是否写入发版说明
    suggest_version(prev_tag, types) -> str 语义化版本号推导
    collect(repo, frm, to) -> dict          采集区间内提交并结构化

命令行：
    python parse.py --repo <仓库路径> [--from <起始tag>] [--to <结束ref>] [--out facts.json]
    --from 缺省时自动取 --to 可达的最近一个 tag；--to 缺省为 HEAD。
"""
import argparse
import json
import re
import subprocess
from pathlib import Path

# ---------------------------------------------------------------------------
# 关键词表：按"竞争优先级"排列，先命中先归类。
# breaking/fix 刻意排在 feat 之前：像"修复导出乱码"这类既像修复又含动作词的句子，
# 归到 fix 更符合用户预期；含"不兼容/破坏性"的则必须优先判为 breaking。
# ---------------------------------------------------------------------------
BREAKING_KW = ["不兼容", "破坏性", "不向下兼容", "breaking", "需迁移", "迁移脚本"]
FIX_KW = ["修复", "修正", "纠正", "fix", "bug", "错误", "失败", "报错", "异常",
          "乱码", "超时", "崩溃", "不生效", "失效", "无响应", "错乱"]
FEAT_KW = ["新增", "增加", "支持", "新功能", "feature", "上线", "add "]
INTERNAL_KW = ["更新依赖", "依赖", "格式化", "加个日志", "日志", "临时", "readme",
               "升级", "重构", "注释", "无用代码", "无用依赖", "废弃", "移除",
               "样式", "chore", "docs", "build", "ci", "test", "refactor", "style"]

# 写入发版说明的类型（用户可见）
VISIBLE_TYPES = ("breaking", "fix", "feat")


def classify(message):
    """
    判定单条提交类型（优先级瀑布）。
    参数: message —— git 提交标题（subject）
    返回: 'breaking' | 'fix' | 'feat' | 'internal' | 'unknown'
    说明: 采用"先命中先归类"，保证同一句里多类关键词共存时结果稳定可复现。
    """
    m = message.lower()
    for kw in BREAKING_KW:
        if kw in m:
            return "breaking"
    for kw in FIX_KW:
        if kw in m:
            return "fix"
    for kw in FEAT_KW:
        if kw in m:
            return "feat"
    for kw in INTERNAL_KW:
        if kw in m:
            return "internal"
    return "unknown"


def include_of(ctype):
    """用户可见性判定：breaking/fix/feat 进发版说明，其余（含 unknown）默认不进。"""
    return ctype in VISIBLE_TYPES


def suggest_version(prev_tag, types):
    """
    依据 prev tag 与本次提交类型集合推导下一个版本号（SemVer）。
    规则: 含 breaking -> major+1；否则含 feat -> minor+1；否则 patch+1。
    参数: prev_tag 形如 'v1.4.0'；types 为类型集合（可迭代）
    返回: 形如 'v1.5.0'
    """
    m = re.match(r"v?(\d+)\.(\d+)\.(\d+)", str(prev_tag).strip())
    if not m:
        raise ValueError("无法解析版本号: %s" % prev_tag)
    major, minor, patch = (int(x) for x in m.groups())
    if "breaking" in types:
        return "v%d.0.0" % (major + 1)
    if "feat" in types:
        return "v%d.%d.0" % (major, minor + 1)
    return "v%d.%d.%d" % (major, minor, patch + 1)


def _git(args, repo):
    """执行 git 命令并返回 stdout；非零退出即抛错，避免把失败当成空结果。"""
    r = subprocess.run(["git", "-C", str(repo)] + args,
                       capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        raise RuntimeError("git %s failed: %s" % (" ".join(args), r.stderr))
    return r.stdout


def previous_tag(repo, to):
    """
    找出 --to 可达的最近一个 tag，作为区间起点（--from 缺省时使用）。
    参数: repo 仓库路径；to 结束 ref（如 HEAD 或 tag）
    返回: 最近的 tag 名（排除 to 自身）
    """
    raw = _git(["tag", "--merged", to, "--sort=-v:refname"], repo)
    for t in raw.splitlines():
        t = t.strip()
        if t and t != to:
            return t
    raise RuntimeError("在 %s 上找不到可作为起点的 tag，请显式指定 --from" % to)


def collect(repo, frm, to):
    """
    采集 frm..to 区间内的提交并结构化。
    参数: repo 仓库路径; frm 起始 tag; to 结束 ref
    返回: dict —— 含 prev/next 版本、类型集合、逐条明细、统计
    说明: 每条提交带 include 与否的判定，以及短 sha（供后续校验定位/溯源）。
    """
    raw = _git(["log", "--no-merges", "--pretty=format:%H%x09%s", "%s..%s" % (frm, to)], repo)
    commits = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        sha, subject = line.split("\t", 1)
        ctype = classify(subject)
        commits.append({
            "sha": sha[:10],
            "message": subject,
            "type": ctype,
            "include": include_of(ctype),
            "source": "script",
        })
    commits.reverse()  # git log 默认倒序，翻正为提交先后顺序，便于阅读
    types = {c["type"] for c in commits}
    return {
        "prev": frm,
        "next": suggest_version(frm, types),
        "types": sorted(types),
        "commits": commits,
        "counts": {
            "total": len(commits),
            "included": sum(1 for c in commits if c["include"]),
            "unknown": sum(1 for c in commits if c["type"] == "unknown"),
        },
    }


def main():
    ap = argparse.ArgumentParser(description="将 git 提交结构化为事实 JSON")
    ap.add_argument("--repo", required=True, help="目标仓库路径")
    ap.add_argument("--from", dest="frm", default=None, help="起始 tag（缺省自动取最近 tag）")
    ap.add_argument("--to", dest="to", default="HEAD", help="结束 ref，默认 HEAD")
    ap.add_argument("--out", default=None, help="事实 JSON 输出路径（同时打印到 stdout）")
    a = ap.parse_args()

    frm = a.frm or previous_tag(a.repo, a.to)
    data = collect(a.repo, frm, a.to)
    text = json.dumps(data, ensure_ascii=False, indent=2)
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()