"""像素级分析预览图：打印尺寸、主色、ASCII 亮度图、若干区域统计。"""

import sys
from collections import Counter

from PIL import Image

CHARS = " .:-=+*#%@"


def load(path):
    img = Image.open(path).convert("RGBA")
    return img


def lum_map(img, cols=78, rows=None):
    w, h = img.size
    if rows is None:
        rows = max(1, int(cols * h / w / 2.1))
    small = img.resize((cols, rows), Image.LANCZOS)
    px = small.load()
    out = []
    for y in range(rows):
        line = []
        for x in range(cols):
            r, g, b, a = px[x, y]
            if a < 40:
                line.append(" ")
                continue
            v = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255.0
            line.append(CHARS[min(len(CHARS) - 1, int(v * len(CHARS)))])
        out.append("".join(line))
    return out


def alpha_map(img, cols=78, rows=None):
    w, h = img.size
    if rows is None:
        rows = max(1, int(cols * h / w / 2.1))
    small = img.resize((cols, rows), Image.LANCZOS)
    px = small.load()
    out = []
    for y in range(rows):
        line = []
        for x in range(cols):
            a = px[x, y][3]
            line.append(" " if a < 40 else ("." if a < 180 else "#"))
        out.append("".join(line))
    return out


def main(paths):
    for path in paths:
        img = load(path)
        w, h = img.size
        print(f"\n=== {path}  {w}x{h} ===")
        px = img.load()
        colors = Counter()
        alpha = Counter()
        for y in range(0, h, max(1, h // 120)):
            for x in range(0, w, max(1, w // 120)):
                r, g, b, a = px[x, y]
                alpha[a // 16 * 16] += 1
                if a > 200:
                    colors[(r // 8 * 8, g // 8 * 8, b // 8 * 8)] += 1
        print("不透明主色(top6):", colors.most_common(6))
        print("alpha 分布:", alpha.most_common(4))
        print("--- 亮度图 ---")
        for line in lum_map(img):
            print(line)
        print("--- alpha 图 ---")
        for line in alpha_map(img):
            print(line)


if __name__ == "__main__":
    main(sys.argv[1:])
