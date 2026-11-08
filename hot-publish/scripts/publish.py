#!/usr/bin/env python3
"""封面 + 标题 + 简介：检查 publish.json，出封面图，写 publish.md。

只用 Python 标准库；出封面要 Chrome（或 Edge / Chromium）。
用法（在用户的工作文件夹里运行）：
  python3 publish.py check   [--dir 热点/日期]   查 publish.json（字数、敏感词、数字出处、搜索词），没错误就写 publish.md
  python3 publish.py cover   [--dir 热点/日期]   按 publish.json 的 cover 出三张网页封面（16:9、4:3、3:4）
有「错误」退出码是 1。
"""
import argparse, glob, json, os, platform, re, shutil, subprocess, sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ASSETS = HERE.parent / "assets"
SIZES = {"16x9": (1920, 1080), "4x3": (1440, 1080), "3x4": (1080, 1440)}
BANNED = [
    (r"预测|竞猜|押注|下注|赔率|博彩|稳赚|包赢", "平台敏感词（换成概率、模拟）"),
    (r"评论区告诉我|评论区聊聊|你觉得呢|欢迎留言", "求互动问句"),
    (r"下期|下一期|下集", "预告下一期"),
    (r"震惊|惊呆了|全网首发|必看|史上最", "营销号腔"),
    (r"https?://|www\.", "简介、标题里不放网址"),
]
NUM = re.compile(r"(?<![A-Za-z\d.])\d+(?:\.\d+)?(?![A-Za-z\d])")


def die(msg):
    print("错误  " + msg)
    sys.exit(1)


def load(dirp):
    pp = dirp / "publish.json"
    if not pp.exists():
        die(f"找不到 {pp}。先照 SKILL.md 写 publish.json；要在用户的工作文件夹里运行，或者用 --dir 指定。")
    pub = json.load(open(pp, encoding="utf-8"))
    sc = json.load(open(dirp / "script.json", encoding="utf-8")) if (dirp / "script.json").exists() else {}
    facts = json.load(open(dirp / "facts.json", encoding="utf-8"))["facts"] if (dirp / "facts.json").exists() else []
    return pub, sc, facts


def known_numbers(facts, sc):
    s = set()
    for f in facts:
        s |= set(NUM.findall(str(f.get("text", "")))) | set(NUM.findall(json.dumps(f.get("value"), ensure_ascii=False)))
    return s | set(NUM.findall(str(sc.get("word", ""))))   # 热榜原词里的数（「晋级4强」）也算有出处


def chapters(sc):
    """B 站章节：开头 + 每个 title 屏开一章。片子不到 90 秒不分章（短片分章没人点）。"""
    if sum(float(s.get("seconds") or 0) for s in sc.get("scenes") or []) < 90:
        return []
    out, t = [], 0.0
    for i, s in enumerate(sc.get("scenes") or []):
        v = s.get("visual") or {}
        if i == 0:
            out.append((0, v.get("text") if v.get("type") == "title" else "开场"))
        elif v.get("type") == "title":
            out.append((t, v.get("text") or s.get("caption") or ""))
        t += float(s.get("seconds") or 0)
    return out if len(out) >= 3 else []


def mmss(t):
    return f"{int(t) // 60:02d}:{int(t) % 60:02d}"


def check(dirp):
    pub, sc, facts = load(dirp)
    errors, warns = [], []
    nums = known_numbers(facts, sc) | set(NUM.findall(str(pub.get("word", ""))))
    if not facts:
        warns.append("没有 facts.json，标题和简介里的数没法核对出处")
    core = [w for w in (pub.get("core_words") or []) if w]
    if not core:
        errors.append("core_words 没填：写 1–3 个观众会搜的核心词（热点里的人名、队名、事件名）")

    def text_checks(label, txt):
        for pat, why in BANNED:
            m = re.search(pat, txt)
            if m:
                errors.append(f"{label}：{why} → {m.group(0)!r}")
        if facts:
            for n in NUM.findall(txt):
                if n not in nums:
                    errors.append(f"{label}：数字 {n} 在 facts.json 里找不到")

    limits = {"douyin": 30, "xhs": 20, "bilibili": 80}
    want = {"douyin": 5, "xhs": 3, "bilibili": 2}
    for plat, lim in limits.items():
        ts = (pub.get("titles") or {}).get(plat) or []
        if len(ts) < want[plat] - 1:
            warns.append(f"{plat} 标题只有 {len(ts)} 条，建议 {want[plat]} 条")
        for t in ts:
            if len(t) > lim:
                errors.append(f"标题（{plat}）{len(t)} 字超过 {lim}：{t}")
            if " " in t:
                errors.append(f"标题（{plat}）有空格：{t}")
            if core and not any(w in t[: max(12, lim // 2)] for w in core):
                warns.append(f"标题（{plat}）前半句没有核心词 {core}：{t}")
            text_checks(f"标题（{plat}）「{t}」", t)
    rec = pub.get("recommend") or []
    dy = (pub.get("titles") or {}).get("douyin") or []
    if len(rec) != 2 or any(not isinstance(i, int) or i >= len(dy) for i in rec):
        errors.append("recommend 要写两个抖音标题的序号（从 0 开始），做 A/B")

    for plat in ("douyin", "xhs"):
        d = (pub.get("desc") or {}).get(plat) or ""
        if not d:
            errors.append(f"desc.{plat} 没写")
            continue
        n = len(re.sub(r"\s", "", d))
        if n < 150 or n > 450:
            warns.append(f"desc.{plat} {n} 字，建议 200–400 字")
        head = re.sub(r"\s", "", d)[:60]          # 开头一两句（AI 声明可以放最前面）
        if core and not any(w in head for w in core):
            errors.append(f"desc.{plat} 开头 60 字里没有核心词 {core}：{head[:30]}…")
        if re.search(r"^\s*\d+[.、]", d, re.M):
            warns.append(f"desc.{plat} 有编号清单，像说明书，改成一个人讲自己刚做的事")
        if "#" in d:
            warns.append(f"desc.{plat} 里写了 #标签，标签放 tags 里，脚本会接在简介后面")
        text_checks(f"desc.{plat}", d)
    if pub.get("ai_generated") and not re.search(r"AI", ((pub.get("desc") or {}).get("douyin") or "")[:80]):
        warns.append("ai_generated 为 true，但抖音简介开头没提 AI 生成 / AI 模拟")

    tags = pub.get("tags") or []
    if not 4 <= len(tags) <= 8:
        warns.append(f"tags {len(tags)} 个，建议 5–8 个")
    for t in tags:
        if not t.startswith("#") or " " in t:
            errors.append(f"标签格式不对（要 #开头、不带空格）：{t!r}")
        text_checks(f"标签 {t}", t)
    if core and not any(w in "".join(tags) for w in core):
        errors.append(f"tags 里没有核心词 {core}")

    cv = pub.get("cover") or {}
    lines = cv.get("lines") or []
    if not 1 <= len(lines) <= 3:
        errors.append("cover.lines 要 1–3 行")
    b = cv.get("big", 1)
    for i, l in enumerate(lines):
        lim, n = (6 if i == b else 9), len(l.replace(" ", ""))
        if n > lim:
            errors.append(f"封面第 {i + 1} 行「{l}」{n} 字，超过 {lim}（{'主角那行' if i == b else '其它行'}）")
        text_checks(f"封面「{l}」", l)
    if cv.get("tag") and len(cv["tag"].replace(" ", "")) > 10:
        errors.append(f"封面小标签「{cv['tag']}」超过 10 字")
    if cv.get("tag"):
        text_checks(f"封面标签「{cv['tag']}」", cv["tag"])

    print(f"标题 抖音 {len(dy)} / 小红书 {len((pub.get('titles') or {}).get('xhs') or [])} / B站 {len((pub.get('titles') or {}).get('bilibili') or [])}，标签 {len(tags)} 个，封面 {len(lines)} 行")
    for e in errors:
        print("错误  " + e)
    for w in warns:
        print("提醒  " + w)
    if errors:
        sys.exit(1)
    write_md(dirp, pub, sc)
    print(f"没有错误，已写 {dirp / 'publish.md'}。提醒里的逐条看一下，有道理就改了再跑。")


def write_md(dirp, pub, sc):
    T = pub.get("titles") or {}
    rec = pub.get("recommend") or []
    tags = " ".join(pub.get("tags") or [])
    L = [f"# 发布文案：{pub.get('word') or sc.get('word') or ''}", ""]
    if pub.get("publish_by"):
        L += [f"**什么时候发**：{pub['publish_by']}", ""]
    if pub.get("ai_generated"):
        L += ["**AI 标注**：发布时勾选「内容由 AI 生成」（抖音：作品声明；小红书：笔记声明；B 站：创作声明）。", ""]
    L += ["## 封面", ""]
    cdir = dirp / "covers"
    order = {"cover_16x9.png": 0, "cover_4x3.png": 1, "cover_3x4.png": 2}
    for f in sorted(cdir.glob("*.png"), key=lambda f: (order.get(f.name, 9), f.name)) if cdir.exists() else []:
        L.append(f"- `covers/{f.name}`")
    cv = pub.get("cover") or {}
    L += [f"- 封面字：{' / '.join(cv.get('lines') or [])}" + (f"（小标签「{cv['tag']}」）" if cv.get("tag") else ""),
          "- 抖音横屏视频用 4:3 或 16:9，小红书和个人页用 3:4，B 站用 16:9。", ""]
    L += ["## 抖音标题（≤ 30 字）", ""]
    for i, t in enumerate(T.get("douyin") or []):
        L.append(f"{i + 1}. {t}（{len(t)}）" + ("  ← 推荐，A/B" if i in rec else ""))
    L += ["", "## 抖音简介", "", (pub.get("desc") or {}).get("douyin", ""), "", tags, ""]
    L += ["## 小红书", "", "标题（≤ 20 字）：", ""]
    for t in T.get("xhs") or []:
        L.append(f"- {t}（{len(t)}）")
    L += ["", "正文：", "", (pub.get("desc") or {}).get("xhs", ""), "", tags, ""]
    L += ["## B 站", "", "标题（≤ 80 字）：", ""]
    for t in T.get("bilibili") or []:
        L.append(f"- {t}（{len(t)}）")
    bz = pub.get("bilibili") or {}
    if bz.get("zone"):
        L.append(f"\n分区：{bz['zone']}")
    btags = bz.get("tags") or [t.lstrip("#") for t in pub.get("tags") or []]
    L.append(f"\n标签（≤ 10 个）：{'、'.join(btags[:10])}")
    ch = chapters(sc)
    if ch:
        L += ["", "简介末尾的章节：", ""] + [f"{mmss(t)} {name}" for t, name in ch]
    L += ["", "简介：同抖音。", ""]
    (dirp / "publish.md").write_text("\n".join(L), encoding="utf-8")


def find_chrome():
    if os.environ.get("CHROME") and Path(os.environ["CHROME"]).exists():
        return os.environ["CHROME"]
    home, sysname = Path.home(), platform.system()
    if sysname == "Darwin":
        cands = ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "/Applications/Chromium.app/Contents/MacOS/Chromium",
                 "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"]
        cands += glob.glob(str(home / "Library/Caches/ms-playwright/chromium-*/chrome-mac*/*.app/Contents/MacOS/*"))
    elif sysname == "Windows":
        pf = [os.environ.get(k, "") for k in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA")]
        cands = [str(Path(p) / s) for p in pf if p for s in ("Google/Chrome/Application/chrome.exe", "Microsoft/Edge/Application/msedge.exe")]
    else:
        cands = [shutil.which(x) for x in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge")]
        cands += glob.glob(str(home / ".cache/ms-playwright/chromium-*/chrome-linux*/chrome"))
    for c in cands:
        if c and Path(c).exists():
            return c
    die("找不到 Chrome / Edge / Chromium。装一个，或者用环境变量 CHROME 指过去。")


def pick_shots(dirp, cv, sc):
    """封面上的两张画面：成片定格图（hot-render 出的 render/check-1920x1080/NNN_<屏号>.png）。
    publish.json 的 cover.shots 可以指定 [{"id": "s8", "label": "人均排名"}]；没写就挑一张条形图、一张对比（没有就挑数字屏）。"""
    files = sorted(glob.glob(str(dirp / "render" / "check-1920x1080" / "*.png")))
    by_id = {re.sub(r"^\d+_", "", Path(f).stem): f for f in files}
    want = cv.get("shots")
    if not want:
        scenes = (sc or {}).get("scenes", [])
        want = []
        for kind in ("bars", "compare", "number"):
            hit = next((x for x in scenes if (x.get("visual") or {}).get("type") == kind and x["id"] in by_id and x["id"] not in [w["id"] for w in want]), None)
            if hit and len(want) < 2:
                want.append({"id": hit["id"], "label": ""})
    return [{"src": by_id[x["id"]], "label": x.get("label", "")} for x in want if x.get("id") in by_id][:2]


def cover(dirp):
    pub, sc, _ = load(dirp)
    cv = pub.get("cover") or {}
    if not cv.get("lines"):
        die("publish.json 里没有 cover.lines")
    chrome = find_chrome()
    work = dirp / "covers" / ".work"
    work.mkdir(parents=True, exist_ok=True)
    shutil.copy(ASSETS / "cover.html", work / "cover.html")
    shots = pick_shots(dirp, cv, sc)
    for i, x in enumerate(shots):
        shutil.copy(x["src"], work / f"shot{i}.png")
        x["src"] = f"shot{i}.png"
    if not shots:
        print("提醒  没找到成片定格图（render/check-1920x1080/），封面下面那排画面先空着")
    for name, (w, h) in SIZES.items():
        spec = {"w": w, "h": h, "lines": cv["lines"], "big": cv.get("big", 1), "tag": cv.get("tag", ""), "shots": shots}
        (work / "cover_spec.js").write_text("window.COVER = " + json.dumps(spec, ensure_ascii=False) + ";", encoding="utf-8")
        out = (dirp / "covers" / f"cover_{name}.png").resolve()
        prof = work / ".chrome"
        r = subprocess.run([chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run", f"--user-data-dir={prof}",
                            "--allow-file-access-from-files", f"--window-size={w},{h}", "--virtual-time-budget=4000",
                            f"--screenshot={out}", (work / "cover.html").resolve().as_uri()], capture_output=True, text=True, timeout=120)
        if not out.exists():
            die(f"封面 {name} 没截出来：{r.stderr[-400:]}")
        print(f"封面 {name}：{out}")
    shutil.rmtree(work, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["check", "cover"])
    ap.add_argument("--dir", default=os.path.join("热点", datetime.now().strftime("%Y-%m-%d")), help="默认 热点/今天日期")
    a = ap.parse_args()
    dirp = Path(a.dir).resolve()
    {"check": lambda: check(dirp), "cover": lambda: cover(dirp)}[a.cmd]()


if __name__ == "__main__":
    main()
