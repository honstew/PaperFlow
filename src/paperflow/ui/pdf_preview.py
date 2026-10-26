from __future__ import annotations

import io
import logging
from pathlib import Path

import pypdfium2 as pdfium
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)


class PdfPreview(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._document: pdfium.PdfDocument | None = None
        self._page_index = 0
        self._page_count = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)
        self.prev_button = QPushButton("‹")
        self.prev_button.setFixedWidth(30)
        self.prev_button.clicked.connect(self.previous_page)
        self.next_button = QPushButton("›")
        self.next_button.setFixedWidth(30)
        self.next_button.clicked.connect(self.next_page)
        self.page_label = QLabel("— / —")
        self.page_label.setObjectName("Hint")
        toolbar.addWidget(self.prev_button)
        toolbar.addWidget(self.next_button)
        toolbar.addWidget(self.page_label)
        toolbar.addStretch(1)
        layout.addLayout(toolbar)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setObjectName("PdfScroll")
        self.image = QLabel("编译成功后在这里预览 PDF")
        self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image.setObjectName("PdfPage")
        self.scroll.setWidget(self.image)
        layout.addWidget(self.scroll, 1)
        self._set_controls(False)

    def load_pdf(self, path: Path) -> bool:
        self.close_document()
        try:
            self._document = pdfium.PdfDocument(str(path))
            self._page_count = len(self._document)
        except Exception:
            logger.exception("Failed to open PDF: %s", path)
            self.image.setText("PDF 预览失败，可用系统阅读器打开")
            self._set_controls(False)
            return False
        self._page_index = 0
        self._set_controls(True)
        self.render_page()
        return True

    def render_page(self) -> None:
        if self._document is None or not self._page_count:
            return
        self._page_index = max(0, min(self._page_index, self._page_count - 1))
        try:
            page = self._document[self._page_index]
            viewport_width = self.scroll.viewport().width()
            target_width = max(320, viewport_width - 28) if viewport_width > 0 else 520
            scale = max(0.35, min(2.5, target_width / max(1.0, page.get_width())))
            bitmap = page.render(scale=scale)
            pil = bitmap.to_pil()
            buffer = io.BytesIO()
            pil.save(buffer, format="PNG")
            image = QImage.fromData(buffer.getvalue(), "PNG")
            self.image.setPixmap(QPixmap.fromImage(image))
            self.image.setText("")
        except Exception:
            logger.exception("Failed to render PDF page")
            self.image.setText("当前页渲染失败")
        self.page_label.setText(f"{self._page_index + 1} / {self._page_count}")

    def previous_page(self) -> None:
        if self._page_index > 0:
            self._page_index -= 1
            self.render_page()

    def next_page(self) -> None:
        if self._page_index + 1 < self._page_count:
            self._page_index += 1
            self.render_page()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self._document is not None:
            self.render_page()

    def _set_controls(self, enabled: bool) -> None:
        self.prev_button.setEnabled(enabled)
        self.next_button.setEnabled(enabled)
        self.page_label.setEnabled(enabled)
        if not enabled:
            self.page_label.setText("— / —")

    def close_document(self) -> None:
        if self._document is not None:
            try:
                self._document.close()
            except Exception:
                logger.debug("Failed to close PDF", exc_info=True)
        self._document = None
        self._page_count = 0
        self._page_index = 0
        self.image.setPixmap(QPixmap())
        self.image.setText("编译成功后在这里预览 PDF")
        self._set_controls(False)

    def shutdown(self) -> None:
        self.close_document()