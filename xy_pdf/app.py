"""程序入口。"""

from __future__ import annotations

import os
import sys


def _prefer_chinese_locale(app) -> None:
    """让 Qt 自带的对话框用简体中文。macOS 系统文件窗口仍跟随系统语言。"""
    from PySide6.QtCore import QLibraryInfo, QLocale, QTranslator

    QLocale.setDefault(QLocale(QLocale.Language.Chinese, QLocale.Country.China))
    translator = QTranslator(app)
    translations = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    if translator.load("qtbase_zh_CN", translations):
        app.installTranslator(translator)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv if argv is None else argv)
    if sys.platform == "darwin":
        os.environ.setdefault("LANG", "zh_CN.UTF-8")
        os.environ.setdefault("QT_MAC_WANTS_LAYER", "1")

    if "--self-check" in args:
        import pymupdf
        from PySide6.QtWidgets import QApplication
        from xy_pdf.core.session import PdfSession

        session = PdfSession()
        session.new_document()
        session.add_blank_page()
        if session.page_count != 1:
            print("self-check failed", file=sys.stderr)
            return 1
        # 确认界面库和 PDF 引擎都能加载，打包后缺文件时这里会失败。
        QApplication([])
        print(f"xinyao-pdf-editor ok pymupdf {pymupdf.pymupdf_version}")
        session.close()
        return 0

    from PySide6.QtWidgets import QApplication

    from xy_pdf import APP_NAME
    from xy_pdf.ui.main_window import MainWindow
    from xy_pdf.ui.theme import apply_theme

    app = QApplication(args)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    _prefer_chinese_locale(app)
    apply_theme(app)
    window = MainWindow()
    window.show()
    return app.exec()
