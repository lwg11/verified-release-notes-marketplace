# -*- coding: utf-8 -*-
"""
cut_release.py —— 端到端发版的最后一步：打 tag 并创建 Release

安全策略（重要）：
    默认只做 dry-run —— 把将要执行的命令打印出来，不产生任何副作用。
    只有显式传入 --execute 才会真正执行 git tag / gh release create。
    若同时传入 --facts，会在执行前再跑一次 verify 校验；不通过则拒绝发版。
    这样"发版前必过校验"这条铁律在最后一刻仍然生效，避免绕过 render_release 直接发版。
"""
import argparse
import json
import subprocess
from pathlib import Path

import verify as V


def _run(cmd, repo, execute):
    """统一执行入口：dry-run 时只打印；execute 时真正运行并返回结果。"""
    pretty = " ".join(cmd)
    if not execute:
        print("  [dry-run] %s" % pretty)
        return 0
    print("  [run] %s" % pretty)
    r = subprocess.run(["git", "-C", str(repo)] + cmd, capture_output=True, text=True,
                       encoding="utf-8")
    if r.stdout:
        print(r.stdout.rstrip())
    if r.returncode != 0:
        print(r.stderr.rstrip())
    return r.returncode


def main():
    ap = argparse.ArgumentParser(description="打 tag 并创建 Release（默认 dry-run）")
    ap.add_argument("--repo", required=True, help="目标仓库路径")
    ap.add_argument("--tag", required=True, help="要打的 tag，例如 v1.5.0")
    ap.add_argument("--notes", required=True, help="发版说明 Markdown 文件")
    ap.add_argument("--title", default=None, help="Release 标题，默认与 tag 相同")
    ap.add_argument("--facts", default=None, help="事实 JSON；提供则在发版前再校验一次")
    ap.add_argument("--execute", action="store_true", help="真正执行（缺省为 dry-run）")
    a = ap.parse_args()

    tag = a.tag
    title = a.title or tag
    notes_path = Path(a.notes)
    repo = Path(a.repo)

    # 发版前闸门：有 facts 就必须校验通过，否则拒绝发版
    if a.facts:
        facts = json.loads(Path(a.facts).read_text(encoding="utf-8"))
        if facts.get("next") != tag:
            print("拒绝发版：facts.next=%s 与 --tag=%s 不一致" % (facts.get("next"), tag))
            raise SystemExit(1)
        res = V.verify(notes_path.read_text(encoding="utf-8"), facts)
        if not res["ok"]:
            print("拒绝发版：发版说明未通过校验")
            for i in res["issues"]:
                print("  ISSUE %s: %s" % (i["code"], i["detail"]))
            raise SystemExit(1)
        print("发版前校验通过（%d 条提交，%d 项警告）"
              % (facts["counts"]["total"], len(res["warnings"])))

    mode = "执行" if a.execute else "dry-run（加 --execute 才会真正执行）"
    print("模式：%s" % mode)

    # 1) 打 git tag（附注 tag，便于追溯）
    rc = _run(["tag", "-a", tag, "-m", "Release %s" % tag], repo, a.execute)
    if rc != 0:
        raise SystemExit(rc)

    # 2) 创建 GitHub Release（notes-from-tag 由 notes 文件提供）
    gh_cmd = ["gh", "release", "create", tag, "--title", title, "--notes-file", str(notes_path)]
    # gh 不在 git 子命令体系内，单独处理：dry-run 只打印，execute 时在仓库目录下执行
    if not a.execute:
        print("  [dry-run] (cwd=%s) %s" % (repo, " ".join(gh_cmd)))
    else:
        print("  [run] (cwd=%s) %s" % (repo, " ".join(gh_cmd)))
        r = subprocess.run(gh_cmd, cwd=str(repo), capture_output=True, text=True,
                           encoding="utf-8")
        if r.stdout:
            print(r.stdout.rstrip())
        if r.returncode != 0:
            print(r.stderr.rstrip())
            raise SystemExit(r.returncode)

    if not a.execute:
        print("以上为 dry-run 预览，确认无误后加 --execute 重跑即可真正发版。")


if __name__ == "__main__":
    main()