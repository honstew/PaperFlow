from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from paperflow.core.document import ImportResult
from paperflow.core.metadata import (
    AffiliationEntry,
    AuthorBio,
    AuthorEntry,
    FieldValue,
    FundEntry,
    M4State,
    MetadataState,
    build_m4_state,
)
from paperflow.core.structure import StructureResult
from paperflow.ui.widgets import Banner, Card, make_button, make_chip

logger = logging.getLogger(__name__)

SOURCE_LABELS = {
    "body": "正文预填",
    "ai": "AI 预填",
    "manual": "手动修改",
    "default": "未填写",
}


class MetadataPage(QWidget):
    metadata_saved = Signal(object)
    status_message = Signal(str)
    next_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._imported: ImportResult | None = None
        self._structure: StructureResult | None = None
        self._state: M4State | None = None
        self._updating = False
        self._dirty = False
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
        title = QLabel("作者与基金")
        title.setObjectName("PageTitle")
        sub = QLabel(
            "正文和 AI 的结果只用于预填；表单是生成源。修改后正文中的对应块会被标记“已吸收”，不会重复输出。"
        )
        sub.setObjectName("PageSub")
        sub.setWordWrap(True)
        header.addWidget(title)
        header.addWidget(sub)
        layout.addLayout(header)

        self.info_banner = Banner(
            "元数据",
            "正在载入正文候选……",
            "info",
        )
        layout.addWidget(self.info_banner)

        self.conflict_banner = Banner("字段冲突", "", "warn")
        self.conflict_banner.setVisible(False)
        layout.addWidget(self.conflict_banner)
        conflict_actions = QHBoxLayout()
        conflict_actions.setContentsMargins(0, 0, 0, 0)
        self.use_body_button = make_button("采用正文值", kind="soft")
        self.use_body_button.clicked.connect(self.reload_from_body)
        self.keep_form_button = make_button("保留表单值", kind="ghost")
        self.keep_form_button.clicked.connect(self.keep_form_values)
        conflict_actions.addWidget(self.use_body_button)
        conflict_actions.addWidget(self.keep_form_button)
        conflict_actions.addStretch(1)
        layout.addLayout(conflict_actions)

        layout.addWidget(self._build_paper_card())
        layout.addWidget(self._build_authors_card())
        layout.addWidget(self._build_affiliations_card())
        layout.addWidget(self._build_abstract_card())
        layout.addWidget(self._build_fund_card())
        layout.addWidget(self._build_bio_card())
        layout.addWidget(self._build_other_card())
        self._connect_dirty_signals()

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 2, 0, 0)
        self.save_hint = QLabel("")
        self.save_hint.setObjectName("Hint")
        footer.addWidget(self.save_hint)
        footer.addStretch(1)
        self.save_button = make_button("保存元数据", kind="primary")
        self.save_button.clicked.connect(self.save_metadata)
        self.next_button = make_button("下一步：参考文献", kind="primary")
        self.next_button.setEnabled(False)
        self.next_button.setToolTip("M5：参考文献逐条确认")
        self.next_button.clicked.connect(self.next_requested.emit)
        footer.addWidget(self.save_button)
        footer.addWidget(self.next_button)
        layout.addLayout(footer)
        layout.addStretch(1)

    def _build_paper_card(self) -> Card:
        self.title_chip = make_chip("未填写", fg="#667085", bg="#f2f4f7", border="#e4e7ec")
        card = Card("论文信息", "题名、英文题名与副题。", right_widget=self.title_chip)
        self.title_edit = QLineEdit()
        self.title_en_edit = QLineEdit()
        self.subtitle_edit = QLineEdit()
        for label, widget in (
            ("中文题名", self.title_edit),
            ("英文题名（可选）", self.title_en_edit),
            ("副题（可选）", self.subtitle_edit),
        ):
            card.body.addWidget(self._field_label(label))
            card.body.addWidget(widget)
        return card

    def _build_authors_card(self) -> Card:
        self.authors_chip = make_chip("0 人", fg="#667085", bg="#f2f4f7", border="#e4e7ec")
        card = Card("作者", "通信作者、邮箱和单位序号可修改。", right_widget=self.authors_chip)
        self.author_table = self._make_table(
            ["姓名", "英文姓名", "单位序号", "通信作者", "邮箱"]
        )
        card.body.addWidget(self.author_table)
        buttons = QHBoxLayout()
        add = make_button("+ 添加作者", kind="soft")
        add.clicked.connect(self.add_author)
        remove = make_button("删除选中作者", kind="ghost")
        remove.clicked.connect(self.remove_author)
        buttons.addWidget(add)
        buttons.addWidget(remove)
        buttons.addStretch(1)
        card.body.addLayout(buttons)
        return card

    def _build_affiliations_card(self) -> Card:
        self.affiliations_chip = make_chip(
            "0 个", fg="#667085", bg="#f2f4f7", border="#e4e7ec"
        )
        card = Card(
            "单位",
            "作者表中的单位序号对应这里的顺序。",
            right_widget=self.affiliations_chip,
        )
        self.affiliation_table = self._make_table(
            ["单位名称", "英文名称", "部门", "城市", "邮编", "国家"]
        )
        card.body.addWidget(self.affiliation_table)
        buttons = QHBoxLayout()
        add = make_button("+ 添加单位", kind="soft")
        add.clicked.connect(self.add_affiliation)
        remove = make_button("删除选中单位", kind="ghost")
        remove.clicked.connect(self.remove_affiliation)
        buttons.addWidget(add)
        buttons.addWidget(remove)
        buttons.addStretch(1)
        card.body.addLayout(buttons)
        return card

    def _build_abstract_card(self) -> Card:
        self.abstract_chip = make_chip("未填写", fg="#667085", bg="#f2f4f7", border="#e4e7ec")
        card = Card(
            "摘要与关键词",
            "关键词用分号分隔；英文摘要可选。",
            right_widget=self.abstract_chip,
        )
        card.body.addWidget(self._field_label("中文摘要"))
        self.abstract_edit = QTextEdit()
        self.abstract_edit.setMinimumHeight(90)
        card.body.addWidget(self.abstract_edit)
        self.keywords_edit = QLineEdit()
        self.keywords_en_edit = QLineEdit()
        card.body.addWidget(self._field_label("中文关键词"))
        card.body.addWidget(self.keywords_edit)
        card.body.addWidget(self._field_label("英文关键词（可选）"))
        card.body.addWidget(self.keywords_en_edit)
        return card

    def _build_fund_card(self) -> Card:
        self.funds_chip = make_chip("0 项", fg="#667085", bg="#f2f4f7", border="#e4e7ec")
        card = Card(
            "基金资助",
            "关闭开关时不输出基金；若正文检测到基金，需要确认。",
            right_widget=self.funds_chip,
        )
        head = QHBoxLayout()
        self.fund_check = QCheckBox("输出基金信息")
        self.fund_check.toggled.connect(self._on_fund_toggled)
        head.addWidget(self.fund_check)
        head.addStretch(1)
        self.fund_note = QLabel("")
        self.fund_note.setObjectName("Hint")
        head.addWidget(self.fund_note)
        card.body.addLayout(head)
        self.fund_table = self._make_table(["基金名称", "项目编号", "项目名称"])
        card.body.addWidget(self.fund_table)
        buttons = QHBoxLayout()
        add = make_button("+ 添加基金", kind="soft")
        add.clicked.connect(self.add_fund)
        remove = make_button("删除选中基金", kind="ghost")
        remove.clicked.connect(self.remove_fund)
        buttons.addWidget(add)
        buttons.addWidget(remove)
        buttons.addStretch(1)
        card.body.addLayout(buttons)
        return card

    def _build_bio_card(self) -> Card:
        self.bios_chip = make_chip("0 条", fg="#667085", bg="#f2f4f7", border="#e4e7ec")
        card = Card("作者简介", "按作者填写；没有可留空。", right_widget=self.bios_chip)
        self.bio_table = self._make_table(["作者", "简介"])
        card.body.addWidget(self.bio_table)
        buttons = QHBoxLayout()
        add = make_button("+ 添加简介", kind="soft")
        add.clicked.connect(self.add_bio)
        remove = make_button("删除选中简介", kind="ghost")
        remove.clicked.connect(self.remove_bio)
        buttons.addWidget(add)
        buttons.addWidget(remove)
        buttons.addStretch(1)
        card.body.addLayout(buttons)
        return card

    def _build_other_card(self) -> Card:
        card = Card("其他信息", "可选项；不填写不影响保存。")
        row1 = QHBoxLayout()
        self.clc_edit = QLineEdit()
        self.doc_type_edit = QLineEdit()
        self.article_edit = QLineEdit()
        for label, widget in (
            ("中图分类号", self.clc_edit),
            ("文献标志码", self.doc_type_edit),
            ("文章编号", self.article_edit),
        ):
            box = QVBoxLayout()
            box.addWidget(self._field_label(label))
            box.addWidget(widget)
            row1.addLayout(box, 1)
        card.body.addLayout(row1)
        row2 = QHBoxLayout()
        self.doi_edit = QLineEdit()
        self.received_edit = QLineEdit()
        for label, widget in (
            ("DOI", self.doi_edit),
            ("收稿日期", self.received_edit),
        ):
            box = QVBoxLayout()
            box.addWidget(self._field_label(label))
            box.addWidget(widget)
            row2.addLayout(box, 1)
        card.body.addLayout(row2)
        card.body.addWidget(self._field_label("致谢（可选）"))
        self.ack_edit = QTextEdit()
        self.ack_edit.setMinimumHeight(60)
        card.body.addWidget(self.ack_edit)
        card.body.addWidget(self._field_label("备注（可选）"))
        self.notes_edit = QLineEdit()
        card.body.addWidget(self.notes_edit)
        return card

    # ------------------------------------------------------------------
    # Context and population
    # ------------------------------------------------------------------
    def set_context(
        self,
        imported: ImportResult,
        structure: StructureResult,
        state: M4State | None = None,
    ) -> None:
        self._imported = imported
        self._structure = structure
        self._state = state or build_m4_state(imported, structure)
        self._load_state()
        self.info_banner.set_state(
            "info",
            "正文候选已载入",
            "表单值用于生成；正文中的对应内容已标记为“已吸收”，不会重复输出。",
        )
        self.info_banner.setVisible(True)
        self.save_hint.setText("未保存")

    def _load_state(self) -> None:
        if self._state is None:
            return
        self._updating = True
        try:
            metadata = self._state.metadata
            self.title_edit.setText(metadata.title.value)
            self.title_en_edit.setText(metadata.title_en.value)
            self.subtitle_edit.setText(metadata.subtitle.value)
            self.abstract_edit.setPlainText(metadata.abstract.value)
            self.keywords_edit.setText("；".join(metadata.keywords))
            self.keywords_en_edit.setText("；".join(metadata.keywords_en))
            self.clc_edit.setText(metadata.clc_number.value)
            self.doc_type_edit.setText(metadata.document_type.value)
            self.article_edit.setText(metadata.article_number.value)
            self.doi_edit.setText(metadata.doi.value)
            self.received_edit.setText(metadata.received_date.value)
            self.ack_edit.setPlainText(metadata.acknowledgement.value)
            self.notes_edit.setText(metadata.notes.value)

            self._load_authors(metadata.authors)
            self._load_affiliations(metadata.affiliations)
            self._load_funds(metadata.funds)
            self._load_bios(metadata.author_bios)
            self.fund_check.setChecked(metadata.fund_enabled)
            self._update_chips(metadata)
            self._update_fund_note()
            self._render_conflicts(metadata)
            self.next_button.setEnabled(False)
            self._dirty = False
        finally:
            self._updating = False

    def _load_authors(self, authors: list[AuthorEntry]) -> None:
        self.author_table.setRowCount(len(authors))
        for row, author in enumerate(authors):
            self.author_table.setItem(row, 0, QTableWidgetItem(author.name))
            self.author_table.setItem(row, 1, QTableWidgetItem(author.name_en))
            self.author_table.setItem(
                row,
                2,
                QTableWidgetItem(",".join(str(index) for index in author.affiliation_indices)),
            )
            checkbox = QCheckBox()
            checkbox.setChecked(author.corresponding)
            checkbox.setToolTip("勾选表示通信作者")
            checkbox.setStyleSheet("margin-left: 22px;")
            self.author_table.setCellWidget(row, 3, checkbox)
            self.author_table.setItem(row, 4, QTableWidgetItem(author.email))

    def _load_affiliations(self, affiliations: list[AffiliationEntry]) -> None:
        self.affiliation_table.setRowCount(len(affiliations))
        for row, item in enumerate(affiliations):
            values = [
                item.name,
                item.name_en,
                item.department,
                item.city,
                item.postcode,
                item.country,
            ]
            for col, value in enumerate(values):
                self.affiliation_table.setItem(row, col, QTableWidgetItem(value))

    def _load_funds(self, funds: list[FundEntry]) -> None:
        self.fund_table.setRowCount(len(funds))
        for row, item in enumerate(funds):
            self.fund_table.setItem(row, 0, QTableWidgetItem(item.name))
            self.fund_table.setItem(row, 1, QTableWidgetItem(item.number))
            self.fund_table.setItem(row, 2, QTableWidgetItem(item.title))

    def _load_bios(self, bios: list[AuthorBio]) -> None:
        self.bio_table.setRowCount(len(bios))
        for row, item in enumerate(bios):
            self.bio_table.setItem(row, 0, QTableWidgetItem(item.author_name))
            self.bio_table.setItem(row, 1, QTableWidgetItem(item.text))
        self.bio_table.resizeRowsToContents()

    def _update_chips(self, metadata: MetadataState) -> None:
        self._set_chip(self.title_chip, metadata.title.source)
        self._set_chip(
            self.authors_chip,
            metadata.authors_source,
            f"{len(metadata.authors)} 人",
        )
        self._set_chip(
            self.affiliations_chip,
            metadata.affiliations_source,
            f"{len(metadata.affiliations)} 个",
        )
        self._set_chip(self.abstract_chip, metadata.abstract.source)
        self._set_chip(
            self.funds_chip,
            metadata.funds_source,
            f"{len(metadata.funds)} 项",
        )
        self._set_chip(
            self.bios_chip,
            metadata.bios_source,
            f"{len(metadata.author_bios)} 条",
        )

    def _set_chip(self, label: QLabel, source: str, count: str | None = None) -> None:
        text = SOURCE_LABELS.get(source, source)
        if count:
            text = f"{count} · {text}"
        colors = {
            "body": ("#2563eb", "#eff4ff", "#dbe7ff"),
            "ai": ("#7a5af8", "#f4f0ff", "#d9ccff"),
            "manual": ("#067647", "#ecfdf3", "#abefc6"),
            "default": ("#667085", "#f2f4f7", "#e4e7ec"),
        }
        fg, bg, border = colors.get(source, colors["default"])
        label.setText(text)
        label.setStyleSheet(
            f"color:{fg}; background:{bg}; border:1px solid {border}; "
            "border-radius:8px; padding:2px 7px; font-size:9px; font-weight:700;"
        )

    # ------------------------------------------------------------------
    # Conflicts
    # ------------------------------------------------------------------
    def _render_conflicts(self, metadata: MetadataState) -> None:
        conflicts = metadata.unresolved_conflicts
        if not conflicts:
            self.conflict_banner.setVisible(False)
            self.use_body_button.setVisible(False)
            self.keep_form_button.setVisible(False)
            return
        self.use_body_button.setVisible(True)
        self.keep_form_button.setVisible(True)
        lines = []
        for conflict in conflicts[:3]:
            lines.append(
                f"{conflict.label}：正文为“{conflict.body_value[:32]}”，表单为“{conflict.form_value[:32]}”"
            )
        self.conflict_banner.set_state(
            "warn",
            f"发现 {len(conflicts)} 个字段与正文不同",
            "；".join(lines) + "。表单将用于生成，正文块已标记“已吸收”。",
        )
        self.conflict_banner.setVisible(True)

    def reload_from_body(self) -> None:
        if self._state is None:
            return
        metadata = self._state.metadata
        self._updating = True
        try:
            self.title_edit.setText(metadata.body_title)
            self.abstract_edit.setPlainText(metadata.body_abstract)
            self.keywords_edit.setText("；".join(metadata.body_keywords))
            self._load_authors(
                [AuthorEntry(name=name, source="body") for name in metadata.body_authors]
            )
            self._load_affiliations(
                [
                    AffiliationEntry(name=name, source="body")
                    for name in metadata.body_affiliations
                ]
            )
            self._load_funds([FundEntry(name=name, source="body") for name in metadata.body_funds])
            self._load_bios(
                [AuthorBio(text=text, source="body") for text in metadata.body_bios]
            )
            self.fund_check.setChecked(bool(metadata.body_funds))
            self._mark_dirty()
        finally:
            self._updating = False
        self.conflict_banner.setVisible(False)
        self.use_body_button.setVisible(False)
        self.keep_form_button.setVisible(False)
        self.info_banner.set_state(
            "ok", "已恢复正文值", "表单已重置为正文候选；请检查后保存。"
        )
        self.info_banner.setVisible(True)

    def keep_form_values(self) -> None:
        if self._state is None:
            return
        self._state.metadata.mark_form_priority()
        self.conflict_banner.setVisible(False)
        self.use_body_button.setVisible(False)
        self.keep_form_button.setVisible(False)
        self.info_banner.set_state(
            "ok",
            "已保留表单值",
            "已记录为表单优先；正文对应块将在生成时跳过。",
        )
        self.info_banner.setVisible(True)

    # ------------------------------------------------------------------
    # Collect and save
    # ------------------------------------------------------------------
    def _collect_metadata(self) -> MetadataState:
        if self._state is None:
            raise ValueError("没有可保存的元数据")
        metadata = self._state.metadata
        metadata.title = self._field_value(
            self.title_edit.text(), metadata.body_title, metadata.title.source
        )
        metadata.title_en = self._field_value(
            self.title_en_edit.text(), "", metadata.title_en.source
        )
        metadata.subtitle = self._field_value(
            self.subtitle_edit.text(), "", metadata.subtitle.source
        )
        metadata.abstract = self._field_value(
            self.abstract_edit.toPlainText(), metadata.body_abstract, metadata.abstract.source
        )
        metadata.keywords = self._split_keywords(self.keywords_edit.text())
        metadata.keywords_en = self._split_keywords(self.keywords_en_edit.text())
        metadata.clc_number = self._field_value(self.clc_edit.text(), "", metadata.clc_number.source)
        metadata.document_type = self._field_value(
            self.doc_type_edit.text(), "", metadata.document_type.source
        )
        metadata.article_number = self._field_value(
            self.article_edit.text(), "", metadata.article_number.source
        )
        metadata.doi = self._field_value(self.doi_edit.text(), "", metadata.doi.source)
        metadata.received_date = self._field_value(
            self.received_edit.text(), "", metadata.received_date.source
        )
        metadata.acknowledgement = self._field_value(
            self.ack_edit.toPlainText(), "", metadata.acknowledgement.source
        )
        metadata.notes = self._field_value(self.notes_edit.text(), "", metadata.notes.source)

        metadata.authors = self._collect_authors()
        metadata.affiliations = self._collect_affiliations()
        metadata.funds = self._collect_funds()
        metadata.author_bios = self._collect_bios()
        metadata.fund_enabled = self.fund_check.isChecked()
        metadata.authors_source = self._list_source(
            [author.name for author in metadata.authors], metadata.body_authors
        )
        metadata.affiliations_source = self._list_source(
            [item.name for item in metadata.affiliations], metadata.body_affiliations
        )
        metadata.keywords_source = self._list_source(
            metadata.keywords, metadata.body_keywords
        )
        metadata.funds_source = self._list_source(
            [item.name for item in metadata.funds], metadata.body_funds
        )
        metadata.bios_source = self._list_source(
            [item.text for item in metadata.author_bios], metadata.body_bios
        )
        metadata.consumed_block_ids = self._consumed_ids(metadata)
        metadata.detect_conflicts()
        return metadata

    def _consumed_ids(self, metadata: MetadataState) -> list[str]:
        if self._structure is None:
            return list(metadata.consumed_block_ids)
        consumed = set(metadata.consumed_block_ids)
        roles = {item.block_id: item.role for item in self._structure.blocks}
        for block in self._structure.document.blocks:
            role = roles.get(block.id, block.kind)
            if role in {"title", "author", "affiliation", "abstract", "keywords"}:
                consumed.add(block.id)
        return sorted(consumed)

    def _collect_authors(self) -> list[AuthorEntry]:
        authors = []
        for row in range(self.author_table.rowCount()):
            name = self._cell(self.author_table, row, 0)
            if not name:
                continue
            indices_text = self._cell(self.author_table, row, 2)
            indices = [
                int(value)
                for value in indices_text.replace("，", ",").split(",")
                if value.strip().isdigit()
            ]
            checkbox = self.author_table.cellWidget(row, 3)
            corresponding = isinstance(checkbox, QCheckBox) and checkbox.isChecked()
            authors.append(
                AuthorEntry(
                    name=name,
                    name_en=self._cell(self.author_table, row, 1),
                    affiliation_indices=indices,
                    corresponding=corresponding,
                    email=self._cell(self.author_table, row, 4),
                    source="manual",
                )
            )
        return authors

    def _collect_affiliations(self) -> list[AffiliationEntry]:
        affiliations = []
        for row in range(self.affiliation_table.rowCount()):
            name = self._cell(self.affiliation_table, row, 0)
            if not name:
                continue
            affiliations.append(
                AffiliationEntry(
                    name=name,
                    name_en=self._cell(self.affiliation_table, row, 1),
                    department=self._cell(self.affiliation_table, row, 2),
                    city=self._cell(self.affiliation_table, row, 3),
                    postcode=self._cell(self.affiliation_table, row, 4),
                    country=self._cell(self.affiliation_table, row, 5) or "中国",
                    source="manual",
                )
            )
        return affiliations

    def _collect_funds(self) -> list[FundEntry]:
        funds = []
        for row in range(self.fund_table.rowCount()):
            name = self._cell(self.fund_table, row, 0)
            number = self._cell(self.fund_table, row, 1)
            title = self._cell(self.fund_table, row, 2)
            if name or number or title:
                funds.append(FundEntry(name=name, number=number, title=title, source="manual"))
        return funds

    def _collect_bios(self) -> list[AuthorBio]:
        bios = []
        for row in range(self.bio_table.rowCount()):
            text = self._cell(self.bio_table, row, 1)
            if text:
                bios.append(
                    AuthorBio(
                        author_name=self._cell(self.bio_table, row, 0),
                        text=text,
                        source="manual",
                    )
                )
        return bios

    def save_metadata(self) -> None:
        if self._state is None or self._imported is None:
            return
        try:
            metadata = self._collect_metadata()
        except Exception as exc:
            self.info_banner.set_state("error", "元数据校验失败", str(exc))
            self.info_banner.setVisible(True)
            return
        if not metadata.title.value.strip():
            self.info_banner.set_state("error", "缺少题名", "请填写中文题名后再保存。")
            self.info_banner.setVisible(True)
            return
        if not metadata.authors:
            self.info_banner.set_state("error", "缺少作者", "请至少填写一位作者后再保存。")
            self.info_banner.setVisible(True)
            return
        if metadata.fund_enabled and not metadata.funds:
            self.info_banner.set_state(
                "error", "基金开关已打开但没有条目", "请添加基金项目，或关闭基金开关。"
            )
            self.info_banner.setVisible(True)
            return
        if (
            metadata.body_funds
            and not metadata.fund_enabled
            and not metadata.fund_off_confirmed
        ):
            answer = QMessageBox.question(
                self,
                "确认关闭基金",
                "正文检测到基金信息，但基金开关已关闭。\n"
                "关闭后输出的论文不会显示基金；是否确认？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            metadata.fund_off_confirmed = True
            metadata.detect_conflicts()
        self._state.metadata = metadata
        self._state.saved_at = datetime.now().astimezone().isoformat()
        content = Path(self._imported.project_dir) / "content"
        content.mkdir(parents=True, exist_ok=True)
        (content / "metadata.json").write_text(
            metadata.to_json() + "\n", encoding="utf-8"
        )
        (content / "m4-state.json").write_text(
            self._state.to_json() + "\n", encoding="utf-8"
        )
        self._update_chips(metadata)
        self._render_conflicts(metadata)
        self._dirty = False
        self.save_hint.setText("元数据已保存")
        if metadata.unresolved_conflicts:
            self.info_banner.set_state(
                "warn",
                "已保存，仍有待确认冲突",
                f"{len(metadata.unresolved_conflicts)} 个字段与正文不同；可点击“采用正文值”或“保留表单值”。",
            )
        else:
            self.info_banner.set_state(
                "ok",
                "元数据已保存",
                "已写入 content/metadata.json 与 content/m4-state.json；正文已吸收块不会重复输出。",
            )
        self.info_banner.setVisible(True)
        self.next_button.setEnabled(True)
        self.metadata_saved.emit(self._state)
        self.status_message.emit("M4 · 元数据已保存")

    # ------------------------------------------------------------------
    # Table actions
    # ------------------------------------------------------------------
    def add_author(self) -> None:
        row = self.author_table.rowCount()
        self.author_table.insertRow(row)
        checkbox = QCheckBox()
        checkbox.setToolTip("勾选表示通信作者")
        checkbox.setStyleSheet("margin-left: 22px;")
        self.author_table.setCellWidget(row, 3, checkbox)
        self._mark_dirty()

    def remove_author(self) -> None:
        row = self.author_table.currentRow()
        if row >= 0:
            self.author_table.removeRow(row)
            self._mark_dirty()

    def add_affiliation(self) -> None:
        self.affiliation_table.insertRow(self.affiliation_table.rowCount())
        self._mark_dirty()

    def remove_affiliation(self) -> None:
        row = self.affiliation_table.currentRow()
        if row >= 0:
            self.affiliation_table.removeRow(row)
            self._mark_dirty()

    def add_fund(self) -> None:
        self.fund_table.insertRow(self.fund_table.rowCount())
        self._mark_dirty()

    def remove_fund(self) -> None:
        row = self.fund_table.currentRow()
        if row >= 0:
            self.fund_table.removeRow(row)
            self._mark_dirty()

    def add_bio(self) -> None:
        self.bio_table.insertRow(self.bio_table.rowCount())
        self._mark_dirty()

    def remove_bio(self) -> None:
        row = self.bio_table.currentRow()
        if row >= 0:
            self.bio_table.removeRow(row)
            self._mark_dirty()

    def _on_fund_toggled(self, _checked: bool) -> None:
        if self._updating:
            return
        self._update_fund_note()
        self._mark_dirty()

    def _update_fund_note(self) -> None:
        if self._state is None:
            return
        body_funds = self._state.metadata.body_funds
        if body_funds and not self.fund_check.isChecked():
            self.fund_note.setText("正文检测到基金；关闭需确认")
            self.fund_note.setStyleSheet("color:#b54708;")
        elif body_funds:
            self.fund_note.setText("正文检测到基金，已预填")
            self.fund_note.setStyleSheet("color:#2563eb;")
        else:
            self.fund_note.setText("")
            self.fund_note.setStyleSheet("")

    def _connect_dirty_signals(self) -> None:
        for widget in (
            self.title_edit,
            self.title_en_edit,
            self.subtitle_edit,
            self.keywords_edit,
            self.keywords_en_edit,
            self.clc_edit,
            self.doc_type_edit,
            self.article_edit,
            self.doi_edit,
            self.received_edit,
            self.notes_edit,
        ):
            widget.textChanged.connect(self._mark_dirty)
        for widget in (self.abstract_edit, self.ack_edit):
            widget.textChanged.connect(self._mark_dirty)
        for table in (
            self.author_table,
            self.affiliation_table,
            self.fund_table,
            self.bio_table,
        ):
            table.itemChanged.connect(self._mark_dirty)

    def _mark_dirty(self, *_args) -> None:
        if self._updating:
            return
        self._dirty = True
        self.save_hint.setText("有未保存修改")
        self.next_button.setEnabled(False)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _make_table(self, headers: list[str]) -> QTableWidget:
        table = QTableWidget(0, len(headers))
        table.setObjectName("MetaTable")
        table.setHorizontalHeaderLabels(headers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(True)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.setMinimumHeight(110)
        table.setMaximumHeight(190)
        return table

    def _field_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("FieldLabel")
        return label

    @staticmethod
    def _cell(table: QTableWidget, row: int, col: int) -> str:
        item = table.item(row, col)
        return item.text().strip() if item else ""

    @staticmethod
    def _split_keywords(text: str) -> list[str]:
        return [item.strip() for item in re.split(r"[；;，,、]\s*", text) if item.strip()]

    @staticmethod
    def _field_value(value: str, body: str, old_source: str) -> FieldValue:
        clean = value.strip()
        if body and clean == body.strip():
            source = "body" if old_source in {"body", "ai"} else "body"
        else:
            source = "manual" if clean else "default"
        return FieldValue(value=clean, source=source, confirmed=bool(clean))

    @staticmethod
    def _list_source(values: list[str], body: list[str]) -> str:
        if not values:
            return "default"
        if [item.strip() for item in values] == [item.strip() for item in body]:
            return "body"
        return "manual"