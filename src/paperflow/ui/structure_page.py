from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QProgressBar,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from paperflow.core.config import AppSettings
from paperflow.core.document import ImportResult
from paperflow.core.structure import (
    ROLE_VALUES,
    SectionNode,
    StructureBlock,
    StructureResponse,
    StructureResult,
    apply_structure_response,
    build_local_structure,
)
from paperflow.llm import StructureError, extract_structure
from paperflow.ui.widgets import (
    Banner,
    Card,
    KpiCard,
    make_button,
    make_chip,
)
from paperflow.ui.workers import FunctionThread

logger = logging.getLogger(__name__)

ROLE_LABELS = {
    "title": "题名",
    "subtitle": "副题",
    "author": "作者",
    "affiliation": "单位",
    "abstract": "摘要",
    "keywords": "关键词",
    "heading": "章节标题",
    "paragraph": "正文",
    "list": "列表",
    "code": "代码",
    "figure": "图片",
    "figure_caption": "图题",
    "table": "表格",
    "table_caption": "表题",
    "equation": "公式",
    "reference": "参考文献",
    "acknowledgement": "致谢",
    "appendix": "附录",
    "unknown": "未确定",
}


class StructurePage(QWidget):
    structure_ready = Signal(object)
    status_message = Signal(str)
    next_requested = Signal()

    def __init__(
        self,
        settings_provider: Callable[[], AppSettings],
        key_provider: Callable[[], str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._settings_provider = settings_provider
        self._key_provider = key_provider
        self._import_result: ImportResult | None = None
        self._working: StructureResult | None = None
        self._thread: FunctionThread | None = None
        self._busy = False
        self._updating = False
        self._dirty = False
        self._row_ids: list[str] = []
        self._role_combos: list[QComboBox] = []
        self._level_combos: list[QComboBox] = []
        self._confidences: list[float] = []
        self._build_ui()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 18, 24, 24)
        layout.setSpacing(12)

        header = QVBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(2)
        title = QLabel("结构校对")
        title.setObjectName("PageTitle")
        sub = QLabel(
            "AI 只给内容块分配角色和章节层级，不改写正文。识别后请逐项核对，再保存结构。"
        )
        sub.setObjectName("PageSub")
        sub.setWordWrap(True)
        header.addWidget(title)
        header.addWidget(sub)
        layout.addLayout(header)

        self.ai_chip = make_chip("未运行", fg="#667085", bg="#f2f4f7", border="#e4e7ec")
        self.recognition_card = Card(
            "结构识别",
            "点击 AI 识别会把正文块发送到当前配置的 API；Key 只用于本次请求。",
            right_widget=self.ai_chip,
        )
        body = self.recognition_card.body
        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(8)
        self.ai_button = make_button("AI 识别结构", kind="primary")
        self.ai_button.clicked.connect(self.run_ai)
        self.local_button = make_button("使用本地规则", kind="soft")
        self.local_button.clicked.connect(self.run_local)
        self.save_button = make_button("保存结构", kind="ghost")
        self.save_button.clicked.connect(self.save_structure)
        actions.addWidget(self.ai_button)
        actions.addWidget(self.local_button)
        actions.addStretch(1)
        actions.addWidget(self.save_button)
        body.addLayout(actions)

        self.ai_status = QLabel("请先导入论文。")
        self.ai_status.setObjectName("Hint")
        self.ai_status.setWordWrap(True)
        body.addWidget(self.ai_status)

        self.meta_label = QLabel("")
        self.meta_label.setObjectName("MetaLabel")
        self.meta_label.setWordWrap(True)
        self.meta_label.setVisible(False)
        body.addWidget(self.meta_label)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(3)
        self.progress.setVisible(False)
        body.addWidget(self.progress)

        self.ai_banner = Banner("结构识别", "", "info")
        self.ai_banner.setVisible(False)
        body.addWidget(self.ai_banner)
        layout.addWidget(self.recognition_card)

        kpi_row = QHBoxLayout()
        kpi_row.setSpacing(8)
        self.kpi_sections = KpiCard("章节", "—", "#2563eb")
        self.kpi_headings = KpiCard("标题块", "—", "#0f9f8f")
        self.kpi_references = KpiCard("参考文献", "—", "#b54708")
        self.kpi_issues = KpiCard("待确认", "—", "#b42318")
        for widget in (self.kpi_sections, self.kpi_headings, self.kpi_references, self.kpi_issues):
            kpi_row.addWidget(widget, 1)
        layout.addLayout(kpi_row)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(10)
        splitter.addWidget(self._build_section_card())
        splitter.addWidget(self._build_block_card())
        splitter.setSizes([250, 850])
        layout.addWidget(splitter, 1)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 2, 0, 0)
        self.save_hint = QLabel("")
        self.save_hint.setObjectName("Hint")
        footer.addWidget(self.save_hint)
        footer.addStretch(1)
        self.next_button = make_button("下一步：图表管理", kind="primary")
        self.next_button.setEnabled(False)
        self.next_button.setToolTip("M4：图片上传、表格编辑与作者信息")
        self.next_button.clicked.connect(self.next_requested.emit)
        footer.addWidget(self.next_button)
        layout.addLayout(footer)

    def _build_section_card(self) -> Card:
        card = Card("章节树", "点击章节定位内容块。")
        self.section_tree = QTreeWidget()
        self.section_tree.setObjectName("SectionTree")
        self.section_tree.setHeaderHidden(True)
        self.section_tree.setIndentation(15)
        self.section_tree.setMinimumWidth(220)
        self.section_tree.itemClicked.connect(self._on_section_clicked)
        card.body.addWidget(self.section_tree)
        return card

    def _build_block_card(self) -> Card:
        card = Card("内容块", "角色和标题级别可修改；正文本身不可编辑。")
        self.block_table = QTableWidget(0, 5)
        self.block_table.setObjectName("StructureTable")
        self.block_table.setHorizontalHeaderLabels(["ID", "角色", "级别", "文本", "置信度"])
        self.block_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.block_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.block_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.block_table.setShowGrid(False)
        self.block_table.setAlternatingRowColors(True)
        self.block_table.verticalHeader().setVisible(False)
        header = self.block_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self.block_table.setColumnWidth(0, 68)
        self.block_table.setColumnWidth(1, 112)
        self.block_table.setColumnWidth(2, 66)
        self.block_table.setColumnWidth(4, 60)
        self.block_table.setMinimumHeight(420)
        card.body.addWidget(self.block_table)
        return card

    # ------------------------------------------------------------------
    # Data
    # ------------------------------------------------------------------
    def set_import_result(self, result: ImportResult | None) -> None:
        self._import_result = result
        self._dirty = False
        self.ai_banner.setVisible(False)
        if result is None:
            self._working = None
            self.block_table.setRowCount(0)
            self.section_tree.clear()
            self.ai_status.setText("请先在“导入论文”完成 TXT/Markdown 导入。")
            self.ai_button.setEnabled(False)
            self.local_button.setEnabled(False)
            self.save_button.setEnabled(False)
            self.meta_label.setVisible(False)
            self._set_chip("未运行", "#667085", "#f2f4f7", "#e4e7ec")
            return
        self._working = build_local_structure(result.document)
        self._populate(self._working)
        self.ai_button.setEnabled(True)
        self.local_button.setEnabled(True)
        self.save_button.setEnabled(True)
        self.ai_status.setText(
            f"已载入 {result.summary.source_name}（{result.summary.block_count} 块）。"
            "当前为本地规则基线；点击 AI 识别获取模型结果。"
        )
        self._set_chip("本地规则", "#b54708", "#fffaeb", "#fedf89")
        self.save_button.setText("保存结构")
        self.save_hint.setText("尚未保存")
        self._show_meta(self._working)
        self.structure_ready.emit(self._working)

    def restore_structure(self, structure: StructureResult) -> None:
        """Load a saved structure without rebuilding it from local rules."""
        self._working = structure
        self._dirty = False
        self._populate(structure)
        self._show_meta(structure)
        self.save_button.setEnabled(True)
        self.save_button.setText("保存结构")
        self.ai_button.setEnabled(True)
        self.local_button.setEnabled(True)
        self.ai_status.setText("已从项目文件恢复结构；可继续修改并保存。")
        self._set_chip("已恢复", "#067647", "#ecfdf3", "#abefc6")
        self.save_hint.setText("已从项目恢复")
        self.structure_ready.emit(structure)

    def run_local(self) -> None:
        if self._import_result is None:
            return
        self._working = build_local_structure(self._import_result.document)
        self._populate(self._working)
        self.ai_status.setText("已使用本地规则：标题、图题、表题、摘要和关键词来自 M2 解析。")
        self._set_chip("本地规则", "#b54708", "#fffaeb", "#fedf89")
        self.ai_banner.set_state(
            "info",
            "本地规则模式",
            "没有调用 API；正文不会离开本机。可继续手动修改角色和级别。",
        )
        self.ai_banner.setVisible(True)
        self._dirty = False
        self.save_button.setText("保存结构")
        self.save_hint.setText("本地结果尚未保存")
        self.structure_ready.emit(self._working)

    def run_ai(self) -> None:
        if self._import_result is None:
            self.ai_banner.set_state("warn", "尚未导入论文", "请先在“导入论文”导入 TXT/Markdown。")
            self.ai_banner.setVisible(True)
            return
        if self._busy:
            return
        key = (self._key_provider() or "").strip()
        if not key:
            self.ai_banner.set_state(
                "error",
                "缺少 API Key",
                "请先在“环境与 API”填写并保存 Key；也可以先使用本地规则。",
            )
            self.ai_banner.setVisible(True)
            return
        try:
            settings = self._settings_provider()
        except Exception as exc:
            self.ai_banner.set_state("error", "API 设置无效", str(exc))
            self.ai_banner.setVisible(True)
            return
        self._set_busy(True)
        self.ai_banner.set_state(
            "info",
            "正在调用 AI",
            f"模型：{settings.model} · 块数：{self._import_result.summary.block_count}。"
            "只发送正文文本，不发送 API Key。",
        )
        self.ai_banner.setVisible(True)
        self.ai_status.setText("正在请求结构识别，请稍候……")
        self._thread = FunctionThread(
            extract_structure,
            settings,
            key,
            self._import_result.document,
            parent=self,
        )
        self._thread.result.connect(self._on_ai_result)
        self._thread.error.connect(self._on_ai_error)
        self._thread.finished.connect(self._on_thread_finished)
        self._thread.start()

    def _on_ai_result(self, result: StructureResult) -> None:
        self._set_busy(False)
        self._working = result
        self._populate(result)
        self._set_chip("AI 已识别", "#067647", "#ecfdf3", "#abefc6")
        self.ai_button.setText("重新识别")
        self.ai_status.setText(
            f"AI 识别完成 · {len(result.blocks)} 块 · {len(result.sections)} 个章节"
            f"{' · ' + result.usage_text if result.usage_text else ''}"
        )
        self.ai_banner.set_state(
            "ok",
            "识别完成",
            "请检查角色和标题级别；如模型标注有误可直接修改后保存。",
        )
        self.ai_banner.setVisible(True)
        self.save_hint.setText("AI 结果尚未保存")
        self.save_button.setText("保存结构 *")
        self._dirty = True
        self.structure_ready.emit(result)

    def _on_ai_error(self, message: str) -> None:
        self._set_busy(False)
        self._set_chip("AI 失败", "#b42318", "#fef3f2", "#fecdca")
        self.ai_status.setText("AI 识别失败；当前仍保留本地规则结果。")
        self.ai_banner.set_state(
            "error",
            "识别失败",
            message or "未知错误。请检查 API Key、网络和模型设置。",
        )
        self.ai_banner.setVisible(True)
        if self._working is not None:
            self.structure_ready.emit(self._working)

    def _on_thread_finished(self) -> None:
        thread = self._thread
        self._thread = None
        if thread is not None:
            thread.deleteLater()
        self._set_busy(False)

    # ------------------------------------------------------------------
    # Population and editing
    # ------------------------------------------------------------------
    def _populate(self, result: StructureResult) -> None:
        self._updating = True
        self._working = result
        self._row_ids = []
        self._role_combos = []
        self._level_combos = []
        self._confidences = []
        blocks = {block.id: block for block in result.document.blocks}
        self.block_table.setRowCount(len(result.blocks))
        for row, item in enumerate(result.blocks):
            block = blocks.get(item.block_id)
            if block is None:
                continue
            self._row_ids.append(item.block_id)
            self._confidences.append(item.confidence)
            id_item = QTableWidgetItem(item.block_id)
            id_item.setData(Qt.ItemDataRole.UserRole, item.block_id)
            self.block_table.setItem(row, 0, id_item)

            role_combo = QComboBox()
            role_combo.setObjectName("RoleCombo")
            role_combo.setToolTip("选择内容块角色")
            for role in ROLE_VALUES:
                role_combo.addItem(ROLE_LABELS.get(role, role), role)
            index = role_combo.findData(item.role)
            role_combo.setCurrentIndex(index if index >= 0 else role_combo.findData("paragraph"))
            self.block_table.setCellWidget(row, 1, role_combo)
            self._role_combos.append(role_combo)

            level_combo = QComboBox()
            level_combo.setObjectName("LevelCombo")
            level_combo.setToolTip("标题级别，仅章节标题可用")
            level_combo.addItem("—", None)
            for level in range(1, 5):
                level_combo.addItem(f"{level} 级", level)
            level_combo.setCurrentIndex(
                level_combo.findData(item.heading_level) if item.heading_level else 0
            )
            level_combo.setEnabled(item.role == "heading")
            self.block_table.setCellWidget(row, 2, level_combo)
            self._level_combos.append(level_combo)

            text = block.text.replace("\n", " ").strip()
            display = text[:160] + ("…" if len(text) > 160 else "")
            text_item = QTableWidgetItem(display)
            text_item.setToolTip(text)
            self.block_table.setItem(row, 3, text_item)

            confidence = QTableWidgetItem(f"{item.confidence:.2f}")
            confidence.setForeground(
                Qt.GlobalColor.darkYellow
                if item.confidence < 0.6
                else Qt.GlobalColor.darkGreen
            )
            self.block_table.setItem(row, 4, confidence)
            self.block_table.setRowHeight(row, 30)

            role_combo.currentIndexChanged.connect(
                lambda _index, row=row: self._on_role_changed(row)
            )
            level_combo.currentIndexChanged.connect(
                lambda _index, row=row: self._on_level_changed(row)
            )

        self._populate_sections(result.sections)
        self.kpi_sections.set_value(_count_sections(result.sections))
        self.kpi_headings.set_value(sum(1 for item in result.blocks if item.role == "heading"))
        self.kpi_references.set_value(sum(1 for item in result.blocks if item.role == "reference"))
        self.kpi_issues.set_value(len(result.issues))
        self._show_meta(result)
        self.save_button.setEnabled(True)
        self.next_button.setEnabled(True)
        self._updating = False
        self.save_hint.setText("结构未保存" if self._dirty else "")

    def _populate_sections(self, sections: list[SectionNode]) -> None:
        self.section_tree.clear()
        root = QTreeWidgetItem(["全文"])
        root.setData(0, Qt.ItemDataRole.UserRole, None)
        self.section_tree.addTopLevelItem(root)
        for section in sections:
            self._add_section_item(root, section)
        root.setExpanded(True)
        self.section_tree.expandAll()

    def _add_section_item(self, parent: QTreeWidgetItem, section: SectionNode) -> None:
        label = section.title
        if section.level:
            label = f"{section.title}  ({_section_block_count(section)})"
        item = QTreeWidgetItem([label])
        item.setData(0, Qt.ItemDataRole.UserRole, section.block_id)
        item.setToolTip(0, section.title)
        parent.addChild(item)
        for child in section.children:
            self._add_section_item(item, child)

    def _show_meta(self, result: StructureResult) -> None:
        metadata = result.metadata
        parts = []
        if metadata.title:
            parts.append(f"题名：{metadata.title}")
        if metadata.authors:
            parts.append("作者：" + "、".join(metadata.authors))
        if metadata.affiliations:
            parts.append("单位：" + "；".join(metadata.affiliations))
        if metadata.keywords:
            parts.append("关键词：" + "；".join(metadata.keywords))
        text = "  ·  ".join(parts)
        self.meta_label.setText(text)
        self.meta_label.setVisible(bool(text))

    def _on_role_changed(self, row: int) -> None:
        if self._updating or row >= len(self._level_combos):
            return
        role = self._role_combos[row].currentData()
        level_combo = self._level_combos[row]
        if role == "heading":
            level_combo.setEnabled(True)
            if level_combo.currentData() is None:
                level_combo.setCurrentIndex(1)
        else:
            level_combo.setCurrentIndex(0)
            level_combo.setEnabled(False)
        self._mark_dirty()

    def _on_level_changed(self, row: int) -> None:
        if self._updating:
            return
        self._mark_dirty()

    def _mark_dirty(self) -> None:
        if self._updating:
            return
        self._dirty = True
        self.save_hint.setText("有未保存修改")
        self.save_button.setText("保存结构 *")

    def _on_section_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        block_id = item.data(0, Qt.ItemDataRole.UserRole)
        if not block_id or block_id not in self._row_ids:
            return
        row = self._row_ids.index(block_id)
        self.block_table.selectRow(row)
        self.block_table.scrollToItem(self.block_table.item(row, 0))

    def _collect_result(self) -> StructureResult:
        if self._working is None:
            raise StructureError("没有可保存的结构")
        items: list[StructureBlock] = []
        for row, block_id in enumerate(self._row_ids):
            role = self._role_combos[row].currentData()
            level = self._level_combos[row].currentData()
            items.append(
                StructureBlock(
                    block_id=block_id,
                    role=role,
                    heading_level=level if role == "heading" else None,
                    confidence=self._confidences[row],
                )
            )
        response = StructureResponse(metadata=self._working.metadata, blocks=items)
        return apply_structure_response(
            self._working.document,
            response,
            source="manual",
        )

    def save_structure(self) -> None:
        if self._import_result is None or self._working is None:
            return
        try:
            result = self._collect_result()
        except Exception as exc:
            self.ai_banner.set_state("error", "结构校验失败", str(exc))
            self.ai_banner.setVisible(True)
            return
        project_dir = Path(self._import_result.project_dir)
        if project_dir:
            content = project_dir / "content"
            content.mkdir(parents=True, exist_ok=True)
            (content / "structure.json").write_text(result.to_json() + "\n", encoding="utf-8")
            (content / "manuscript-structured.json").write_text(
                result.document.to_json() + "\n", encoding="utf-8"
            )
        self._working = result
        self._dirty = False
        self.save_button.setText("保存结构")
        self.save_hint.setText("结构已保存")
        self._set_chip("已保存", "#067647", "#ecfdf3", "#abefc6")
        self.ai_status.setText(
            f"结构已保存 · {len(result.sections)} 个章节 · {len(result.blocks)} 块"
        )
        self.ai_banner.set_state("ok", "结构已保存", "已写入项目 content/structure.json。")
        self.ai_banner.setVisible(True)
        self.status_message.emit("M3 · 结构已保存")
        self.structure_ready.emit(result)

    # ------------------------------------------------------------------
    # Misc
    # ------------------------------------------------------------------
    def _set_chip(self, text: str, fg: str, bg: str, border: str) -> None:
        if self.ai_chip is not None:
            self.ai_chip.setText(text)
            self.ai_chip.setStyleSheet(
                f"color:{fg}; background:{bg}; border:1px solid {border}; "
                "border-radius:8px; padding:2px 7px; font-size:9px; font-weight:700;"
            )

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.progress.setVisible(busy)
        self.ai_button.setEnabled(not busy and self._import_result is not None)
        self.local_button.setEnabled(not busy and self._import_result is not None)
        self.save_button.setEnabled(not busy and self._working is not None)
        self.next_button.setEnabled(False)

    def shutdown(self) -> None:
        if self._thread is not None and self._thread.isRunning():
            self._thread.quit()
            if not self._thread.wait(1500):
                self._thread.terminate()
                self._thread.wait(500)
        self._thread = None

    @property
    def working_result(self) -> StructureResult | None:
        return self._working


def _count_sections(sections: list[SectionNode]) -> int:
    total = 0
    for section in sections:
        if section.level:
            total += 1
        total += _count_sections(section.children)
    return total


def _section_block_count(section: SectionNode) -> int:
    return len(section.block_ids) + sum(
        _section_block_count(child) for child in section.children
    )