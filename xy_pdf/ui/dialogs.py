"""合并、拆分和文字框对话框。"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
    QColorDialog,
)
from PySide6.QtGui import QColor

from xy_pdf import APP_NAME


class TextBoxDialog(QDialog):
    def __init__(self, parent=None, text: str = "", fontsize: int = 14, color: QColor | None = None, fill: bool = False):
        super().__init__(parent)
        self.setWindowTitle("文字框")
        self.resize(420, 280)
        self.color = color or QColor("#1a1a1a")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("输入要写在图纸上的文字，可以换行。"))
        self.editor = QPlainTextEdit()
        self.editor.setPlainText(text)
        layout.addWidget(self.editor)
        form = QFormLayout()
        self.size = QSpinBox()
        self.size.setRange(8, 72)
        self.size.setValue(fontsize)
        self.size.setSuffix(" 磅")
        form.addRow("字号", self.size)
        self.color_button = QPushButton("选择颜色")
        self.color_button.clicked.connect(self._pick_color)
        form.addRow("颜色", self.color_button)
        self.fill = QCheckBox("加浅色底，方便压在线条上")
        self.fill.setChecked(fill)
        form.addRow("", self.fill)
        layout.addLayout(form)
        self._paint_color_button()
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("确定")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _pick_color(self) -> None:
        chosen = QColorDialog.getColor(self.color, self, "文字颜色")
        if chosen.isValid():
            self.color = chosen
            self._paint_color_button()

    def _paint_color_button(self) -> None:
        self.color_button.setStyleSheet(
            f"background: {self.color.name()}; color: white; border-radius: 4px; padding: 6px 12px;"
        )

    def _accept(self) -> None:
        if not self.editor.toPlainText().strip():
            QMessageBox.warning(self, APP_NAME, "文字不能为空。")
            return
        self.accept()

    def values(self) -> dict:
        fill = (1.0, 0.98, 0.93) if self.fill.isChecked() else None
        return {
            "text": self.editor.toPlainText().strip(),
            "fontsize": self.size.value(),
            "color": (self.color.redF(), self.color.greenF(), self.color.blueF()),
            "fill": fill,
        }


class MergeDialog(QDialog):
    def __init__(self, parent=None, can_include: bool = False):
        super().__init__(parent)
        self.setWindowTitle("合并 PDF")
        self.resize(480, 420)
        self.output = ""
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("按列表从上到下的顺序合并。可以调整顺序。"))
        self.include = QCheckBox("把当前打开的文档放在最前面")
        self.include.setEnabled(can_include)
        self.include.setChecked(can_include)
        layout.addWidget(self.include)
        self.files = QListWidget()
        self.files.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.files.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        layout.addWidget(self.files)
        row = QHBoxLayout()
        add = QPushButton("添加文件")
        remove = QPushButton("移除")
        up = QPushButton("上移")
        down = QPushButton("下移")
        add.clicked.connect(self._add)
        remove.clicked.connect(self._remove)
        up.clicked.connect(lambda: self._move(-1))
        down.clicked.connect(lambda: self._move(1))
        for button in (add, remove, up, down):
            row.addWidget(button)
        layout.addLayout(row)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("合并并保存")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def paths(self) -> list[str]:
        return [self.files.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.files.count())]

    def _add(self) -> None:
        chosen, _ = QFileDialog.getOpenFileNames(self, "选择要合并的 PDF", "", "PDF 文件 (*.pdf)")
        for path in chosen:
            self.files.addItem(os.path.basename(path))
            self.files.item(self.files.count() - 1).setData(Qt.ItemDataRole.UserRole, path)
            self.files.item(self.files.count() - 1).setToolTip(path)

    def _remove(self) -> None:
        row = self.files.currentRow()
        if row >= 0:
            self.files.takeItem(row)

    def _move(self, delta: int) -> None:
        row = self.files.currentRow()
        target = row + delta
        if row < 0 or target < 0 or target >= self.files.count():
            return
        item = self.files.takeItem(row)
        self.files.insertItem(target, item)
        self.files.setCurrentRow(target)

    def _accept(self) -> None:
        extra = 1 if self.include.isChecked() else 0
        if self.files.count() + extra < 2:
            QMessageBox.warning(self, APP_NAME, "请至少准备两个 PDF。")
            return
        path, _ = QFileDialog.getSaveFileName(self, "保存合并后的 PDF", "合并.pdf", "PDF 文件 (*.pdf)")
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        self.output = path
        self.accept()


class SplitDialog(QDialog):
    def __init__(self, parent=None, page_count: int = 1):
        super().__init__(parent)
        self.setWindowTitle("拆分 / 提取页面")
        self.resize(460, 280)
        self.page_count = page_count
        self.output = ""
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"当前文档共 {page_count} 页。页码从 1 开始。"))
        self.by_range = QRadioButton("按页码范围拆成多个文件")
        self.each = QRadioButton("每一页单独存成一个文件")
        self.extract = QRadioButton("提取指定页面，存成一个文件")
        self.by_range.setChecked(True)
        for button in (self.by_range, self.each, self.extract):
            layout.addWidget(button)
            button.toggled.connect(self._sync)
        self.spec = QLineEdit()
        self.spec.setPlaceholderText("例如 1-3,5,8-10")
        layout.addWidget(self.spec)
        self.hint = QLabel("逗号分隔每一份文件。1-3,5 会得到“第1-3页”和“第5页”两个 PDF。")
        self.hint.setWordWrap(True)
        self.hint.setObjectName("hint")
        layout.addWidget(self.hint)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("选择位置并执行")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._sync()

    def mode(self) -> str:
        if self.each.isChecked():
            return "each"
        if self.extract.isChecked():
            return "extract"
        return "ranges"

    def _sync(self) -> None:
        needs_spec = not self.each.isChecked()
        self.spec.setEnabled(needs_spec)
        if self.extract.isChecked():
            self.hint.setText("提取结果是一个 PDF，页序与填写顺序一致。例如 4,2 会先放第 4 页，再放第 2 页。")
        elif self.each.isChecked():
            self.hint.setText("会在所选文件夹里为每一页生成一个 PDF。")
        else:
            self.hint.setText("逗号分隔每一份文件。1-3,5 会得到“第1-3页”和“第5页”两个 PDF。")

    def _accept(self) -> None:
        if self.mode() != "each" and not self.spec.text().strip():
            QMessageBox.warning(self, APP_NAME, "请填写页码范围，例如 1-3,5。")
            return
        if self.mode() == "extract":
            path, _ = QFileDialog.getSaveFileName(self, "保存提取结果", "提取.pdf", "PDF 文件 (*.pdf)")
            if not path:
                return
            if not path.lower().endswith(".pdf"):
                path += ".pdf"
            self.output = path
        else:
            folder = QFileDialog.getExistingDirectory(self, "选择输出文件夹")
            if not folder:
                return
            self.output = folder
        self.accept()
