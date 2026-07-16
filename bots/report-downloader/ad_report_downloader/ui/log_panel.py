"""
LogPanel — real-time log display widget.

Receives (timestamp, media_code, message) tuples via append_log()
and renders them with light color coding.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

# Color mapping per media code (soft pastels that work on both light/dark bg)
_MEDIA_COLORS: dict[str, str] = {
    "naver":  "#1ec800",
    "google": "#4285F4",
    "google_sa": "#4285F4",
    "google_da": "#34A853",
    "meta":   "#1877F2",
    "kakao":  "#FEE500",
    "adn":    "#FF6B35",
    "mobion": "#9B59B6",
    "x":      "#14171A",
    "SYSTEM": "#E74C3C",
}
_DEFAULT_COLOR = "#555555"


class LogPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # Toolbar
        toolbar = QHBoxLayout()
        self._clear_btn = QPushButton("로그 지우기")
        self._clear_btn.setFixedWidth(90)
        self._clear_btn.clicked.connect(self.clear)
        toolbar.addStretch()
        toolbar.addWidget(self._clear_btn)
        layout.addLayout(toolbar)

        # Log area
        self._text = QPlainTextEdit()
        self._text.setReadOnly(True)
        self._text.setMaximumBlockCount(5000)
        self._text.setFont(self._monospace_font())
        layout.addWidget(self._text)

    def append_log(self, timestamp: str, media: str, message: str) -> None:
        """Append a formatted log line. Safe to call from any thread via Signal."""
        color = _MEDIA_COLORS.get(media, _DEFAULT_COLOR)
        line = f"[{timestamp}] [{media:8s}] {message}"

        cursor = self._text.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)

        fmt = QTextCharFormat()
        # Error/warning lines get a different color
        if message.startswith("✗") or "실패" in message:
            fmt.setForeground(QColor("#E74C3C"))
        elif message.startswith("⚠") or "경고" in message:
            fmt.setForeground(QColor("#F39C12"))
        elif message.startswith("✓") or "완료" in message:
            fmt.setForeground(QColor("#27AE60"))
        else:
            fmt.setForeground(QColor(color))

        cursor.insertText(line + "\n", fmt)
        self._text.setTextCursor(cursor)
        self._text.ensureCursorVisible()

    def clear(self) -> None:
        self._text.clear()

    @staticmethod
    def _monospace_font():
        from PySide6.QtGui import QFont
        font = QFont("Consolas")
        if not font.exactMatch():
            font = QFont("Courier New")
        font.setPointSize(9)
        return font
