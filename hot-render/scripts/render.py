#!/usr/bin/env python3
"""把 script.json 渲染成视频（数据画面 + 字幕 + 背景音乐 + 转场音效），画面有几种风格可选（--style）。

只用 Python 标准库；另外要 Node 22+、Chrome（或 Edge / Chromium）、ffmpeg（没有会自动装 imageio-ffmpeg）。
用法（在用户的工作文件夹里运行）：
  python3 render.py --check                 只出每屏的定格图和总览拼图，先看画面
  python3 render.py                         出整条 video.mp4
选项：
  --dir 热点/今天日期        默认今天的文件夹
  --size 1920x1080           横屏（默认）；竖屏用 1080x1920
  --style poster|chalk|paper|sticker  画面风格：poster 海报风（默认）、chalk 黑板粉笔、paper 纸面卡片、sticker 绘本贴纸
  --music beat|none|文件路径  beat = 自带合成的节奏（默认）；none = 只留转场音效（发布时在 App 里选热门音乐）；
                              也可以给一个 mp3 / wav（自己有版权的）
  --avatar 图片路径           字幕胶囊左边的圆形头像（可选；默认用 热点/ip/avatar.png，其次 热点/avatar.png，没有就不放）
稿子是 voice: tts 时自动配旁白（MiniMax 语音合成，见 voice.py），每屏停多久按念多久算，字幕跟着念到的字走。
  --fps 30   --jobs 4         帧率、同时开几个 Chrome
  --only s3,s5                --check 时只出这几屏
"""
import argparse, glob, json, math, os, platform, re, shutil, subprocess, sys, time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ASSETS = HERE.parent / "assets"
sys.path.insert(0, str(HERE))
import audio  # noqa: E402
import voice  # noqa: E402

try:
    sys.stdout.reconfigure(line_buffering=True)   # 被管道接走时也按顺序立刻打出来
except Exception:
    pass

TYPES = {"title", "number", "bars", "compare", "list", "quote", "vote"}
STYLES = {"poster": "海报风：热橙 / 墨黑大色块、超大斜体粗字、整块色板换屏",
          "chalk": "黑板粉笔：墨绿黑板、粉笔字一笔笔写出来、手画下划线和圈",
          "paper": "纸面卡片：米色点阵底、白卡片、绿色强调",
          "sticker": "绘本贴纸：米色纸画框、铅笔线画出来、水彩荧光笔、拿工具的小机器人跟着蹦"}


def die(msg):
    print("错误  " + msg)
    sys.exit(1)


# ---------- 找工具 ----------
def find_node():
    cands = [os.environ.get("NODE"), shutil.which("node")]
    home = Path.home()
    cands += glob.glob(str(home / ".workbuddy/binaries/**/bin/node"), recursive=True)
    cands += glob.glob(str(home / ".workbuddy/binaries/**/node.exe"), recursive=True)
    for c in cands:
        if not c or not Path(c).exists():
            continue
        try:
            v = subprocess.run([c, "-v"], capture_output=True, text=True).stdout.strip()
            if int(v.lstrip("v").split(".")[0]) >= 22:
                return c
        except Exception:
            pass
    die("找不到 Node 22 以上的版本（要它自带的 WebSocket）。装一个新版 Node（nodejs.org），或者用环境变量 NODE 指过去。")


def find_chrome():
    if os.environ.get("CHROME") and Path(os.environ["CHROME"]).exists():
        return os.environ["CHROME"]
    sysname = platform.system()
    home = Path.home()
    if sysname == "Darwin":
        cands = ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                 "/Applications/Chromium.app/Contents/MacOS/Chromium",
                 "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"]
        cands += glob.glob(str(home / "Library/Caches/ms-playwright/chromium-*/chrome-mac*/*.app/Contents/MacOS/*"))
    elif sysname == "Windows":
        pf = [os.environ.get(k, "") for k in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA")]
        cands = [str(Path(p) / sub) for p in pf if p for sub in
                 ("Google/Chrome/Application/chrome.exe", "Microsoft/Edge/Application/msedge.exe")]
        cands += glob.glob(str(Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright/chromium-*/chrome-win*/chrome.exe"))
    else:
        cands = [shutil.which(x) for x in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge")]
        cands += glob.glob(str(home / ".cache/ms-playwright/chromium-*/chrome-linux*/chrome"))
    for c in cands:
        if c and Path(c).exists():
            return c
    die("找不到 Chrome / Edge / Chromium。装一个 Chrome，或者运行 `npx playwright install chromium` 后再跑；也可以用环境变量 CHROME 指过去。")


def find_ffmpeg():
    for c in (os.environ.get("FFMPEG"), shutil.which("ffmpeg")):
        if c and Path(c).exists():
            return c
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        print("没有 ffmpeg，自动装 imageio-ffmpeg（自带 ffmpeg，约 30MB）……")
        r = subprocess.run([sys.executable, "-m", "pip", "install", "--user", "-q", "imageio-ffmpeg"])
        if r.returncode == 0:
            import site, importlib
            sys.path.append(site.getusersitepackages())
            importlib.invalidate_caches()
            import imageio_ffmpeg
            return imageio_ffmpeg.get_ffmpeg_exe()
    die("找不到 ffmpeg，自动安装也失败了。手动装一个 ffmpeg，或者 `pip install imageio-ffmpeg`。")


# ---------- 读稿子 ----------
def load(dirp, size, avatar, vo=None):
    sp = dirp / "script.json"
    if not sp.exists():
        die(f"找不到 {sp}。要在用户的工作文件夹里运行（里面有「热点」文件夹），或者用 --dir 指定。")
    sc = json.load(open(sp, encoding="utf-8"))
    scenes, t, warns = [], 0.0, []
    for s in sc.get("scenes") or []:
        v = s.get("visual") or {}
        if v.get("type") not in TYPES:
            die(f"{s.get('id')}：画面类型「{v.get('type')}」不认识，只认 {'/'.join(sorted(TYPES))}。先回 hot-script 改稿。")
        d = float(s.get("seconds") or 3)
        row = {"id": s.get("id"), "t0": round(t, 3), "dur": d, "visual": v, "caption": s.get("caption") or ""}
        if vo and s.get("id") in vo:              # 配了旁白：这屏停多久按念多久算，字幕跟着念到的字走
            x = vo[s.get("id")]
            d = row["dur"] = voice.scene_seconds(x["dur"])
            row["voice"] = x["file"]
            row["subs"] = [{"a": round(voice.LEAD + c["a"], 3), "text": c["text"]} for c in x["subs"]]
        elif d * 2 != round(d * 2):
            warns.append(f"{s.get('id')}：停 {d} 秒，不是 0.5 秒的整数倍，切换不在拍子上")
        scenes.append(row)
        t += d
    if not scenes:
        die("script.json 里没有 scenes")
    tgt = sc.get("target_seconds")
    if tgt and abs(tgt - t) >= 1 and not vo:
        warns.append(f"script.json 的 target_seconds 是 {tgt}，实际各屏加起来 {round(t, 1)} 秒（以实际为准）")
    w, h = (int(x) for x in size.lower().split("x"))
    spec = {"w": w, "h": h, "corner": sc.get("corner") or "", "avatar": None, "scenes": scenes, "total": round(t, 3), "voiced": bool(vo)}
    return sc, spec, warns


def prepare(dirp, spec, avatar, style):
    rd = dirp / "render"
    rd.mkdir(exist_ok=True)
    shutil.copy(ASSETS / "styles" / f"{style}.html", rd / "page.html")
    shutil.copy(ASSETS / "styles" / "core.js", rd / "core.js")
    shutil.copytree(ASSETS / "fonts", rd / "fonts", dirs_exist_ok=True)
    if style == "sticker":
        shutil.copytree(ASSETS / "stickers", rd / "stickers", dirs_exist_ok=True)
        own = dirp.parent / "ip" / "stickers"   # 用户自己的角色贴纸：同名文件盖掉自带的小机器人
        if own.is_dir():
            for f in own.glob("bot*.png"):
                shutil.copy(f, rd / "stickers" / f.name)
    if avatar:
        ap = Path(avatar)
        if not ap.exists():
            die(f"头像文件不存在：{ap}")
        shutil.copy(ap, rd / ("avatar" + ap.suffix.lower()))
        spec["avatar"] = "avatar" + ap.suffix.lower()
    # capAt：这一刻字幕条上显示什么。配了旁白就是正在念的那一句，没配就是这屏的 caption
    cap_js = ("window.capAt = (sc, t) => { if (!sc.subs || !sc.subs.length) return sc.caption; const lt = t - sc.t0; "
              "let c = sc.subs[0].text; for (const s of sc.subs) if (lt >= s.a) c = s.text; return c; };\n")
    (rd / "spec.js").write_text("window.SPEC = " + json.dumps(spec, ensure_ascii=False) + ";\n" + cap_js, encoding="utf-8")
    return rd


def run_frames(node, chrome, ffmpeg, rd, spec, extra, profile):
    cmd = [node, str(HERE / "frames.mjs"), "--page", (rd / "page.html").resolve().as_uri(), "--size", f"{spec['w']}x{spec['h']}",
           "--chrome", chrome, "--profile", str(profile), "--ffmpeg", ffmpeg, *extra]
    return subprocess.Popen(cmd)


def stills(node, chrome, ffmpeg, rd, spec, only):
    chk = rd / f"check-{spec['w']}x{spec['h']}"     # 横竖屏分开放，互不覆盖
    if chk.exists():
        shutil.rmtree(chk)
    chk.mkdir()
    ts, names = [], []
    for i, s in enumerate(spec["scenes"]):
        if only and s["id"] not in only:
            continue
        if i == 0:                               # 第 0 帧：刷到时第一眼、也是平台默认封面
            ts.append(0)
            names.append(f"{len(names) + 1:03d}_{s['id']}_open")
        ts.append(s["t0"] + s["dur"] - .12)      # 每屏最后的定格
        names.append(f"{len(names) + 1:03d}_{s['id']}")
    prof = rd / ".chrome-check"
    extra = ["--stills", ",".join(f"{t:.3f}" for t in ts), "--names", ",".join(names), "--outdir", str(chk)]
    for attempt in (1, 2):                       # Chrome 偶尔起不来，重试一次
        shutil.rmtree(prof, ignore_errors=True)
        if run_frames(node, chrome, ffmpeg, rd, spec, extra, prof).wait() == 0:
            break
        if attempt == 2:
            die("截图失败，看上面 Chrome / 页面的报错")
        print("截图失败，重试一次……")
    shutil.rmtree(prof, ignore_errors=True)
    portrait = spec["h"] > spec["w"]
    cols = 6 if portrait else 4
    rows = math.ceil(len(names) / cols)
    tw = 270 if portrait else 480
    files = sorted(chk.glob("*.png"))
    seq = chk / "_seq"
    seq.mkdir()
    for i, f in enumerate(files):
        shutil.copy(f, seq / f"{i:03d}.png")
    subprocess.run([ffmpeg, "-v", "error", "-y", "-framerate", "1", "-i", str(seq / "%03d.png"), "-vf",
                    f"scale={tw}:-1,pad=iw+8:ih+8:4:4:white,tile={cols}x{rows}:color=white", "-frames:v", "1", str(chk / "sheet.jpg")], check=True)
    shutil.rmtree(seq)
    return chk, files


def video(node, chrome, ffmpeg, rd, spec, fps, jobs):
    frames = math.ceil(spec["total"] * fps)
    jobs = max(1, min(jobs, frames // (fps * 3) or 1))
    step = math.ceil(frames / jobs)
    procs, segs = [], []
    for j in range(jobs):
        a, b = j * step, min(frames, (j + 1) * step)
        if a >= b:
            break
        seg = rd / f"seg{j}.mp4"
        segs.append(seg)
        procs.append((run_frames(node, chrome, ffmpeg, rd, spec, ["--video", str(seg), "--fps", str(fps), "--start", str(a), "--end", str(b), "--label", f"第 {j + 1}/{jobs} 段"], rd / f".chrome-{j}"), j))
    bad = [j for p, j in procs if p.wait() != 0]
    for j in list(bad):                          # 失败的段重跑一次
        print(f"第 {j} 段失败，重跑一次……")
        shutil.rmtree(rd / f".chrome-{j}", ignore_errors=True)
        a, b = j * step, min(frames, (j + 1) * step)
        p = run_frames(node, chrome, ffmpeg, rd, spec, ["--video", str(segs[j]), "--fps", str(fps), "--start", str(a), "--end", str(b)], rd / f".chrome-{j}")
        if p.wait() == 0:
            bad.remove(j)
    for j in range(len(procs)):
        shutil.rmtree(rd / f".chrome-{j}", ignore_errors=True)
    if bad:
        die(f"第 {bad} 段渲染失败，看上面的报错")
    lst = rd / "segs.txt"
    lst.write_text("".join(f"file '{s.name}'\n" for s in segs), encoding="utf-8")
    out = rd / "video_noaudio.mp4"
    subprocess.run([ffmpeg, "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(out)], check=True, cwd=rd)
    for s in segs:
        s.unlink()
    lst.unlink()
    return out


def make_audio(ffmpeg, rd, spec, music):
    """音乐 + 转场音效（+ 旁白）。有旁白时音乐压到 0.3，旁白在每屏开头 voice.LEAD 秒开口。"""
    total = spec["total"]
    cuts = [s["t0"] for s in spec["scenes"]]
    sfx, kept = audio.sfx_track(total, cuts)
    wav = rd / "audio_raw.wav"
    if music == "beat":
        audio.write_wav(wav, audio.mix(audio.music_bed(total), sfx, .8, .55))
    else:
        audio.write_wav(rd / "sfx.wav", sfx)
        if music == "none":
            shutil.move(rd / "sfx.wav", wav)
        else:
            mp = Path(music)
            if not mp.exists():
                die(f"音乐文件不存在：{mp}")
            fo = max(0, total - 1.5)
            subprocess.run([ffmpeg, "-v", "error", "-y", "-stream_loop", "-1", "-i", str(mp), "-i", str(rd / "sfx.wav"), "-filter_complex",
                            f"[0:a]atrim=0:{total},afade=t=out:st={fo}:d=1.5,volume=0.8[m];[1:a]volume=0.55[s];[m][s]amix=2:normalize=0:duration=first",
                            "-ac", "1", "-ar", str(audio.SR), str(wav)], check=True)
            (rd / "sfx.wav").unlink()
    if spec.get("voiced"):
        vs = [(s["t0"] + voice.LEAD, s["voice"]) for s in spec["scenes"] if s.get("voice")]
        args, fl = [ffmpeg, "-v", "error", "-y", "-i", str(wav)], ["[0:a]volume=0.3[b]"]
        for k, (st, f) in enumerate(vs, start=1):
            args += ["-i", f]
            fl.append(f"[{k}:a]aresample={audio.SR},adelay={int(st * 1000)}:all=1[v{k}]")
        fl.append("[b]" + "".join(f"[v{k}]" for k in range(1, len(vs) + 1)) + f"amix={len(vs) + 1}:normalize=0:duration=first[o]")
        mixed = rd / "audio_voice.wav"
        subprocess.run(args + ["-filter_complex", ";".join(fl), "-map", "[o]", "-ac", "1", "-ar", str(audio.SR), str(mixed)], check=True)
        wav.unlink()
        wav = mixed
    out = rd / "audio.m4a"
    target = "-16" if music != "none" or spec.get("voiced") else "-18"
    subprocess.run([ffmpeg, "-v", "error", "-y", "-i", str(wav), "-af", f"loudnorm=I={target}:TP=-1.5:LRA=11", "-ar", "48000", "-ac", "2",
                    "-c:a", "aac", "-b:a", "192k", str(out)], check=True)
    wav.unlink()
    return out, len(kept)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=os.path.join("热点", datetime.now().strftime("%Y-%m-%d")), help="稿子所在文件夹，默认 热点/今天日期")
    ap.add_argument("--size", default="1920x1080", help="1920x1080 横屏（默认）/ 1080x1920 竖屏")
    ap.add_argument("--style", default="poster", choices=sorted(STYLES), help="画面风格：poster（默认）/ chalk / paper / sticker")
    ap.add_argument("--music", default="beat", help="beat（默认，自带合成节奏）/ none（只留转场音效）/ 音乐文件路径")
    ap.add_argument("--avatar", default=None, help="字幕胶囊头像，默认 热点/avatar.png")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--jobs", type=int, default=min(4, os.cpu_count() or 2))
    ap.add_argument("--check", action="store_true", help="只出定格图和总览拼图")
    ap.add_argument("--only", default="", help="--check 时只出这几屏，例 s3,s5")
    a = ap.parse_args()
    if not re.fullmatch(r"\d{3,4}x\d{3,4}", a.size):
        die("--size 写成 1920x1080 或 1080x1920")
    dirp = Path(a.dir).resolve()
    avatar = a.avatar
    if avatar is None:                            # IP 文件夹里的头像优先，其次是老位置 热点/avatar.png
        for c in (dirp.parent / "ip" / "avatar.png", dirp.parent / "ip" / "avatar.jpg", dirp.parent / "avatar.png", dirp.parent / "avatar.jpg"):
            if c.exists():
                avatar = str(c)
                break
    if not (dirp / "script.json").exists():
        die(f"找不到 {dirp / 'script.json'}。要在用户的工作文件夹里运行（里面有「热点」文件夹），或者用 --dir 指定。")
    node, chrome, ffmpeg = find_node(), find_chrome(), find_ffmpeg()
    vo = voice.ensure(dirp, ffmpeg, strict=not a.check) or {}   # 稿子是 voice: tts 才会配音
    sc, spec, warns = load(dirp, a.size, avatar, vo)
    rd = prepare(dirp, spec, avatar, a.style)
    t0 = time.time()
    print(f"{len(spec['scenes'])} 屏，{spec['total']} 秒，{a.size}，风格：{a.style}（{STYLES[a.style]}），头像：{'有' if spec['avatar'] else '无'}，旁白：{('有（' + str(len(vo)) + ' 屏）') if vo else '无'}")
    for w in warns:
        print("提醒  " + w)

    chk = rd / f"check-{spec['w']}x{spec['h']}"
    sheet = chk / "sheet.jpg"
    tag = chk / "style.txt"   # 定格图是哪种风格出的；换了风格就得重出
    stamp = f"{a.style} {spec['total']}"   # 风格或总长（配音改了会变）不一样就重出
    fresh = (sheet.exists() and tag.exists() and tag.read_text(encoding="utf-8").strip() == stamp
             and sheet.stat().st_mtime > (dirp / "script.json").stat().st_mtime
             and sheet.stat().st_mtime > (ASSETS / "styles" / f"{a.style}.html").stat().st_mtime)
    if a.check or a.only or not fresh:
        chk, files = stills(node, chrome, ffmpeg, rd, spec, set(filter(None, a.only.split(","))))
        (chk / "style.txt").write_text(stamp, encoding="utf-8")
        print(f"定格图 {len(files)} 张：{chk}（总览拼图 {chk / 'sheet.jpg'}）")
    else:
        print(f"定格图比稿子新，不重出：{sheet}")
    if a.check:
        return

    print(f"开始渲染（{a.jobs} 个 Chrome 同时跑）……")
    vid = video(node, chrome, ffmpeg, rd, spec, a.fps, a.jobs)
    aud, n_sfx = make_audio(ffmpeg, rd, spec, a.music)
    out = dirp / "video.mp4"
    subprocess.run([ffmpeg, "-v", "error", "-y", "-i", str(vid), "-i", str(aud), "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "copy",
                    "-shortest", "-movflags", "+faststart", str(out)], check=True)
    vid.unlink()
    aud.unlink()
    mb = out.stat().st_size / 1e6
    print(f"完成：{out}（{spec['total']} 秒，{mb:.1f}MB，风格 {a.style}，音乐 {a.music}，转场音效 {n_sfx} 个，用时 {time.time() - t0:.0f} 秒）")


if __name__ == "__main__":
    main()
