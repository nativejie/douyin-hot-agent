"""把生图出来的白底贴纸抠成透明底 PNG，并裁到边（要 Pillow：pip install pillow）。

    python cutout.py in.png [out.png]      # 默认覆盖原图
    python cutout.py a.png b.png c.png --batch

做法：接近白的像素先压成纯白（生图的白底其实是 250–254），再从四角和四边中点漫水填成透明，最后按内容裁边。
角色身上的白（机器人身体、T 恤）被铅笔线围着，填不进去。线有缺口的话会漏，出来后要看一眼。
不用 mix-blend-mode: multiply 去白底：元素一动（位移 / 旋转 / 半透明）就失效，露出白框。
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw

WHITE = (236, 236, 232)   # r、g 都 ≥236 且 b ≥232 的算白
KEY = (255, 0, 255, 0)


def cutout(src: Path, dst: Path, pad: int = 4) -> tuple[int, int]:
    im = Image.open(src).convert("RGBA")
    w, h = im.size
    px = im.load()
    for y in range(h):
        for x in range(w):
            r, g, b, _ = px[x, y]
            if r >= WHITE[0] and g >= WHITE[1] and b >= WHITE[2]:
                px[x, y] = (255, 255, 255, 255)
    for p in [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1), (w // 2, 0), (w // 2, h - 1), (0, h // 2), (w - 1, h // 2)]:
        if px[p] == (255, 255, 255, 255):
            ImageDraw.floodfill(im, p, KEY, thresh=0)
    for y in range(h):
        for x in range(w):
            if px[x, y] == KEY:
                px[x, y] = (255, 255, 255, 0)
    box = im.getbbox()
    if box:
        box = (max(0, box[0] - pad), max(0, box[1] - pad), min(w, box[2] + pad), min(h, box[3] + pad))
        im = im.crop(box)
    im.save(dst)
    return im.size


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        sys.exit(__doc__)
    if "--batch" in sys.argv or len(args) != 2:
        for a in args:
            print(a, cutout(Path(a), Path(a)))
    else:
        print(args[1], cutout(Path(args[0]), Path(args[1])))
