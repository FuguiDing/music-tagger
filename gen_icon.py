# -*- coding: utf-8 -*-
"""生成应用图标 icon.ico。"""

import os
from PIL import Image, ImageDraw


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def make(size=256):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    c1, c2 = (47, 111, 237), (124, 58, 237)

    # 渐变圆角底
    radius = size // 5
    grad = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grad)
    for y in range(size):
        gd.line([(0, y), (size, y)], fill=lerp(c1, c2, y / size))
    mask = Image.new("L", (size, size), 0)
    md = ImageDraw.Draw(mask)
    md.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=255)
    img.paste(grad, (0, 0), mask)

    s = size / 256.0
    white = (255, 255, 255, 255)
    # 音符：双柱 + 斜梁 + 两个符头
    d.rounded_rectangle([int(96 * s), int(60 * s), int(112 * s), int(186 * s)],
                        radius=int(6 * s), fill=white)
    d.rounded_rectangle([int(176 * s), int(78 * s), int(192 * s), int(168 * s)],
                        radius=int(6 * s), fill=white)
    d.polygon([(int(92 * s), int(64 * s)), (int(196 * s), int(84 * s)),
               (int(196 * s), int(110 * s)), (int(92 * s), int(90 * s))], fill=white)
    d.ellipse([int(64 * s), int(168 * s), int(122 * s), int(216 * s)], fill=white)
    d.ellipse([int(144 * s), int(150 * s), int(202 * s), int(198 * s)], fill=white)

    # 右下小高光点
    d.ellipse([int(196 * s), int(196 * s), int(216 * s), int(216 * s)],
              fill=(255, 255, 255, 110))
    return img


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    assets = os.path.join(here, "assets")
    os.makedirs(assets, exist_ok=True)
    img = make(256)
    img.save(os.path.join(assets, "icon.ico"),
             sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64),
                    (128, 128), (256, 256)])
    img.save(os.path.join(assets, "icon_256.png"))
    print("icon ->", assets)


if __name__ == "__main__":
    main()
