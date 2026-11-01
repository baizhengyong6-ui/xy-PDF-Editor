"""当前打开的文档：翻页、文字框、旋转、排序，以及撤销。"""

from __future__ import annotations

import json
import os
import tempfile

import pymupdf

from xy_pdf.core.errors import PdfError
from xy_pdf.core.files import document_stem, open_pdf, save_pdf
from xy_pdf.core.geometry import as_rect, normalize, unrotated_to_visual, visual_to_unrotated
from xy_pdf.core.rasterize import render_textbox_png
from xy_pdf.core.registry import new_id, read_boxes, write_boxes
from xy_pdf.core.stamp import apply_qifeng, apply_stamp

_UNDO_LIMIT = 8
_UNDO_MAX_BYTES = 40 * 1024 * 1024


class PdfSession:
    def __init__(self) -> None:
        self.doc: pymupdf.Document | None = None
        self.path: str | None = None
        self.boxes: list[dict] = []
        self.dirty = False
        self._undo: list[tuple[bytes, str]] = []

    @property
    def page_count(self) -> int:
        return 0 if self.doc is None else self.doc.page_count

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    def stem(self) -> str:
        if self.path:
            return os.path.splitext(os.path.basename(self.path))[0]
        if self.doc is not None:
            return document_stem(self.doc)
        return "未命名"

    def new_document(self) -> None:
        self.close()
        self.doc = pymupdf.open()
        self.path = None
        self.boxes = []
        self.dirty = False
        self._undo.clear()

    def add_blank_page(self, width: float = 595, height: float = 842) -> int:
        self._require()
        page = self.doc.new_page(width=width, height=height)
        self.dirty = True
        return page.number

    def open_path(self, path: str) -> None:
        doc = open_pdf(path)
        self.close()
        self.doc = doc
        self.path = os.path.abspath(path)
        self.boxes = read_boxes(doc)
        self.dirty = False
        self._undo.clear()

    def close(self) -> None:
        if self.doc is not None:
            self.doc.close()
            self.doc = None
        self.path = None
        self.boxes = []
        self.dirty = False
        self._undo.clear()

    def write_temp_copy(self) -> str:
        """把当前文档（含未保存的修改）写到临时文件，供合并使用。"""
        self._require()
        write_boxes(self.doc, self.boxes)
        fd, path = tempfile.mkstemp(prefix="xinyao-", suffix=".pdf")
        os.close(fd)
        self.doc.save(path, garbage=4, deflate=True)
        return path

    def save(self, path: str | None = None) -> str:
        self._require()
        target = path or self.path
        if not target:
            raise PdfError("请先选择保存位置。")
        write_boxes(self.doc, self.boxes)
        save_pdf(self.doc, target)
        self.path = os.path.abspath(target)
        self.dirty = False
        return self.path

    def page(self, index: int):
        self._require()
        if index < 0 or index >= self.doc.page_count:
            raise PdfError("页码超出范围。")
        return self.doc[index]

    def add_textbox(
        self,
        page_index: int,
        visual_rect,
        text: str,
        fontsize: float = 14,
        color=(0.1, 0.1, 0.1),
        fill=None,
    ) -> dict:
        text = (text or "").strip()
        if not text:
            raise PdfError("文字不能为空。")
        page = self.page(page_index)
        visual = normalize(visual_rect)
        if visual.width < 8 or visual.height < 8:
            raise PdfError("文字框太小。")
        self._checkpoint()
        unrotated = visual_to_unrotated(page, visual)
        if not self._insert_text(page, unrotated, text, fontsize, color, fill):
            self._discard_checkpoint()
            raise PdfError("文字放不进这个框，请把框拉大或把字号改小。")
        box = {
            "id": new_id(),
            "page": page_index,
            "rect": _rect_list(unrotated),
            "text": text,
            "fontsize": float(fontsize),
            "color": list(color),
            "fill": list(fill) if fill else None,
        }
        self.boxes.append(box)
        self.dirty = True
        return box

    def update_textbox(
        self,
        box_id: str,
        *,
        text: str | None = None,
        visual_rect=None,
        fontsize: float | None = None,
        color=None,
        fill=...,
    ) -> dict:
        box = self.box(box_id)
        page = self.page(int(box["page"]))
        new_text = box["text"] if text is None else text.strip()
        if not new_text:
            raise PdfError("文字不能为空。")
        new_size = float(box["fontsize"] if fontsize is None else fontsize)
        new_color = tuple(box["color"]) if color is None else tuple(color)
        new_fill = box.get("fill") if fill is ... else fill
        if visual_rect is None:
            unrotated = as_rect(box["rect"])
        else:
            unrotated = visual_to_unrotated(page, normalize(visual_rect))
        self._checkpoint()
        self._redact_text(page, as_rect(box["rect"]), remove_fill=bool(box.get("fill")))
        if not self._insert_text(page, unrotated, new_text, new_size, new_color, new_fill):
            self._redact_text(page, unrotated, remove_fill=bool(new_fill))
            self._insert_text(
                page,
                as_rect(box["rect"]),
                box["text"],
                box["fontsize"],
                box["color"],
                box.get("fill"),
            )
            self._discard_checkpoint()
            raise PdfError("文字放不进这个框，请把框拉大或把字号改小。")
        box["rect"] = _rect_list(unrotated)
        box["text"] = new_text
        box["fontsize"] = new_size
        box["color"] = list(new_color)
        box["fill"] = list(new_fill) if new_fill else None
        self.dirty = True
        return box

    def delete_textbox(self, box_id: str) -> None:
        box = self.box(box_id)
        page = self.page(int(box["page"]))
        self._checkpoint()
        self._redact_text(page, as_rect(box["rect"]), remove_fill=bool(box.get("fill")))
        self.boxes = [item for item in self.boxes if item["id"] != box_id]
        self.dirty = True

    def box(self, box_id: str) -> dict:
        for box in self.boxes:
            if box["id"] == box_id:
                return box
        raise PdfError("找不到这个文字框，可能已被删除。")

    def boxes_on_page(self, page_index: int) -> list[dict]:
        return [box for box in self.boxes if int(box["page"]) == page_index]

    def visual_rect_of(self, box: dict):
        return unrotated_to_visual(self.page(int(box["page"])), box["rect"])

    def rotate_page(self, page_index: int, delta: int = 90) -> None:
        page = self.page(page_index)
        self._checkpoint()
        page.set_rotation((page.rotation + delta) % 360)
        self.dirty = True

    def delete_pages(self, indices: list[int]) -> None:
        self._require()
        removed = sorted(set(indices))
        count = self.doc.page_count
        if not removed:
            return
        if any(index < 0 or index >= count for index in removed):
            raise PdfError("页码超出范围。")
        if len(removed) >= count:
            raise PdfError("至少要保留一页。")
        self._checkpoint()
        removed_set = set(removed)
        mapping = {}
        new_index = 0
        for old in range(count):
            if old in removed_set:
                continue
            mapping[old] = new_index
            new_index += 1
        toc = _remap_toc(self.doc, mapping)
        for index in reversed(removed):
            self.doc.delete_page(index)
        if toc:
            self.doc.set_toc(toc)
        else:
            self.doc.set_toc([])
        self.boxes = _remap_boxes(self.boxes, mapping)
        self.dirty = True

    def reorder_pages(self, order: list[int]) -> None:
        self._require()
        count = self.doc.page_count
        if sorted(order) != list(range(count)):
            raise PdfError("页面顺序无效。")
        if list(order) == list(range(count)):
            return
        self._checkpoint()
        mapping = {old: new for new, old in enumerate(order)}
        rebuilt = pymupdf.open()
        try:
            for old in order:
                rebuilt.insert_pdf(self.doc, from_page=old, to_page=old)
            toc = _remap_toc(self.doc, mapping)
            if toc:
                rebuilt.set_toc(toc)
        except Exception:
            rebuilt.close()
            raise
        self.doc.close()
        self.doc = rebuilt
        self.boxes = _remap_boxes(self.boxes, mapping)
        self.dirty = True

    def move_page(self, source: int, target: int) -> None:
        count = self.page_count
        if not (0 <= source < count and 0 <= target < count):
            raise PdfError("页码超出范围。")
        order = list(range(count))
        item = order.pop(source)
        order.insert(target, item)
        self.reorder_pages(order)

    def stamp(self, page_indices: list[int], png_bytes: bytes, visual_rect, opacity: float = 1.0) -> None:
        self._require()
        self._checkpoint()
        apply_stamp(self.doc, page_indices, png_bytes, visual_rect, opacity)
        self.dirty = True

    def qifeng(self, page_indices: list[int], png_bytes: bytes, **kwargs) -> None:
        self._require()
        self._checkpoint()
        apply_qifeng(self.doc, page_indices, png_bytes, **kwargs)
        self.dirty = True

    def rasterize_textboxes(self) -> int:
        """把全部文字框改成图片，方便在没有中文字体的电脑上查看。"""
        self._require()
        if not self.boxes:
            raise PdfError("当前没有可转换的文字框。")
        self._checkpoint()
        count = 0
        grouped: dict[int, list[dict]] = {}
        for box in self.boxes:
            grouped.setdefault(int(box["page"]), []).append(box)
        for page_index, boxes in grouped.items():
            page = self.doc[page_index]
            for box in boxes:
                visual = unrotated_to_visual(page, box["rect"])
                png = render_textbox_png(
                    box["text"],
                    visual.width,
                    visual.height,
                    float(box["fontsize"]),
                    box["color"],
                    box.get("fill"),
                )
                apply_stamp(self.doc, [page_index], png, visual, opacity=1)
                self._redact_text(page, as_rect(box["rect"]), remove_fill=bool(box.get("fill")))
                count += 1
        self.boxes = []
        self.dirty = True
        return count

    def undo(self) -> None:
        if not self._undo:
            raise PdfError("没有可以撤销的操作。")
        raw, boxes = self._undo.pop()
        self.doc.close()
        self.doc = pymupdf.open(stream=raw, filetype="pdf")
        self.boxes = json.loads(boxes)
        self.dirty = True

    def _insert_text(self, page, unrotated, text, fontsize, color, fill) -> bool:
        result = page.insert_textbox(
            unrotated,
            text,
            fontname="china-ss",
            fontsize=float(fontsize),
            color=tuple(color),
            fill=tuple(fill) if fill else None,
            rotate=page.rotation,
            align=pymupdf.TEXT_ALIGN_LEFT,
        )
        if result < 0:
            self._redact_text(page, unrotated, remove_fill=bool(fill))
            return False
        return True

    def _redact_text(self, page, unrotated, remove_fill: bool) -> None:
        page.add_redact_annot(as_rect(unrotated))
        graphics = (
            pymupdf.PDF_REDACT_LINE_ART_REMOVE_IF_COVERED
            if remove_fill
            else pymupdf.PDF_REDACT_LINE_ART_NONE
        )
        page.apply_redactions(
            images=pymupdf.PDF_REDACT_IMAGE_NONE,
            graphics=graphics,
            text=pymupdf.PDF_REDACT_TEXT_REMOVE,
        )

    def _checkpoint(self) -> None:
        self._require()
        raw = self.doc.tobytes()
        if len(raw) > _UNDO_MAX_BYTES:
            self._undo.clear()
            return
        self._undo.append((raw, json.dumps(self.boxes, ensure_ascii=False)))
        if len(self._undo) > _UNDO_LIMIT:
            self._undo.pop(0)

    def _discard_checkpoint(self) -> None:
        if self._undo:
            self._undo.pop()

    def _require(self) -> None:
        if self.doc is None:
            raise PdfError("请先打开一个 PDF。")


def _rect_list(rect) -> list[float]:
    rect = as_rect(rect)
    return [float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1)]


def _remap_boxes(boxes: list[dict], mapping: dict[int, int]) -> list[dict]:
    kept = []
    for box in boxes:
        old = int(box["page"])
        if old not in mapping:
            continue
        copied = dict(box)
        copied["page"] = mapping[old]
        kept.append(copied)
    return kept


def _remap_toc(doc: pymupdf.Document, mapping: dict[int, int]) -> list[list]:
    toc = []
    try:
        raw = doc.get_toc(simple=True)
    except Exception:
        return toc
    for item in raw:
        if len(item) < 3 or int(item[2]) < 1:
            continue
        old = int(item[2]) - 1
        if old in mapping:
            toc.append([int(item[0]), str(item[1]), mapping[old] + 1])
    return toc
