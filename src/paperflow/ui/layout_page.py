from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from paperflow.core.layout import LayoutSettings
from paperflow.ui.widgets import Banner, Card, make_button, make_chip

logger = logging.getLogger(__name__)


class LayoutPage(QWidget):
    layout_saved = Signal(object)
    status_message = Signal(str)
    next_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._project_dir: Path | None = None
        self._settings = LayoutSettings()
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 18, 24, 24)
        layout.setSpacing(12)

        header = QVBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(2)
        title = QLabel("版式设置")
        title.setObjectName("PageTitle")
        sub = QLabel(
            "首版只内置“国标通用”模板；单栏/双栏、页边距和字号作为参数。"
            "最终 LaTeX 由程序渲染，不让 AI 直接写 .tex。"
        )
        sub.setObjectName("PageSub")
        sub.setWordWrap(True)
        header.addWidget(title)
        header.addWidget(sub)
        layout.addLayout(header)

        self.info_banner = Banner(
            "版式参数",
            "这些参数会写入 main.tex 的文档类和 geometry，不改变正文文字。",
            "info",
        )
        layout.addWidget(self.info_banner)

        template_card = Card(
            "模板",
            "国标通用：结构按 GB/T 7713.2-2022；字号字体按附录 B 参考值。",
            right_widget=make_chip("唯一内置", fg="#067647", bg="#ecfdf3", border="#abefc6"),
        )
        self.template_label = QLabel("国标通用（GB/T 7713.2-2022）")
        self.template_label.setObjectName("TemplateName")
        template_card.body.addWidget(self.template_label)
        layout.addWidget(template_card)

        params_card = Card("页面与字号", "修改后保存，再进入生成导出。")
        row1 = QHBoxLayout()
        self.columns_combo = QComboBox()
        self.columns_combo.addItem("单栏", 1)
        self.columns_combo.addItem("双栏", 2)
        self.margin_spin = QSpinBox()
        self.margin_spin.setRange(15, 40)
        self.margin_spin.setSuffix(" mm")
        self.line_spacing_combo = QComboBox()
        for value in (1.0, 1.15, 1.25, 1.5, 1.75, 2.0):
            self.line_spacing_combo.addItem(f"{value:.2f}", value)
        for label, widget in (
            ("栏数", self.columns_combo),
            ("页边距", self.margin_spin),
            ("行距", self.line_spacing_combo),
        ):
            box = QVBoxLayout()
            box.addWidget(self._field_label(label))
            box.addWidget(widget)
            row1.addLayout(box, 1)
        params_card.body.addLayout(row1)

        row2 = QHBoxLayout()
        self.body_size_spin = QDoubleSpinBox()
        self.body_size_spin.setRange(9.0, 14.0)
        self.body_size_spin.setSingleStep(0.5)
        self.body_size_spin.setSuffix(" pt")
        self.title_size_spin = QDoubleSpinBox()
        self.title_size_spin.setRange(12.0, 24.0)
        self.title_size_spin.setSingleStep(1.0)
        self.title_size_spin.setSuffix(" pt")
        for label, widget in (
            ("正文号", self.body_size_spin),
            ("题名号", self.title_size_spin),
        ):
            box = QVBoxLayout()
            box.addWidget(self._field_label(label))
            box.addWidget(widget)
            row2.addLayout(box, 1)
        row2.addStretch(1)
        params_card.body.addLayout(row2)

        self.summary_label = QLabel("")
        self.summary_label.setObjectName("MetaLabel")
        self.summary_label.setWordWrap(True)
        params_card.body.addWidget(self.summary_label)
        layout.addWidget(params_card)
        self._connect_changed()

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 2, 0, 0)
        self.save_hint = QLabel("")
        self.save_hint.setObjectName("Hint")
        footer.addWidget(self.save_hint)
        footer.addStretch(1)
        self.save_button = make_button("保存版式", kind="primary")
        self.save_button.clicked.connect(self.save_layout)
        self.next_button = make_button("下一步：生成导出", kind="primary")
        self.next_button.setEnabled(False)
        self.next_button.clicked.connect(self.next_requested.emit)
        footer.addWidget(self.save_button)
        footer.addWidget(self.next_button)
        layout.addLayout(footer)
        layout.addStretch(1)

    def set_context(self, project_dir: Path, settings: LayoutSettings | None = None) -> None:
        self._project_dir = project_dir
        self._settings = settings or LayoutSettings()
        self.columns_combo.setCurrentIndex(
            self.columns_combo.findData(self._settings.columns)
        )
        self.margin_spin.setValue(self._settings.margin_mm)
        self.line_spacing_combo.setCurrentIndex(
            self.line_spacing_combo.findData(self._settings.line_spacing)
        )
        self.body_size_spin.setValue(self._settings.body_size_pt)
        self.title_size_spin.setValue(self._settings.title_size_pt)
        self._update_summary()
        self.next_button.setEnabled(False)
        self.save_hint.setText("未保存")

    def _connect_changed(self) -> None:
        self.columns_combo.currentIndexChanged.connect(self._on_changed)
        self.margin_spin.valueChanged.connect(self._on_changed)
        self.line_spacing_combo.currentIndexChanged.connect(self._on_changed)
        self.body_size_spin.valueChanged.connect(self._on_changed)
        self.title_size_spin.valueChanged.connect(self._on_changed)

    def _on_changed(self, *_args) -> None:
        self._update_summary()
        self.save_hint.setText("有未保存修改")
        self.next_button.setEnabled(False)

    def _update_summary(self) -> None:
        columns = "双栏" if self.columns_combo.currentData() == 2 else "单栏"
        self.summary_label.setText(
            f"当前：{columns} · A4 · 页边距 {self.margin_spin.value()} mm · "
            f"行距 {self.line_spacing_combo.currentData():.2f} · "
            f"正文 {self.body_size_spin.value():.1f} pt · "
            f"题名 {self.title_size_spin.value():.1f} pt"
        )

    def _collect(self) -> LayoutSettings:
        return LayoutSettings(
            columns=2 if self.columns_combo.currentData() == 2 else 1,
            margin_mm=self.margin_spin.value(),
            line_spacing=float(self.line_spacing_combo.currentData()),
            body_size_pt=float(self.body_size_spin.value()),
            title_size_pt=float(self.title_size_spin.value()),
        )

    def save_layout(self) -> None:
        if self._project_dir is None:
            return
        settings = self._collect()
        content = self._project_dir / "content"
        content.mkdir(parents=True, exist_ok=True)
        (content / "layout.json").write_text(settings.to_json() + "\n", encoding="utf-8")
        self._settings = settings
        self.save_hint.setText("版式已保存")
        self.next_button.setEnabled(True)
        self.info_banner.set_state(
            "ok",
            "版式已保存",
            self.summary_label.text(),
        )
        self.layout_saved.emit(settings)
        self.status_message.emit("M5 · 版式已保存")

    @staticmethod
    def _field_label(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("FieldLabel")
        return label