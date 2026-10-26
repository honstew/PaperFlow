from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from paperflow.core.fixes import FixPlan
from paperflow.ui.pdf_preview import PdfPreview
from paperflow.ui.widgets import Card, make_button


class FixCompareDialog(QDialog):
    """Before/after preview for a whitelisted automatic fix."""

    def __init__(
        self,
        before_pdf: Path,
        after_pdf: Path,
        plan: FixPlan,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("修复前后对比")
        self.setMinimumSize(1180, 720)
        self.before_pdf = before_pdf
        self.after_pdf = after_pdf
        self.keep_changes = False
        self._build_ui(plan)
        self.finished.connect(self._shutdown_previews)

    def _build_ui(self, plan: FixPlan) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)
        title = QLabel("白名单修复前后对比")
        title.setObjectName("PageTitle")
        layout.addWidget(title)
        note = QLabel(
            f"已应用 {len(plan.actions)} 项受控修改，并重新编译。"
            "请对比前后 PDF；不保留会恢复原来的 TeX/PDF 和覆盖设置。"
        )
        note.setObjectName("PageSub")
        note.setWordWrap(True)
        layout.addWidget(note)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(10)
        self.before_preview = self._preview_panel("修改前", self.before_pdf)
        self.after_preview = self._preview_panel("修改后", self.after_pdf)
        splitter.addWidget(self.before_preview)
        splitter.addWidget(self.after_preview)
        splitter.setSizes([600, 600])
        layout.addWidget(splitter, 1)

        changes = QLabel(
            "；".join(action.description for action in plan.actions)
        )
        changes.setObjectName("Hint")
        changes.setWordWrap(True)
        layout.addWidget(changes)

        footer = QHBoxLayout()
        skipped = QLabel(
            f"跳过 {len(plan.skipped)} 条：不满足白名单或缺少 target。"
            if plan.skipped
            else ""
        )
        skipped.setObjectName("Hint")
        footer.addWidget(skipped)
        footer.addStretch(1)
        rollback = make_button("回滚", kind="ghost")
        rollback.clicked.connect(self.reject)
        keep = make_button("保留修改", kind="primary")
        keep.clicked.connect(self._keep)
        footer.addWidget(rollback)
        footer.addWidget(keep)
        layout.addLayout(footer)

    def _preview_panel(self, title: str, pdf: Path) -> QWidget:
        card = Card(title, pdf.name)
        preview = PdfPreview()
        preview.load_pdf(pdf)
        card.body.addWidget(preview)
        card._preview = preview  # keep reference for close
        return card

    def _keep(self) -> None:
        self.keep_changes = True
        self.accept()

    def _shutdown_previews(self) -> None:
        for panel in (self.before_preview, self.after_preview):
            preview = getattr(panel, "_preview", None)
            if preview is not None:
                preview.shutdown()

    def closeEvent(self, event) -> None:  # noqa: N802
        self._shutdown_previews()
        super().closeEvent(event)