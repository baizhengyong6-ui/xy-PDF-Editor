"""把文字框画成透明 PNG。

内置中文字体不会完整嵌入 PDF。外发前可转成图片，任何阅读器都能看见。
优先使用 Windows 自带的微软雅黑，不把字体文件打进安装包。
"""

from __future__ import annotations

import io
import os

from PIL import Image, ImageDraw, ImageFont

from xy_pdf.core.errors import PdfError

# 固定索引的字体。Noto 的第 3 个面（index 2）是简体中文。
FONT_CANDIDATES = (
    (os.environ.get("XINYAO_CJK_FONT") or "", 0),
    (r"C:\Windows\Fonts\msyh.ttc", 0),
    (r"C:\Windows\Fonts\msyh.ttf", 0),
    (r"C:\Windows\Fonts\simsun.ttc", 0),
    (r"C:\Windows\Fonts\simhei.ttf", 0),
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 2),
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 0),
    ("/System/Library/Fonts/Hiragino Sans GB.ttc", 0),
    ("/System/Library/Fonts/STHeiti Medium.ttc", 0),
    ("/Library/Fonts/Arial Unicode.ttf", 0),
)

# 苹方等字体集里简体面的序号不固定，打开时逐个试。
MACOS_FONT_COLLECTIONS = (
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Supplemental/Songti.ttc",
    "/System/Library/Fonts/Supplemental/Songti SC.ttc",
)

_FONT_CACHE: tuple[str, int] | None = None
_FONT_LOOKED_UP = False


def find_cjk_font() -> tuple[str, int] | None:
    global _FONT_CACHE, _FONT_LOOKED_UP
    if _FONT_LOOKED_UP:
        return _FONT_CACHE
    _FONT_LOOKED_UP = True
    for path, index in FONT_CANDIDATES:
        if path and os.path.isfile(path) and _supports_chinese(path, index):
            _FONT_CACHE = (path, index)
            return _FONT_CACHE
    for path in MACOS_FONT_COLLECTIONS:
        if not os.path.isfile(path):
            continue
        for index in range(32):
            if _supports_chinese(path, index):
                _FONT_CACHE = (path, index)
                return _FONT_CACHE
    return None


def _supports_chinese(path: str, index: int) -> bool:
    try:
        font = ImageFont.truetype(path, 48, index=index)
        box = font.getbbox("鑫")
    except Exception:
        return False
    return box[2] - box[0] >= 10


def render_textbox_png(text: str, width_pt: float, height_pt: float, fontsize: float, color, fill, scale: float = 3.0) -> bytes:
    font_info = find_cjk_font()
    if font_info is None:
        raise PdfError("没有找到中文字体，无法把文字转成图片。")
    path, index = font_info
    width = max(1, int(width_pt * scale))
    height = max(1, int(height_pt * scale))
    if fill:
        background = tuple(int(channel * 255) for channel in fill) + (255,)
    else:
        background = (0, 0, 0, 0)
    image = Image.new("RGBA", (width, height), background)
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(path, max(1, int(fontsize * scale)), index=index)
    ink = tuple(int(channel * 255) for channel in color) + (255,)
    padding = max(2, int(3 * scale))
    max_width = max(1, width - padding * 2)
    line_gap = max(1, int(fontsize * scale * 1.35))
    y = padding
    for line in _wrap(text, font, max_width):
        if y > height - padding:
            break
        draw.text((padding, y), line, font=font, fill=ink)
        y += line_gap
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _wrap(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    lines: list[str] = []
    paragraphs = text.splitlines() or [""]
    for paragraph in paragraphs:
        if paragraph == "":
            lines.append("")
            continue
        current = ""
        for char in paragraph:
            trial = current + char
            if font.getlength(trial) <= max_width or not current:
                current = trial
            else:
                lines.append(current)
                current = char
        if current:
            lines.append(current)
    return lines
