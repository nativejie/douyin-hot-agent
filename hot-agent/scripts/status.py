#!/usr/bin/env python3
"""追热点 Agent 的进度和体检：今天做到第几步、下一步是什么、工具和密钥齐不齐；顺便记流水账。

只用 Python 标准库。在用户的工作文件夹里运行：
  python3 status.py                       看进度（默认今天）
  python3 status.py --dir 热点/2026-11-07
  python3 status.py log 3 开始            往 热点/日期/agent-log.md 记一行（带时间）
"""
import argparse, glob, json, os, platform, shutil, subprocess, sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILLS = HERE.parent.parent
STEPS = [
    (1, "hot-topics", "抓热点", ["shortlist.json"]),
    (2, "hot-score", "值不值得做", ["pick.json"]),
    (3, "hot-breakdown", "拆同题爆款", ["brief.json"]),
    (4, "hot-script", "查事实 + 写稿", ["facts.json", "script.json"]),
    (5, "hot-render", "出画面", ["video.mp4"]),
    (6, "hot-publish", "封面 + 标题", ["publish.json", "publish.md"]),
]


def mtime(p):
    return p.stat().st_mtime if p.exists() else 0


def step_state(dirp):
    """每一步：done / stale（前一步改过、要重做）/ todo。"""
    out, prev_t = [], 0
    for n, skill, name, files in STEPS:
        ts = [mtime(dirp / f) for f in files]
        if not all(ts):
            st = "todo"
        elif min(ts) + 1 < prev_t:
            st = "stale"
        else:
            st = "done"
        if n == 4 and st == "done":                 # 稿子要过了检查才算做完
            r = subprocess.run([sys.executable, str(SKILLS / "hot-script/scripts/check_script.py"), "--dir", str(dirp)], capture_output=True, text=True)
            if r.returncode != 0:
                st = "check"
        if n == 6 and st == "done" and not list((dirp / "covers").glob("cover_*.png")):
            st = "todo"
        out.append((n, skill, name, st))
        prev_t = max(ts) if all(ts) else prev_t
    return out


def tools():
    res = []
    res.append(("TIKHUB_API_KEY", bool(os.environ.get("TIKHUB_API_KEY")), "第 1–3 步要用（这三步做完了就不需要）：去 tikhub.io 生成，设成环境变量"))
    node = shutil.which("node") or next(iter(glob.glob(str(Path.home() / ".workbuddy/binaries/**/bin/node"), recursive=True)), None)
    ok = False
    if node:
        try:
            ok = int(subprocess.run([node, "-v"], capture_output=True, text=True).stdout.strip().lstrip("v").split(".")[0]) >= 22
        except Exception:
            pass
    res.append(("Node 22+", ok, "第 5 步要用：装新版 Node（nodejs.org）"))
    chrome = os.environ.get("CHROME") or next((c for c in [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        shutil.which("google-chrome") or "", shutil.which("chromium") or "",
        str(Path(os.environ.get("PROGRAMFILES", "C:/Program Files")) / "Google/Chrome/Application/chrome.exe"),
        str(Path(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)")) / "Microsoft/Edge/Application/msedge.exe")] if c and Path(c).exists()), None)
    res.append(("Chrome / Edge", bool(chrome), "第 5、6 步要用：装一个 Chrome"))
    ff = shutil.which("ffmpeg")
    if not ff:
        try:
            import imageio_ffmpeg  # noqa: F401
            ff = "imageio-ffmpeg"
        except ImportError:
            pass
    res.append(("ffmpeg", bool(ff), "第 3、5 步要用：没有的话脚本会自动装 imageio-ffmpeg"))
    try:
        free = shutil.disk_usage(".").free / 1e9
        res.append((f"硬盘空闲 {free:.1f}GB", free > 1, "渲染要 1GB 以上，先清出空间"))
    except Exception:
        pass
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs="?", default="show", choices=["show", "log"])
    ap.add_argument("rest", nargs="*")
    ap.add_argument("--dir", default=os.path.join("热点", datetime.now().strftime("%Y-%m-%d")))
    a = ap.parse_args()
    dirp = Path(a.dir)
    if not Path("热点").is_dir():
        sys.exit("当前文件夹里没有「热点」文件夹：要在用户的工作文件夹里运行（别在 skill 文件夹里跑）。")
    if a.cmd == "log":
        if len(a.rest) < 2:
            sys.exit("用法：status.py log <第几步> <开始 / 完成 / 一句话>")
        dirp.mkdir(parents=True, exist_ok=True)
        lp = dirp / "agent-log.md"
        if not lp.exists():
            lp.write_text("# 追热点 Agent 流水账\n\n| 时间 | 步 | 记录 |\n|---|---|---|\n", encoding="utf-8")
        with open(lp, "a", encoding="utf-8") as f:
            f.write(f"| {datetime.now().strftime('%H:%M:%S')} | {a.rest[0]} | {' '.join(a.rest[1:])} |\n")
        print(f"已记：{lp}")
        return

    prof = dirp.parent / "profile.md"
    print(f"工作文件夹：{Path.cwd()}")
    print(f"账号档案：{'有' if prof.exists() else '没有（第 1 步会问）'}  {prof}")
    missing = [s for _, s, _, _ in STEPS if not (SKILLS / s / "SKILL.md").exists()]
    if missing:
        print(f"缺 skill：{', '.join(missing)}（要和 hot-agent 放在同一个 skills 文件夹里）")
    print("\n工具：")
    for name, ok, hint in tools():
        print(f"  {'✓' if ok else '✗'} {name}" + ("" if ok else f"  ← {hint}"))
    print(f"\n今天（{dirp}）的进度：")
    nxt = None
    for n, skill, name, st in step_state(dirp):
        mark = {"done": "✓ 做完", "stale": "↻ 要重做（前一步改过）", "todo": "· 没做", "check": "✗ 稿子没过检查（跑 check_script.py 看错误）"}[st]
        print(f"  {n}. {name:<8} {skill:<14} {mark}")
        if st != "done" and nxt is None:
            nxt = (n, skill, name)
    pk = dirp / "pick.json"
    if pk.exists():
        try:
            p = json.load(open(pk, encoding="utf-8"))
            m = p.get("main") or p
            print(f"\n今天主推：{m.get('word', '?')}（{m.get('score', '?')} 分）  角度：{m.get('angle', '')}")
        except Exception:
            pass
    print("\n下一步：" + (f"第 {nxt[0]} 步 {nxt[2]}（读 {SKILLS / nxt[1] / 'SKILL.md'}）" if nxt else "全部做完，把成片、封面和 publish.md 交给用户"))


if __name__ == "__main__":
    main()
