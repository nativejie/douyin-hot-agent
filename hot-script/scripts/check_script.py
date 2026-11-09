#!/usr/bin/env python3
"""检查 script.json：AI 腔、数字有没有出处、节奏、字数、标题长度、有没有没填的【待…】。

只用 Python 标准库。
用法：
  python3 check_script.py [--dir 热点/今天日期] [--pace 3.0]
--pace：每 10 秒至少换几屏（默认读 brief.json 的 pace_cuts_per_10s，没有就 3）。
有「错误」退出码是 1，只有「提醒」退出码是 0。
"""
import argparse, json, os, re, sys
from datetime import datetime

BANNED = [
    (r"不是[^，。！？,.!?]{1,15}[，,]\s*(而)?是", "「不是 A，是 B」句式"),
    (r"[^0-9]：|[^0-9]:", "冒号揭晓 / 冒号列举（画面字里的比分、时间除外）"),
    (r"说到点子上|更离谱的是|那一刻我才明白|我最喜欢的细节|不得不说|值得一提的是|毫无疑问|让我们来看看|"
     r"接下来|总而言之|简单来说|一起来看|众所周知|话不多说|废话不多说", "套话"),
    (r"评论区告诉我|评论区聊聊|你觉得呢|你怎么看|欢迎留言", "结尾求互动问句"),
    (r"下期|下一期|下集|关注我.{0,6}(看|了解)", "预告下一期 / 求关注"),
    (r"预测|竞猜|押注|赔率|博彩", "平台敏感词（换成概率、模拟）"),
    (r"大家好|今天来聊聊|今天给大家", "铺垫开场"),
]
TRIPLE = re.compile(r"([^，。！？]{2,8})[，、]([^，。！？]{2,8})[，、]([^，。！？]{2,8})[。！]")
PLACEHOLDER = re.compile(r"【待[^】]*】|TODO|XX%|X%")
# 前后挨着字母的不算（S16、T1、GPT4 是名字不是数）
NUM = re.compile(r"(?<![A-Za-z\d.])\d+(?:\.\d+)?(?![A-Za-z\d])")


def norm(n):
    """2.80 → 2.8，3.0 → 3：写法不同的同一个数算一样。"""
    return n.rstrip("0").rstrip(".") if "." in n else n


def numbers_in(text):
    return {norm(n) for n in NUM.findall(text or "")}


def converted(n, known):
    """单位换算也算有出处：20334 亿 → 2.03 万亿、1386 万 → 0.14 亿（差 1 万倍，按 n 的小数位四舍五入对得上）。"""
    dec = len(n.split(".")[1]) if "." in n else 0
    x = float(n)
    for k in known:
        try:
            v = float(k)
        except ValueError:
            continue
        for y in (v / 10000, v * 10000):
            if abs(round(y, dec) - x) < 1e-9 and x != 0:
                return True
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=os.path.join("热点", datetime.now().strftime("%Y-%m-%d")))
    ap.add_argument("--pace", type=float, default=None)
    a = ap.parse_args()
    sp, fp = os.path.join(a.dir, "script.json"), os.path.join(a.dir, "facts.json")
    if not os.path.exists(sp):
        sys.exit(f"找不到 {sp}。要在用户的工作文件夹里运行（里面有「热点」文件夹），或者用 --dir 指定。")
    sc = json.load(open(sp, encoding="utf-8"))
    facts = {f["id"]: f for f in (json.load(open(fp, encoding="utf-8"))["facts"] if os.path.exists(fp) else [])}
    pace = a.pace
    bp = os.path.join(a.dir, "brief.json")
    if pace is None and os.path.exists(bp):
        pace = json.load(open(bp, encoding="utf-8")).get("pace_cuts_per_10s")
    pace = pace or 3.0

    errors, warns = [], []
    scenes = sc.get("scenes") or []
    voice = sc.get("voice", "none")
    if not facts:
        errors.append("没有 facts.json 或里面是空的")

    for s in scenes:
        sid = s.get("id", "?")
        vis = json.dumps(s.get("visual") or {}, ensure_ascii=False)
        cap, nar = s.get("caption") or "", s.get("narration") or ""
        spoken = nar if voice == "tts" else cap
        for pat, why in BANNED:
            target = spoken if why.startswith("冒号") else cap + " " + nar
            if re.search(pat, target):
                errors.append(f"{sid}：{why} → {re.search(pat, target).group(0)!r}")
        if TRIPLE.search(nar):
            warns.append(f"{sid}：像三连排比 → {TRIPLE.search(nar).group(0)!r}")
        if PLACEHOLDER.search(cap + nar + vis):
            errors.append(f"{sid}：还有没填的占位 → {PLACEHOLDER.search(cap + nar + vis).group(0)!r}")
        if len(cap) > 14:
            errors.append(f"{sid}：caption {len(cap)} 字，超过 14 字")
        if voice == "tts" and not nar:
            errors.append(f"{sid}：voice=tts 但这屏没有旁白")
        if voice == "none" and nar:
            warns.append(f"{sid}：voice=none 但写了旁白，旁白不会出现")
        for sent in re.split(r"[。！？]", nar):
            if len(sent) > 40:
                warns.append(f"{sid}：一句话 {len(sent)} 字，太长 → {sent[:20]}…")
        sec = s.get("seconds") or 0
        if voice == "none" and sec > 4:
            warns.append(f"{sid}：不配旁白的一屏停 {sec} 秒，超过 4 秒")
        if voice == "tts" and nar and sec < len(re.sub(r'\s', '', nar)) / 5.5:
            warns.append(f"{sid}：{len(nar)} 字的旁白只给了 {sec} 秒，念不完（每秒约 5 字；出画面时会按配音实际长度重算，这里只是估算偏短）")
        # 数字出处：这一屏出现的每个数，都要在它引用的 fact 的 text/value 里
        ref = s.get("facts") or []
        missing = [r for r in ref if r not in facts]
        if missing:
            errors.append(f"{sid}：引用了不存在的 fact {missing}")
        known = set()
        for r in ref:
            if r in facts:
                known |= numbers_in(facts[r].get("text")) | numbers_in(json.dumps(facts[r].get("value"), ensure_ascii=False))
        v = dict(s.get("visual") or {})
        if str(v.get("from", "")).strip().rstrip("%") in ("0", "0.0"):
            v.pop("from")  # 从 0 滚起不用出处
        vis_chk = json.dumps(v, ensure_ascii=False)
        for n in numbers_in(cap) | numbers_in(nar) | numbers_in(vis_chk):
            if n not in known and not converted(n, known):
                errors.append(f"{sid}：数字 {n} 在引用的 fact 里找不到（引用了 {ref or '无'}）")
        # 画面字段的字数上限（见 script-format.md）
        t = v.get("type")
        lim = lambda txt, n, what: errors.append(f"{sid}：{what} {len(txt)} 字，超过 {n}") if txt and len(str(txt)) > n else None
        if t == "title":
            lim(v.get("text"), 12, "title.text")
        elif t == "list":
            items = v.get("items") or []
            if len(items) > 5:
                errors.append(f"{sid}：list {len(items)} 条，超过 5")
            for it in items:
                lim(it, 16, "list 每条")
        elif t == "quote":
            lim(v.get("text"), 40, "quote.text")
        elif t == "vote":
            lim(v.get("question"), 10, "vote.question")
            if not 2 <= len(v.get("options") or []) <= 4:
                errors.append(f"{sid}：vote 选项要 2–4 个")
        elif t == "bars":
            if len(v.get("items") or []) > 6:
                errors.append(f"{sid}：bars {len(v.get('items'))} 项，超过 6")
        elif t == "number":
            lab = str(v.get("label") or "")
            wid = sum(1 if ord(c) > 255 else .5 for c in lab)   # 汉字算 1，英文数字空格算半个
            if wid > 12:
                errors.append(f"{sid}：number.label 约 {wid:g} 个汉字宽，超过 12（英文数字算半个）")
        elif t != "compare":
            errors.append(f"{sid}：visual.type「{t}」不认识（只认 title / number / bars / compare / list / quote / vote）")
        lim(v.get("kicker"), 20, "kicker")

    total = sum(s.get("seconds") or 0 for s in scenes)
    if scenes and total:
        per10 = round(len(scenes) / total * 10, 1)
        if per10 < pace:
            errors.append(f"节奏：{len(scenes)} 屏 {total} 秒，每 10 秒换 {per10} 屏，低于要求的 {pace}")
    tgt = sc.get("target_seconds")
    if tgt and abs(total - tgt) > tgt * 0.25:
        warns.append(f"总长 {total} 秒，和目标 {tgt} 秒差太多")
    if scenes and (scenes[-1].get("visual") or {}).get("type") not in ("vote", "number", "bars", "title", "compare"):
        warns.append("最后一屏不是站队按钮或结论数字，检查结尾是不是落在事实上")

    limits = {"douyin": 30, "xhs": 20, "bilibili": 80}
    for plat, lim in limits.items():
        for t in (sc.get("titles") or {}).get(plat, []):
            if len(t) > lim:
                errors.append(f"标题（{plat}）{len(t)} 字超过 {lim}：{t}")
            if " " in t:
                warns.append(f"标题（{plat}）有空格：{t}")
            if re.search(r"预测|竞猜", t):
                errors.append(f"标题（{plat}）有敏感词：{t}")
            if re.search(r"[：:]", t):
                warns.append(f"标题（{plat}）有冒号，像 AI 标题，能改就改成一句话：{t}")

    print(f"{len(scenes)} 屏，{total} 秒，每 10 秒 {round(len(scenes) / total * 10, 1) if total else 0} 屏（要求 ≥ {pace}）")
    for e in errors:
        print("错误  " + e)
    for w in warns:
        print("提醒  " + w)
    if not errors:
        print("没有错误。提醒里的逐条看一下，有道理就改。")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
