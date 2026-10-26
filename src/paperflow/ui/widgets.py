from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from paperflow.core.env import EnvItem, EnvStatus


def repolish(widget: QWidget) -> None:
    style = widget.style()
    if style is not None:
        style.unpolish(widget)
        style.polish(widget)
    widget.update()


class Card(QFrame):
    """White rounded panel with an optional header and a body layout."""

    def __init__(
        self,
        title: str = "",
        subtitle: str = "",
        *,
        right_widget: QWidget | None = None,
        body_margins: tuple[int, int, int, int] = (16, 14, 16, 15),
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(0, 0, 0, 0)
        self._outer.setSpacing(0)

        if title:
            header = QFrame(self)
            header.setObjectName("CardHeader")
            header_layout = QHBoxLayout(header)
            header_layout.setContentsMargins(16, 11, 16, 10)
            header_layout.setSpacing(8)
            text_layout = QVBoxLayout()
            text_layout.setContentsMargins(0, 0, 0, 0)
            text_layout.setSpacing(1)
            title_label = QLabel(title)
            title_label.setObjectName("CardTitle")
            text_layout.addWidget(title_label)
            if subtitle:
                sub = QLabel(subtitle)
                sub.setObjectName("CardSub")
                sub.setWordWrap(True)
                text_layout.addWidget(sub)
            header_layout.addLayout(text_layout, 1)
            if right_widget is not None:
                header_layout.addWidget(right_widget, 0, Qt.AlignmentFlag.AlignVCenter)
            self._outer.addWidget(header)

        body = QWidget(self)
        self.body = QVBoxLayout(body)
        self.body.setContentsMargins(*body_margins)
        self.body.setSpacing(10)
        self._outer.addWidget(body, 1)


class Banner(QFrame):
    def __init__(
        self,
        title: str = "",
        text: str = "",
        state: str = "info",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("Banner")
        self.setProperty("state", state)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(8)
        self.icon = QLabel()
        self.icon.setFixedWidth(14)
        self.icon.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.addWidget(self.icon)
        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(1)
        self.title = QLabel(title)
        self.title.setObjectName("BannerTitle")
        self.text = QLabel(text)
        self.text.setObjectName("BannerText")
        self.text.setWordWrap(True)
        text_layout.addWidget(self.title)
        text_layout.addWidget(self.text)
        layout.addLayout(text_layout, 1)
        self.set_state(state, title, text)

    def set_state(self, state: str, title: str, text: str) -> None:
        self.setProperty("state", state)
        self.title.setText(title)
        self.text.setText(text)
        self.text.setVisible(bool(text))
        icons = {"ok": "✓", "warn": "!", "error": "×", "info": "i"}
        colors = {
            "ok": "#067647",
            "warn": "#b54708",
            "error": "#b42318",
            "info": "#2563eb",
        }
        self.icon.setText(icons.get(state, "i"))
        self.icon.setStyleSheet(
            f"color: {colors.get(state, '#2563eb')}; font-weight: 700; font-size: 12px;"
        )
        repolish(self)


class StatusRow(QFrame):
    def __init__(
        self,
        item: EnvItem | None = None,
        *,
        label: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._label = label
        self.setObjectName("StatusRow")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 7, 0, 7)
        layout.setSpacing(8)
        self.dot = QLabel("•")
        self.dot.setObjectName("StatusDot")
        self.dot.setFixedWidth(16)
        self.dot.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.addWidget(self.dot)
        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(1)
        self.title = QLabel("")
        self.title.setObjectName("StatusTitle")
        self.detail = QLabel("")
        self.detail.setObjectName("StatusDetail")
        self.detail.setWordWrap(True)
        text_layout.addWidget(self.title)
        text_layout.addWidget(self.detail)
        layout.addLayout(text_layout, 1)
        self.right = QLabel("")
        self.right.setObjectName("StatusRight")
        self.right.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self.right.setMinimumWidth(64)
        layout.addWidget(self.right)
        if item is not None:
            self.set_item(item)
        else:
            self.set_placeholder()

    def set_placeholder(self) -> None:
        self.dot.setText("•")
        self.dot.setStyleSheet("color: #98a2b3;")
        self.title.setText(self._label or "等待检测")
        self.detail.setText("等待检测")
        self.right.setText("—")
        self.right.setStyleSheet("color: #98a2b3;")

    def set_item(self, item: EnvItem) -> None:
        self.title.setText(item.label)
        self.detail.setText(item.detail)
        status_map = {
            EnvStatus.OK: ("✓", "#067647", "可用"),
            EnvStatus.WARN: ("!", "#b54708", "需注意"),
            EnvStatus.MISSING: ("×", "#b42318", "缺失"),
            EnvStatus.SKIPPED: ("–", "#98a2b3", "跳过"),
        }
        symbol, color, text = status_map.get(item.status, ("•", "#98a2b3", "—"))
        self.dot.setText(symbol)
        self.dot.setStyleSheet(f"color: {color}; font-weight: 700; font-size: 13px;")
        self.right.setText(text)
        self.right.setStyleSheet(f"color: {color}; font-weight: 600;")
        if item.path:
            self.setToolTip(item.path)


class NavStep(QFrame):
    clicked = Signal(str)

    def __init__(
        self,
        key: str,
        number: int,
        title: str,
        hint: str,
        *,
        available: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.key = key
        self._available = available
        self.setObjectName("NavStep")
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setCursor(
            Qt.CursorShape.PointingHandCursor
            if available
            else Qt.CursorShape.ForbiddenCursor
        )
        self.setFixedHeight(46)
        self.setProperty("available", "true" if available else "false")
        self.setProperty("active", "false")
        self.setEnabled(available)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(7, 5, 8, 5)
        layout.setSpacing(9)
        self.num = QLabel(str(number))
        self.num.setObjectName("StepNum")
        self.num.setFixedSize(25, 25)
        self.num.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.num)
        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(0)
        self.title = QLabel(title)
        self.title.setObjectName("StepTitle")
        self.hint = QLabel(hint)
        self.hint.setObjectName("StepHint")
        text_layout.addWidget(self.title)
        text_layout.addWidget(self.hint)
        layout.addLayout(text_layout, 1)

    def set_active(self, active: bool) -> None:
        self.setProperty("active", "true" if active else "false")
        repolish(self)

    def set_available(self, available: bool) -> None:
        self._available = available
        self.setEnabled(available)
        self.setCursor(
            Qt.CursorShape.PointingHandCursor
            if available
            else Qt.CursorShape.ForbiddenCursor
        )
        self.setProperty("available", "true" if available else "false")
        if available:
            self.setToolTip("")
        repolish(self)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 (Qt API)
        if self._available and event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.key)
        super().mousePressEvent(event)


class Divider(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(1)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setStyleSheet("background: #e4e9f1; border: 0;")


def make_button(
    text: str,
    *,
    kind: str = "default",
    tooltip: str = "",
) -> QPushButton:
    button = QPushButton(text)
    if kind == "primary":
        button.setObjectName("PrimaryButton")
    elif kind == "soft":
        button.setObjectName("SoftButton")
    elif kind == "ghost":
        button.setObjectName("GhostButton")
    elif kind == "link":
        button.setObjectName("LinkButton")
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    if tooltip:
        button.setToolTip(tooltip)
    button.setMinimumHeight(28)
    return button


def field_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("FieldLabel")
    return label


def hint_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("Hint")
    label.setWordWrap(True)
    return label


class KpiCard(QFrame):
    def __init__(self, label: str, value: str = "—", accent: str = "#2563eb") -> None:
        super().__init__()
        self.setObjectName("KpiCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(1)
        self.value = QLabel(value)
        self.value.setObjectName("KpiValue")
        self.value.setStyleSheet(f"color:{accent};")
        caption = QLabel(label)
        caption.setObjectName("KpiLabel")
        layout.addWidget(self.value)
        layout.addWidget(caption)

    def set_value(self, value: int | str) -> None:
        self.value.setText(str(value))


def make_chip(
    text: str,
    *,
    fg: str = "#2563eb",
    bg: str = "#eff4ff",
    border: str = "#dbe7ff",
) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet(
        f"color:{fg}; background:{bg}; border:1px solid {border}; "
        "border-radius:8px; padding:2px 7px; font-size:9px; font-weight:700;"
    )
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return label