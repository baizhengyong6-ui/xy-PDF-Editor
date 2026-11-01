"""程序入口。"""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv if argv is None else argv)
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
    apply_theme(app)
    window = MainWindow()
    window.show()
    return app.exec()
