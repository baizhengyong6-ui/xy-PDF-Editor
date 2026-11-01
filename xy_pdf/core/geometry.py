"""页面坐标换算。

PyMuPDF 的绘制坐标是未旋转的页面空间，而 ``page.rect`` 和渲染结果是
用户看到的方向。界面上的拖拽一律使用视觉坐标，写入 PDF 前再换算。
"""

from __future__ import annotations

import pymupdf

MM_TO_PT = 72.0 / 25.4


def as_rect(rect) -> pymupdf.Rect:
    if isinstance(rect, pymupdf.Rect):
        return pymupdf.Rect(rect)
    return pymupdf.Rect(*rect)


def normalize(rect) -> pymupdf.Rect:
    rect = as_rect(rect)
    return pymupdf.Rect(
        min(rect.x0, rect.x1),
        min(rect.y0, rect.y1),
        max(rect.x0, rect.x1),
        max(rect.y0, rect.y1),
    )


def visual_to_unrotated(page, rect) -> pymupdf.Rect:
    return normalize(as_rect(rect) * page.derotation_matrix)


def unrotated_to_visual(page, rect) -> pymupdf.Rect:
    return normalize(as_rect(rect) * page.rotation_matrix)


def clamp_visual_rect(rect, page) -> pymupdf.Rect:
    """把矩形平移进页面。比页面更大时缩小到页面内。"""
    bounds = page.rect
    rect = normalize(rect)
    if rect.width > bounds.width:
        rect.x0 = bounds.x0
        rect.x1 = bounds.x1
    elif rect.x0 < bounds.x0:
        rect.x1 += bounds.x0 - rect.x0
        rect.x0 = bounds.x0
    elif rect.x1 > bounds.x1:
        rect.x0 -= rect.x1 - bounds.x1
        rect.x1 = bounds.x1
    if rect.height > bounds.height:
        rect.y0 = bounds.y0
        rect.y1 = bounds.y1
    elif rect.y0 < bounds.y0:
        rect.y1 += bounds.y0 - rect.y0
        rect.y0 = bounds.y0
    elif rect.y1 > bounds.y1:
        rect.y0 -= rect.y1 - bounds.y1
        rect.y1 = bounds.y1
    return rect
