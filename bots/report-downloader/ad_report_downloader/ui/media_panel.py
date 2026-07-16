"""
MediaPanel — checkbox list of media platforms with per-row status icons.

Emits settings_requested(media_code) when a "설정" button is clicked.
GFA 행 하단에 분석단위/기간단위/게재위치/오디언스 버튼 옵션 패널 표시.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from config_schema import MEDIA_LABELS, MEDIA_ORDER

# Status label text per status key
_STATUS_TEXT: dict[str, str] = {
    "idle":    "─",
    "running": "⏳ 실행 중",
    "success": "✓ 완료",
    "failed":  "✗ 실패",
    "skipped": "↷ 건너뜀",
}
_STATUS_COLOR: dict[str, str] = {
    "idle":    "#888",
    "running": "#F39C12",
    "success": "#27AE60",
    "failed":  "#E74C3C",
    "skipped": "#888",
}

_BTN_STYLE = """
    QPushButton {
        font-size: 11px;
        padding: 1px 8px;
        border: 1px solid #bbb;
        border-radius: 3px;
        background: #f5f5f5;
    }
    QPushButton:checked {
        background: #2980B9;
        color: white;
        font-weight: bold;
        border-color: #1a6699;
    }
    QPushButton:hover:!checked {
        background: #e0e8f0;
    }
"""


# ──────────────────────────────────────────────────────────────────────────────
# GFA 옵션 선택 위젯
# ──────────────────────────────────────────────────────────────────────────────
class GFAOptionsWidget(QWidget):
    """GFA 보고서 옵션(분석단위/기간단위/게재위치/오디언스)을 버튼으로 선택."""

    _OPTIONS: list[tuple[str, str, list[str]]] = [
        ("분석단위", "analysis_unit", ["광고 계정", "캠페인", "광고 그룹", "애셋 그룹", "광고 소재"]),
        ("기간단위", "period_unit",   ["전체", "일", "주", "월", "시간"]),
        ("게재위치", "placement",     ["전체", "매체 그룹", "매체 그룹 및 게재 위치"]),
        ("오디언스", "audience",      ["전체", "연령", "성별", "연령 및 성별", "기기", "기기 및 OS"]),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._btn_groups: dict[str, QButtonGroup] = {}
        self.setStyleSheet("background: #f8f9fa;")
        self._build_ui()

    def _build_ui(self) -> None:
        vbox = QVBoxLayout(self)
        vbox.setContentsMargins(28, 4, 8, 6)
        vbox.setSpacing(4)

        for label, key, options in self._OPTIONS:
            row = QHBoxLayout()
            row.setSpacing(4)

            lbl = QLabel(f"{label}:")
            lbl.setFixedWidth(55)
            lbl.setStyleSheet("font-size: 11px; color: #555; background: transparent;")
            row.addWidget(lbl)

            group = QButtonGroup(self)
            group.setExclusive(True)

            for i, opt in enumerate(options):
                btn = QPushButton(opt, self)
                btn.setCheckable(True)
                btn.setFixedHeight(24)
                btn.setStyleSheet(_BTN_STYLE)
                group.addButton(btn, i)
                row.addWidget(btn)

            row.addStretch()
            group.button(0).setChecked(True)
            self._btn_groups[key] = group

            vbox.addLayout(row)

    # ── Public API ─────────────────────────────────────────────────────────────

    def get_options(self) -> dict[str, str]:
        result = {}
        for _, key, options in self._OPTIONS:
            group = self._btn_groups[key]
            btn = group.checkedButton()
            result[key] = btn.text() if btn else options[0]
        return result

    def set_options(self, opts: dict) -> None:
        for _, key, options in self._OPTIONS:
            value = opts.get(key, options[0])
            group = self._btn_groups[key]
            matched = False
            for i, opt in enumerate(options):
                if opt == value:
                    group.button(i).setChecked(True)
                    matched = True
                    break
            if not matched:
                group.button(0).setChecked(True)

    def set_all_enabled(self, enabled: bool) -> None:
        for group in self._btn_groups.values():
            for btn in group.buttons():
                btn.setEnabled(enabled)


# ──────────────────────────────────────────────────────────────────────────────
# 메인 MediaPanel
# ──────────────────────────────────────────────────────────────────────────────
class MediaPanel(QGroupBox):
    settings_requested = Signal(str)  # media_code

    def __init__(self, parent=None):
        super().__init__("매체 선택", parent)
        self._checkboxes: dict[str, QCheckBox] = {}
        self._status_labels: dict[str, QLabel] = {}
        self._gfa_options: GFAOptionsWidget | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        grid = QGridLayout(self)
        grid.setColumnStretch(0, 1)

        for row, code in enumerate(MEDIA_ORDER):
            label = MEDIA_LABELS.get(code, code)

            cb = QCheckBox(label)
            self._checkboxes[code] = cb

            btn = QPushButton("설정")
            btn.setFixedWidth(50)
            btn.setObjectName(code)
            btn.clicked.connect(self._on_settings_clicked)

            status = QLabel(_STATUS_TEXT["idle"])
            status.setFixedWidth(90)
            status.setStyleSheet(f"color: {_STATUS_COLOR['idle']};")
            self._status_labels[code] = status

            grid.addWidget(cb,     row, 0)
            grid.addWidget(btn,    row, 1)
            grid.addWidget(status, row, 2)

        # GFA 옵션 패널 — GFA 행 바로 아래
        gfa_row = MEDIA_ORDER.index("gfa")
        self._gfa_options = GFAOptionsWidget()
        grid.addWidget(self._gfa_options, gfa_row + 1, 0, 1, 3)

        # GFA 체크박스 상태에 따라 옵션 패널 보이기/숨기기
        gfa_cb = self._checkboxes["gfa"]
        gfa_cb.stateChanged.connect(self._on_gfa_checked)
        self._gfa_options.setVisible(gfa_cb.isChecked())

    # ── Public API ────────────────────────────────────────────────────────────

    def get_enabled_media(self) -> list[str]:
        return [code for code, cb in self._checkboxes.items() if cb.isChecked()]

    def load_from_config(self, config: dict) -> None:
        media_cfg = config.get("media", {})
        for code, cb in self._checkboxes.items():
            cb.setChecked(media_cfg.get(code, {}).get("enabled", False))

        # GFA 옵션: 첫 번째 계정 기준으로 로드
        if self._gfa_options:
            gfa_accounts = media_cfg.get("gfa", {}).get("accounts", [{}])
            first_acct = gfa_accounts[0] if gfa_accounts else {}
            self._gfa_options.set_options(first_acct)
            self._gfa_options.setVisible(self._checkboxes["gfa"].isChecked())

    def save_to_config(self, config: dict) -> None:
        for code, cb in self._checkboxes.items():
            config.setdefault("media", {}).setdefault(code, {})["enabled"] = cb.isChecked()

        # GFA 옵션 → 모든 GFA 계정에 반영
        if self._gfa_options:
            opts = self._gfa_options.get_options()
            gfa_cfg = config.setdefault("media", {}).setdefault("gfa", {})
            accounts = gfa_cfg.get("accounts", [{}])
            for acct in accounts:
                acct.update(opts)
            gfa_cfg["accounts"] = accounts

    def set_media_status(self, media_code: str, status: str) -> None:
        lbl = self._status_labels.get(media_code)
        if lbl:
            lbl.setText(_STATUS_TEXT.get(status, status))
            lbl.setStyleSheet(f"color: {_STATUS_COLOR.get(status, '#888')};")

    def reset_statuses(self) -> None:
        for code in MEDIA_ORDER:
            self.set_media_status(code, "idle")

    def set_enabled(self, enabled: bool) -> None:
        """Lock/unlock checkboxes during a run."""
        for cb in self._checkboxes.values():
            cb.setEnabled(enabled)
        if self._gfa_options:
            self._gfa_options.set_all_enabled(enabled)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _on_settings_clicked(self) -> None:
        code = self.sender().objectName()
        self.settings_requested.emit(code)

    def _on_gfa_checked(self, state: int) -> None:
        if self._gfa_options:
            self._gfa_options.setVisible(bool(state))
