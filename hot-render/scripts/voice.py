"""配旁白：稿子是 voice: tts 时，把每屏的 narration 用 MiniMax 语音合成念出来。由 render.py 调用，也可以单独跑：

    python3 voice.py --dir 热点/日期

- 产出：热点/日期/voice/<屏id>.mp3（+ <屏id>.words.json 逐字时间，+ <屏id>.key 记着这句是用什么文字和音色生成的）。
- 接口：设环境变量 MINIMAX_API_KEY（在中国大陆以外用，再设 MINIMAX_API_HOST=https://api.minimax.io）。
  已经生成过、文字和音色都没变的句子不会重复花钱；改了哪屏的旁白就只重出那一屏。
- 没有密钥：列出还缺哪几屏、每屏该用的音色和语速，用户在 MiniMax 网页「文本转语音」里生成、下载，
  按屏 id 存成 voice/s1.mp3、voice/s2.mp3……再跑一次。自己录的也照这个名字放，脚本不会覆盖（没有 .key 文件的都当成你自己的）。
- 音色：热点/ip/voice.json（可选），例 {"voice_id": "Chinese (Mandarin)_Radio_Host", "speed": 1.2}。
  也可以填自己在 MiniMax 复刻出来的音色 id。没有就用默认（电台男主播，语速 1.2）。
- 旁白里可以写 MiniMax 的标记：<#0.4#> 停顿，(laughs) (sighs) (chuckle) 之类的语气声，行(hang2) 纠正读音。字幕里会自动去掉。
- 密钥只从环境变量读，不写进任何文件、不打印。
"""
import argparse, hashlib, json, math, os, re, subprocess, sys, time
import urllib.error, urllib.request
from pathlib import Path

DEFAULT = {"model": "speech-2.8-hd", "voice_id": "Chinese (Mandarin)_Radio_Host", "speed": 1.2}
MARKUP = re.compile(r"<#[\d.]+#>|\([a-z]+\d?\)")          # 停顿、语气声、注音
PUNCT = "。！？；，、,.!?;:：…—“”\"'‘’（）() "
LEAD, TAIL = .2, .35                                       # 切屏后多久开口；念完留多久再切


def clean(text):
    return re.sub(r"\s+", " ", MARKUP.sub("", text or "")).strip()


def load_voice(dirp):
    vp = dirp.parent / "ip" / "voice.json"
    v = dict(DEFAULT)
    if vp.exists():
        v.update(json.loads(vp.read_text(encoding="utf-8")))
    return v


def post(url, body, key):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())


def words_from(sub):
    """MiniMax 的逐字字幕文件 -> [{text, start, end}]（秒）。形状宽容：有 text/word 和 time_begin/time_end 的都算；大于 100 的当毫秒。"""
    out = []

    def walk(x):
        if isinstance(x, dict):
            tw = x.get("timestamped_words")
            if isinstance(tw, list) and tw:
                return walk(tw)
            text = x.get("word", x.get("text"))
            if isinstance(text, str) and "time_begin" in x and "time_end" in x:
                out.append({"text": text, "start": float(x["time_begin"]), "end": float(x["time_end"])})
                return
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    walk(sub)
    if out and max(w["end"] for w in out) > 100:
        for w in out:
            w["start"] /= 1000
            w["end"] /= 1000
    return out


def generate(text, voice, key, host):
    vs = {"voice_id": voice["voice_id"], "speed": voice.get("speed", 1.0), "vol": voice.get("vol", 1.0), "pitch": voice.get("pitch", 0)}
    if voice.get("emotion"):
        vs["emotion"] = voice["emotion"]
    body = {"model": voice.get("model", DEFAULT["model"]), "text": text, "stream": False, "voice_setting": vs,
            "audio_setting": {"sample_rate": 32000, "bitrate": 128000, "format": "mp3", "channel": 1},
            "subtitle_enable": True, "subtitle_type": "word"}
    res = post(f"{host}/v1/t2a_v2", body, key)
    st = res.get("base_resp") or {}
    if st.get("status_code", 0) != 0:
        raise RuntimeError(f"MiniMax {st.get('status_code')}：{st.get('status_msg')}（1008 多半是余额不足，2049 / 1004 多半是密钥不对）")
    data = res.get("data") or {}
    audio = bytes.fromhex(data["audio"])
    words = []
    sub_url = data.get("subtitle_file") or res.get("subtitle_file")
    if sub_url:
        try:
            with urllib.request.urlopen(sub_url, timeout=60) as r:
                words = words_from(json.loads(r.read()))
        except (urllib.error.URLError, ValueError):
            words = []
    return audio, words


def duration(ffmpeg, path):
    r = subprocess.run([ffmpeg, "-hide_banner", "-i", str(path)], capture_output=True, text=True, encoding="utf-8", errors="replace")
    m = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", r.stderr)
    if not m:
        raise SystemExit(f"读不出配音长度：{path}")
    return int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3])


def chunks(text, maxlen=16):
    """念的字切成一条条字幕：按标点断，太长的再按 maxlen 切；返回 [(字幕, 这一条里能念出来的字数)]"""
    parts, cur = [], ""
    for c in text:
        cur += c
        if c in "。！？；，,.!?;":
            parts.append(cur)
            cur = ""
    if cur:
        parts.append(cur)
    out = []
    for p in parts:
        p = p.strip().rstrip("，,、；;")
        while len(p) > maxlen:
            out.append(p[:maxlen])
            p = p[maxlen:]
        if p:
            out.append(p)
    return [(c, sum(1 for ch in c if ch not in PUNCT)) for c in out]


def subs_for(text, dur, words):
    """每条字幕什么时候出（相对开口的秒数）。有逐字时间就按字对，没有就按字数平均分。"""
    cs = chunks(text)
    total = sum(n for _, n in cs) or 1
    # 第 k 个能念出来的字是什么时候念的
    if words:
        times = []
        for w in words:
            n = sum(1 for ch in w["text"] if ch not in PUNCT)
            for j in range(n):
                times.append(w["start"] + (w["end"] - w["start"]) * j / max(n, 1))
    out, k = [], 0
    for c, n in cs:
        a = times[k] if words and k < len(times) else dur * k / total
        out.append({"a": round(a, 3), "text": c})
        k += n
    return out


def ensure(dirp, ffmpeg, strict=True):
    """把稿子里每屏的旁白配好。返回 {屏id: {"file", "dur", "subs"}}；缺文件时 strict=True 就退出并列清单，否则返回 None。"""
    sc = json.loads((dirp / "script.json").read_text(encoding="utf-8"))
    if sc.get("voice") != "tts":
        return {}
    voice = load_voice(dirp)
    out = dirp / "voice"
    out.mkdir(exist_ok=True)
    key = os.environ.get("MINIMAX_API_KEY", "").strip()
    host = os.environ.get("MINIMAX_API_HOST", "https://api.minimax.cn").rstrip("/")
    missing, made, res = [], 0, {}
    for s in sc.get("scenes") or []:
        sid, say = s.get("id"), (s.get("narration") or "").strip()
        if not say:
            continue
        mp3, stamp, wj = out / f"{sid}.mp3", out / f"{sid}.key", out / f"{sid}.words.json"
        sig = hashlib.sha1(json.dumps([say, voice], ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:12]
        if not (mp3.exists() and (not stamp.exists() or stamp.read_text() == sig)):
            if not key:
                missing.append(f"  {sid}.mp3   {say}")
                continue
            for attempt in range(3):
                try:
                    audio, words = generate(say, voice, key, host)
                    break
                except (urllib.error.URLError, RuntimeError, KeyError, TimeoutError) as e:
                    if attempt == 2 or "余额" in str(e) or "密钥" in str(e):
                        raise SystemExit(f"{sid}：MiniMax 配音失败：{e}")
                    time.sleep(3)
            mp3.write_bytes(audio)
            wj.write_text(json.dumps(words, ensure_ascii=False), encoding="utf-8")
            stamp.write_text(sig)
            made += 1
            print(f"  配音 {sid}：{clean(say)[:30]}")
        d = duration(ffmpeg, mp3)
        words = json.loads(wj.read_text(encoding="utf-8")) if wj.exists() else []
        res[sid] = {"file": str(mp3), "dur": round(d, 3), "subs": subs_for(clean(say), d, words)}
    if missing:
        msg = (f"没有设 MINIMAX_API_KEY，还缺 {len(missing)} 屏的配音。\n"
               f"在 MiniMax 网页「文本转语音」里用音色「{voice['voice_id']}」、语速 {voice.get('speed', 1.0)}、模型 {voice.get('model')} 一屏一屏生成，"
               f"下载后按下面的名字存进 {out}，再跑一次：\n" + "\n".join(missing))
        if strict:
            print(msg)
            sys.exit(2)
        print("提醒  " + msg.splitlines()[0] + "定格图先按稿子里的秒数出。")
        return None
    if made:
        print(f"配音：新生成 {made} 屏（MiniMax {voice.get('model')}，音色 {voice['voice_id']}）")
    return res


def scene_seconds(vdur):
    """一屏停多久：开口前 LEAD + 念完 + TAIL，向上取到半秒（切换落在音乐拍子上），最少 1.5 秒"""
    return max(1.5, math.ceil((vdur + LEAD + TAIL) * 2) / 2)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True, help="稿子所在文件夹，例 热点/2026-11-09")
    ap.add_argument("--ffmpeg", default="ffmpeg")
    a = ap.parse_args()
    r = ensure(Path(a.dir).resolve(), a.ffmpeg)
    for sid, v in (r or {}).items():
        print(f"{sid}  {v['dur']:.2f} 秒 -> 这屏停 {scene_seconds(v['dur'])} 秒")
