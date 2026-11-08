#!/usr/bin/env python3
"""给 shortlist 里每个热点查抖音同题：今天已经有多少人做、做得多好、小号有没有爆、评论区吵不吵、
有没有人用过同一个角度。

只用 Python 标准库 + 系统 curl。密钥从环境变量 TIKHUB_API_KEY 读。
用法：
  python3 competition.py [--dir 热点/今天日期] [--me 自己的抖音昵称]
读 shortlist.json，每个热点搜两次：
  1. 热点原词，近 1 天，按最多点赞 → 同题竞争
  2. items[].kw（角度搜索词，由 AI 在运行前写进 shortlist.json；没有就跳过），近 7 天 → 同角度有没有人做过
每次搜索 0.01 美元，7 个热点约 0.14 美元。
产出：competition.json（原始统计）、competition.md（给人看）。
"""
import argparse, json, os, statistics, subprocess, sys, time
from datetime import datetime

BASE = os.environ.get("TIKHUB_BASE", "https://api.tikhub.io")
KEY = os.environ.get("TIKHUB_API_KEY", "")
ME = ""  # 自己的抖音昵称，命令行 --me 设置；搜到自己的视频不算竞争


def search(keyword, publish_time):
    body = {"keyword": keyword, "cursor": 0, "sort_type": "1", "publish_time": str(publish_time),
            "filter_duration": "0", "content_type": "1", "search_id": "", "backtrace": ""}
    cmd = ["curl", "-s", "-m", "90", "-X", "POST", BASE + "/api/v1/douyin/search/fetch_video_search_v2",
           "-H", "Authorization: Bearer " + KEY, "-H", "Content-Type: application/json",
           "-d", json.dumps(body, ensure_ascii=False)]
    if os.environ.get("TIKHUB_NOPROXY"):
        cmd[1:1] = ["--noproxy", "*"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    try:
        out = json.loads(r.stdout)
    except json.JSONDecodeError:
        return None, f"接口没返回：{(r.stdout or r.stderr)[:150]}（代理问题就设 TIKHUB_NOPROXY=1）"
    if out.get("code") != 200:
        return None, f"接口报错：{out.get('message_zh') or str(out)[:200]}"
    vids = []
    for it in (out.get("data") or {}).get("business_data") or []:
        a = (it.get("data") or {}).get("aweme_info")
        if not a:
            continue
        s, au = a.get("statistics") or {}, a.get("author") or {}
        vids.append({
            "title": (a.get("desc") or "").replace("\n", " ")[:60],
            "likes": s.get("digg_count") or 0, "comments": s.get("comment_count") or 0,
            "collects": s.get("collect_count") or 0, "shares": s.get("share_count") or 0,
            "fans": au.get("follower_count") or 0, "author": au.get("nickname") or "",
            "hours_ago": round((time.time() - a.get("create_time", time.time())) / 3600, 1),
            "duration_s": round((a.get("duration") or 0) / 1000),
            "url": f"https://www.douyin.com/video/{a.get('aweme_id')}",
            "mine": bool(ME) and (au.get("nickname") or "") == ME,
        })
    return vids, ""


def stats(vids):
    vids = [v for v in vids if not v.get("mine")]
    if not vids:
        return {"n": 0}
    likes = [v["likes"] for v in vids]
    cl = [v["comments"] / v["likes"] for v in vids if v["likes"] >= 100]
    return {
        "n": len(vids),
        "max_likes": max(likes),
        "median_likes": int(statistics.median(likes)),
        # 粉丝不到 1 万、赞过 1 万：小号也能爆
        "small_hits": sum(1 for v in vids if v["fans"] < 10000 and v["likes"] >= 10000),
        # 大号（50 万粉以上）占了几条
        "big_accounts": sum(1 for v in vids if v["fans"] >= 500000),
        # 评论 ÷ 赞 的中位数：越高越有得吵（一般视频 0.02–0.05）
        "comment_like_ratio": round(statistics.median(cl), 3) if cl else None,
        "has_ai_angle": sum(1 for v in vids if "AI" in v["title"].upper() or "人工智能" in v["title"]),
    }


def fmt_n(n):
    return f"{n / 10000:.1f}万" if n >= 10000 else str(n)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=os.path.join("热点", datetime.now().strftime("%Y-%m-%d")))
    ap.add_argument("--me", default="", help="自己的抖音昵称")
    a = ap.parse_args()
    global ME
    ME = a.me.strip()
    if not KEY:
        sys.exit("没有 TIKHUB_API_KEY 环境变量。")
    sl_path = os.path.join(a.dir, "shortlist.json")
    if not os.path.exists(sl_path):
        sys.exit(f"找不到 {sl_path}，先跑上一步 hot-topics。")
    sl = json.load(open(sl_path, encoding="utf-8"))

    results, md = [], [f"# 同题竞争 {datetime.now():%Y-%m-%d %H:%M}", "",
                       "每个热点两组搜索：「同题」= 热点原词近 1 天最多赞的视频；「同角度」= 角度搜索词近 7 天。",
                       "评赞比 = 评论 ÷ 赞 的中位数，一般 0.02–0.05，越高越有得吵。小号爆款 = 粉丝 < 1 万且赞 ≥ 1 万。", ""]
    for it in sl["items"]:
        row = {"word": it["word"], "searches": []}
        for label, kw, pt in (("同题", it["word"], 1), ("同角度", it.get("kw"), 7)):
            if not kw:
                continue
            vids, err = search(kw, pt)
            row["searches"].append({"label": label, "keyword": kw, "days": pt, "error": err,
                                    "stats": stats(vids or []), "videos": vids or []})
        results.append(row)

        md += [f"## {it['word']}", ""]
        for s in row["searches"]:
            st = s["stats"]
            if s["error"]:
                md.append(f"- **{s['label']}**（搜「{s['keyword']}」）：{s['error']}")
                continue
            if not st["n"]:
                md.append(f"- **{s['label']}**（搜「{s['keyword']}」，近 {s['days']} 天）：没搜到视频")
                continue
            md.append(f"- **{s['label']}**（搜「{s['keyword']}」，近 {s['days']} 天）：{st['n']} 条，"
                      f"最高 {fmt_n(st['max_likes'])} 赞，中位 {fmt_n(st['median_likes'])}，小号爆款 {st['small_hits']} 条，"
                      f"50 万粉以上大号 {st['big_accounts']} 条，评赞比 {st['comment_like_ratio']}，标题带 AI 的 {st['has_ai_angle']} 条")
            # 同角度要逐条判断是不是同一个角度，全列；同题列前 3 条
            for i, v in enumerate(s["videos"] if s["label"] == "同角度" else s["videos"][:3], 1):
                md.append(f"  {i}. {'【自己的】' if v.get('mine') else ''}{fmt_n(v['likes'])} 赞 / {fmt_n(v['comments'])} 评 / 作者 {fmt_n(v['fans'])} 粉 / "
                          f"{v['hours_ago']} 小时前 / {v['duration_s']} 秒 | {v['author'][:10]} | {v['title']} | {v['url']}")
        md.append("")

    with open(os.path.join(a.dir, "competition.json"), "w", encoding="utf-8") as f:
        json.dump({"checked_at": f"{datetime.now():%Y-%m-%d %H:%M}", "items": results}, f, ensure_ascii=False, indent=1)
    with open(os.path.join(a.dir, "competition.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(md) + "\n")
    n = sum(len(r["searches"]) for r in results)
    print(f"搜了 {n} 次 → {os.path.join(a.dir, 'competition.md')}")


if __name__ == "__main__":
    main()
