#!/usr/bin/env python3
"""抓抖音热点：热搜榜 + 娱乐榜 + 上升热点榜（按热度、按排名飙升），合并去重，先用规则滤掉不能碰的。

只用 Python 标准库 + 系统 curl。密钥从环境变量 TIKHUB_API_KEY 读。
用法：
  python3 fetch_hot.py [--out 目录] [--force]
同一天 1 小时内抓过就直接复用（省钱），--force 强制重抓。
产出（默认 ./热点/今天日期/）：
  hot.json     全部热点（含被滤掉的和原因），给下一步用
  hot.md       人能看的表
一次运行调 4 个接口，约 0.004 美元。
"""
import argparse, json, os, re, subprocess, sys, time
from datetime import datetime

BASE = os.environ.get("TIKHUB_BASE", "https://api.tikhub.io")
KEY = os.environ.get("TIKHUB_API_KEY", "")

# 抖音热点分类代码 → 名称（来自 TikHub fetch_hot_category_list，2026-11-07）
TAGS = {
    "美食": [9000], "旅行": [10000], "站内玩法": [1000, 1001, 1002, 1003, 1004],
    "话题互动": [20, 20000, 20001, 20002, 20003, 20005, 20006],
    "娱乐": list(range(2000, 2013)), "社会": [4000, 4003, 4004, 4005, 4006, 4007],
    "二次元": [13000], "交通": [23000], "亲子": [19000], "体育": [5000, 5001, 5002],
    "军事": [21000], "剧情": [18000], "动物萌宠": [8000], "天气": [22001, 22002],
    "才艺": [17000], "文化教育": [14000], "时尚": [16000], "时政": [3000, 3001, 3002],
    "校园": [15000], "汽车": [11000], "游戏": [12000, 12001], "科技": [6000], "财经": [7000],
}
TAG_NAME = {code: name for name, codes in TAGS.items() for code in codes}

# 一律不碰的分类
BLOCK_CATS = {"时政", "军事"}
# 标题里出现就不碰（灾难、伤亡、案件、国际冲突、逝者）
#（写具体的词，别写单字：「战」会误伤「挑战」，「死」会误伤「死心塌地」，「核」会误伤「核桃」）
BLOCK_WORDS = re.compile(
    "死亡|身亡|猝死|死者|致死|遇难|丧生|离世|去世|逝世|悼念|哀悼|遗体|"
    "事故|车祸|坠机|坠楼|坠亡|火灾|起火|爆炸|地震|洪水|洪灾|坍塌|倒塌|塌方|溺水|"
    "袭击|枪击|开枪|命案|案件|涉案|立案|破案|嫌疑人|警方|通报|拘留|判刑|宣判|判决|"
    "殴打|受伤|伤亡|重伤|自杀|轻生|失踪|走失|"
    "战争|开战|交战|空袭|导弹|核武|核弹|制裁|外交部|总统|主席|总理|国防部|领导人|访华"
)
# 平台敏感词：标题、标签里别用（S16「LOL赛事预测」标签没过审）
RISKY_WORDS = re.compile("预测|竞猜|押注|赔率|博彩")


def call(path, params):
    url = BASE + path + "?" + "&".join(f"{k}={v}" for k, v in params.items())
    cmd = ["curl", "-s", "-m", "60", url, "-H", "Authorization: Bearer " + KEY]
    if os.environ.get("TIKHUB_NOPROXY"):  # 有的沙箱代理会掐断大响应
        cmd[1:1] = ["--noproxy", "*"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    try:
        out = json.loads(r.stdout)
    except json.JSONDecodeError:
        sys.exit(f"接口没返回（{path}）：{r.stdout[:200] or r.stderr[:200]}。"
                 "如果是代理问题，设 TIKHUB_NOPROXY=1 再试。")
    if out.get("code") != 200:
        sys.exit(f"接口报错（{path}）：{out.get('message_zh') or out.get('detail') or str(out)[:300]}")
    return out["data"]


def hours_since(ts):
    return round((time.time() - ts) / 3600, 1) if ts else None


def from_hot_search(data, source):
    items = []
    for w in (data.get("data") or {}).get("word_list") or []:
        if not w.get("position"):  # 置顶那条没有排名，跳过
            continue
        items.append({
            "word": w["word"], "source": source, "rank": w["position"],
            "hot": w.get("hot_value", 0), "cat": TAG_NAME.get(w.get("sentence_tag"), "其他"),
            "videos": w.get("video_count"), "age_h": hours_since(w.get("event_time")),
            "trend": None,
        })
    return items


def from_rise(data, source):
    items = []
    for x in (data.get("data") or {}).get("objs") or []:
        tr = [t["hot_score"] for t in x.get("trends") or []]
        trend = round((tr[-1] - tr[0]) / tr[0] * 100) if len(tr) >= 2 and tr[0] else None
        items.append({
            "word": x["sentence"], "source": source, "rank": x["rank"],
            "hot": x.get("hot_score", 0), "cat": x.get("sentence_tag_name") or TAG_NAME.get(x.get("sentence_tag"), "其他"),
            "videos": x.get("video_count"), "age_h": hours_since(x.get("create_at")),
            "trend": trend,  # 近几小时热度涨跌 %
        })
    return items


def judge(it):
    if it["cat"] in BLOCK_CATS:
        return f"分类「{it['cat']}」不碰"
    m = BLOCK_WORDS.search(it["word"])
    if m:
        return f"含「{m.group(0)}」"
    return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join("热点", datetime.now().strftime("%Y-%m-%d")))
    ap.add_argument("--force", action="store_true", help="1 小时内抓过也重抓")
    a = ap.parse_args()
    cached = os.path.join(a.out, "hot.json")
    if not a.force and os.path.exists(cached) and time.time() - os.path.getmtime(cached) < 3600:
        mins = int((time.time() - os.path.getmtime(cached)) / 60)
        print(f"{mins} 分钟前抓过，直接用 → {os.path.join(a.out, 'hot.md')}（要重抓加 --force）")
        return
    if not KEY:
        sys.exit("没有 TIKHUB_API_KEY。去 tikhub.io 注册拿密钥，然后设环境变量 TIKHUB_API_KEY。")

    items = []
    items += from_hot_search(call("/api/v1/douyin/app/v3/fetch_hot_search_list", {"board_type": 0}), "热搜榜")
    items += from_hot_search(call("/api/v1/douyin/app/v3/fetch_hot_search_list",
                                  {"board_type": 2, "board_sub_type": 2}), "娱乐榜")
    items += from_rise(call("/api/v1/douyin/billboard/fetch_hot_rise_list",
                            {"page": 1, "page_size": 50, "order": "rank"}), "上升榜")
    items += from_rise(call("/api/v1/douyin/billboard/fetch_hot_rise_list",
                            {"page": 1, "page_size": 30, "order": "rank_diff"}), "飙升榜")

    # 同一个词出现在多个榜：合并，记下所有来源，热度取最大
    merged = {}
    for it in items:
        k = re.sub(r"\s", "", it["word"])
        if k in merged:
            m = merged[k]
            if it["source"] not in m["source"]:
                m["source"] += "、" + it["source"]
            m["hot"] = max(m["hot"], it["hot"])
            for f in ("trend", "videos", "age_h"):
                if m[f] is None:
                    m[f] = it[f]
        else:
            merged[k] = dict(it)
    rows = sorted(merged.values(), key=lambda r: -r["hot"])
    for r in rows:
        r["blocked"] = judge(r)
        r["risky_words"] = bool(RISKY_WORDS.search(r["word"]))

    os.makedirs(a.out, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    with open(os.path.join(a.out, "hot.json"), "w", encoding="utf-8") as f:
        json.dump({"fetched_at": stamp, "items": rows}, f, ensure_ascii=False, indent=1)

    ok = [r for r in rows if not r["blocked"]]
    bad = [r for r in rows if r["blocked"]]
    fmt = lambda v, s="": "" if v is None else f"{v}{s}"
    lines = [f"# 抖音热点 {stamp}", "",
             f"共 {len(rows)} 条，规则滤掉 {len(bad)} 条，剩 {len(ok)} 条。", "",
             "热度：抖音给的热度值。涨跌：只有上升榜 / 飙升榜的条目有，是近几小时热度的变化，空着表示没有这个数据（不是没涨）。"
             "上榜(小时)：离这个热点在抖音出现过去了多久（热搜榜用事件时间，上升榜用创建时间）。", "",
             "| # | 热点 | 分类 | 热度 | 涨跌 | 上榜(小时) | 来源 |", "|---|---|---|---|---|---|---|"]
    for i, r in enumerate(ok, 1):
        lines.append(f"| {i} | {r['word']}{' ⚠️标题避开预测/竞猜' if r['risky_words'] else ''} | {r['cat']} | {r['hot']:,} | "
                     f"{fmt(r['trend'], '%')} | {fmt(r['age_h'])} | {r['source']} |")
    lines += ["", "## 滤掉的", ""] + [f"- {r['word']}（{r['blocked']}）" for r in bad]
    with open(os.path.join(a.out, "hot.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"抓到 {len(rows)} 条，剩 {len(ok)} 条能看 → {os.path.join(a.out, 'hot.md')}")


if __name__ == "__main__":
    main()
