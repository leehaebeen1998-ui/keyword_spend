"""
MainWindow — the top-level PySide6 window.

Layout (top → bottom):
  1. Warning banner  (visible only during a run)
  2. Period + save-path controls
  3. MediaPanel      (checkboxes + status)
  4. Control bar     (Run / Stop / Settings + progress bar)
  5. LogPanel        (real-time log)
"""
from __future__ import annotations
import copy
from datetime import date

from PySide6.QtCore import Qt, QDate
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.orchestrator import OrchestratorWorker, RunParams
from ui.log_panel import LogPanel
from ui.media_panel import MediaPanel
from ui.settings_dialog import SettingsDialog
from utils.config_manager import load as load_config, save as save_config


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("광고 매체 보고서 자동 다운로드")
        self.setMinimumSize(760, 680)

        self._config = load_config()
        self._worker: OrchestratorWorker | None = None

        self._build_ui()
        self._load_config_to_ui()

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        vbox = QVBoxLayout(root)
        vbox.setSpacing(8)
        vbox.setContentsMargins(12, 12, 12, 12)

        # 1. Warning banner
        self._banner = QLabel(
            "⚠  자동화 실행 중 — 이 시간 동안 자동화 Chrome 창을 직접 조작하지 마세요"
        )
        self._banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._banner.setStyleSheet(
            "background:#F39C12; color:white; font-weight:bold; padding:6px; border-radius:4px;"
        )
        self._banner.hide()
        vbox.addWidget(self._banner)

        # 2. Period + save path
        vbox.addWidget(self._build_period_box())

        # 3. Media panel
        self._media_panel = MediaPanel()
        self._media_panel.settings_requested.connect(self._open_media_settings)
        vbox.addWidget(self._media_panel)

        # 4. Control bar
        vbox.addWidget(self._build_control_bar())

        # 5. Log panel
        self._log_panel = LogPanel()
        vbox.addWidget(self._log_panel, stretch=1)

    def _build_period_box(self) -> QGroupBox:
        box = QGroupBox("보고서 기간 및 저장 경로")
        form = QVBoxLayout(box)

        # Date row
        date_row = QHBoxLayout()
        date_row.addWidget(QLabel("시작일:"))
        self._start_date = QDateEdit(calendarPopup=True)
        self._start_date.setDisplayFormat("yyyy-MM-dd")
        date_row.addWidget(self._start_date)
        date_row.addSpacing(12)
        date_row.addWidget(QLabel("종료일:"))
        self._end_date = QDateEdit(calendarPopup=True)
        self._end_date.setDisplayFormat("yyyy-MM-dd")
        date_row.addWidget(self._end_date)
        date_row.addStretch()
        form.addLayout(date_row)

        # Brand row
        brand_row = QHBoxLayout()
        brand_row.addWidget(QLabel("브랜드:"))
        self._brand_combo = QComboBox()
        self._brand_combo.setMinimumWidth(180)
        self._brand_combo.currentTextChanged.connect(self._on_brand_changed)
        brand_row.addWidget(self._brand_combo)
        add_brand_btn = QPushButton("+ 추가")
        add_brand_btn.setFixedWidth(60)
        add_brand_btn.clicked.connect(self._on_add_brand)
        del_brand_btn = QPushButton("삭제")
        del_brand_btn.setFixedWidth(50)
        del_brand_btn.clicked.connect(self._on_delete_brand)
        brand_row.addWidget(add_brand_btn)
        brand_row.addWidget(del_brand_btn)
        brand_row.addStretch()
        form.addLayout(brand_row)

        # Save path row
        path_row = QHBoxLayout()
        path_row.addWidget(QLabel("저장 경로:"))
        self._save_path_edit = QLineEdit()
        self._save_path_edit.setPlaceholderText("보고서를 저장할 폴더를 선택하세요")
        browse_btn = QPushButton("찾아보기")
        browse_btn.clicked.connect(self._browse_save_path)
        path_row.addWidget(self._save_path_edit, stretch=1)
        path_row.addWidget(browse_btn)
        form.addLayout(path_row)

        return box

    def _build_control_bar(self) -> QWidget:
        bar = QWidget()
        hbox = QHBoxLayout(bar)
        hbox.setContentsMargins(0, 0, 0, 0)

        self._run_btn = QPushButton("▶  실행")
        self._run_btn.setFixedHeight(36)
        self._run_btn.setStyleSheet("font-weight:bold; background:#27AE60; color:white;")
        self._run_btn.clicked.connect(self._on_run)

        self._stop_btn = QPushButton("■  중지")
        self._stop_btn.setFixedHeight(36)
        self._stop_btn.setStyleSheet("font-weight:bold; background:#E74C3C; color:white;")
        self._stop_btn.setEnabled(False)
        self._stop_btn.clicked.connect(self._on_stop)

        settings_btn = QPushButton("⚙  설정")
        settings_btn.setFixedHeight(36)
        settings_btn.clicked.connect(self._open_global_settings)

        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setTextVisible(True)
        self._progress.setFormat("%v / %m 매체")
        self._progress.hide()

        hbox.addWidget(self._run_btn)
        hbox.addWidget(self._stop_btn)
        hbox.addWidget(settings_btn)
        hbox.addStretch()
        hbox.addWidget(self._progress)

        return bar

    # ── Config ────────────────────────────────────────────────────────────────

    def _load_config_to_ui(self) -> None:
        cfg = self._config

        # Dates: default to yesterday
        yesterday = date.today().replace(day=date.today().day - 1) if date.today().day > 1 \
                    else date.today()
        start_str = cfg.get("last_run_period", {}).get("start", "")
        end_str   = cfg.get("last_run_period", {}).get("end", "")

        self._start_date.setDate(
            QDate.fromString(start_str, "yyyy-MM-dd") if start_str
            else QDate(yesterday.year, yesterday.month, yesterday.day)
        )
        self._end_date.setDate(
            QDate.fromString(end_str, "yyyy-MM-dd") if end_str
            else QDate(yesterday.year, yesterday.month, yesterday.day)
        )
        self._save_path_edit.setText(cfg.get("save_root_path", ""))

        # 브랜드 콤보박스 채우기
        brands = cfg.get("brands", [])
        active = cfg.get("active_brand", "")
        self._brand_combo.blockSignals(True)
        self._brand_combo.clear()
        for b in brands:
            self._brand_combo.addItem(b["name"])
        if active:
            idx = self._brand_combo.findText(active)
            if idx >= 0:
                self._brand_combo.setCurrentIndex(idx)
        self._brand_combo.blockSignals(False)

        # blockSignals로 인해 _on_brand_changed가 호출되지 않았으므로
        # active brand의 media를 config에 직접 반영
        if active:
            for b in cfg.get("brands", []):
                if b["name"] == active:
                    import copy as _copy
                    cfg["media"] = _copy.deepcopy(b["media"])
                    break

        self._media_panel.load_from_config(cfg)

    def _save_ui_to_config(self) -> None:
        self._config["save_root_path"] = self._save_path_edit.text().strip()
        active_brand = self._brand_combo.currentText()
        self._config["active_brand"] = active_brand
        self._config["brand_name"] = active_brand
        self._config.setdefault("last_run_period", {}).update({
            "start": self._start_date.date().toString("yyyy-MM-dd"),
            "end":   self._end_date.date().toString("yyyy-MM-dd"),
        })
        self._media_panel.save_to_config(self._config)
        for b in self._config.get("brands", []):
            if b["name"] == active_brand:
                b["media"] = copy.deepcopy(self._config.get("media", {}))
                break
        save_config(self._config)

    # ── Run / Stop ────────────────────────────────────────────────────────────

    def _on_run(self) -> None:
        enabled = self._media_panel.get_enabled_media()
        if not enabled:
            QMessageBox.warning(self, "선택 없음", "하나 이상의 매체를 선택해주세요.")
            return

        start = self._start_date.date().toPython()
        end   = self._end_date.date().toPython()
        if start > end:
            QMessageBox.warning(self, "날짜 오류", "시작일이 종료일보다 늦습니다.")
            return

        self._save_ui_to_config()

        # ADN이 선택된 경우 keyring에서 비밀번호 로드 (로그인.bat에서 사전 저장 필요)
        if "adn" in enabled:
            login_id = self._config.get("media", {}).get("adn", {}).get("login_id", "giomglobal")
            pw = self._get_adn_password(login_id)
            if pw:
                self._config["_adn_password_runtime"] = pw
            # 비밀번호 없어도 실행은 계속 (adn.py에서 keyring 재시도)

        # 모비온이 선택된 경우 keyring에서 계정별 비밀번호 로드
        mobon_medias = [m for m in enabled if m.startswith("mobion")]
        if mobon_medias:
            self._config["_mobon_passwords_runtime"] = self._get_mobon_passwords(mobon_medias)

        # Determine run mode (mock when Chrome settings not configured)
        chrome = self._config.get("chrome", {})
        use_mock = not (chrome.get("user_data_dir") and chrome.get("profile_directory"))
        if use_mock:
            self._log_panel.append_log("--:--:--", "SYSTEM", "Chrome 미설정 — 테스트 모드로 실행")

        params = RunParams(
            start_date=start,
            end_date=end,
            enabled_media=enabled,
            config=self._config,
            use_mock=use_mock,
        )

        self._media_panel.reset_statuses()
        self._start_run_ui(len(enabled))

        self._worker = OrchestratorWorker(params)
        self._worker.log_message.connect(self._log_panel.append_log)
        self._worker.media_status_changed.connect(self._media_panel.set_media_status)
        self._worker.progress_updated.connect(self._on_progress)
        self._worker.run_finished.connect(self._on_finished)
        self._worker.login_required.connect(self._on_login_required)
        self._worker.start()

    def _on_stop(self) -> None:
        if self._worker and self._worker.isRunning():
            self._log_panel.append_log("--:--:--", "SYSTEM", "중지 요청 — 현재 매체 완료 후 종료합니다")
            self._worker.request_stop()
            self._stop_btn.setEnabled(False)

    def _on_progress(self, completed: int, total: int) -> None:
        self._progress.setMaximum(total)
        self._progress.setValue(completed)

    def _on_finished(self, summary: dict) -> None:
        # 메모리에서 비밀번호 즉시 삭제
        self._config.pop("_adn_password_runtime", None)
        self._config.pop("_mobon_passwords_runtime", None)
        self._end_run_ui()
        success = [k for k, v in summary.items() if v == "success"]
        failed  = [k for k, v in summary.items() if v == "failed"]
        skipped = [k for k, v in summary.items() if v == "skipped"]

        lines = [
            f"✓ 성공 ({len(success)}): {', '.join(success)}" if success else None,
            f"✗ 실패 ({len(failed)}): {', '.join(failed)}"   if failed  else None,
            f"↷ 건너뜀 ({len(skipped)}): {', '.join(skipped)}" if skipped else None,
        ]
        msg = "\n".join(l for l in lines if l)
        self._log_panel.append_log("--:--:--", "SYSTEM", "══ 실행 요약 ══")
        for l in (l for l in lines if l):
            self._log_panel.append_log("--:--:--", "SYSTEM", l)

        if failed:
            QMessageBox.warning(self, "일부 실패", f"다음 매체 다운로드 실패:\n{', '.join(failed)}")

    def _on_login_required(self, media_code: str) -> None:
        self._log_panel.append_log(
            "--:--:--", media_code,
            "⚠ 로그인 필요 — 해당 매체의 Chrome 프로필에 수동으로 재로그인해주세요"
        )

    # ── UI state helpers ──────────────────────────────────────────────────────

    def _start_run_ui(self, total: int) -> None:
        self._run_btn.setEnabled(False)
        self._stop_btn.setEnabled(True)
        self._media_panel.set_enabled(False)
        self._progress.setMaximum(total)
        self._progress.setValue(0)
        self._progress.show()
        self._banner.show()

    def _end_run_ui(self) -> None:
        self._run_btn.setEnabled(True)
        self._stop_btn.setEnabled(False)
        self._media_panel.set_enabled(True)
        self._banner.hide()

    # ── ADN / 모비온 비밀번호 (Windows 자격 증명 관리자) ────────────────────

    _KEYRING_SERVICE = "ad_report_downloader_adn"
    _MOBON_KEYRING_SERVICE = "ad_report_downloader_mobon"

    def _get_adn_password(self, login_id: str) -> str:
        """Windows 자격 증명 관리자에서 ADN 비밀번호 조회. 없으면 빈 문자열 반환."""
        try:
            import keyring
            return keyring.get_password(self._KEYRING_SERVICE, login_id) or ""
        except Exception:
            return ""

    def _get_mobon_passwords(self, mobon_medias: list) -> dict:
        """
        모비온 계정별 비밀번호를 keyring에서 읽어 {account_id: password} dict 반환.
        모비온_비밀번호설정.bat 로 사전 저장 필요.
        """
        try:
            import keyring
        except Exception:
            return {}

        passwords: dict = {}
        media_cfg = self._config.get("media", {})
        for media_code in mobon_medias:
            accounts = media_cfg.get(media_code, {}).get("accounts", [])
            for acc in accounts:
                acc_id = acc.get("account_id", "")
                if acc_id and acc_id not in passwords:
                    pw = keyring.get_password(self._MOBON_KEYRING_SERVICE, acc_id) or ""
                    if pw:
                        passwords[acc_id] = pw
        return passwords


    # ── Brand management ─────────────────────────────────────────────────────

    def _on_brand_changed(self, name: str) -> None:
        if not name:
            return
        prev = self._config.get("active_brand", "")
        if prev and prev != name:
            self._media_panel.save_to_config(self._config)
            for b in self._config.get("brands", []):
                if b["name"] == prev:
                    b["media"] = copy.deepcopy(self._config.get("media", {}))
                    break
        for b in self._config.get("brands", []):
            if b["name"] == name:
                self._config["media"] = copy.deepcopy(b["media"])
                break
        self._config["active_brand"] = name
        self._config["brand_name"] = name
        self._media_panel.load_from_config(self._config)

    def _on_add_brand(self) -> None:
        name, ok = QInputDialog.getText(self, "브랜드 추가", "브랜드명을 입력하세요:")
        if not ok or not name.strip():
            return
        name = name.strip()
        brands = self._config.setdefault("brands", [])
        if any(b["name"] == name for b in brands):
            QMessageBox.warning(self, "중복", f"'{name}' 브랜드가 이미 있습니다.")
            return
        from config_schema import DEFAULT_CONFIG
        brands.append({"name": name, "media": copy.deepcopy(DEFAULT_CONFIG["media"])})
        self._brand_combo.blockSignals(True)
        self._brand_combo.addItem(name)
        self._brand_combo.blockSignals(False)
        self._brand_combo.setCurrentText(name)

    def _on_delete_brand(self) -> None:
        if self._brand_combo.count() <= 1:
            QMessageBox.warning(self, "삭제 불가", "마지막 브랜드는 삭제할 수 없습니다.")
            return
        name = self._brand_combo.currentText()
        reply = QMessageBox.question(
            self, "삭제 확인",
            f"'{name}' 브랜드를 삭제할까요? (복구 불가)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._config["brands"] = [b for b in self._config.get("brands", []) if b["name"] != name]
        idx = self._brand_combo.findText(name)
        self._brand_combo.removeItem(idx)
        save_config(self._config)

    # ── Dialogs ───────────────────────────────────────────────────────────────

    def _browse_save_path(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "저장 폴더 선택")
        if path:
            self._save_path_edit.setText(path)

    def _open_global_settings(self) -> None:
        # 설정 열기 전 active brand의 media를 self._config["media"]에 강제 동기화
        active = self._brand_combo.currentText()
        for b in self._config.get("brands", []):
            if b["name"] == active:
                self._config["media"] = copy.deepcopy(b["media"])
                break
        dlg = SettingsDialog(self._config, self)
        dlg.exec()
        self._load_config_to_ui()

    def _open_media_settings(self, media_code: str) -> None:
        # 설정 열기 전 active brand의 media를 self._config["media"]에 강제 동기화
        active = self._brand_combo.currentText()
        for b in self._config.get("brands", []):
            if b["name"] == active:
                self._config["media"] = copy.deepcopy(b["media"])
                break
        dlg = SettingsDialog(self._config, self)
        dlg.exec()
        self._load_config_to_ui()

    # ── Window close ─────────────────────────────────────────────────────────

    def closeEvent(self, event) -> None:
        if self._worker and self._worker.isRunning():
            reply = QMessageBox.question(
                self, "종료 확인",
                "자동화가 실행 중입니다. 종료하시겠습니까?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self._worker.request_stop()
            self._worker.wait(3000)
        self._save_ui_to_config()
        event.accept()
