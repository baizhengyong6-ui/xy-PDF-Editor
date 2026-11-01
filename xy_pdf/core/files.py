"""合并、拆分、提取。这些操作直接读写 PDF 文件。"""

from __future__ import annotations

import os
import tempfile

import pymupdf

from xy_pdf.core.errors import PdfError
from xy_pdf.core.ranges import flatten_groups, parse_page_groups
from xy_pdf.core.registry import new_id, read_boxes, write_boxes


def open_pdf(path: str) -> pymupdf.Document:
    try:
        doc = pymupdf.open(path)
    except Exception as exc:
        raise PdfError(f"无法打开文件：{os.path.basename(path)}") from exc
    if doc.needs_pass:
        doc.close()
        raise PdfError(f"“{os.path.basename(path)}”已加密，请先去除密码。")
    return doc


def save_pdf(doc: pymupdf.Document, path: str) -> None:
    path = os.path.abspath(path)
    folder = os.path.dirname(path) or "."
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".xinyao-", suffix=".pdf", dir=folder)
    os.close(fd)
    try:
        doc.save(tmp, garbage=4, deflate=True)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def merge_pdfs(paths: list[str], output: str) -> None:
    if len(paths) < 2:
        raise PdfError("请至少选择两个 PDF 再合并。")
    output_doc = pymupdf.open()
    boxes: list[dict] = []
    toc: list[list] = []
    try:
        for path in paths:
            source = open_pdf(path)
            try:
                start = output_doc.page_count
                output_doc.insert_pdf(source)
                for box in read_boxes(source):
                    copied = dict(box)
                    copied["page"] = int(box["page"]) + start
                    copied["id"] = new_id()
                    boxes.append(copied)
                for level, title, page in _simple_toc(source):
                    toc.append([level, title, start + page])
            finally:
                source.close()
        if toc:
            output_doc.set_toc(toc)
        write_boxes(output_doc, boxes)
        save_pdf(output_doc, output)
    finally:
        output_doc.close()


def split_by_ranges(doc: pymupdf.Document, boxes: list[dict], spec: str, output_dir: str, stem: str) -> list[str]:
    groups = parse_page_groups(spec, doc.page_count)
    return [_write_subset(doc, boxes, group, _subset_path(output_dir, stem, group)) for group in groups]


def split_each_page(doc: pymupdf.Document, boxes: list[dict], output_dir: str, stem: str) -> list[str]:
    paths = []
    for index in range(doc.page_count):
        group = [index]
        paths.append(_write_subset(doc, boxes, group, _subset_path(output_dir, stem, group)))
    return paths


def extract_pages(doc: pymupdf.Document, boxes: list[dict], spec: str, output: str) -> str:
    pages = flatten_groups(parse_page_groups(spec, doc.page_count))
    if not pages:
        raise PdfError("没有可提取的页面。")
    _write_subset(doc, boxes, pages, output)
    return output


def document_stem(doc: pymupdf.Document, fallback: str = "未命名") -> str:
    name = doc.name or ""
    if not name or name.startswith("<"):
        return fallback
    stem = os.path.splitext(os.path.basename(name))[0]
    return stem or fallback


def _write_subset(doc: pymupdf.Document, boxes: list[dict], indices: list[int], path: str) -> str:
    subset = pymupdf.open()
    try:
        for index in indices:
            subset.insert_pdf(doc, from_page=index, to_page=index)
        copied_boxes = []
        for new_index, old_index in enumerate(indices):
            for box in boxes:
                if int(box["page"]) != old_index:
                    continue
                copied = dict(box)
                copied["page"] = new_index
                copied["id"] = new_id()
                copied_boxes.append(copied)
        write_boxes(subset, copied_boxes)
        mapping = {}
        for new_index, old_index in enumerate(indices):
            mapping.setdefault(old_index, new_index)
        toc = []
        for level, title, page in _simple_toc(doc):
            old_index = page - 1
            if old_index in mapping:
                toc.append([level, title, mapping[old_index] + 1])
        if toc:
            subset.set_toc(toc)
        save_pdf(subset, path)
    finally:
        subset.close()
    return path


def _subset_path(output_dir: str, stem: str, indices: list[int]) -> str:
    os.makedirs(output_dir, exist_ok=True)
    pages = [index + 1 for index in indices]
    if len(pages) == 1:
        label = f"第{pages[0]}页"
    elif pages == list(range(pages[0], pages[0] + len(pages))):
        label = f"第{pages[0]}-{pages[-1]}页"
    else:
        label = "第" + "-".join(str(page) for page in pages) + "页"
    return _unique_path(os.path.join(output_dir, f"{stem}_{label}.pdf"))


def _unique_path(path: str) -> str:
    if not os.path.exists(path):
        return path
    root, ext = os.path.splitext(path)
    number = 2
    while True:
        candidate = f"{root}_{number}{ext}"
        if not os.path.exists(candidate):
            return candidate
        number += 1


def _simple_toc(doc: pymupdf.Document) -> list[tuple[int, str, int]]:
    items = []
    try:
        raw = doc.get_toc(simple=True)
    except Exception:
        return items
    for item in raw:
        if len(item) < 3:
            continue
        level, title, page = int(item[0]), str(item[1]), int(item[2])
        if page >= 1 and title:
            items.append((level, title, page))
    return items
