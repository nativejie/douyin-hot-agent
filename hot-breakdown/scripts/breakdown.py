#!/usr/bin/env python3
"""拆同题爆款：把 pick.json 里的对手视频拉下来，量节奏、截画面、拉热评，给 AI 看。

只用 Python 标准库 + 系统 curl + ffmpeg（没有 ffmpeg 会自动 pip 装 imageio-ffmpeg）。
密钥从环境变量 TIKHUB_API_KEY 读。
用法：
  python3 breakdown.py [--dir 热点/今天日期] [--url 抖音视频链接 ...] [--me 自己的抖音昵称] [--keep] [--force]
1 小时内拆过、又没加新的 --url，就直接复用上次的结果（--force 重拆）。
默认读 pick.json 的 competitors；--url 可以再加别的视频（比如同格式的老爆款）。
每条视频：详情 1 次 + 评论 1 次，约 0.002 美元。
产出（在 --dir/breakdown/ 下）：
  <id>_cover.jpg  封面
  <id>_open.jpg   开头 0–4 秒 8 帧拼图（看第一眼放什么）
  <id>_all.jpg    全片均匀取帧拼图（4–16 帧，按时长，看整体结构）
  breakdown.json / breakdown.md
视频文件默认分析完就删（只做分析，不留存、不搬运），--keep 保留。
"""
import argparse, glob, json, os, re, shutil, subprocess, sys, time
from datetime import datetime

BASE = os.environ.get("TIKHUB_BASE", "https://api.tikhub.io")
KEY = os.environ.get("TIKHUB_API_KEY", "")


def api(path, params):
    url = BASE + path + "?" + "&".join(f"{k}={v}" for k, v in params.items())
    cmd = ["curl", "-s", "-m", "60", url, "-H", "Authorization: Bearer " + KEY]
    if os.environ.get("TIKHUB_NOPROXY"):
        cmd[1:1] = ["--noproxy", "*"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return {"error": (r.stdout or r.stderr)[:150]}


def detail(aweme_id):
    """先用 v1，被过滤（filter_list）再用 v3；v3 偶尔报 400，再试一次。"""
    for ep in ("fetch_one_video", "fetch_one_video_v3", "fetch_one_video_v3"):
        out = api(f"/api/v1/douyin/app/v3/{ep}", {"aweme_id": aweme_id})
        a = (out.get("data") or {}).get("aweme_detail")
        if a:
            return a, ""
    return None, f"拿不到视频详情（{str(out)[:120]}）"


def comments(aweme_id):
    out = api("/api/v1/douyin/app/v3/fetch_video_comments", {"aweme_id": aweme_id, "cursor": 0})
    res = []
    for c in (out.get("data") or {}).get("comments") or []:
        res.append({"text": (c.get("text") or "").replace("\n", " ")[:120], "likes": c.get("digg_count") or 0,
                    "replies": c.get("reply_comment_total") or 0, "ip": c.get("ip_label") or ""})
    return sorted(res, key=lambda c: -c["likes"])


def find_ffmpeg():
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg
    except ImportError:
        print("没有 ffmpeg，正在装 imageio-ffmpeg（自带 ffmpeg，约 30MB）…")
        subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "--user", "imageio-ffmpeg"])
        try:
            import site, importlib
            importlib.reload(site)
            import imageio_ffmpeg
        except ImportError:
            return None
    return imageio_ffmpeg.get_ffmpeg_exe()


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def media_duration(ff, path):
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", run([ff, "-hide_banner", "-i", path]).stderr)
    return int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3]) if m else 0


def cuts(ff, path):
    """镜头切换时间点（画面变化超过阈值就算一刀）。"""
    err = run([ff, "-hide_banner", "-i", path, "-vf", "select='gt(scene,0.25)',showinfo", "-f", "null", "-"]).stderr
    # 0.2 秒以内的是片头第一帧，不算切换
    return [round(float(t), 2) for t in re.findall(r"pts_time:([\d.]+)", err) if float(t) > 0.2]


def has_voice(ff, path):
    """粗看有没有持续的人声 / 声音：平均音量高于 -35dB 算有声。"""
    err = run([ff, "-hide_banner", "-i", path, "-af", "volumedetect", "-f", "null", "-"]).stderr
    m = re.search(r"mean_volume: (-?[\d.]+) dB", err)
    return float(m[1]) if m else None


def changes(ff, path, fps=4, w=48, h=84, block_thr=22):
    """画面变化次数：每秒取 4 帧缩成小灰度图，切成 4×4 块，任何一块平均变化超过阈值就算变了一次。
    比镜头切换检测灵：固定外框只换中间、同一底色换数据面板，都能测到。返回变化发生的时间点。"""
    r = subprocess.run([ff, "-hide_banner", "-loglevel", "error", "-i", path, "-vf",
                        f"fps={fps},scale={w}:{h},format=gray", "-f", "rawvideo", "-"], capture_output=True)
    data, n = r.stdout, w * h
    frames = [data[i:i + n] for i in range(0, len(data) - n + 1, n)]
    bw, bh, times, last = w // 4, h // 4, [], -9
    for k in range(1, len(frames)):
        a, b = frames[k - 1], frames[k]
        worst = 0
        for by in range(4):
            for bx in range(4):
                tot = 0
                for y in range(by * bh, by * bh + bh, 2):
                    row = y * w
                    for x in range(bx * bw, bx * bw + bw, 2):
                        tot += abs(a[row + x] - b[row + x])
                worst = max(worst, tot / ((bh // 2) * (bw // 2)))
        t = k / fps
        if worst > block_thr and t - last > 0.6:  # 0.6 秒内连着变算一次（动画过渡）
            times.append(round(t, 2))
            last = t
    return times


def sheet(ff, path, times, out, cols):
    tmp = out + "_frames"
    os.makedirs(tmp, exist_ok=True)
    for i, t in enumerate(times):
        # -ss 放在 -i 后面：逐帧精确定位（放前面会跳到关键帧，第 0 秒可能取错）
        run([ff, "-hide_banner", "-loglevel", "error", "-i", path, "-ss", f"{t:.2f}", "-frames:v", "1",
             "-vf", "scale=360:-2", "-y", os.path.join(tmp, f"{i:02d}.jpg")])
    n = len(glob.glob(os.path.join(tmp, "*.jpg")))
    if n:
        rows = (n + cols - 1) // cols
        run([ff, "-hide_banner", "-loglevel", "error", "-i", os.path.join(tmp, "%02d.jpg"),
             "-vf", f"tile={cols}x{rows}:padding=6:color=white", "-frames:v", "1", "-y", out])
    shutil.rmtree(tmp, ignore_errors=True)
    return os.path.exists(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=os.path.join("热点", datetime.now().strftime("%Y-%m-%d")))
    ap.add_argument("--url", nargs="*", default=[])
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--me", default="", help="自己的抖音昵称，拆到自己的视频会标出来")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    if not KEY:
        sys.exit("没有 TIKHUB_API_KEY 环境变量。")
    cached = os.path.join(a.dir, "breakdown.json")
    if not a.force and not a.url and os.path.exists(cached) and time.time() - os.path.getmtime(cached) < 3600:
        print(f"1 小时内拆过，直接用 → {os.path.join(a.dir, 'breakdown.md')}（要重拆加 --force）")
        return
    urls = list(a.url)
    pick_path = os.path.join(a.dir, "pick.json")
    if os.path.exists(pick_path):
        comp = json.load(open(pick_path, encoding="utf-8")).get("competitors") or []
        if isinstance(comp, dict):  # {"same_angle": [...], "same_topic": [...]}
            comp = comp.get("same_angle", []) + comp.get("same_topic", [])
        urls = comp + urls
    ids = []
    for u in urls:
        m = re.search(r"(\d{15,})", u)
        if m and m[1] not in ids:
            ids.append(m[1])
    if not ids:
        sys.exit("没有要拆的视频：pick.json 里没有 competitors，也没给 --url。")

    # 详情接口不给粉丝数，从上一步的 competition.json 里补
    fans_from_search = {}
    cpath = os.path.join(a.dir, "competition.json")
    if os.path.exists(cpath):
        for it in json.load(open(cpath, encoding="utf-8")).get("items", []):
            for srch in it.get("searches", []):
                for v in srch.get("videos", []):
                    m = re.search(r"(\d{15,})", v.get("url", ""))
                    if m:
                        fans_from_search[m[1]] = v.get("fans")

    ff = find_ffmpeg()
    outdir = os.path.join(a.dir, "breakdown")
    os.makedirs(outdir, exist_ok=True)
    results, md = [], [f"# 拆同题爆款 {datetime.now():%Y-%m-%d %H:%M}", "",
                       "每条：基本数据、节奏（画面变化次数 + 硬切镜头）、声音、封面、开头拼图（0–4 秒 8 帧，左上到右下）、全片拼图（按时长均匀 4–16 帧）、热评前 10。", ""]
    if not ff:
        md.append("**没有 ffmpeg，也没装上 imageio-ffmpeg：节奏和画面没分析，只有数据和评论。**\n")

    for vid in ids:
        a_, err = detail(vid)
        row = {"id": vid, "url": f"https://www.douyin.com/video/{vid}", "error": err}
        if not a_:
            results.append(row)
            md += [f"## {vid}", "", f"- {err}", ""]
            continue
        s, au, v = a_.get("statistics") or {}, a_.get("author") or {}, a_.get("video") or {}
        row.update({
            "title": (a_.get("desc") or "").replace("\n", " "), "author": au.get("nickname"),
            "fans": au.get("follower_count") or fans_from_search.get(vid), "likes": s.get("digg_count"), "comments": s.get("comment_count"),
            "collects": s.get("collect_count"), "shares": s.get("share_count"),
            "duration_s": round((a_.get("duration") or 0) / 1000, 1),
            "hours_ago": round((time.time() - (a_.get("create_time") or time.time())) / 3600, 1),
            "size": f"{v.get('width')}x{v.get('height')}", "is_aigc": bool(a_.get("is_aigc_media")),
            "mine": bool(a.me) and au.get("nickname") == a.me.strip(),
        })
        cover = ((v.get("origin_cover") or v.get("cover") or {}).get("url_list") or [None])[0]
        if cover:
            cp = os.path.join(outdir, f"{vid}_cover.jpg")
            run(["curl", "-sL", "-m", "60", "-A", "Mozilla/5.0", cover, "-o", cp])
            row["cover"] = f"{vid}_cover.jpg" if os.path.exists(cp) and os.path.getsize(cp) > 1000 else None
        row["top_comments"] = comments(vid)[:10]

        if ff:
            play = ((v.get("play_addr_h264") or v.get("play_addr") or {}).get("url_list") or [None])[0]
            mp4 = os.path.join(outdir, f"{vid}.mp4")
            if play:
                dl = ["curl", "-sL", "-m", "180", "-A", "Mozilla/5.0", play, "-o", mp4]
                run(dl)
            if os.path.exists(mp4) and os.path.getsize(mp4) > 10000:
                dur = media_duration(ff, mp4) or row["duration_s"]
                ct = cuts(ff, mp4)
                row["cuts"] = ct
                row["shots"] = len(ct) + 1
                row["avg_shot_s"] = round(dur / (len(ct) + 1), 1)
                row["cuts_per_10s"] = round(len(ct) / dur * 10, 1) if dur else None
                row["first_cut_s"] = ct[0] if ct else None
                ch = changes(ff, mp4)
                row["changes"] = ch
                row["changes_per_10s"] = round(len(ch) / dur * 10, 1) if dur else None
                row["pace_ok"] = bool(dur and dur >= 10)   # 不到 10 秒的片子，每 10 秒几次没法比
                row["mean_volume_db"] = has_voice(ff, mp4)
                open_t = [t for t in (0, 0.5, 1, 1.5, 2, 2.5, 3, 4) if t < dur]
                n_all = max(4, min(16, int(dur / 1.5)))  # 短片少取几帧，免得帧帧一样
                all_t = [dur * (i + 0.5) / n_all for i in range(n_all)]
                row["open_sheet"] = f"{vid}_open.jpg" if sheet(ff, mp4, open_t, os.path.join(outdir, f"{vid}_open.jpg"), 4) else None
                row["all_sheet"] = f"{vid}_all.jpg" if sheet(ff, mp4, all_t, os.path.join(outdir, f"{vid}_all.jpg"), 4) else None
                row["all_sheet_times"] = [round(t, 1) for t in all_t]
                if not a.keep:
                    os.remove(mp4)
            else:
                row["video_error"] = "视频没下载下来（链接过期或被拦）"
        results.append(row)

        fmt = lambda n: f"{n / 10000:.1f}万" if (n or 0) >= 10000 else str(n)
        md += [f"## {row['title'][:50]}", "",
               f"- {'【自己的】' if row.get('mine') else ''}{row['url']} | {row['author']}（{fmt(row['fans'])} 粉）| {row['hours_ago']} 小时前 | {row['duration_s']} 秒 | {row['size']}{' | 标了 AI 生成' if row['is_aigc'] else ''}",
               f"- {fmt(row['likes'])} 赞 / {fmt(row['comments'])} 评 / {fmt(row['collects'])} 藏 / {fmt(row['shares'])} 转"]
        if "cuts" in row:
            if row.get("pace_ok", True):
                pace = f"**画面每 10 秒变 {row['changes_per_10s']} 次**（分块帧差，主要看这个）；硬切镜头 {row['shots']} 个、每 10 秒 {row['cuts_per_10s']} 次"
            else:
                pace = f"片子不到 10 秒，不算进节奏对比（画面变了 {len(row['changes'])} 次，只作参考）"
            md.append(f"- 节奏：{pace}；平均音量 {row['mean_volume_db']} dB（低于 -35 基本没声音；分不出旁白和音乐）")
            md.append(f"- 封面：breakdown/{row.get('cover')}")
            md.append(f"- 开头拼图：breakdown/{row['open_sheet']}（0、0.5、1、1.5、2、2.5、3、4 秒）")
            md.append(f"- 全片拼图：breakdown/{row['all_sheet']}（{'、'.join(str(t) for t in row['all_sheet_times'])} 秒）")
        elif row.get("video_error"):
            md.append(f"- {row['video_error']}")
        md.append("- 热评：")
        for c in row["top_comments"]:
            rep = f" / {c['replies']} 回复" if c["replies"] else ""
            md.append(f"  - {c['likes']} 赞{rep}：{c['text']}")
        md.append("")

    with open(os.path.join(a.dir, "breakdown.json"), "w", encoding="utf-8") as f:
        json.dump({"checked_at": f"{datetime.now():%Y-%m-%d %H:%M}", "videos": results}, f, ensure_ascii=False, indent=1)
    with open(os.path.join(a.dir, "breakdown.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(md) + "\n")
    print(f"拆了 {len(results)} 条 → {os.path.join(a.dir, 'breakdown.md')}")


if __name__ == "__main__":
    main()
