"""把文字框记录写进 PDF 目录，再次打开后仍可编辑。"""

from __future__ import annotations

import json
import uuid

import pymupdf

REGISTRY_KEY = "XinyaoBoxes"


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def read_boxes(doc: pymupdf.Document) -> list[dict]:
    try:
        kind, value = doc.xref_get_key(doc.pdf_catalog(), REGISTRY_KEY)
    except Exception:
        return []
    if kind != "string" or not value:
        return []
    try:
        data = json.loads(value)
    except json.JSONDecodeError:
        return []
    boxes = data.get("boxes") if isinstance(data, dict) else data
    if not isinstance(boxes, list):
        return []
    return [box for box in boxes if _valid_box(box)]


def write_boxes(doc: pymupdf.Document, boxes: list[dict]) -> None:
    payload = json.dumps({"boxes": boxes}, ensure_ascii=False, separators=(",", ":"))
    doc.xref_set_key(doc.pdf_catalog(), REGISTRY_KEY, pymupdf.get_pdf_str(payload))


def _valid_box(box) -> bool:
    if not isinstance(box, dict):
        return False
    rect = box.get("rect")
    return (
        isinstance(box.get("text"), str)
        and isinstance(rect, (list, tuple))
        and len(rect) == 4
        and "page" in box
    )
