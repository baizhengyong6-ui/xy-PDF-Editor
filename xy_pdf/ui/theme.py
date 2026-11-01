"""界面样式。偏图纸纸色和墨蓝色，方便长时间看图。"""

import sys

from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QPixmap
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication


def ui_font_families() -> list[str]:
    if sys.platform == "darwin":
        # 苹方是 macOS 自带的简体中文界面字体。
        return ["PingFang SC", "Hiragino Sans GB", "Songti SC", "Heiti SC", "Noto Sans CJK SC", "sans-serif"]
    return [
        "Noto Sans CJK SC",
        "Noto Sans SC",
        "Microsoft YaHei",
        "PingFang SC",
        "Source Han Sans SC",
        "sans-serif",
    ]

STYLESHEET = """
QMainWindow, QDialog, QWidget {
    background: #f3efe6;
    color: #1c2430;
    font-size: 13px;
}
QToolBar {
    background: #1e3344;
    border: none;
    spacing: 4px;
    padding: 4px 8px;
}
QToolBar QToolButton {
    color: #f6f1e7;
    background: transparent;
    padding: 6px 10px;
    border-radius: 4px;
}
QToolBar QToolButton:hover {
    background: #2d4c63;
}
QToolBar QToolButton:checked {
    background: #8c2f2f;
}
QToolBar::separator {
    background: #3d5c74;
    width: 1px;
    margin: 6px 8px;
}
QStatusBar {
    background: #1e3344;
    color: #f6f1e7;
}
QListWidget {
    background: #fbf8f2;
    border: none;
    outline: none;
}
QListWidget::item {
    padding: 6px 8px;
    border-bottom: 1px solid #efe8dc;
}
QListWidget::item:selected {
    background: #efe2d2;
    color: #1c2430;
}
QDockWidget {
    titlebar-close-icon: none;
}
QDockWidget::title {
    background: #e7e0d4;
    padding: 6px;
    font-weight: 600;
}
QFrame#SidePanel {
    background: #fbf8f2;
}
QGroupBox {
    background: #fbf8f2;
    border: 1px solid #e0d8cb;
    border-radius: 6px;
    margin-top: 12px;
    padding: 10px 8px 8px 8px;
    font-weight: 600;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
}
QLineEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background: white;
    border: 1px solid #d5cec1;
    border-radius: 4px;
    padding: 4px 6px;
}
QPushButton {
    background: #1e3344;
    color: #f6f1e7;
    border: none;
    border-radius: 4px;
    padding: 6px 12px;
}
QPushButton:hover {
    background: #2d4c63;
}
QPushButton:disabled {
    background: #c8c0b4;
    color: #f6f1e7;
}
QPushButton#accent {
    background: #8c2f2f;
}
QPushButton#accent:hover {
    background: #a13b3b;
}
QLabel#hint {
    color: #5c564c;
}
QSlider::groove:horizontal {
    height: 4px;
    background: #ddd4c6;
    border-radius: 2px;
}
QSlider::handle:horizontal {
    width: 14px;
    margin: -6px 0;
    background: #8c2f2f;
    border-radius: 7px;
}
"""


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    font = QFont()
    font.setFamilies(ui_font_families())
    font.setPointSize(10)
    app.setFont(font)
    app.setStyleSheet(STYLESHEET)
    app.setWindowIcon(make_app_icon())


def make_app_icon() -> QIcon:
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor("#8c2f2f"))
    painter.setPen(QPen(QColor("#f7ecc4"), 3))
    painter.drawEllipse(3, 3, 58, 58)
    painter.setPen(QColor("#f7ecc4"))
    glyph = QFont()
    glyph.setFamilies(ui_font_families())
    glyph.setPixelSize(28)
    glyph.setBold(True)
    painter.setFont(glyph)
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "垚")
    painter.end()
    return QIcon(pixmap)
