"""出 IP 的图：角色定稿图、头像、sticker 风格的 7 张角色贴纸，全部放进 热点/ip/。用 Vizluma 生图（gen_image.py），一张 ¥0.20。
在用户的工作文件夹（有「热点」文件夹的那个）里运行：

    python3 make_ip.py ref --desc "一只戴圆眼镜的橘猫，穿灰色卫衣"   # 按描述画角色定稿图 -> 热点/ip/ref.png
    python3 make_ip.py ref --photo 我的角色.png                       # 已经有角色图：直接当定稿图，不花钱
    python3 make_ip.py avatar                                         # 头像 -> 热点/ip/avatar.png
    python3 make_ip.py stickers                                       # 7 张角色贴纸 -> 热点/ip/stickers/bot1–7.png
    python3 make_ip.py stickers bot2 bot4                             # 只出这几张（不满意的重出）
    python3 make_ip.py all --desc "..."                               # 定稿图（没有才出）+ 头像 + 7 张贴纸，约 ¥1.8

- 后面每张都拿 ref.png 当参考图，角色才长得一样。先只出 ref，让用户看过满意再出别的。
- 画风默认是 sticker 风格那套（铅笔线稿 + 淡水彩、低饱和、Q 版）；想要别的画风用 --look "画风描述"，整套都要用同一句。
- 贴纸出来是白底，脚本自动抠成透明（要 Pillow：pip install pillow），再缩到高度不超过 900。抠完要打开看一眼：
  角色的线有缺口时身上的白会被一起抠掉，那张用 stickers botN 重出。
- 已经有的文件不重出，要重出加 --force。
- 密钥只从环境变量 VIZLUMA_API_KEY 读。生成请求失败不会自动重发（可能已经扣费），先看控制台 sub.vizluma.online 的调用记录。
"""
import argparse
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent.parent / "hot-render" / "scripts"))
from gen_image import generate, save  # noqa: E402

LOOK = ("画风：手绘绘本插画，铅笔线稿上淡淡的水彩，线条细、略带手抖感；配色克制、低饱和，米白、暖灰、浅木色为主，"
        "没有高饱和的颜色、没有强烈高光和光晕。角色画成 Q 版，大约 2.5 头身，大脑袋小身子，表情简单直接。")
WHITE = "纯白色背景，只画这个角色，周围大量留白，没有地面、阴影、背景物件和边框。画面里不要任何文字、字母、数字或 Logo。"
SAME = "角色和参考图里的是同一个：长相、发型、配色、衣服都保持一致。"
# 和 hot-render 的 sticker 风格对应：每种画面拿一样工具（assets/styles/sticker.html 的 TOOL 表）
TOOLS = {
    "bot1": "双手举着一个大放大镜，凑近了在看东西，好奇",
    "bot2": "双手捧着一架小天平，天平两边各放一个小方块，认真",
    "bot3": "一只手拿着一把大剪刀，另一只手捏着一张纸条，开心",
    "bot4": "双手抱着一支比自己还长的大铅笔，像要画画，干劲十足",
    "bot5": "双手握着一支大毛笔，笔尖朝下，像要写字，得意",
    "bot6": "双手在胸前举着一个小木相框，相框里是空白的，微笑",
    "bot7": "一只手举着一根指挥棒指向斜上方，另一只手叉腰，自信",
}


def ip_dir() -> Path:
    if not Path("热点").is_dir():
        sys.exit("当前文件夹里没有「热点」文件夹：要在用户的工作文件夹里运行。")
    d = Path("热点") / "ip"
    d.mkdir(exist_ok=True)
    return d


def run(prompt: str, size: str, refs: list[Path], out: Path) -> Path:
    print(f"生成 {out.name} ……", flush=True)
    try:
        raw = generate(prompt, size, refs)[0]
    except RuntimeError as e:
        sys.exit(f"  失败：{e}（被内容审核拒的话，把情绪词换成动作描写再试）")
    p = save(raw, out)
    print(f"  存好 {p}", flush=True)
    return p


def make_ref(d: Path, a) -> Path:
    ref = d / "ref.png"
    if ref.exists() and not a.force:
        print(f"已有定稿图 {ref}（重出加 --force）")
        return ref
    if a.photo:
        src = Path(a.photo)
        if not src.exists():
            sys.exit(f"找不到图：{src}")
        shutil.copy(src, ref)
        print(f"定稿图用你给的图：{ref}")
        return ref
    if not a.desc:
        sys.exit("出定稿图要 --desc \"角色长什么样\"，或者 --photo 已有的角色图")
    return run(f"{a.look}一张角色定稿图：{a.desc}。全身站着，正面略侧，双手自然垂下，表情友好。{WHITE}", "1024x1024", [], ref)


def need_ref(d: Path) -> Path:
    ref = d / "ref.png"
    if not ref.exists():
        sys.exit("先出定稿图：make_ip.py ref --desc \"...\"（或 --photo 已有的角色图）")
    return ref


def make_avatar(d: Path, a) -> None:
    out = d / "avatar.png"
    if out.exists() and not a.force:
        print(f"已有头像 {out}（重出加 --force）")
        return
    ref = need_ref(d)
    run(f"{a.look}{SAME}画这个角色的头像：头和肩膀，正脸，脸在画面正中略偏上、占画面大部分，表情开心。"
        "背景是很浅的暖米色纯色。画面里不要任何文字。", "1024x1024", [ref], out)


def make_stickers(d: Path, a) -> None:
    from cutout import cutout   # hot-render/scripts/cutout.py，要 Pillow
    from PIL import Image
    ref = need_ref(d)
    sd = d / "stickers"
    (sd / "raw").mkdir(parents=True, exist_ok=True)
    names = a.which or list(TOOLS)
    bad = [n for n in names if n not in TOOLS]
    if bad:
        sys.exit(f"不认识：{' '.join(bad)}（只有 {' '.join(TOOLS)}）")
    todo = [n for n in names if a.force or a.which or not (sd / f"{n}.png").exists()]
    print(f"要出 {len(todo)} 张贴纸，约 ¥{0.2 * len(todo):.2f}")
    for n in todo:
        raw = run(f"{a.look}{SAME}画这个角色全身站着，{TOOLS[n]}。脚在画面底部附近。{WHITE}", "1024x1024", [ref], sd / "raw" / f"{n}.png")
        out = sd / f"{n}.png"
        cutout(raw, out)
        im = Image.open(out)
        if im.height > 900:
            im.resize((round(im.width * 900 / im.height), 900), Image.LANCZOS).save(out)
        print(f"  抠好 {out}（打开看一眼身上的白有没有被抠掉）")


def main() -> None:
    ap = argparse.ArgumentParser(description="出 IP 的定稿图、头像、角色贴纸（Vizluma 生图）")
    ap.add_argument("what", choices=["ref", "avatar", "stickers", "all"])
    ap.add_argument("which", nargs="*", help="stickers 时只出这几张，例 bot2 bot4")
    ap.add_argument("--desc", help="角色长什么样（出定稿图用）")
    ap.add_argument("--photo", help="已有的角色图，直接当定稿图")
    ap.add_argument("--look", default=LOOK, help="画风描述（整套用同一句）")
    ap.add_argument("--force", action="store_true", help="已有的也重出")
    a = ap.parse_args()
    d = ip_dir()
    if a.what in ("ref", "all"):
        make_ref(d, a)
    if a.what in ("avatar", "all"):
        make_avatar(d, a)
    if a.what in ("stickers", "all"):
        make_stickers(d, a)


if __name__ == "__main__":
    main()
