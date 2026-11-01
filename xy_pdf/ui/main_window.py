"""主窗口。"""

from __future__ import annotations

import os

import pymupdf
from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QColor, QIcon, QKeySequence, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QComboBox,
    QDockWidget,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QSplitter,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from xy_pdf import APP_NAME, __version__
from xy_pdf.core.errors import PdfError
from xy_pdf.core.files import extract_pages, merge_pdfs, split_by_ranges, split_each_page
from xy_pdf.core.geometry import MM_TO_PT
from xy_pdf.core.ranges import flatten_groups, parse_page_groups
from xy_pdf.core.session import PdfSession
from xy_pdf.core.stamp import preview_strip_png, qifeng_preview_rect
from xy_pdf.ui.canvas import PageCanvas, _qpixmap
from xy_pdf.ui.dialogs import MergeDialog, SplitDialog, TextBoxDialog

SEAL_MM = 42.0


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.session = PdfSession()
        self.page_index = 0
        self.zoom = 1.0
        self.mode = "browse"
        self.selected_box_id: str | None = None
        self.stamp_bytes: bytes | None = None
        self.stamp_name = ""
        self.free_stamp_rect: tuple[float, float, float, float] | None = None
        self.qifeng_height = SEAL_MM * MM_TO_PT
        self.qifeng_top: float | None = None
        self.qifeng_edge = "right"
        self.qifeng_inset = 2 * MM_TO_PT
        self._building_thumbs = False
        self._fitted = False
        self.setWindowTitle(APP_NAME)
        self.resize(1280, 800)
        self._build_actions()
        self._build_toolbar()
        self._build_canvas()
        self._build_side()
        self._build_menu()
        self.statusBar().showMessage("打开 PDF，或把多份文件合并成一份。")
        self._update_actions()

    def _build_actions(self) -> None:
        self.act_open = QAction("打开", self)
        self.act_open.setShortcut(QKeySequence.StandardKey.Open)
        self.act_open.triggered.connect(self.open_file)
        self.act_save = QAction("保存", self)
        self.act_save.setShortcut(QKeySequence.StandardKey.Save)
        self.act_save.triggered.connect(self.save_file)
        self.act_save_as = QAction("另存为", self)
        self.act_save_as.setShortcut(QKeySequence.StandardKey.SaveAs)
        self.act_save_as.triggered.connect(self.save_file_as)
        self.act_merge = QAction("合并", self)
        self.act_merge.triggered.connect(self.merge_files)
        self.act_split = QAction("拆分", self)
        self.act_split.triggered.connect(self.split_file)
        self.act_undo = QAction("撤销", self)
        self.act_undo.setShortcut(QKeySequence.StandardKey.Undo)
        self.act_undo.triggered.connect(self.undo)
        self.act_prev = QAction("上一页", self)
        self.act_prev.triggered.connect(lambda: self.go_page(self.page_index - 1))
        self.act_next = QAction("下一页", self)
        self.act_next.triggered.connect(lambda: self.go_page(self.page_index + 1))
        self.act_zoom_in = QAction("放大", self)
        self.act_zoom_in.setShortcut(QKeySequence.StandardKey.ZoomIn)
        self.act_zoom_in.triggered.connect(lambda: self._set_zoom(self.zoom * 1.2))
        self.act_zoom_out = QAction("缩小", self)
        self.act_zoom_out.setShortcut(QKeySequence.StandardKey.ZoomOut)
        self.act_zoom_out.triggered.connect(lambda: self._set_zoom(self.zoom / 1.2))
        self.act_fit = QAction("适应宽度", self)
        self.act_fit.triggered.connect(self.fit_width)
        self.act_rotate = QAction("顺时针旋转", self)
        self.act_rotate.triggered.connect(lambda: self._rotate(90))
        self.act_rotate_ccw = QAction("逆时针旋转", self)
        self.act_rotate_ccw.triggered.connect(lambda: self._rotate(-90))
        self.act_delete_page = QAction("删除本页", self)
        self.act_delete_page.triggered.connect(self.delete_current_page)
        self.act_up = QAction("页面上移", self)
        self.act_up.triggered.connect(lambda: self._move_current(-1))
        self.act_down = QAction("页面下移", self)
        self.act_down.triggered.connect(lambda: self._move_current(1))
        self.act_raster = QAction("文字转图片", self)
        self.act_raster.triggered.connect(self.rasterize_text)

    def _build_toolbar(self) -> None:
        bar = QToolBar("工具")
        bar.setMovable(False)
        bar.setIconSize(QSize(16, 16))
        self.addToolBar(bar)
        for action in (
            self.act_open,
            self.act_save,
            self.act_save_as,
            self.act_merge,
            self.act_split,
            self.act_undo,
        ):
            bar.addAction(action)
        bar.addSeparator()
        for action in (self.act_prev, self.act_next, self.act_zoom_out, self.act_zoom_in, self.act_fit):
            bar.addAction(action)
        bar.addSeparator()
        for action in (self.act_rotate, self.act_rotate_ccw, self.act_delete_page, self.act_up, self.act_down):
            bar.addAction(action)
        self.addToolBarBreak(Qt.ToolBarArea.TopToolBarArea)
        mode_bar = QToolBar("编辑模式")
        mode_bar.setMovable(False)
        self.addToolBar(mode_bar)
        mode_label = QLabel("  编辑模式")
        mode_label.setStyleSheet("color: #f6f1e7; background: transparent; padding-right: 8px;")
        mode_bar.addWidget(mode_label)
        self.mode_group = QActionGroup(self)
        self.mode_group.setExclusive(True)
        self.mode_actions = {}
        for key, text in (("browse", "浏览"), ("text", "添加文字"), ("stamp", "盖章"), ("qifeng", "骑缝章")):
            action = QAction(text, self)
            action.setCheckable(True)
            action.setData(key)
            self.mode_group.addAction(action)
            mode_bar.addAction(action)
            self.mode_actions[key] = action
        self.mode_actions["browse"].setChecked(True)
        self.mode_group.triggered.connect(self._on_mode_action)

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("文件")
        for action in (self.act_open, self.act_save, self.act_save_as, self.act_merge, self.act_split):
            file_menu.addAction(action)
        file_menu.addSeparator()
        quit_action = QAction("退出", self)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)
        page_menu = self.menuBar().addMenu("页面")
        for action in (
            self.act_prev,
            self.act_next,
            self.act_rotate,
            self.act_rotate_ccw,
            self.act_delete_page,
            self.act_up,
            self.act_down,
        ):
            page_menu.addAction(action)
        tool_menu = self.menuBar().addMenu("工具")
        for action in self.mode_actions.values():
            tool_menu.addAction(action)
        tool_menu.addSeparator()
        tool_menu.addAction(self.act_raster)
        tool_menu.addAction(self.act_undo)
        help_menu = self.menuBar().addMenu("帮助")
        about = QAction("关于", self)
        about.triggered.connect(self._about)
        help_menu.addAction(about)

    def _build_canvas(self) -> None:
        self.thumbs = QListWidget()
        self.thumbs.setIconSize(QSize(72, 96))
        self.thumbs.setMinimumWidth(168)
        self.thumbs.setMaximumWidth(220)
        self.thumbs.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.thumbs.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.thumbs.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.thumbs.currentRowChanged.connect(self._on_thumb)
        self.thumbs.model().rowsMoved.connect(self._on_rows_moved)
        self.canvas = PageCanvas()
        self.canvas.textBoxDrawn.connect(self._on_text_drawn)
        self.canvas.textBoxSelected.connect(self._select_box)
        self.canvas.textBoxMoved.connect(self._on_text_moved)
        self.canvas.stampGeometryChanged.connect(self._on_stamp_geometry)
        self.canvas.emptyClicked.connect(self._clear_selection)
        self.canvas.zoomRequested.connect(lambda direction: self._set_zoom(self.zoom * (1.2 if direction > 0 else 1 / 1.2)))
        splitter = QSplitter()
        splitter.addWidget(self.thumbs)
        splitter.addWidget(self.canvas)
        splitter.setStretchFactor(1, 1)
        self.setCentralWidget(splitter)
        self._thumb_timer = QTimer(self)
        self._thumb_timer.setSingleShot(True)
        self._thumb_timer.timeout.connect(self._render_one_thumb)
        self._thumb_queue: list[int] = []

    def _build_side(self) -> None:
        panel = QWidget()
        panel.setObjectName("SidePanel")
        layout = QVBoxLayout(panel)
        self.page_label = QLabel("尚未打开文档")
        self.page_label.setWordWrap(True)
        layout.addWidget(self.page_label)
        jump_row = QHBoxLayout()
        jump_row.addWidget(QLabel("跳转到"))
        self.page_spin = QSpinBox()
        self.page_spin.setMinimum(1)
        self.page_spin.valueChanged.connect(self._on_spin)
        jump_row.addWidget(self.page_spin)
        jump_row.addWidget(QLabel("页"))
        layout.addLayout(jump_row)

        self.text_group = QGroupBox("选中的文字框")
        text_form = QVBoxLayout(self.text_group)
        self.text_edit = QPlainTextEdit()
        self.text_edit.setFixedHeight(90)
        text_form.addWidget(self.text_edit)
        size_row = QHBoxLayout()
        size_row.addWidget(QLabel("字号"))
        self.text_size = QSpinBox()
        self.text_size.setRange(8, 72)
        self.text_size.setSuffix(" 磅")
        size_row.addWidget(self.text_size)
        text_form.addLayout(size_row)
        self.text_color = QColor("#1a1a1a")
        self.text_color_button = QPushButton("文字颜色")
        self.text_color_button.clicked.connect(self._pick_text_color)
        text_form.addWidget(self.text_color_button)
        update = QPushButton("更新文字")
        update.clicked.connect(self._update_selected_text)
        delete = QPushButton("删除文字框")
        delete.setObjectName("accent")
        delete.clicked.connect(self.delete_selected_text)
        text_form.addWidget(update)
        text_form.addWidget(delete)
        layout.addWidget(self.text_group)

        self.stamp_group = QGroupBox("盖章")
        stamp_layout = QVBoxLayout(self.stamp_group)
        self.stamp_file_label = QLabel("尚未选择印章")
        self.stamp_file_label.setWordWrap(True)
        stamp_layout.addWidget(self.stamp_file_label)
        change = QPushButton("更换印章图片")
        change.clicked.connect(self._pick_stamp_file)
        stamp_layout.addWidget(change)
        stamp_layout.addWidget(QLabel("不透明度"))
        self.opacity = QSlider(Qt.Orientation.Horizontal)
        self.opacity.setRange(20, 100)
        self.opacity.setValue(100)
        stamp_layout.addWidget(self.opacity)
        self.stamp_current = QRadioButton("当前页")
        self.stamp_all = QRadioButton("全部页面")
        self.stamp_range = QRadioButton("指定页码")
        self.stamp_current.setChecked(True)
        self.stamp_target = QButtonGroup(self)
        for button in (self.stamp_current, self.stamp_all, self.stamp_range):
            self.stamp_target.addButton(button)
            stamp_layout.addWidget(button)
        self.stamp_spec = QLineEdit()
        self.stamp_spec.setPlaceholderText("例如 1-3,5")
        stamp_layout.addWidget(self.stamp_spec)
        hint = QLabel("在页面上拖动印章，拖右下角可以缩放。")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        stamp_layout.addWidget(hint)
        apply = QPushButton("把印章写入页面")
        apply.setObjectName("accent")
        apply.clicked.connect(self.apply_stamp)
        stamp_layout.addWidget(apply)
        layout.addWidget(self.stamp_group)

        self.qifeng_group = QGroupBox("骑缝章")
        qifeng_layout = QVBoxLayout(self.qifeng_group)
        qifeng_layout.addWidget(QLabel("印章会按页序从左到右切开，贴在每页边缘。装订后侧面能对成一枚完整章。"))
        form = QFormLayout()
        self.qifeng_height_box = QSpinBox()
        self.qifeng_height_box.setRange(15, 80)
        self.qifeng_height_box.setValue(int(SEAL_MM))
        self.qifeng_height_box.setSuffix(" 毫米")
        self.qifeng_height_box.valueChanged.connect(self._qifeng_params_changed)
        form.addRow("印章高度", self.qifeng_height_box)
        self.qifeng_inset_box = QSpinBox()
        self.qifeng_inset_box.setRange(0, 20)
        self.qifeng_inset_box.setValue(2)
        self.qifeng_inset_box.setSuffix(" 毫米")
        self.qifeng_inset_box.valueChanged.connect(self._qifeng_params_changed)
        form.addRow("离页边", self.qifeng_inset_box)
        self.qifeng_edge_box = QComboBox()
        self.qifeng_edge_box.addItem("右边缘", "right")
        self.qifeng_edge_box.addItem("左边缘", "left")
        self.qifeng_edge_box.currentIndexChanged.connect(self._qifeng_params_changed)
        form.addRow("位置", self.qifeng_edge_box)
        qifeng_layout.addLayout(form)
        self.qifeng_all = QRadioButton("全部页面")
        self.qifeng_range = QRadioButton("指定页码")
        self.qifeng_all.setChecked(True)
        self.qifeng_pages = QButtonGroup(self)
        self.qifeng_pages.addButton(self.qifeng_all)
        self.qifeng_pages.addButton(self.qifeng_range)
        qifeng_layout.addWidget(self.qifeng_all)
        qifeng_layout.addWidget(self.qifeng_range)
        self.qifeng_spec = QLineEdit()
        self.qifeng_spec.setPlaceholderText("例如 1-6")
        self.qifeng_all.toggled.connect(self._qifeng_params_changed)
        self.qifeng_range.toggled.connect(self._qifeng_params_changed)
        self.qifeng_spec.editingFinished.connect(self._qifeng_params_changed)
        qifeng_layout.addWidget(self.qifeng_spec)
        drag_hint = QLabel("可以上下拖动预览条，拖右下角改变大小。")
        drag_hint.setObjectName("hint")
        drag_hint.setWordWrap(True)
        qifeng_layout.addWidget(drag_hint)
        apply_qifeng = QPushButton("写入骑缝章")
        apply_qifeng.setObjectName("accent")
        apply_qifeng.clicked.connect(self.apply_qifeng)
        qifeng_layout.addWidget(apply_qifeng)
        layout.addWidget(self.qifeng_group)

        self.hint_label = QLabel(
            "浏览时可以点选文字框。添加文字时，在页面上拖出一个矩形。"
            "公章和骑缝章先摆好位置，再写入页面。写入后请另存为新文件。"
        )
        self.hint_label.setWordWrap(True)
        self.hint_label.setObjectName("hint")
        layout.addWidget(self.hint_label)
        raster = QPushButton("外发：把文字框转成图片")
        raster.clicked.connect(self.rasterize_text)
        layout.addWidget(raster)
        layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(panel)
        scroll.setMinimumWidth(280)
        dock = QDockWidget("操作", self)
        dock.setWidget(scroll)
        dock.setFeatures(QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)
        dock.setAllowedAreas(Qt.DockWidgetArea.RightDockWidgetArea | Qt.DockWidgetArea.LeftDockWidgetArea)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
        self._sync_side()

    def open_file(self) -> None:
        if not self._confirm_discard():
            return
        path, _ = QFileDialog.getOpenFileName(self, "打开 PDF", "", "PDF 文件 (*.pdf)")
        if not path:
            return
        self._open_path(path)

    def _open_path(self, path: str) -> None:
        try:
            self.session.open_path(path)
        except PdfError as exc:
            QMessageBox.warning(self, APP_NAME, str(exc))
            return
        self.page_index = 0
        self.selected_box_id = None
        self.free_stamp_rect = None
        self.qifeng_top = None
        self._fitted = False
        self._set_mode("browse")
        self._refresh_all()
        self.fit_width()

    def save_file(self) -> None:
        if self.session.doc is None:
            return
        if not self.session.path:
            self.save_file_as()
            return
        self._save_to(self.session.path)

    def save_file_as(self) -> None:
        if self.session.doc is None:
            return
        suggested = self.session.path or "未命名.pdf"
        path, _ = QFileDialog.getSaveFileName(self, "另存为", suggested, "PDF 文件 (*.pdf)")
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        self._save_to(path)

    def _save_to(self, path: str) -> None:
        try:
            self.session.save(path)
        except PdfError as exc:
            QMessageBox.warning(self, APP_NAME, str(exc))
            return
        except Exception as exc:
            QMessageBox.critical(self, APP_NAME, f"保存失败：{exc}")
            return
        self._update_title()
        self.statusBar().showMessage(f"已保存到 {path}")

    def merge_files(self) -> None:
        dialog = MergeDialog(self, can_include=self.session.doc is not None)
        if dialog.exec() != QDialog_Accepted():
            return
        paths = dialog.paths()
        temp = None
        if dialog.include.isChecked() and self.session.doc is not None:
            try:
                temp = self.session.write_temp_copy()
            except PdfError as exc:
                QMessageBox.warning(self, APP_NAME, str(exc))
                return
            paths.insert(0, temp)
        try:
            merge_pdfs(paths, dialog.output)
        except PdfError as exc:
            QMessageBox.warning(self, APP_NAME, str(exc))
            return
        except Exception as exc:
            QMessageBox.critical(self, APP_NAME, f"合并失败：{exc}")
            return
        finally:
            if temp and os.path.exists(temp):
                os.remove(temp)
        if self.session.doc is not None and self.session.dirty and not dialog.include.isChecked():
            if not self._confirm_discard():
                self.statusBar().showMessage(f"已保存合并结果：{dialog.output}")
                return
        self._open_path(dialog.output)
        self.statusBar().showMessage(f"已合并 {len(paths)} 个文件")

    def split_file(self) -> None:
        if self.session.doc is None:
            return
        dialog = SplitDialog(self, self.session.page_count)
        if dialog.exec() != QDialog_Accepted():
            return
        try:
            if dialog.mode() == "each":
                paths = split_each_page(self.session.doc, self.session.boxes, dialog.output, self.session.stem())
            elif dialog.mode() == "extract":
                paths = [extract_pages(self.session.doc, self.session.boxes, dialog.spec.text(), dialog.output)]
            else:
                paths = split_by_ranges(
                    self.session.doc,
                    self.session.boxes,
                    dialog.spec.text(),
                    dialog.output,
                    self.session.stem(),
                )
        except PdfError as exc:
            QMessageBox.warning(self, APP_NAME, str(exc))
            return
        except Exception as exc:
            QMessageBox.critical(self, APP_NAME, f"拆分失败：{exc}")
            return
        QMessageBox.information(self, APP_NAME, "已生成 {} 个文件。\n{}".format(len(paths), "\n".join(paths[:8])))

    def undo(self) -> None:
        try:
            self.session.undo()
        except PdfError as exc:
            self.statusBar().showMessage(str(exc))
            return
        if self.page_index >= self.session.page_count:
            self.page_index = max(0, self.session.page_count - 1)
        self.selected_box_id = None
        self._refresh_all()

    def go_page(self, index: int) -> None:
        if self.session.doc is None:
            return
        if index < 0 or index >= self.session.page_count:
            return
        self.page_index = index
        self.selected_box_id = None
        self.thumbs.blockSignals(True)
        self.thumbs.setCurrentRow(index)
        self.thumbs.blockSignals(False)
        self._refresh_page()

    def fit_width(self) -> None:
        if self.session.doc is None or self.session.page_count == 0:
            return
        page = self.session.page(self.page_index)
        width = self.canvas.viewport().width() - 28
        if page.rect.width <= 0 or width < 40:
            return
        self.zoom = max(0.25, min(4.0, width / page.rect.width))
        self._fitted = True
        self._refresh_page()

    def delete_current_page(self) -> None:
        if self.session.doc is None:
            return
        if not _confirm(self, f"删除第 {self.page_index + 1} 页？此操作可撤销。"):
            return
        try:
            self.session.delete_pages([self.page_index])
        except PdfError as exc:
            QMessageBox.warning(self, APP_NAME, str(exc))
            return
        self.page_index = min(self.page_index, self.session.page_count - 1)
        self.selected_box_id = None
        self._refresh_all()

    def delete_selected_text(self) -> None:
        if not self.selected_box_id:
            return
        try:
            self.session.delete_textbox(self.selected_box_id)
        except PdfError as exc:
            QMessageBox.warning(self, APP_NAME, str(exc))
            return
        self.selected_box_id = None
        self._refresh_page()
        self._refresh_current_thumb()

    def apply_stamp(self) -> None:
        if not self.stamp_bytes or not self.free_stamp_rect:
            QMessageBox.warning(self, APP_NAME, "请先选择印章并放到页面上。")
            return
        try:
            pages = self._target_pages(self.stamp_current, self.stamp_all, self.stamp_range, self.stamp_spec)
            self.session.stamp(pages, self.stamp_bytes, self.free_stamp_rect, self.opacity.value() / 100)
        except PdfError as exc:
            QMessageBox.warning(self, APP_NAME, str(exc))
            return
        self._set_mode("browse")
        self._refresh_page()
        self._refresh_current_thumb()
        self.statusBar().showMessage("印章已写入。可以继续调整后再次盖章，或撤销。")

    def apply_qifeng(self) -> None:
        if not self.stamp_bytes:
            QMessageBox.warning(self, APP_NAME, "请先选择印章图片。")
            return
        try:
            pages = self._qifeng_pages()
            self.session.qifeng(
                pages,
                self.stamp_bytes,
                seal_height=self.qifeng_height,
                top=self.qifeng_top,
                edge=self.qifeng_edge,
                inset=self.qifeng_inset,
                opacity=self.opacity.value() / 100,
            )
        except PdfError as exc:
            QMessageBox.warning(self, APP_NAME, str(exc))
            return
        self._set_mode("browse")
        self._refresh_all()
        self.statusBar().showMessage("骑缝章已写入。装订时请按页序对齐页边。")

    def rasterize_text(self) -> None:
        if self.session.doc is None:
            return
        if not _confirm(self, "把全部文字框转成图片？转换后任何阅读器都能看到文字，但不能再当文字编辑。此操作可撤销。"):
            return
        try:
            count = self.session.rasterize_textboxes()
        except PdfError as exc:
            QMessageBox.warning(self, APP_NAME, str(exc))
            return
        self.selected_box_id = None
        self._refresh_page()
        self.statusBar().showMessage(f"已把 {count} 个文字框转成图片")

    def keyPressEvent(self, event) -> None:
        focused = self.focusWidget()
        if isinstance(focused, (QLineEdit, QPlainTextEdit, QSpinBox, QComboBox)):
            super().keyPressEvent(event)
            return
        if event.key() == Qt.Key.Key_Escape:
            self._set_mode("browse")
            return
        if event.key() == Qt.Key.Key_Delete and self.selected_box_id:
            self.delete_selected_text()
            return
        if event.key() in (Qt.Key.Key_PageDown, Qt.Key.Key_Right):
            self.go_page(self.page_index + 1)
            return
        if event.key() in (Qt.Key.Key_PageUp, Qt.Key.Key_Left):
            self.go_page(self.page_index - 1)
            return
        super().keyPressEvent(event)

    def closeEvent(self, event) -> None:
        if self._confirm_discard():
            self.session.close()
            event.accept()
        else:
            event.ignore()

    def _on_mode_action(self, action: QAction) -> None:
        mode = action.data()
        if self.session.doc is None and mode != "browse":
            QMessageBox.information(self, APP_NAME, "请先打开一个 PDF。")
            self._set_mode("browse")
            return
        if mode in ("stamp", "qifeng") and not self._ensure_stamp_file():
            self._set_mode("browse")
            return
        if mode == "qifeng" and self.session.page_count < 2:
            QMessageBox.information(self, APP_NAME, "骑缝章至少需要 2 页。")
            self._set_mode("browse")
            return
        self.mode = mode
        if mode == "stamp":
            self._ensure_stamp_rect()
        if mode == "qifeng":
            self._read_qifeng_widgets()
        self.canvas.set_mode(mode)
        self._refresh_page()
        if mode == "text":
            self.statusBar().showMessage("在页面上按住鼠标拖出一个矩形，然后输入文字。按 Esc 返回浏览。")
        elif mode == "stamp":
            self.statusBar().showMessage("拖动印章摆放位置，拖右下角缩放，然后点“把印章写入页面”。")
        elif mode == "qifeng":
            self.statusBar().showMessage("上下拖动页边的印章切片，确认高度后写入骑缝章。")

    def _set_mode(self, mode: str) -> None:
        self.mode = mode
        action = self.mode_actions.get(mode)
        if action:
            action.setChecked(True)
        self.canvas.set_mode(mode)
        self._sync_side()

    def _on_text_drawn(self, x0: float, y0: float, x1: float, y1: float) -> None:
        dialog = TextBoxDialog(self)
        if dialog.exec() != QDialog_Accepted():
            return
        values = dialog.values()
        try:
            box = self.session.add_textbox(self.page_index, (x0, y0, x1, y1), **values)
        except PdfError as exc:
            QMessageBox.warning(self, APP_NAME, str(exc))
            return
        self.selected_box_id = box["id"]
        self._load_selected_box()
        self._refresh_page()
        self._refresh_current_thumb()

    def _on_text_moved(self, box_id: str, x0: float, y0: float, x1: float, y1: float) -> None:
        try:
            self.session.update_textbox(box_id, visual_rect=(x0, y0, x1, y1))
        except PdfError as exc:
            QMessageBox.warning(self, APP_NAME, str(exc))
        self.selected_box_id = box_id
        self._refresh_page()

    def _select_box(self, box_id: str) -> None:
        self.selected_box_id = box_id
        self._load_selected_box()
        self._refresh_page()

    def _clear_selection(self) -> None:
        if self.selected_box_id:
            self.selected_box_id = None
            self._sync_side()
            self._refresh_page()

    def _update_selected_text(self) -> None:
        if not self.selected_box_id:
            return
        try:
            self.session.update_textbox(
                self.selected_box_id,
                text=self.text_edit.toPlainText(),
                fontsize=self.text_size.value(),
                color=(self.text_color.redF(), self.text_color.greenF(), self.text_color.blueF()),
            )
        except PdfError as exc:
            QMessageBox.warning(self, APP_NAME, str(exc))
            return
        self._refresh_page()
        self.statusBar().showMessage("文字已更新")

    def _on_stamp_geometry(self, x0: float, y0: float, x1: float, y1: float) -> None:
        if self.mode == "qifeng":
            self.qifeng_top = y0
            self.qifeng_height = max(8.0, y1 - y0)
            self.qifeng_height_box.blockSignals(True)
            self.qifeng_height_box.setValue(int(round(self.qifeng_height / MM_TO_PT)))
            self.qifeng_height_box.blockSignals(False)
            return
        self.free_stamp_rect = (x0, y0, x1, y1)

    def _qifeng_params_changed(self) -> None:
        if self.mode != "qifeng":
            return
        previous_edge = self.qifeng_edge
        self._read_qifeng_widgets()
        if previous_edge != self.qifeng_edge:
            self.qifeng_top = None
        self._refresh_page()

    def _read_qifeng_widgets(self) -> None:
        self.qifeng_height = self.qifeng_height_box.value() * MM_TO_PT
        self.qifeng_inset = self.qifeng_inset_box.value() * MM_TO_PT
        self.qifeng_edge = self.qifeng_edge_box.currentData()

    def _pick_stamp_file(self) -> bool:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择公章图片",
            "",
            "图片 (*.png *.jpg *.jpeg *.webp *.bmp)",
        )
        if not path:
            return False
        try:
            with open(path, "rb") as handle:
                self.stamp_bytes = handle.read()
        except OSError as exc:
            QMessageBox.warning(self, APP_NAME, f"无法读取图片：{exc}")
            return False
        self.stamp_name = os.path.basename(path)
        self.free_stamp_rect = None
        self.qifeng_top = None
        self.stamp_file_label.setText(f"当前印章：{self.stamp_name}")
        return True

    def _ensure_stamp_file(self) -> bool:
        if self.stamp_bytes:
            self.stamp_file_label.setText(f"当前印章：{self.stamp_name}")
            return True
        return self._pick_stamp_file()

    def _ensure_stamp_rect(self) -> None:
        if self.free_stamp_rect is not None or self.session.doc is None:
            return
        page = self.session.page(self.page_index)
        side = SEAL_MM * MM_TO_PT
        margin = 18 * MM_TO_PT
        x0 = max(0.0, page.rect.width - margin - side)
        y0 = max(0.0, page.rect.height - margin - side)
        self.free_stamp_rect = (x0, y0, x0 + side, y0 + side)

    def _rotate(self, delta: int) -> None:
        if self.session.doc is None:
            return
        self.session.rotate_page(self.page_index, delta)
        self._refresh_page()
        self._refresh_current_thumb()

    def _move_current(self, delta: int) -> None:
        if self.session.doc is None:
            return
        target = self.page_index + delta
        if target < 0 or target >= self.session.page_count:
            return
        self.session.move_page(self.page_index, target)
        self.page_index = target
        self._refresh_all()

    def _on_thumb(self, row: int) -> None:
        if self._building_thumbs or row < 0:
            return
        self.go_page(row)

    def _on_spin(self, number: int) -> None:
        if self.session.doc is None:
            return
        self.go_page(number - 1)

    def _on_rows_moved(self, *_args) -> None:
        if self._building_thumbs or self.session.doc is None:
            return
        order = [int(self.thumbs.item(i).data(Qt.ItemDataRole.UserRole)) for i in range(self.thumbs.count())]
        if order == list(range(len(order))):
            return
        current = self.page_index
        try:
            self.session.reorder_pages(order)
        except PdfError as exc:
            QMessageBox.warning(self, APP_NAME, str(exc))
            self._rebuild_thumbs()
            return
        self.page_index = order.index(current)
        self._building_thumbs = True
        for index in range(self.thumbs.count()):
            item = self.thumbs.item(index)
            item.setData(Qt.ItemDataRole.UserRole, index)
            item.setText(f"第 {index + 1} 页")
        self.thumbs.setCurrentRow(self.page_index)
        self._building_thumbs = False
        self._refresh_page()

    def _refresh_all(self) -> None:
        self._rebuild_thumbs()
        self._refresh_page()

    def _rebuild_thumbs(self) -> None:
        self._building_thumbs = True
        self._thumb_queue = []
        self.thumbs.clear()
        count = self.session.page_count
        for index in range(count):
            item = QListWidgetItem(f"第 {index + 1} 页")
            item.setData(Qt.ItemDataRole.UserRole, index)
            item.setSizeHint(QSize(150, 108))
            self.thumbs.addItem(item)
        if count:
            self.thumbs.setCurrentRow(min(self.page_index, count - 1))
        self._building_thumbs = False
        self._thumb_queue = list(range(count))
        if self._thumb_queue:
            self._thumb_timer.start(0)
        self._update_actions()
        self._update_title()

    def _render_one_thumb(self) -> None:
        if not self._thumb_queue or self.session.doc is None:
            return
        index = self._thumb_queue.pop(0)
        if index >= self.session.page_count:
            return
        page = self.session.page(index)
        scale = 78 / max(page.rect.width, 1)
        pix = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
        item = self.thumbs.item(index)
        if item is not None:
            item.setIcon(QIcon(_qpixmap(pix)))
        if self._thumb_queue:
            self._thumb_timer.start(0)

    def _refresh_current_thumb(self) -> None:
        if self.session.doc is None:
            return
        if self.page_index not in self._thumb_queue:
            self._thumb_queue.append(self.page_index)
        self._thumb_timer.start(0)

    def _refresh_page(self) -> None:
        if self.session.doc is None or self.session.page_count == 0:
            self.canvas.set_page(None, self.zoom, [])
            self._sync_side()
            self._update_actions()
            self._update_title()
            return
        self.page_index = min(self.page_index, self.session.page_count - 1)
        page = self.session.page(self.page_index)
        outlines = []
        for box in self.session.boxes_on_page(self.page_index):
            outlines.append((box["id"], self.session.visual_rect_of(box), box["id"] == self.selected_box_id))
        stamp_bytes, stamp_rect, lock, inset = self._stamp_preview(page)
        self.canvas.set_stamp(stamp_bytes, stamp_rect, lock, inset)
        self.canvas.set_mode(self.mode)
        self.canvas.set_page(page, self.zoom, outlines)
        self.page_spin.blockSignals(True)
        self.page_spin.setMaximum(max(1, self.session.page_count))
        self.page_spin.setValue(self.page_index + 1)
        self.page_spin.blockSignals(False)
        self._sync_side()
        self._update_actions()
        self._update_title()
        name = os.path.basename(self.session.path) if self.session.path else "未命名"
        state = "已修改" if self.session.dirty else "未修改"
        self.statusBar().showMessage(
            f"{name}    第 {self.page_index + 1} / {self.session.page_count} 页    {int(self.zoom * 100)}%    {state}"
        )

    def _stamp_preview(self, page):
        if self.mode == "stamp" and self.stamp_bytes and self.free_stamp_rect:
            return self.stamp_bytes, self.free_stamp_rect, None, 0.0
        if self.mode == "qifeng" and self.stamp_bytes:
            try:
                pages = self._qifeng_pages()
            except PdfError:
                return None, None, None, 0.0
            rect = qifeng_preview_rect(
                page,
                self.stamp_bytes,
                pages,
                self.page_index,
                self.qifeng_height,
                self.qifeng_top,
                self.qifeng_edge,
                self.qifeng_inset,
            )
            strip = preview_strip_png(self.stamp_bytes, pages, self.page_index)
            if rect is None or strip is None:
                return None, None, None, 0.0
            preview = (rect.x0, rect.y0, rect.x1, rect.y1)
            return strip, preview, self.qifeng_edge, self.qifeng_inset
        return None, None, None, 0.0

    def _target_pages(self, current, all_pages, custom, editor) -> list[int]:
        count = self.session.page_count
        if current.isChecked():
            return [self.page_index]
        if all_pages.isChecked():
            return list(range(count))
        return flatten_groups(parse_page_groups(editor.text(), count), unique=True)

    def _qifeng_pages(self) -> list[int]:
        count = self.session.page_count
        if self.qifeng_range.isChecked():
            return flatten_groups(parse_page_groups(self.qifeng_spec.text(), count), unique=True)
        return list(range(count))

    def _load_selected_box(self) -> None:
        if not self.selected_box_id:
            return
        try:
            box = self.session.box(self.selected_box_id)
        except PdfError:
            self.selected_box_id = None
            return
        self.text_edit.setPlainText(box["text"])
        self.text_size.setValue(int(box["fontsize"]))
        color = box.get("color") or [0.1, 0.1, 0.1]
        self.text_color = QColor.fromRgbF(color[0], color[1], color[2])
        self.text_color_button.setStyleSheet(
            f"background: {self.text_color.name()}; color: white;"
        )

    def _pick_text_color(self) -> None:
        chosen = QColorDialog_get(self.text_color, self)
        if chosen is not None:
            self.text_color = chosen
            self.text_color_button.setStyleSheet(f"background: {chosen.name()}; color: white;")

    def _sync_side(self) -> None:
        count = self.session.page_count
        if count == 0:
            self.page_label.setText("打开一份 PDF 开始查看和编辑。")
        else:
            self.page_label.setText(f"第 {self.page_index + 1} 页，共 {count} 页")
        show_text = self.selected_box_id is not None and self.mode in ("browse", "text")
        self.text_group.setVisible(show_text)
        self.stamp_group.setVisible(self.mode == "stamp")
        self.qifeng_group.setVisible(self.mode == "qifeng")
        if self.selected_box_id and self.text_group.isVisible():
            if not self.text_edit.hasFocus():
                self._load_selected_box()

    def _set_zoom(self, zoom: float) -> None:
        self.zoom = max(0.25, min(4.0, zoom))
        self._refresh_page()

    def _update_actions(self) -> None:
        ready = self.session.doc is not None and self.session.page_count > 0
        multi = ready and self.session.page_count > 1
        for action in (
            self.act_save,
            self.act_save_as,
            self.act_split,
            self.act_prev,
            self.act_next,
            self.act_zoom_in,
            self.act_zoom_out,
            self.act_fit,
            self.act_rotate,
            self.act_rotate_ccw,
            self.act_delete_page,
            self.act_raster,
        ):
            action.setEnabled(ready)
        self.act_up.setEnabled(multi)
        self.act_down.setEnabled(multi)
        self.act_undo.setEnabled(self.session.can_undo)
        for action in self.mode_actions.values():
            action.setEnabled(ready or action.data() == "browse")

    def _update_title(self) -> None:
        title = APP_NAME
        if self.session.doc is not None:
            name = os.path.basename(self.session.path) if self.session.path else "未命名.pdf"
            mark = "*" if self.session.dirty else ""
            title = f"{APP_NAME} — {mark}{name}"
        self.setWindowTitle(title)

    def _confirm_discard(self) -> bool:
        if self.session.doc is None or not self.session.dirty:
            return True
        return _confirm(self, "当前文件有未保存的修改。确定放弃这些修改？")

    def _about(self) -> None:
        QMessageBox.about(
            self,
            APP_NAME,
            f"{APP_NAME}\n版本 {__version__}\n\n"
            "供建筑设计图纸的查看、合并、拆分、文字标注和公章使用。\n"
            "本程序基于 PyMuPDF，按 AGPL-3.0 发布。\n"
            "公司内部使用无需额外授权；若向他人分发本程序，需同时提供源代码。",
        )


def _confirm(parent, text: str) -> bool:
    box = QMessageBox(parent)
    box.setWindowTitle(APP_NAME)
    box.setIcon(QMessageBox.Icon.Question)
    box.setText(text)
    box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    box.button(QMessageBox.StandardButton.Yes).setText("确定")
    box.button(QMessageBox.StandardButton.No).setText("取消")
    box.setDefaultButton(QMessageBox.StandardButton.No)
    return box.exec() == QMessageBox.StandardButton.Yes


def QDialog_Accepted():
    from PySide6.QtWidgets import QDialog

    return QDialog.DialogCode.Accepted


def QColorDialog_get(initial: QColor, parent) -> QColor | None:
    from PySide6.QtWidgets import QColorDialog

    chosen = QColorDialog.getColor(initial, parent, "文字颜色")
    return chosen if chosen.isValid() else None
