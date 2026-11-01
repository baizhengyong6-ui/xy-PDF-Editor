"""页面预览：缩略图之外的主画布，负责缩放、文字框和印章拖拽。"""

from __future__ import annotations

import pymupdf
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPen, QPixmap, QBrush
from PySide6.QtWidgets import QGraphicsPixmapItem, QGraphicsRectItem, QGraphicsView, QGraphicsScene

from xy_pdf.core.geometry import as_rect


class StampItem(QGraphicsPixmapItem):
    """可拖动的印章预览。骑缝章会锁在页面左缘或右缘。"""

    def __init__(self, pixmap: QPixmap, on_release) -> None:
        super().__init__(pixmap)
        self.on_release = on_release
        self.lock_edge: str | None = None
        self.page_width = 0.0
        self.page_height = 0.0
        self.inset = 0.0
        self._resizing = False
        self._press = QPointF()
        self._start_scale = 1.0
        self.setFlags(
            QGraphicsPixmapItem.GraphicsItemFlag.ItemIsMovable
            | QGraphicsPixmapItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsPixmapItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
        self.setZValue(10)

    def itemChange(self, change, value):
        if change == QGraphicsPixmapItem.GraphicsItemChange.ItemPositionChange and self.lock_edge:
            point = QPointF(value)
            width = self.boundingRect().width() * self.scale()
            height = self.boundingRect().height() * self.scale()
            if self.lock_edge == "left":
                point.setX(self.inset)
            else:
                point.setX(max(0.0, self.page_width - self.inset - width))
            point.setY(_clamp(point.y(), 0.0, max(0.0, self.page_height - height)))
            return point
        return super().itemChange(change, value)

    def mousePressEvent(self, event) -> None:
        local = event.pos()
        bounds = self.boundingRect()
        handle = QRectF(bounds.right() - 18, bounds.bottom() - 18, 18, 18)
        if handle.contains(local):
            self._resizing = True
            self._press = event.scenePos()
            self._start_scale = self.scale()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._resizing:
            delta = event.scenePos().x() - self._press.x()
            base = max(1.0, self.boundingRect().width())
            self.setScale(max(0.2, self._start_scale + delta / base))
            self._stick_to_edge()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        was_resize = self._resizing
        self._resizing = False
        if not was_resize:
            super().mouseReleaseEvent(event)
        self._stick_to_edge()
        if self.on_release:
            self.on_release()

    def _stick_to_edge(self) -> None:
        if not self.lock_edge:
            return
        width = self.boundingRect().width() * self.scale()
        if self.lock_edge == "left":
            self.setX(self.inset)
        else:
            self.setX(max(0.0, self.page_width - self.inset - width))


class TextBoxOutline(QGraphicsRectItem):
    def __init__(self, box_id: str, on_select, on_release) -> None:
        super().__init__()
        self.box_id = box_id
        self.on_select = on_select
        self.on_release = on_release
        self._origin = QPointF()
        self.setFlags(
            QGraphicsRectItem.GraphicsItemFlag.ItemIsMovable
            | QGraphicsRectItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self.setZValue(5)

    def mousePressEvent(self, event) -> None:
        self._origin = self.pos()
        if self.on_select:
            self.on_select(self.box_id)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        super().mouseReleaseEvent(event)
        if self.on_release and (self.pos() - self._origin).manhattanLength() > 2:
            self.on_release(self)


class PageCanvas(QGraphicsView):
    textBoxDrawn = Signal(float, float, float, float)
    textBoxSelected = Signal(str)
    textBoxMoved = Signal(str, float, float, float, float)
    stampGeometryChanged = Signal(float, float, float, float)
    emptyClicked = Signal()
    zoomRequested = Signal(int)

    def __init__(self) -> None:
        super().__init__()
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHints(
            self.renderHints()
            | QPainterRenderHint_smooth()
        )
        self.setBackgroundBrush(QBrush(QColor("#d9d3c7")))
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.zoom = 1.0
        self.mode = "browse"
        self._page = None
        self._rubber: QGraphicsRectItem | None = None
        self._rubber_origin: QPointF | None = None
        self._stamp_bytes: bytes | None = None
        self._stamp_rect = None
        self._stamp_item: StampItem | None = None
        self._lock_edge: str | None = None
        self._inset_pt = 0.0
        self._rebuilding = False

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        self._sync_outline_interaction()

    def set_page(self, page, zoom: float, outlines: list[tuple[str, object, bool]]) -> None:
        self._page = page
        self.zoom = zoom
        self._rebuilding = True
        self._scene.clear()
        self._stamp_item = None
        self._rubber = None
        if page is None:
            self._rebuilding = False
            return
        render_scale = min(zoom, 2.0)
        pix = page.get_pixmap(matrix=pymupdf.Matrix(render_scale, render_scale), alpha=False)
        pixmap = _qpixmap(pix)
        page_item = QGraphicsPixmapItem(pixmap)
        page_item.setScale(zoom / render_scale)
        page_item.setZValue(0)
        self._scene.addItem(page_item)
        scene_width = page.rect.width * zoom
        scene_height = page.rect.height * zoom
        shadow = QGraphicsRectItem(-6, 5, scene_width + 4, scene_height + 2)
        shadow.setBrush(QColor(0, 0, 0, 35))
        shadow.setPen(QPen(Qt.PenStyle.NoPen))
        shadow.setZValue(-2)
        shadow.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self._scene.addItem(shadow)
        self._scene.setSceneRect(-20, -20, scene_width + 40, scene_height + 40)
        for box_id, rect, selected in outlines:
            visual = as_rect(rect)
            item = TextBoxOutline(box_id, self.textBoxSelected.emit, self._emit_box_moved)
            item.setRect(0, 0, visual.width * zoom, visual.height * zoom)
            item.setPos(visual.x0 * zoom, visual.y0 * zoom)
            color = QColor("#8c2f2f") if selected else QColor("#1e3344")
            pen = QPen(color, 2, Qt.PenStyle.SolidLine if selected else Qt.PenStyle.DashLine)
            item.setPen(pen)
            item.setBrush(QColor(140, 47, 47, 36) if selected else QColor(30, 51, 68, 18))
            self._scene.addItem(item)
        self._sync_outline_interaction()
        self._rebuild_stamp(scene_width, scene_height)
        self._rebuilding = False

    def set_stamp(self, png_bytes: bytes | None, visual_rect, lock_edge: str | None = None, inset_pt: float = 0.0) -> None:
        self._stamp_bytes = png_bytes
        self._stamp_rect = None if visual_rect is None else tuple(visual_rect)
        self._lock_edge = lock_edge
        self._inset_pt = inset_pt
        if self._page is not None:
            self._rebuild_stamp(self._page.rect.width * self.zoom, self._page.rect.height * self.zoom)

    def wheelEvent(self, event) -> None:
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.zoomRequested.emit(1 if event.angleDelta().y() > 0 else -1)
            event.accept()
            return
        super().wheelEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        interactive = self._interactive_at(event.position().toPoint())
        if interactive is not None:
            super().mousePressEvent(event)
            return
        if self.mode == "text":
            origin = self.mapToScene(event.position().toPoint())
            self._rubber_origin = origin
            self._rubber = QGraphicsRectItem()
            self._rubber.setPen(QPen(QColor("#8c2f2f"), 1, Qt.PenStyle.DashLine))
            self._rubber.setBrush(QColor(140, 47, 47, 40))
            self._rubber.setZValue(8)
            self._scene.addItem(self._rubber)
            event.accept()
            return
        self.emptyClicked.emit()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._rubber is not None and self._rubber_origin is not None:
            current = self.mapToScene(event.position().toPoint())
            self._rubber.setRect(QRectF(self._rubber_origin, current).normalized())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._rubber is not None and self._rubber_origin is not None:
            rect = self._rubber.rect()
            self._scene.removeItem(self._rubber)
            self._rubber = None
            self._rubber_origin = None
            if rect.width() > 8 and rect.height() > 8:
                z = self.zoom or 1
                self.textBoxDrawn.emit(rect.left() / z, rect.top() / z, rect.right() / z, rect.bottom() / z)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _emit_box_moved(self, item: TextBoxOutline) -> None:
        if self._rebuilding:
            return
        bounds = item.sceneBoundingRect()
        z = self.zoom or 1
        self.textBoxMoved.emit(
            item.box_id,
            bounds.left() / z,
            bounds.top() / z,
            bounds.right() / z,
            bounds.bottom() / z,
        )

    def _emit_stamp(self) -> None:
        if self._rebuilding or self._stamp_item is None:
            return
        bounds = self._stamp_item.mapRectToScene(self._stamp_item.boundingRect())
        z = self.zoom or 1
        rect = (bounds.left() / z, bounds.top() / z, bounds.right() / z, bounds.bottom() / z)
        self._stamp_rect = rect
        self.stampGeometryChanged.emit(*rect)

    def _rebuild_stamp(self, scene_width: float, scene_height: float) -> None:
        if not self._stamp_bytes or not self._stamp_rect:
            self._stamp_item = None
            return
        x0, y0, x1, y1 = self._stamp_rect
        width = max(8, int((x1 - x0) * self.zoom))
        height = max(8, int((y1 - y0) * self.zoom))
        pixmap = QPixmap()
        pixmap.loadFromData(self._stamp_bytes)
        if pixmap.isNull():
            return
        pixmap = pixmap.scaled(width, height, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
        item = StampItem(pixmap, self._emit_stamp)
        item.lock_edge = self._lock_edge
        item.page_width = scene_width
        item.page_height = scene_height
        item.inset = self._inset_pt * self.zoom
        item.setPos(x0 * self.zoom, y0 * self.zoom)
        self._scene.addItem(item)
        self._stamp_item = item

    def _sync_outline_interaction(self) -> None:
        enabled = self.mode in ("browse", "text")
        for item in self._scene.items():
            if isinstance(item, TextBoxOutline):
                item.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemIsMovable, enabled)
                item.setAcceptedMouseButtons(Qt.MouseButton.LeftButton if enabled else Qt.MouseButton.NoButton)

    def _interactive_at(self, viewport_pos):
        for item in self.items(viewport_pos):
            if isinstance(item, StampItem) and self.mode in ("stamp", "qifeng"):
                return item
            if isinstance(item, TextBoxOutline) and self.mode in ("browse", "text"):
                return item
        return None


def _qpixmap(pix: pymupdf.Pixmap) -> QPixmap:
    image = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGB888)
    return QPixmap.fromImage(image.copy())


def QPainterRenderHint_smooth():
    from PySide6.QtGui import QPainter

    return QPainter.RenderHint.SmoothPixmapTransform | QPainter.RenderHint.Antialiasing


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))
