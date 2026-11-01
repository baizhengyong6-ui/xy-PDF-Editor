"""把 PNG 公章和骑缝章写入页面。

传入的矩形是用户在预览里看到的视觉坐标。图片本身也按视觉方向绘制，
函数会按页面旋转角预先转正，避免盖章后印章横过来。
"""

from __future__ import annotations

import io

import pymupdf
from PIL import Image

from xy_pdf.core.errors import PdfError
from xy_pdf.core.geometry import clamp_visual_rect, visual_to_unrotated


def apply_stamp(
    doc: pymupdf.Document,
    page_indices: list[int],
    png_bytes: bytes,
    visual_rect,
    opacity: float = 1.0,
) -> None:
    if not page_indices:
        raise PdfError("请选择要盖章的页面。")
    image = _load_rgba(png_bytes, opacity)
    prepared: dict[int, bytes] = {}
    xrefs: dict[int, int] = {}
    for index in page_indices:
        page = doc[index]
        rect = clamp_visual_rect(visual_rect, page)
        if rect.width < 2 or rect.height < 2:
            continue
        rotation = page.rotation
        if rotation not in prepared:
            prepared[rotation] = _png_bytes(_rotate_upright(image, rotation))
        _insert(page, rect, prepared[rotation], xrefs, rotation)


def apply_qifeng(
    doc: pymupdf.Document,
    page_indices: list[int],
    png_bytes: bytes,
    *,
    seal_height: float,
    top: float | None,
    edge: str = "right",
    inset: float = 0.0,
    opacity: float = 1.0,
) -> None:
    """骑缝章：把印章竖切，按页序贴到每页边缘。"""
    pages = list(dict.fromkeys(page_indices))
    if len(pages) < 2:
        raise PdfError("骑缝章至少需要 2 页。")
    if seal_height < 8:
        raise PdfError("骑缝章太小了。")
    if edge not in ("left", "right"):
        raise PdfError("骑缝章只能放在左边缘或右边缘。")
    image = _load_rgba(png_bytes, opacity)
    if image.width < len(pages):
        new_width = len(pages)
        new_height = max(1, round(image.height * new_width / image.width))
        image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)
    widths = _strip_widths(image.width, len(pages))
    seal_width = seal_height * (image.width / image.height)
    cursor = 0
    for position, index in enumerate(pages):
        strip_px = widths[position]
        strip = image.crop((cursor, 0, cursor + strip_px, image.height))
        cursor += strip_px
        page = doc[index]
        strip_width = seal_width * (strip_px / image.width)
        rect = _edge_rect(page, strip_width, seal_height, top, edge, inset)
        prepared = _png_bytes(_rotate_upright(strip, page.rotation))
        _insert(page, rect, prepared, {}, (index, position))


def qifeng_preview_rect(page, png_bytes: bytes, page_indices: list[int], page_index: int, seal_height: float, top: float | None, edge: str, inset: float):
    """当前页应显示的那一条印章，供界面预览。不在范围内时返回 None。"""
    pages = list(dict.fromkeys(page_indices))
    if page_index not in pages or len(pages) < 2:
        return None
    image = _load_rgba(png_bytes, 1.0)
    if image.width < len(pages):
        image = image.resize((len(pages), max(1, round(image.height * len(pages) / image.width))), Image.Resampling.LANCZOS)
    widths = _strip_widths(image.width, len(pages))
    position = pages.index(page_index)
    seal_width = seal_height * (image.width / image.height)
    strip_width = seal_width * (widths[position] / image.width)
    return _edge_rect(page, strip_width, seal_height, top, edge, inset)


def preview_strip_png(png_bytes: bytes, page_indices: list[int], page_index: int) -> bytes | None:
    pages = list(dict.fromkeys(page_indices))
    if page_index not in pages or len(pages) < 2:
        return None
    image = _load_rgba(png_bytes, 1.0)
    if image.width < len(pages):
        image = image.resize((len(pages), max(1, round(image.height * len(pages) / image.width))), Image.Resampling.LANCZOS)
    widths = _strip_widths(image.width, len(pages))
    position = pages.index(page_index)
    cursor = sum(widths[:position])
    strip = image.crop((cursor, 0, cursor + widths[position], image.height))
    return _png_bytes(strip)


def _edge_rect(page, strip_width: float, seal_height: float, top: float | None, edge: str, inset: float):
    bounds = page.rect
    inset = max(0.0, inset)
    height = min(seal_height, bounds.height)
    width = min(strip_width, max(1.0, bounds.width - inset))
    if top is None:
        y0 = max(0.0, (bounds.height - height) / 2)
    else:
        y0 = min(max(0.0, top), max(0.0, bounds.height - height))
    if edge == "left":
        x0 = min(inset, max(0.0, bounds.width - width))
    else:
        x0 = max(0.0, bounds.width - inset - width)
    return pymupdf.Rect(x0, y0, x0 + width, y0 + height)


def _insert(page, visual_rect, png_bytes: bytes, xrefs: dict, cache_key) -> None:
    unrotated = visual_to_unrotated(page, visual_rect)
    if cache_key in xrefs:
        page.insert_image(unrotated, xref=xrefs[cache_key], keep_proportion=False, overlay=True)
        return
    xref = page.insert_image(unrotated, stream=png_bytes, keep_proportion=False, overlay=True)
    if not xref:
        raise PdfError("写入印章图片失败。")
    xrefs[cache_key] = xref


def _load_rgba(png_bytes: bytes, opacity: float) -> Image.Image:
    try:
        image = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    except Exception as exc:
        raise PdfError("无法读取印章图片，请换一张 PNG 或 JPG。") from exc
    if image.width < 2 or image.height < 2:
        raise PdfError("印章图片太小。")
    opacity = max(0.05, min(1.0, float(opacity)))
    if opacity < 0.999:
        red, green, blue, alpha = image.split()
        alpha = alpha.point(lambda value, scale=opacity: int(value * scale))
        image = Image.merge("RGBA", (red, green, blue, alpha))
    return image


def _rotate_upright(image: Image.Image, rotation: int) -> Image.Image:
    """页面顺时针旋转后，把图片反向转正，视觉上仍是正的。"""
    rotation = rotation % 360
    if rotation == 90:
        return image.transpose(Image.Transpose.ROTATE_90)
    if rotation == 180:
        return image.transpose(Image.Transpose.ROTATE_180)
    if rotation == 270:
        return image.transpose(Image.Transpose.ROTATE_270)
    return image


def _png_bytes(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _strip_widths(width: int, count: int) -> list[int]:
    base, remainder = divmod(width, count)
    return [base + (1 if index < remainder else 0) for index in range(count)]
