"""页码范围解析。用户输入从 1 开始，内部使用从 0 开始的页索引。"""

from __future__ import annotations

from xy_pdf.core.errors import PdfError


def parse_page_groups(spec: str, page_count: int) -> list[list[int]]:
    """把 ``1-3,5,8-10`` 解析成多组页索引。

    逗号分组：拆分时每一组生成一个文件。中文逗号、顿号和各种横线都可以。
    """
    if page_count < 1:
        raise PdfError("文档没有页面。")
    if spec is None or not str(spec).strip():
        raise PdfError("请填写页码范围，例如 1-3,5,8-10。")
    text = (
        str(spec)
        .replace("，", ",")
        .replace("、", ",")
        .replace("－", "-")
        .replace("—", "-")
        .replace("–", "-")
        .replace(" ", "")
    )
    groups: list[list[int]] = []
    for part in text.split(","):
        if not part:
            continue
        groups.append(_parse_part(part, page_count))
    if not groups:
        raise PdfError("请填写页码范围，例如 1-3,5,8-10。")
    return groups


def flatten_groups(groups: list[list[int]], *, unique: bool = False) -> list[int]:
    pages: list[int] = []
    seen: set[int] = set()
    for group in groups:
        for index in group:
            if unique and index in seen:
                continue
            seen.add(index)
            pages.append(index)
    return pages


def _parse_part(part: str, page_count: int) -> list[int]:
    if "-" in part:
        left, right = part.split("-", 1)
        if not left or not right:
            raise PdfError(f"无法识别页码范围“{part}”。")
        start = _page_number(left, page_count)
        end = _page_number(right, page_count)
        if start > end:
            start, end = end, start
        return list(range(start - 1, end))
    return [_page_number(part, page_count) - 1]


def _page_number(token: str, page_count: int) -> int:
    if not token.isdigit():
        raise PdfError(f"无法识别页码“{token}”。")
    number = int(token)
    if number < 1 or number > page_count:
        raise PdfError(f"页码 {number} 超出范围，这份文档共 {page_count} 页。")
    return number
