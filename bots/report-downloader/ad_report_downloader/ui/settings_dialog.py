"""
SettingsDialog — 전역 설정(Chrome 프로필, 저장 경로) +
                 매체별 설정(계정 목록: account_name / account_id / report_name,
                             다운로드 타임아웃)

저장 버튼 클릭 시에만 config에 반영 (PRD §5.3.3).
"""
from __future__ import annotations
import copy
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from config_schema import (
    MEDIA_LABELS,
    MEDIA_ORDER,
    read_chrome_profiles,
    validate_chrome_settings,
    validate_save_path,
)


# ──────────────────────────────────────────────────────────────────────────────
# 계정 테이블 위젯 (매체별)
# ──────────────────────────────────────────────────────────────────────────────
class AccountsTableWidget(QWidget):
    """
    계정 목록을 편집 가능한 테이블로 표시.
    컬럼: 계정명 | 계정 ID | 보고서명
    """

    HEADERS = ["계정명", "계정 ID", "보고서명"]
    COL_NAME   = 0
    COL_ID     = 1
    COL_REPORT = 2

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # 테이블
        self._table = QTableWidget(0, 3)
        self._table.setHorizontalHeaderLabels(self.HEADERS)
        self._table.horizontalHeader().setSectionResizeMode(
            self.COL_REPORT, QHeaderView.ResizeMode.Stretch
        )
        self._table.horizontalHeader().setSectionResizeMode(
            self.COL_NAME, QHeaderView.ResizeMode.ResizeToContents
        )
        self._table.horizontalHeader().setSectionResizeMode(
            self.COL_ID, QHeaderView.ResizeMode.ResizeToContents
        )
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setMinimumHeight(80)
        self._table.setMaximumHeight(160)
        layout.addWidget(self._table)

        # 버튼 행
        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 0, 0, 0)
        add_btn = QPushButton("+ 계정 추가")
        add_btn.setFixedWidth(90)
        add_btn.clicked.connect(self._add_row)
        del_btn = QPushButton("− 삭제")
        del_btn.setFixedWidth(60)
        del_btn.clicked.connect(self._del_row)
        btn_row.addWidget(add_btn)
        btn_row.addWidget(del_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

    # ── Public API ────────────────────────────────────────────────────────────

    def load_accounts(self, accounts: list[dict]) -> None:
        """config의 accounts 리스트를 테이블에 채운다."""
        self._table.setRowCount(0)
        for acct in accounts:
            self._append_row(
                acct.get("account_name", ""),
                acct.get("account_id", ""),
                acct.get("report_name", ""),
            )
        if self._table.rowCount() == 0:
            self._add_row()

    def get_accounts(self) -> list[dict]:
        """테이블 내용을 accounts 리스트로 반환. 빈 행은 제외."""
        result = []
        for row in range(self._table.rowCount()):
            name   = self._cell(row, self.COL_NAME)
            acc_id = self._cell(row, self.COL_ID)
            report = self._cell(row, self.COL_REPORT)
            # account_name 또는 account_id 중 하나라도 있으면 포함
            if name or acc_id or report:
                result.append({
                    "account_name": name,
                    "account_id":   acc_id,
                    "report_name":  report,
                })
        # 하나도 없으면 빈 기본 행 1개 반환
        if not result:
            result = [{"account_name": "", "account_id": "", "report_name": ""}]
        return result

    # ── Private helpers ───────────────────────────────────────────────────────

    def _append_row(self, name: str, acc_id: str, report: str) -> None:
        row = self._table.rowCount()
        self._table.insertRow(row)
        self._table.setItem(row, self.COL_NAME,   QTableWidgetItem(name))
        self._table.setItem(row, self.COL_ID,     QTableWidgetItem(acc_id))
        self._table.setItem(row, self.COL_REPORT, QTableWidgetItem(report))

    def _add_row(self) -> None:
        self._append_row("", "", "")
        # 새 행 선택 + 첫 셀 편집 시작
        new_row = self._table.rowCount() - 1
        self._table.setCurrentCell(new_row, self.COL_NAME)
        self._table.editItem(self._table.item(new_row, self.COL_NAME))

    def _del_row(self) -> None:
        rows = sorted(
            {idx.row() for idx in self._table.selectedIndexes()},
            reverse=True,
        )
        for row in rows:
            self._table.removeRow(row)
        if self._table.rowCount() == 0:
            self._add_row()

    def _cell(self, row: int, col: int) -> str:
        item = self._table.item(row, col)
        return item.text().strip() if item else ""


# ──────────────────────────────────────────────────────────────────────────────
# 설정 다이얼로그
# ──────────────────────────────────────────────────────────────────────────────
class SettingsDialog(QDialog):
    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("설정")
        self.setMinimumWidth(560)
        self._config = config
        self._build_ui()
        self._load()

    # ── UI Construction ───────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        tabs = QTabWidget()
        tabs.addTab(self._build_chrome_tab(), "Chrome 설정")
        tabs.addTab(self._build_media_tab(),  "매체별 설정")
        layout.addWidget(tabs)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save |
            QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self._on_save)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _build_chrome_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)

        # User Data Dir
        udd_row = QHBoxLayout()
        self._udd_edit = QLineEdit()
        self._udd_edit.setPlaceholderText(
            r"예: C:\Users\User\AppData\Local\Google\Chrome\User Data"
        )
        udd_btn = QPushButton("찾아보기")
        udd_btn.clicked.connect(self._browse_udd)
        udd_row.addWidget(self._udd_edit)
        udd_row.addWidget(udd_btn)
        form.addRow("Chrome User Data 경로:", udd_row)

        # Profile Directory
        profile_row = QHBoxLayout()
        self._profile_combo = QComboBox()
        self._profile_combo.setEditable(True)
        self._profile_combo.setPlaceholderText("예: Profile 3")
        refresh_btn = QPushButton("목록 새로고침")
        refresh_btn.clicked.connect(self._refresh_profiles)
        profile_row.addWidget(self._profile_combo, 1)
        profile_row.addWidget(refresh_btn)
        form.addRow("프로필 폴더:", profile_row)

        hint = QLabel(
            "💡 chrome://version 에서 '프로필 경로' 확인 후\n"
            "   마지막 폴더명(예: Profile 3)을 입력하세요."
        )
        hint.setStyleSheet("color: #666; font-size: 10px;")
        form.addRow("", hint)

        save_row = QHBoxLayout()
        self._save_edit = QLineEdit()
        save_btn = QPushButton("찾아보기")
        save_btn.clicked.connect(self._browse_save)
        save_row.addWidget(self._save_edit)
        save_row.addWidget(save_btn)
        form.addRow("보고서 저장 경로:", save_row)

        # Retry count
        self._retry_spin = QSpinBox()
        self._retry_spin.setRange(1, 5)
        self._retry_spin.setValue(2)
        form.addRow("최대 재시도 횟수:", self._retry_spin)

        return w

    def _build_media_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        vbox = QVBoxLayout(container)

        self._media_rows: dict[str, dict] = {}
        for code in MEDIA_ORDER:
            label = MEDIA_LABELS.get(code, code)
            box = QGroupBox(label)
            form = QFormLayout(box)

            # 타임아웃 (매체 레벨)
            timeout_spin = QSpinBox()
            timeout_spin.setRange(30, 600)
            timeout_spin.setSuffix(" 초")
            form.addRow("다운로드 타임아웃:", timeout_spin)

            # 계정 목록 테이블
            acct_hint = QLabel(
                "계정명: 파일명에 포함될 라벨 (자유 입력)\n"
                "계정 ID: URL에서 추출한 광고 계정 번호\n"
                "보고서명: 보고서 화면에서 클릭할 저장된 보고서 이름"
            )
            acct_hint.setStyleSheet("color: #666; font-size: 10px;")
            form.addRow("", acct_hint)

            accounts_table = AccountsTableWidget()
            form.addRow("계정 목록:", accounts_table)

            vbox.addWidget(box)
            self._media_rows[code] = {
                "timeout_sec":    timeout_spin,
                "accounts_table": accounts_table,
            }

        vbox.addStretch()
        scroll.setWidget(container)
        return scroll

    # ── Load / Save ───────────────────────────────────────────────────────────

    def _load(self) -> None:
        chrome = self._config.get("chrome", {})
        self._udd_edit.setText(chrome.get("user_data_dir", ""))
        self._profile_combo.setCurrentText(chrome.get("profile_directory", ""))
        self._save_edit.setText(self._config.get("save_root_path", ""))
        self._retry_spin.setValue(self._config.get("retry", {}).get("max_attempts", 2))

        for code, row in self._media_rows.items():
            mcfg = self._config.get("media", {}).get(code, {})
            row["timeout_sec"].setValue(mcfg.get("timeout_sec", 90))

            # accounts: 신 형식 우선, 구 형식(account_id 단일) 자동 변환
            accounts = mcfg.get("accounts")
            if not accounts:
                accounts = [{
                    "account_name": "",
                    "account_id":   mcfg.get("account_id", ""),
                    "report_name":  mcfg.get("report_name", ""),
                }]
            row["accounts_table"].load_accounts(accounts)

        self._refresh_profiles()

    def _on_save(self) -> None:
        udd       = self._udd_edit.text().strip()
        profile   = self.get_profile_directory()
        save_path = self._save_edit.text().strip()

        if udd or profile:
            ok, err = validate_chrome_settings(udd, profile)
            if not ok:
                QMessageBox.warning(self, "Chrome 설정 오류", err)
                return

        if save_path:
            ok, err = validate_save_path(save_path)
            if not ok:
                QMessageBox.warning(self, "저장 경로 오류", err)
                return

        # config 업데이트
        self._config.setdefault("chrome", {})["user_data_dir"]    = udd
        self._config.setdefault("chrome", {})["profile_directory"] = profile
        self._config["save_root_path"] = save_path
        self._config.setdefault("retry", {})["max_attempts"] = self._retry_spin.value()

        for code, row in self._media_rows.items():
            mcfg = self._config.setdefault("media", {}).setdefault(code, {})
            mcfg["timeout_sec"] = row["timeout_sec"].value()
            new_accounts = row["accounts_table"].get_accounts()

            if code == "gfa":
                # GFA: 보고서명 필드 = column_preset
                # analysis_unit/period_unit/placement/audience 는 MediaPanel 버튼에서 관리하므로 보존
                existing = mcfg.get("accounts", [])
                for i, acct in enumerate(new_accounts):
                    # report_name → column_preset 연동
                    acct["column_preset"] = acct.get("report_name", "")
                    # 기존 GFA 전용 필드 보존
                    if i < len(existing):
                        for field in ("analysis_unit", "period_unit", "placement", "audience"):
                            if field in existing[i]:
                                acct.setdefault(field, existing[i][field])

            mcfg["accounts"] = new_accounts
            # 구 형식 키 제거 (있으면)
            mcfg.pop("account_id",  None)
            mcfg.pop("report_name", None)

        # ── 활성 브랜드에도 동기화 (핵심 버그 수정) ─────────────────────────────
        # settings_dialog는 top-level cfg['media']를 수정하지만,
        # 다음 load() 시 cfg['brands'][active]['media']가 top-level을 덮어씀.
        # 저장 전에 active brand의 media도 함께 업데이트해야 한다.
        active_brand = self._config.get("active_brand", "")
        if active_brand:
            for brand in self._config.get("brands", []):
                if brand["name"] == active_brand:
                    brand["media"] = copy.deepcopy(self._config["media"])
                    break

        from utils.config_manager import save
        save(self._config)
        self.accept()

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _browse_udd(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Chrome User Data 폴더 선택")
        if path:
            self._udd_edit.setText(path)
            self._refresh_profiles()

    def _browse_save(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "보고서 저장 폴더 선택")
        if path:
            self._save_edit.setText(path)

    def _refresh_profiles(self) -> None:
        udd = self._udd_edit.text().strip()
        if not udd:
            return
        profiles = read_chrome_profiles(udd)
        current = self._profile_combo.currentText()
        self._profile_combo.clear()
        for display_name, folder_name in profiles.items():
            self._profile_combo.addItem(f"{display_name} ({folder_name})", folder_name)
        if current:
            idx = self._profile_combo.findText(current)
            if idx >= 0:
                self._profile_combo.setCurrentIndex(idx)

    def get_profile_directory(self) -> str:
        data = self._profile_combo.currentData()
        return data if data else self._profile_combo.currentText().strip()
