from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
)

from paperflow.llm.review_ai import AIReviewResult, ReviewFinding
from paperflow.ui.widgets import make_button

SEVERITY_LABELS = {"major": "严重", "minor": "一般", "info": "提示"}


class AIReviewDialog(QDialog):
    def __init__(self, result: AIReviewResult, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("AI PDF 审阅")
        self.setMinimumSize(920, 560)
        self._result = result
        self.selected_findings: list[ReviewFinding] = []
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)
        title = QLabel("AI PDF 版式审阅")
        title.setObjectName("PageTitle")
        layout.addWidget(title)
        sub = QLabel(
            f"已审阅 {self._result.page_count} 页，发现 {len(self._result.findings)} 条问题。"
            "可选中条目应用白名单修复；不会改写正文。"
        )
        sub.setObjectName("PageSub")
        sub.setWordWrap(True)
        layout.addWidget(sub)

        self.table = QTableWidget(0, 5)
        self.table.setObjectName("AIReviewTable")
        self.table.setHorizontalHeaderLabels(["页", "严重度", "类别", "证据", "建议"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(0, 46)
        self.table.setColumnWidth(1, 70)
        self.table.setColumnWidth(2, 130)
        self.table.itemSelectionChanged.connect(self._show_detail)
        layout.addWidget(self.table, 2)

        self.detail = QTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setMinimumHeight(120)
        layout.addWidget(self.detail)

        for finding in self._result.findings:
            row = self.table.rowCount()
            self.table.insertRow(row)
            values = [
                str(finding.page),
                SEVERITY_LABELS.get(finding.severity, finding.severity),
                finding.category,
                finding.evidence,
                finding.suggestion,
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setTextAlignment(
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
                )
                self.table.setItem(row, col, item)
            self.table.setRowHeight(row, 28)
        if self.table.rowCount():
            self.table.selectRow(0)
        else:
            self.detail.setPlainText("本次没有发现明确的版式问题。")

        footer = QHBoxLayout()
        note = QLabel("只应用受控参数（图片宽度/跨栏、表格跨栏、标题前分页）；可回滚。")
        note.setObjectName("Hint")
        footer.addWidget(note)
        footer.addStretch(1)
        self.apply_button = make_button("应用选中并重新编译", kind="primary")
        self.apply_button.setEnabled(bool(self._result.findings))
        self.apply_button.clicked.connect(self._accept_selected)
        close = make_button("关闭", kind="ghost")
        close.clicked.connect(self.reject)
        footer.addWidget(close)
        footer.addWidget(self.apply_button)
        layout.addLayout(footer)

    def _accept_selected(self) -> None:
        rows = sorted({index.row() for index in self.table.selectedIndexes()})
        self.selected_findings = [
            self._result.findings[row]
            for row in rows
            if 0 <= row < len(self._result.findings)
        ]
        if self.selected_findings:
            self.accept()

    def _show_detail(self) -> None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self._result.findings):
            return
        finding = self._result.findings[row]
        lines = [
            f"页码：{finding.page}",
            f"严重度：{SEVERITY_LABELS.get(finding.severity, finding.severity)}",
            f"类别：{finding.category}",
            f"置信度：{finding.confidence:.2f}",
            f"目标：{finding.target or '未指定'}",
            "",
            "证据：",
            finding.evidence or "（无）",
            "",
            "建议：",
            finding.suggestion or "（无）",
        ]
        self.detail.setPlainText("\n".join(lines))