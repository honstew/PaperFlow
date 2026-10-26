from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QTextEdit,
    QVBoxLayout,
)

from paperflow.llm.compile_ai import CompileFixResult
from paperflow.ui.widgets import Banner, Card, make_button


class CompileFixDialog(QDialog):
    def __init__(self, result: CompileFixResult, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("AI 编译修复建议")
        self.setMinimumSize(880, 620)
        self.result = result
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)
        title = QLabel("AI 编译错误分析与修改方案")
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        self.banner = Banner(
            "只建议，不覆盖正文",
            "AI 只修改与编译错误相关的最小片段；应用前会备份 main.tex，失败会自动回滚。",
            "info",
        )
        layout.addWidget(self.banner)

        diagnosis_card = Card("诊断", "AI 对根因的判断，供人工核对。")
        self.diagnosis = QTextEdit()
        self.diagnosis.setReadOnly(True)
        self.diagnosis.setMinimumHeight(100)
        self.diagnosis.setPlainText(self.result.diagnosis or "（AI 没有给出诊断）")
        diagnosis_card.body.addWidget(self.diagnosis)
        layout.addWidget(diagnosis_card)

        patch_card = Card(
            "修改片段",
            f"共 {len(self.result.patches)} 个 patch；应用后重新编译，失败会回滚。",
        )
        self.patches = QTextEdit()
        self.patches.setReadOnly(True)
        self.patches.setMinimumHeight(240)
        blocks = []
        for index, patch in enumerate(self.result.patches, start=1):
            blocks.append(
                f"--- patch {index} ---\n"
                f"原因：{patch.reason or '（未说明）'}\n"
                f"搜索：\n{patch.search}\n\n"
                f"替换为：\n{patch.replace}\n"
            )
        self.patches.setPlainText("\n".join(blocks) or "AI 没有给出可应用 patch。")
        patch_card.body.addWidget(self.patches)
        layout.addWidget(patch_card)

        footer = QHBoxLayout()
        confidence = QLabel(f"置信度：{self.result.confidence:.2f}")
        confidence.setObjectName("Hint")
        footer.addWidget(confidence)
        footer.addStretch(1)
        close = make_button("关闭", kind="ghost")
        close.clicked.connect(self.reject)
        self.apply_button = make_button("应用并重新编译", kind="primary")
        self.apply_button.setEnabled(bool(self.result.patches))
        self.apply_button.clicked.connect(self.accept)
        footer.addWidget(close)
        footer.addWidget(self.apply_button)
        layout.addLayout(footer)