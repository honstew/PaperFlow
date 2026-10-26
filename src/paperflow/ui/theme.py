from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

ACCENT = "#2563eb"
ACCENT_DARK = "#1d4ed8"
SIDEBAR = "#0b1526"
INK = "#162033"
MUTED = "#667085"
LINE = "#e4e9f1"
BG = "#f2f5fa"

APP_QSS = r"""
* {
    font-family: "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI";
    font-size: 12px;
    color: #162033;
}
QMainWindow, QWidget#Root {
    background: #f2f5fa;
}
QWidget#ContentScroll, QScrollArea#ContentScroll, QScrollArea#ContentScroll > QWidget > QWidget {
    background: transparent;
    border: 0;
}
QFrame#Sidebar {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #111f35, stop:1 #0b1526);
    border: 0;
}
QLabel#BrandMark {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #60a5fa, stop:0.55 #2563eb, stop:1 #0f9f8f);
    color: white;
    border-radius: 10px;
    font-size: 17px;
    font-weight: 700;
}
QLabel#BrandName {
    color: #ffffff;
    font-size: 18px;
    font-weight: 700;
}
QLabel#BrandSub {
    color: #94a3b8;
    font-size: 9px;
    letter-spacing: 1.4px;
}
QFrame#ProjectPill {
    background: rgba(255, 255, 255, 0.045);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 10px;
}
QLabel#ProjectIcon {
    background: rgba(96, 165, 250, 0.16);
    color: #93c5fd;
    border-radius: 7px;
    font-size: 12px;
}
QLabel#ProjectName {
    color: #ffffff;
    font-size: 11px;
    font-weight: 600;
}
QLabel#ProjectMeta {
    color: #94a3b8;
    font-size: 9px;
}
QFrame#NavStep {
    background: transparent;
    border: 1px solid transparent;
    border-radius: 9px;
}
QFrame#NavStep:hover {
    background: rgba(255, 255, 255, 0.055);
}
QFrame#NavStep[active="true"] {
    background: rgba(37, 99, 235, 0.22);
    border: 1px solid rgba(96, 165, 250, 0.18);
}
QFrame#NavStep[available="false"] {
    background: transparent;
}
QLabel#StepNum {
    background: rgba(255, 255, 255, 0.07);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 7px;
    color: #cbd5e1;
    font-size: 10px;
    font-weight: 700;
}
QFrame#NavStep[active="true"] QLabel#StepNum {
    background: #2563eb;
    border: 1px solid #2563eb;
    color: #ffffff;
}
QFrame#NavStep[available="false"] QLabel#StepNum {
    background: rgba(255, 255, 255, 0.035);
    border: 1px solid rgba(255, 255, 255, 0.04);
    color: #475569;
}
QLabel#StepTitle {
    color: #cbd5e1;
    font-size: 11px;
    font-weight: 600;
}
QFrame#NavStep[active="true"] QLabel#StepTitle {
    color: #ffffff;
}
QFrame#NavStep[available="false"] QLabel#StepTitle {
    color: #64748b;
}
QLabel#StepHint {
    color: #64748b;
    font-size: 9px;
}
QFrame#NavStep[active="true"] QLabel#StepHint {
    color: #a9c2f8;
}
QFrame#NavStep[available="false"] QLabel#StepHint {
    color: #475569;
}
QLabel#SideFooter {
    color: #64748b;
    font-size: 9px;
}
QLabel#SideFooterStrong {
    color: #a7f3d0;
    font-size: 9px;
}
QFrame#TopBar {
    background: rgba(255, 255, 255, 0.88);
    border-bottom: 1px solid #e4e9f1;
}
QLabel#Crumb {
    color: #667085;
    font-size: 10px;
}
QLabel#PageTitle {
    color: #162033;
    font-size: 19px;
    font-weight: 700;
}
QLabel#PageSub {
    color: #667085;
    font-size: 10px;
}
QLabel#TopTitle {
    color: #162033;
    font-size: 14px;
    font-weight: 700;
}
QLabel#TopSub {
    color: #667085;
    font-size: 10px;
}
QFrame#SavePill {
    background: #ffffff;
    border: 1px solid #e4e9f1;
    border-radius: 999px;
}
QLabel#SaveDot {
    color: #12b76a;
    font-size: 12px;
}
QLabel#SaveText {
    color: #667085;
    font-size: 9px;
}
QPushButton {
    border: 1px solid #d7deea;
    background: #ffffff;
    color: #344054;
    border-radius: 8px;
    padding: 6px 11px;
    font-size: 10px;
    font-weight: 600;
}
QPushButton:hover {
    border-color: #b9c6da;
    background: #fbfcfe;
}
QPushButton:pressed {
    background: #f2f5fa;
}
QPushButton:disabled {
    color: #98a2b3;
    background: #f8fafc;
    border-color: #e4e9f1;
}
QPushButton#PrimaryButton {
    background: #2563eb;
    border: 1px solid #2563eb;
    color: #ffffff;
}
QPushButton#PrimaryButton:hover {
    background: #1d4ed8;
    border-color: #1d4ed8;
}
QPushButton#PrimaryButton:disabled {
    background: #b2ccff;
    border-color: #b2ccff;
    color: #ffffff;
}
QPushButton#SoftButton {
    background: #eff4ff;
    border: 1px solid #dbe7ff;
    color: #2563eb;
}
QPushButton#SoftButton:hover {
    background: #e5efff;
}
QPushButton#GhostButton {
    background: transparent;
    border: 1px solid transparent;
    color: #667085;
}
QPushButton#GhostButton:hover {
    background: #f2f5fa;
    color: #162033;
}
QPushButton#LinkButton {
    background: transparent;
    border: 0;
    color: #2563eb;
    padding: 3px 0;
    font-weight: 600;
}
QPushButton#LinkButton:hover {
    color: #1d4ed8;
    text-decoration: underline;
}
QFrame#Card {
    background: #ffffff;
    border: 1px solid #e4e9f1;
    border-radius: 12px;
}
QFrame#CardHeader {
    border-bottom: 1px solid #e4e9f1;
    background: transparent;
}
QLabel#CardTitle {
    font-size: 12px;
    font-weight: 700;
    color: #162033;
}
QLabel#CardSub {
    font-size: 9px;
    color: #667085;
}
QLabel#FieldLabel {
    font-size: 9px;
    font-weight: 700;
    color: #344054;
}
QLabel#Hint {
    font-size: 9px;
    color: #667085;
}
QLabel#Muted {
    color: #667085;
    font-size: 9px;
}
QLineEdit, QComboBox, QSpinBox, QTextEdit {
    background: #ffffff;
    border: 1px solid #d7deea;
    border-radius: 7px;
    padding: 6px 8px;
    color: #162033;
    selection-background-color: #bfdbfe;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QTextEdit:focus {
    border: 1px solid #84adff;
}
QLineEdit:disabled, QComboBox:disabled {
    background: #f8fafc;
    color: #98a2b3;
}
QComboBox::drop-down {
    border: 0;
    width: 20px;
}
QComboBox QAbstractItemView {
    background: #ffffff;
    border: 1px solid #d7deea;
    selection-background-color: #eff4ff;
    selection-color: #1d4ed8;
    padding: 3px;
}
QCheckBox {
    font-size: 9px;
    color: #667085;
    spacing: 5px;
}
QCheckBox::indicator {
    width: 13px;
    height: 13px;
    border: 1px solid #b9c6da;
    border-radius: 3px;
    background: #ffffff;
}
QCheckBox::indicator:checked {
    background: #2563eb;
    border-color: #2563eb;
}
QFrame#Banner {
    border-radius: 8px;
    border: 1px solid #dbe7ff;
    background: #eff4ff;
}
QFrame#Banner[state="ok"] {
    background: #ecfdf3;
    border-color: #abefc6;
}
QFrame#Banner[state="warn"] {
    background: #fffaeb;
    border-color: #fedf89;
}
QFrame#Banner[state="error"] {
    background: #fef3f2;
    border-color: #fecdca;
}
QLabel#BannerTitle {
    font-size: 10px;
    font-weight: 700;
    color: #1e3a8a;
}
QFrame#Banner[state="ok"] QLabel#BannerTitle { color: #067647; }
QFrame#Banner[state="warn"] QLabel#BannerTitle { color: #b54708; }
QFrame#Banner[state="error"] QLabel#BannerTitle { color: #b42318; }
QLabel#BannerText {
    color: #475467;
    font-size: 9px;
}
QFrame#StatusRow {
    background: transparent;
    border-bottom: 1px dashed #eef2f7;
}
QFrame#StatusRow[last="true"] {
    border-bottom: 0;
}
QLabel#StatusDot {
    font-size: 14px;
    font-weight: 700;
}
QLabel#StatusTitle {
    font-size: 10px;
    font-weight: 700;
    color: #162033;
}
QLabel#StatusDetail {
    font-size: 9px;
    color: #667085;
}
QLabel#StatusRight {
    font-size: 9px;
    color: #667085;
}
QFrame#InstallOption {
    background: #fbfdff;
    border: 1px solid #e4e9f1;
    border-radius: 9px;
}
QLabel#InstallTitle {
    font-size: 10px;
    font-weight: 700;
    color: #162033;
}
QLabel#InstallText {
    font-size: 9px;
    color: #667085;
}
QFrame#RightPanel, QStackedWidget#RightStack, QStackedWidget#PageStack {
    background: transparent;
    border: 0;
}
QFrame#RightCard {
    background: #ffffff;
    border: 1px solid #e4e9f1;
    border-radius: 12px;
}
QLabel#RightTitle {
    font-size: 11px;
    font-weight: 700;
}
QLabel#RightText {
    font-size: 9px;
    color: #667085;
}
QLabel#RightValue {
    font-size: 11px;
    font-weight: 700;
    color: #162033;
}
QLabel#CheckItem {
    font-size: 10px;
    color: #344054;
}
QFrame#StatusBar {
    background: #ffffff;
    border-top: 1px solid #e4e9f1;
}
QLabel#StatusBarText {
    font-size: 9px;
    color: #667085;
}
QLabel#StatusBarOk {
    font-size: 9px;
    color: #067647;
}
QLabel#StatusBarWarn {
    font-size: 9px;
    color: #b54708;
}
QLabel#PageTitle {
    font-size: 20px;
    font-weight: 700;
    color: #162033;
}
QLabel#PageSub {
    font-size: 10px;
    color: #667085;
}
QFrame#DropZone {
    background: #ffffff;
    border: 1px dashed #b8c6dd;
    border-radius: 12px;
}
QFrame#DropZone:hover, QFrame#DropZone[dragOver="true"] {
    background: #f8fbff;
    border-color: #2563eb;
}
QLabel#DropIcon {
    color: #2563eb;
    font-size: 23px;
    font-weight: 700;
}
QLabel#DropTitle {
    font-size: 12px;
    font-weight: 700;
    color: #162033;
}
QLabel#DropHint {
    font-size: 9px;
    color: #667085;
}
QFrame#KpiCard {
    background: #f8fafc;
    border: 1px solid #e4e9f1;
    border-radius: 8px;
}
QLabel#KpiValue {
    font-size: 18px;
    font-weight: 700;
}
QLabel#KpiLabel {
    font-size: 9px;
    color: #667085;
}
QLabel#FileIcon {
    background: #eff4ff;
    color: #2563eb;
    border-radius: 8px;
    font-size: 9px;
    font-weight: 700;
}
QLabel#FileTitle {
    font-size: 12px;
    font-weight: 700;
    color: #162033;
}
QLabel#FileMeta {
    font-size: 9px;
    color: #667085;
}
QLabel#SubCardTitle {
    font-size: 11px;
    font-weight: 700;
    color: #162033;
}
QTableWidget#BlockTable, QTableWidget#AssetTable, QTableWidget#StructureTable,
QTableWidget#MetaTable, QTableWidget#ReferenceTable,
QTableWidget#AIReviewTable, QTableWidget#RecentTable {
    background: #ffffff;
    border: 1px solid #e4e9f1;
    border-radius: 8px;
    alternate-background-color: #fbfdff;
    selection-background-color: #eff4ff;
    selection-color: #162033;
    gridline-color: transparent;
}
QTableWidget#BlockTable QHeaderView::section,
QTableWidget#AssetTable QHeaderView::section,
QTableWidget#StructureTable QHeaderView::section,
QTableWidget#MetaTable QHeaderView::section,
QTableWidget#ReferenceTable QHeaderView::section,
QTableWidget#AIReviewTable QHeaderView::section,
QTableWidget#RecentTable QHeaderView::section {
    background: #f8fafc;
    color: #667085;
    border: 0;
    border-bottom: 1px solid #e4e9f1;
    padding: 6px 8px;
    font-size: 9px;
    font-weight: 700;
}
QTableWidget#BlockTable::item,
QTableWidget#AssetTable::item,
QTableWidget#StructureTable::item,
QTableWidget#MetaTable::item,
QTableWidget#ReferenceTable::item,
QTableWidget#AIReviewTable::item,
QTableWidget#RecentTable::item {
    padding: 3px 8px;
    border-bottom: 1px solid #f2f4f7;
    font-size: 10px;
}
QTreeWidget#SectionTree {
    background: #ffffff;
    border: 0;
    outline: 0;
    font-size: 10px;
}
QTreeWidget#SectionTree::item {
    padding: 4px 3px;
    border-radius: 4px;
    color: #344054;
}
QTreeWidget#SectionTree::item:hover {
    background: #f4f7fc;
}
QTreeWidget#SectionTree::item:selected {
    background: #eff4ff;
    color: #1d4ed8;
}
QLabel#MetaLabel {
    font-size: 9px;
    color: #475467;
    background: #f8fafc;
    border: 1px solid #e4e9f1;
    border-radius: 7px;
    padding: 5px 8px;
}
QComboBox#RoleCombo, QComboBox#LevelCombo {
    min-height: 21px;
    padding: 0 4px;
    font-size: 10px;
    border-radius: 5px;
}
QListWidget#AssetList {
    background: #ffffff;
    border: 0;
    outline: 0;
    font-size: 10px;
}
QListWidget#AssetList::item {
    padding: 7px 8px;
    border-radius: 6px;
    color: #344054;
    border-bottom: 1px solid #f2f4f7;
}
QListWidget#AssetList::item:selected {
    background: #eff4ff;
    color: #1d4ed8;
}
QLabel#FigurePreview {
    background: #f8fafc;
    border: 1px dashed #cbd5e1;
    border-radius: 9px;
    color: #98a2b3;
    font-size: 10px;
}
QLabel#EmptyEditor {
    background: #ffffff;
    color: #98a2b3;
    font-size: 11px;
    padding: 40px;
}
QTableWidget#TableEditor {
    background: #ffffff;
    border: 1px solid #e4e9f1;
    border-radius: 8px;
    gridline-color: #edf1f7;
    selection-background-color: #eff4ff;
    selection-color: #162033;
}
QTableWidget#TableEditor QHeaderView::section {
    background: #f8fafc;
    color: #667085;
    border: 0;
    border-bottom: 1px solid #e4e9f1;
    border-right: 1px solid #f2f4f7;
    padding: 5px 7px;
    font-size: 9px;
    font-weight: 700;
}
QTableWidget#TableEditor::item {
    padding: 4px 7px;
    font-size: 10px;
}
QComboBox#AnchorCombo {
    min-height: 25px;
    font-size: 10px;
}
QTextEdit#BuildLog {
    background: #0b1220;
    color: #d7e3f4;
    border: 1px solid #1e293b;
    border-radius: 8px;
    padding: 8px;
    selection-background-color: #1d4ed8;
}
QLabel#PdfPage {
    background: #ffffff;
    border: 1px solid #d7deea;
    padding: 10px;
    color: #98a2b3;
}
QScrollArea#PdfScroll {
    background: #e9eef6;
    border: 0;
}
QLabel#TemplateName {
    font-size: 13px;
    font-weight: 700;
    color: #162033;
}
QProgressBar {
    background: #e4e9f1;
    border: 0;
    border-radius: 1px;
}
QProgressBar::chunk {
    background: #2563eb;
    border-radius: 1px;
}
QScrollBar:vertical {
    background: transparent;
    width: 9px;
    margin: 2px;
}
QScrollBar::handle:vertical {
    background: #cbd5e1;
    min-height: 28px;
    border-radius: 4px;
}
QScrollBar::handle:vertical:hover {
    background: #94a3b8;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QScrollBar:horizontal {
    background: transparent;
    height: 9px;
}
QScrollBar::handle:horizontal {
    background: #cbd5e1;
    min-width: 28px;
    border-radius: 4px;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0;
}
QToolTip {
    background: #101828;
    color: #ffffff;
    border: 0;
    padding: 4px 7px;
    font-size: 9px;
}
"""


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    font = QFont("Microsoft YaHei UI", 9)
    app.setFont(font)
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(BG))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(INK))
    palette.setColor(QPalette.ColorRole.Base, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.Text, QColor(INK))
    palette.setColor(QPalette.ColorRole.Button, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(INK))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#dbeafe"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(INK))
    app.setPalette(palette)
    app.setStyleSheet(APP_QSS)
