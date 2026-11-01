import io
import os

import pymupdf
import pytest
from PIL import Image, ImageDraw

from xy_pdf.core.errors import PdfError
from xy_pdf.core.files import extract_pages, merge_pdfs, split_by_ranges, split_each_page
from xy_pdf.core.ranges import flatten_groups, parse_page_groups
from xy_pdf.core.registry import read_boxes
from xy_pdf.core.session import PdfSession


def _pdf_with_labels(path, labels):
    doc = pymupdf.open()
    for label in labels:
        page = doc.new_page()
        page.insert_text((72, 80), label, fontname="helv", fontsize=28)
    doc.save(path)
    doc.close()


def _png(size, painter) -> bytes:
    image = Image.new("RGBA", size, (0, 0, 0, 0))
    painter(ImageDraw.Draw(image))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _solid(color, size=(48, 48)) -> bytes:
    return _png(size, lambda draw: draw.rectangle((0, 0, size[0] - 1, size[1] - 1), fill=color))


def _bars() -> bytes:
    def paint(draw):
        draw.rectangle((0, 0, 39, 59), fill=(255, 0, 0, 255))
        draw.rectangle((40, 0, 79, 59), fill=(0, 255, 0, 255))
        draw.rectangle((80, 0, 119, 59), fill=(0, 0, 255, 255))

    return _png((120, 60), paint)


def _count(page, rect, predicate, dpi=72):
    pix = page.get_pixmap(dpi=dpi, alpha=False)
    scale = dpi / 72
    x0 = max(0, int(rect.x0 * scale))
    y0 = max(0, int(rect.y0 * scale))
    x1 = min(pix.width, int(rect.x1 * scale))
    y1 = min(pix.height, int(rect.y1 * scale))
    found = 0
    for y in range(y0, y1):
        row = y * pix.width
        for x in range(x0, x1):
            i = (row + x) * 3
            if predicate(pix.samples[i], pix.samples[i + 1], pix.samples[i + 2]):
                found += 1
    return found


def _is_red(r, g, b):
    return r > 180 and g < 80 and b < 80


def _is_green(r, g, b):
    return g > 180 and r < 80 and b < 80


def _is_blue(r, g, b):
    return b > 180 and r < 80 and g < 90


def _is_black(r, g, b):
    return r < 60 and g < 60 and b < 60


def test_parse_page_groups_accepts_chinese_punctuation():
    groups = parse_page_groups("1-3，5、8—10", 12)
    assert groups == [[0, 1, 2], [4], [7, 8, 9]]
    assert flatten_groups(groups, unique=True) == [0, 1, 2, 4, 7, 8, 9]


def test_parse_page_groups_rejects_out_of_range():
    with pytest.raises(PdfError, match="超出范围"):
        parse_page_groups("1-4", 3)
    with pytest.raises(PdfError, match="页码范围"):
        parse_page_groups("  ", 3)


def test_merge_preserves_order_and_text(tmp_path):
    first = tmp_path / "a.pdf"
    second = tmp_path / "b.pdf"
    output = tmp_path / "merged.pdf"
    _pdf_with_labels(first, ["AAA", "BBB"])
    _pdf_with_labels(second, ["CCC"])
    merge_pdfs([str(first), str(second)], str(output))
    doc = pymupdf.open(output)
    assert doc.page_count == 3
    assert "AAA" in doc[0].get_text()
    assert "BBB" in doc[1].get_text()
    assert "CCC" in doc[2].get_text()
    doc.close()


def test_merge_requires_two_files(tmp_path):
    source = tmp_path / "a.pdf"
    _pdf_with_labels(source, ["AAA"])
    with pytest.raises(PdfError, match="两个"):
        merge_pdfs([str(source)], str(tmp_path / "out.pdf"))


def test_split_by_ranges_and_each_page(tmp_path):
    source_path = tmp_path / "src.pdf"
    _pdf_with_labels(source_path, ["P1", "P2", "P3", "P4", "P5"])
    doc = pymupdf.open(source_path)
    ranged = split_by_ranges(doc, [], "1-2,4", str(tmp_path / "ranges"), "图纸")
    assert len(ranged) == 2
    first = pymupdf.open(ranged[0])
    second = pymupdf.open(ranged[1])
    assert first.page_count == 2
    assert "P1" in first[0].get_text() and "P2" in first[1].get_text()
    assert second.page_count == 1 and "P4" in second[0].get_text()
    first.close()
    second.close()
    each = split_each_page(doc, [], str(tmp_path / "each"), "图纸")
    assert len(each) == 5
    page3 = pymupdf.open(each[2])
    assert "P3" in page3[0].get_text()
    page3.close()
    doc.close()


def test_extract_pages_keeps_requested_order(tmp_path):
    source_path = tmp_path / "src.pdf"
    output = tmp_path / "extract.pdf"
    _pdf_with_labels(source_path, ["P1", "P2", "P3", "P4"])
    doc = pymupdf.open(source_path)
    extract_pages(doc, [], "4,2", str(output))
    doc.close()
    extracted = pymupdf.open(output)
    assert extracted.page_count == 2
    assert "P4" in extracted[0].get_text()
    assert "P2" in extracted[1].get_text()
    extracted.close()


def test_text_box_edit_delete_and_reopen(tmp_path):
    session = PdfSession()
    session.new_document()
    session.add_blank_page()
    # 一条穿过文字区域的蓝线，编辑文字时不应被删掉。
    session.page(0).draw_line((40, 100), (400, 100), color=(0, 0, 1), width=3)
    box = session.add_textbox(0, (72, 80, 320, 160), "鑫垚设计\n一层平面图", fontsize=16, color=(0.7, 0, 0))
    assert "鑫垚设计" in session.page(0).get_text()
    session.update_textbox(box["id"], text="修改后的楼梯详图")
    assert "楼梯详图" in session.page(0).get_text()
    assert "鑫垚设计" not in session.page(0).get_text()
    blues = _count(session.page(0), pymupdf.Rect(40, 96, 200, 106), _is_blue)
    assert blues > 20
    path = tmp_path / "notes.pdf"
    session.save(str(path))
    reopened = PdfSession()
    reopened.open_path(str(path))
    assert reopened.boxes[0]["text"] == "修改后的楼梯详图"
    reopened.delete_textbox(reopened.boxes[0]["id"])
    assert "楼梯详图" not in reopened.page(0).get_text()
    assert _count(reopened.page(0), pymupdf.Rect(40, 96, 200, 106), _is_blue) > 20
    reopened.close()
    session.close()


def test_text_box_rejects_overflow_and_blank():
    session = PdfSession()
    session.new_document()
    session.add_blank_page()
    with pytest.raises(PdfError, match="不能为空"):
        session.add_textbox(0, (72, 72, 200, 120), "   ")
    with pytest.raises(PdfError, match="放不进"):
        session.add_textbox(0, (72, 72, 90, 86), "这是一段很长的建筑设计说明文字", fontsize=20)
    assert session.page(0).get_text().strip() == ""
    session.close()


def test_rotate_delete_reorder_and_undo():
    session = PdfSession()
    session.new_document()
    for label in ("甲", "乙", "丙"):
        session.add_blank_page()
        session.page(session.page_count - 1).insert_textbox(
            pymupdf.Rect(72, 72, 200, 120), label, fontname="china-ss", fontsize=24
        )
    session.rotate_page(0, 90)
    assert session.page(0).rotation == 90
    assert session.page(0).rect.width > session.page(0).rect.height
    session.reorder_pages([2, 0, 1])
    assert "丙" in session.page(0).get_text()
    assert "甲" in session.page(1).get_text()
    session.delete_pages([0])
    assert session.page_count == 2
    assert "丙" not in session.page(0).get_text()
    session.undo()
    assert session.page_count == 3
    session.close()


def test_textbox_follows_reordered_page(tmp_path):
    session = PdfSession()
    session.new_document()
    session.add_blank_page()
    session.add_blank_page()
    session.add_textbox(1, (80, 80, 280, 150), "第二页说明")
    session.move_page(1, 0)
    assert session.boxes[0]["page"] == 0
    assert "第二页说明" in session.page(0).get_text()
    path = tmp_path / "moved.pdf"
    session.save(str(path))
    saved = pymupdf.open(path)
    assert read_boxes(saved)[0]["page"] == 0
    saved.close()
    session.close()


def test_stamp_only_selected_pages_and_position():
    session = PdfSession()
    session.new_document()
    session.add_blank_page()
    session.add_blank_page()
    session.add_blank_page()
    rect = pymupdf.Rect(100, 120, 180, 200)
    session.stamp([0, 2], _solid((255, 0, 0, 255)), rect)
    assert _count(session.page(0), rect, _is_red) > 200
    assert _count(session.page(2), rect, _is_red) > 200
    assert _count(session.page(1), rect, _is_red) == 0
    outside = pymupdf.Rect(10, 10, 40, 40)
    assert _count(session.page(0), outside, _is_red) == 0
    session.close()


def test_stamp_on_rotated_page_stays_upright_and_in_place():
    session = PdfSession()
    session.new_document()
    session.add_blank_page()
    session.rotate_page(0, 90)
    # 左红右蓝，用来确认旋转后没有被转横。
    def paint(draw):
        draw.rectangle((0, 0, 39, 39), fill=(255, 0, 0, 255))
        draw.rectangle((40, 0, 79, 39), fill=(0, 0, 255, 255))

    png = _png((80, 40), paint)
    rect = pymupdf.Rect(40, 50, 200, 110)
    session.stamp([0], png, rect)
    assert _count(session.page(0), pymupdf.Rect(50, 60, 100, 100), _is_red) > 30
    assert _count(session.page(0), pymupdf.Rect(140, 60, 190, 100), _is_blue) > 30
    session.close()


def test_qifeng_splits_colors_across_page_edges():
    session = PdfSession()
    session.new_document()
    for _ in range(3):
        session.add_blank_page()
    session.qifeng(
        [0, 1, 2],
        _bars(),
        seal_height=90,
        top=100,
        edge="right",
        inset=0,
        opacity=1,
    )
    checks = (_is_red, _is_green, _is_blue)
    for index, predicate in enumerate(checks):
        page = session.page(index)
        sample = pymupdf.Rect(page.rect.width - 18, 120, page.rect.width - 2, 170)
        assert _count(page, sample, predicate) > 20
        # 其他颜色不应占据这条边缘的中部。
        for other in checks:
            if other is predicate:
                continue
            assert _count(page, sample, other) < 5
    session.close()


def test_qifeng_requires_two_pages():
    session = PdfSession()
    session.new_document()
    session.add_blank_page()
    with pytest.raises(PdfError, match="至少需要 2 页"):
        session.qifeng([0], _solid((255, 0, 0, 255)), seal_height=40, top=10, edge="right", inset=0)
    session.close()


def test_rasterize_textboxes_removes_real_text_but_keeps_ink(tmp_path):
    session = PdfSession()
    session.new_document()
    session.add_blank_page()
    session.add_textbox(0, (72, 80, 320, 160), "外发说明", fontsize=18, color=(0.75, 0, 0))
    session.rasterize_textboxes()
    assert session.boxes == []
    assert "外发说明" not in session.page(0).get_text()
    assert _count(session.page(0), pymupdf.Rect(72, 80, 320, 160), _is_red) > 10
    path = tmp_path / "raster.pdf"
    session.save(str(path))
    assert os.path.getsize(path) > 500
    session.close()


def test_encrypted_pdf_is_rejected(tmp_path):
    source = tmp_path / "secret.pdf"
    doc = pymupdf.open()
    doc.new_page()
    doc.save(source, encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="secret", owner_pw="secret")
    doc.close()
    session = PdfSession()
    with pytest.raises(PdfError, match="加密"):
        session.open_path(str(source))
    with pytest.raises(PdfError, match="加密"):
        merge_pdfs([str(source), str(source)], str(tmp_path / "no.pdf"))


def test_text_on_rotated_page_roundtrips():
    session = PdfSession()
    session.new_document()
    session.add_blank_page()
    session.rotate_page(0, 90)
    session.add_textbox(0, (50, 40, 250, 110), "旋转后的说明", fontsize=16, color=(0, 0, 0))
    assert "旋转后的说明" in session.page(0).get_text()
    assert _count(session.page(0), pymupdf.Rect(50, 40, 250, 110), _is_black) > 15
    session.close()
