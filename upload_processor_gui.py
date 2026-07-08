from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import threading
import time
import tkinter as tk
from datetime import date, timedelta
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from index_classifier.download_folder_processor import process_download_folder
from index_classifier.brand_template_writer import write_brand_template
from index_classifier.exchange_rate import ExchangeRateError, fetch_usd_krw_rate
from index_classifier.google_sheets_uploader import upload_csv_to_google_sheet
from index_classifier.schedule_rules import custom_download_window, default_download_window, parse_date, parse_time
from index_classifier.brand_settings import (
    BrandProfile,
    DEFAULT_OUTPUT_ROOT,
    UI_TYPE_ILRO,
    UI_TYPE_LABELS,
    UI_TYPE_OHYUN,
    UI_TYPE_TAEHA,
    brand_names,
    default_output_path,
    default_upload_csv_path,
    ensure_directory,
    load_profiles,
    resolve_app_path,
    rule_for_profile,
    safe_name,
    save_profiles,
    ui_type_for_brand,
    ui_type_for_profile,
)

DEFAULT_TEST_SPREADSHEET_URL = "https://docs.google.com/spreadsheets/d/1AHu6zuHdrNKJ8mcL9jFrRenlzZFL91URAMqwPN5UVgM/edit?gid=0#gid=0"
DEFAULT_TEST_SPREADSHEET_SHEET = "시트1"


class UploadProcessorApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("브랜드 파일 가공")
        self.geometry("940x700")
        self.minsize(860, 600)

        self.profiles = load_profiles()
        self.brand_var = tk.StringVar(value="법무법인 태하")
        self.download_folder_var = tk.StringVar()
        self.rules_path_var = tk.StringVar(value=str(resolve_app_path("examples\\brand-upload-rules.example.csv")))
        self.output_root_var = tk.StringVar(value=str(DEFAULT_OUTPUT_ROOT))
        self.upload_csv_var = tk.StringVar()
        self.template_path_var = tk.StringVar()
        self.output_path_var = tk.StringVar()
        self.template_update_mode_var = tk.StringVar(value="삭제 후 신규")
        self.template_category_mode_var = tk.StringVar(value="카테고리별 시트")
        self.categories_var = tk.StringVar()
        self.google_categories_var = tk.StringVar()
        self.rolling_days_var = tk.StringVar(value="7")
        self.today_offset_var = tk.StringVar(value="1")
        self.run_date_var = tk.StringVar(value=date.today().strftime("%Y-%m-%d"))
        self.login_command_var = tk.StringVar()
        self.downloader_command_var = tk.StringVar()
        self.spreadsheet_url_var = tk.StringVar(value=DEFAULT_TEST_SPREADSHEET_URL)
        self.spreadsheet_sheet_var = tk.StringVar(value=DEFAULT_TEST_SPREADSHEET_SHEET)
        self.spreadsheet_credentials_var = tk.StringVar()
        self.spreadsheet_upload_mode_var = tk.StringVar(value="삭제 후 신규")
        self.schedule_mode_var = tk.StringVar(value="일반")
        self.start_time_var = tk.StringVar(value="08:00")
        self.custom_start_var = tk.StringVar()
        self.custom_end_var = tk.StringVar()
        self.folder_date_var = tk.StringVar()
        self.download_window_var = tk.StringVar()
        self.status_var = tk.StringVar(value="대기")
        self.exchange_rate_status_var = tk.StringVar(value="환율 미적용 (USD 원본 그대로 사용)")
        self._exchange_rate: float | None = None
        self._running = False
        self._operation_started_at: float | None = None
        self._syncing_default_paths = False
        self._loading_profile = False
        self.run_date_var.trace_add("write", self._on_run_date_changed)

        self._build()
        self._load_brand_profile()
        self._set_default_paths(force_empty_only=True)
        self._set_default_download_folder()
        self._refresh_schedule()

    def _build(self) -> None:
        outer = ttk.Frame(self, padding=12)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(1, weight=1)

        row = 0
        ttk.Label(outer, text="브랜드").grid(row=row, column=0, sticky="w", pady=4)
        self.brand_combo = ttk.Combobox(
            outer,
            textvariable=self.brand_var,
            values=self._brand_values(),
            width=28,
        )
        self.brand_combo.grid(row=row, column=1, sticky="w", pady=4)
        self.brand_combo.bind("<<ComboboxSelected>>", lambda _event: self._on_brand_changed())
        brand_buttons = ttk.Frame(outer)
        brand_buttons.grid(row=row, column=2, sticky="e", padx=(8, 0), pady=4)
        ttk.Button(brand_buttons, text="브랜드 추가", command=self._add_brand).pack(side="left")
        ttk.Button(brand_buttons, text="설정 저장", command=self._save_current_profile).pack(side="left", padx=(6, 0))

        row += 1
        self._path_row(outer, row, "다운로드 폴더", self.download_folder_var, self._choose_download_folder, extra_text="폴더 열기", extra_command=self._open_download_folder)
        row += 1
        self._path_row(outer, row, "규칙 파일", self.rules_path_var, self._choose_rules_file, extra_text="인덱스 열기", extra_command=self._open_index_editor)
        row += 1
        self._path_row(outer, row, "출력 루트", self.output_root_var, self._choose_output_root)
        row += 1
        self._path_row(outer, row, "업로드 CSV", self.upload_csv_var, self._choose_upload_csv_save)

        row += 1
        ttk.Separator(outer).grid(row=row, column=0, columnspan=3, sticky="ew", pady=12)

        row += 1
        ttk.Label(outer, text="실행 기준일").grid(row=row, column=0, sticky="w", pady=4)
        ttk.Entry(outer, textvariable=self.run_date_var).grid(row=row, column=1, sticky="ew", pady=4)
        ttk.Label(outer, text="비우면 오늘").grid(row=row, column=2, sticky="w", padx=(8, 0), pady=4)

        row += 1
        ttk.Separator(outer).grid(row=row, column=0, columnspan=3, sticky="ew", pady=(4, 8))

        row += 1
        self.notebook = ttk.Notebook(outer)
        self.notebook.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(0, 8))
        self._build_ohyun_tab()
        self._build_taeha_tab()
        self._build_ilro_tab()
        self.notebook.bind("<<NotebookTabChanged>>", lambda _event: self._on_tab_changed())

        row += 1
        exchange = ttk.Frame(outer)
        exchange.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(4, 4))
        ttk.Label(exchange, text="환율(USD→KRW)").pack(side="left")
        ttk.Label(exchange, textvariable=self.exchange_rate_status_var).pack(side="left", padx=(8, 8))
        ttk.Button(exchange, text="환율 적용", command=self._run_apply_exchange_rate).pack(side="left")
        ttk.Button(exchange, text="해제", command=self._clear_exchange_rate).pack(side="left", padx=(6, 0))

        row += 1
        integration = ttk.LabelFrame(outer, text="로그인 봇 / 다운로더 호출", padding=8)
        integration.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(8, 4))
        integration.columnconfigure(1, weight=1)
        ttk.Label(integration, text="로그인 명령").grid(row=0, column=0, sticky="w")
        ttk.Entry(integration, textvariable=self.login_command_var).grid(row=0, column=1, sticky="ew", padx=(8, 8))
        ttk.Button(integration, text="로그인 실행", command=self._run_login_bot).grid(row=0, column=2, sticky="e")
        ttk.Label(integration, text="다운로더 명령").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(integration, textvariable=self.downloader_command_var).grid(row=1, column=1, sticky="ew", padx=(8, 8), pady=(8, 0))
        ttk.Button(integration, text="다운로더 실행", command=self._run_downloader).grid(row=1, column=2, sticky="e", pady=(8, 0))

        row += 1
        schedule = ttk.LabelFrame(outer, text="스케줄", padding=8)
        schedule.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(8, 4))
        schedule.columnconfigure(5, weight=1)
        ttk.Label(schedule, text="모드").grid(row=0, column=0, sticky="w", padx=(0, 6))
        ttk.Combobox(
            schedule,
            textvariable=self.schedule_mode_var,
            values=["일반", "공휴일 수동"],
            width=14,
            state="readonly",
        ).grid(row=0, column=1, sticky="w", padx=(0, 12))
        ttk.Label(schedule, text="시작").grid(row=0, column=2, sticky="w", padx=(0, 6))
        ttk.Entry(schedule, textvariable=self.start_time_var, width=8).grid(row=0, column=3, sticky="w", padx=(0, 12))
        ttk.Button(schedule, text="계산", command=self._refresh_schedule).grid(row=0, column=4, sticky="w")
        ttk.Label(schedule, textvariable=self.download_window_var).grid(row=0, column=5, sticky="w", padx=(12, 0))

        ttk.Label(schedule, text="수동 기간").grid(row=1, column=0, sticky="w", pady=(8, 0), padx=(0, 6))
        ttk.Entry(schedule, textvariable=self.custom_start_var, width=12).grid(row=1, column=1, sticky="w", pady=(8, 0), padx=(0, 12))
        ttk.Label(schedule, text="~").grid(row=1, column=2, sticky="w", pady=(8, 0), padx=(0, 6))
        ttk.Entry(schedule, textvariable=self.custom_end_var, width=12).grid(row=1, column=3, sticky="w", pady=(8, 0), padx=(0, 12))
        ttk.Label(schedule, text="폴더일").grid(row=1, column=4, sticky="w", pady=(8, 0), padx=(0, 6))
        ttk.Entry(schedule, textvariable=self.folder_date_var, width=12).grid(row=1, column=5, sticky="w", pady=(8, 0))
        schedule_buttons = ttk.Frame(schedule)
        schedule_buttons.grid(row=1, column=6, sticky="e", pady=(8, 0), padx=(12, 0))
        ttk.Button(schedule_buttons, text="예약 등록", command=self._run_register_schedule).pack(side="left")
        ttk.Button(schedule_buttons, text="예약 확인", command=self._run_check_schedule).pack(side="left", padx=(6, 0))

        row += 1
        buttons = ttk.Frame(outer)
        buttons.grid(row=row, column=0, columnspan=3, sticky="e", pady=(12, 8))
        ttk.Label(buttons, textvariable=self.status_var).pack(side="left", padx=(0, 16))
        ttk.Button(buttons, text="1. 업로드 CSV 생성", command=self._run_process_folder).pack(side="left")
        ttk.Button(buttons, text="2. 템플릿 반영", command=self._run_template_update).pack(side="left", padx=(8, 0))
        ttk.Button(buttons, text="3. 스프레드시트 업로드", command=self._run_spreadsheet_upload).pack(side="left", padx=(8, 0))
        ttk.Button(buttons, text="전체 실행", command=self._run_all).pack(side="left", padx=(8, 0))

        row += 1
        log_frame = ttk.LabelFrame(outer, text="실행 로그", padding=8)
        log_frame.grid(row=row, column=0, columnspan=3, sticky="nsew")
        outer.rowconfigure(row, weight=1)
        self.log_box = tk.Text(log_frame, height=12, wrap="word")
        self.log_box.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_box.yview)
        self.log_box.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")

    def _build_ohyun_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=8)
        tab.columnconfigure(1, weight=1)
        self.notebook.add(tab, text=UI_TYPE_LABELS[UI_TYPE_OHYUN])
        self._tab_ohyun = tab

        self._path_row(tab, 0, "템플릿", self.template_path_var, self._choose_template)
        self._path_row(tab, 1, "결과 파일", self.output_path_var, self._choose_output_file)
        ttk.Label(tab, text="반영 방식").grid(row=2, column=0, sticky="w", pady=4)
        ttk.Combobox(
            tab,
            textvariable=self.template_update_mode_var,
            values=["삭제 후 신규", "기존 시트 누적"],
            width=18,
            state="readonly",
        ).grid(row=2, column=1, sticky="w", pady=4)
        ttk.Label(tab, text="카테고리 (신규 브랜드용, 쉼표로 구분)").grid(row=3, column=0, columnspan=2, sticky="w", pady=(8, 0))
        ttk.Entry(tab, textvariable=self.categories_var).grid(row=4, column=0, columnspan=2, sticky="ew", pady=(0, 4))
        ttk.Label(tab, text="예: 형사, 이혼, 성범죄 (이미 등록된 브랜드는 비워도 됩니다)").grid(row=5, column=0, columnspan=2, sticky="w")

    def _build_taeha_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=8)
        tab.columnconfigure(1, weight=1)
        self.notebook.add(tab, text=UI_TYPE_LABELS[UI_TYPE_TAEHA])
        self._tab_taeha = tab

        self._path_row(tab, 0, "템플릿", self.template_path_var, self._choose_template)
        self._path_row(tab, 1, "결과 파일", self.output_path_var, self._choose_output_file)
        ttk.Label(tab, text="반영 방식").grid(row=2, column=0, sticky="w", pady=4)
        ttk.Combobox(
            tab,
            textvariable=self.template_update_mode_var,
            values=["삭제 후 신규", "기존 시트 누적"],
            width=18,
            state="readonly",
        ).grid(row=2, column=1, sticky="w", pady=4)
        ttk.Label(tab, text="롤링 일수").grid(row=3, column=0, sticky="w", pady=4)
        ttk.Entry(tab, textvariable=self.rolling_days_var, width=6).grid(row=3, column=1, sticky="w", pady=4)
        ttk.Label(tab, text="카테고리 (신규 브랜드용, 쉼표로 구분)").grid(row=4, column=0, columnspan=2, sticky="w", pady=(8, 0))
        ttk.Entry(tab, textvariable=self.categories_var).grid(row=5, column=0, columnspan=2, sticky="ew", pady=(0, 4))
        ttk.Label(tab, text="구글 카테고리 (선택, 쉼표로 구분)").grid(row=6, column=0, columnspan=2, sticky="w", pady=(4, 0))
        ttk.Entry(tab, textvariable=self.google_categories_var).grid(row=7, column=0, columnspan=2, sticky="ew", pady=(0, 4))
        ttk.Label(tab, text="예: 형, 이, 마 (이미 등록된 브랜드는 비워도 됩니다) / 롤링 일수는 TODAY 기준 며칠치 시트를 갱신할지").grid(row=8, column=0, columnspan=2, sticky="w")

    def _build_ilro_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=8)
        tab.columnconfigure(1, weight=1)
        self.notebook.add(tab, text=UI_TYPE_LABELS[UI_TYPE_ILRO])
        self._tab_ilro = tab

        ttk.Label(tab, text="스프레드시트 URL/ID").grid(row=0, column=0, sticky="w")
        ttk.Entry(tab, textvariable=self.spreadsheet_url_var).grid(row=0, column=1, sticky="ew", padx=(8, 8))
        ttk.Label(tab, text="시트명").grid(row=0, column=2, sticky="w")
        ttk.Entry(tab, textvariable=self.spreadsheet_sheet_var, width=18).grid(row=0, column=3, sticky="ew", padx=(8, 0))
        ttk.Label(tab, text="인증 JSON").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(tab, textvariable=self.spreadsheet_credentials_var).grid(row=1, column=1, sticky="ew", padx=(8, 8), pady=(8, 0))
        ttk.Button(tab, text="찾기", command=self._choose_spreadsheet_credentials).grid(row=1, column=2, sticky="e", pady=(8, 0))
        ttk.Combobox(
            tab,
            textvariable=self.spreadsheet_upload_mode_var,
            values=["삭제 후 신규", "기존 시트 누적"],
            width=16,
            state="readonly",
        ).grid(row=1, column=3, sticky="ew", padx=(8, 0), pady=(8, 0))
        ttk.Label(tab, text="이 유형은 템플릿 반영 없이 '3. 스프레드시트 업로드'만 사용해도 됩니다.\n(단일 시트 엑셀로도 반영하려면 '오현형' 탭에서 템플릿/결과 파일을 지정하세요.)").grid(row=2, column=0, columnspan=4, sticky="w", pady=(8, 0))

    def _current_ui_type(self) -> str:
        if not hasattr(self, "notebook"):
            return UI_TYPE_OHYUN
        index = self.notebook.index("current")
        return {0: UI_TYPE_OHYUN, 1: UI_TYPE_TAEHA, 2: UI_TYPE_ILRO}.get(index, UI_TYPE_OHYUN)

    def _select_tab_for_type(self, ui_type: str) -> None:
        if not hasattr(self, "notebook"):
            return
        index = {UI_TYPE_OHYUN: 0, UI_TYPE_TAEHA: 1, UI_TYPE_ILRO: 2}.get(ui_type, 0)
        self.notebook.select(index)

    def _on_tab_changed(self) -> None:
        # 사용자가 탭을 직접 바꾸는 것은 "새 브랜드를 이 유형으로 추가/저장하겠다"는
        # 의도로 취급한다. 기존 브랜드를 불러오는 중(_load_brand_profile)에는
        # 여기서 아무것도 할 필요 없다 (그쪽에서 이미 알맞은 탭을 선택해 준다).
        if self._loading_profile:
            return

    def _path_row(
        self,
        parent: ttk.Frame,
        row: int,
        label: str,
        var: tk.StringVar,
        command,
        *,
        extra_text: str | None = None,
        extra_command=None,
    ) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=4)
        ttk.Entry(parent, textvariable=var).grid(row=row, column=1, sticky="ew", pady=4)
        buttons = ttk.Frame(parent)
        buttons.grid(row=row, column=2, sticky="e", padx=(8, 0), pady=4)
        ttk.Button(buttons, text="찾기", command=command).pack(side="left")
        if extra_text and extra_command:
            ttk.Button(buttons, text=extra_text, command=extra_command).pack(side="left", padx=(6, 0))

    def _brand_values(self) -> list[str]:
        return brand_names(rules_path=self.rules_path_var.get().strip(), profiles=self.profiles)

    def _refresh_brand_values(self) -> None:
        values = self._brand_values()
        self.brand_combo.configure(values=values)
        if self.brand_var.get().strip() not in values and values:
            self.brand_var.set(values[0])

    def _add_brand(self) -> None:
        name = simpledialog.askstring(
            "브랜드 추가",
            f"추가할 브랜드명을 입력해 주세요.\n(현재 선택된 탭 '{UI_TYPE_LABELS[self._current_ui_type()]}' 유형으로 추가됩니다.)",
            parent=self,
        )
        if not name:
            return
        name = name.strip()
        if not name:
            return
        ui_type = self._current_ui_type()
        category_mode = "single_sheet" if ui_type == UI_TYPE_ILRO else "category_sheets"
        sheet_mode = "rolling_day_sheets" if ui_type == UI_TYPE_TAEHA else "fixed_today_offset"
        self.profiles.setdefault(name, BrandProfile(name=name, category_mode=category_mode, sheet_mode=sheet_mode))
        self.brand_var.set(name)
        self._refresh_brand_values()
        self._load_brand_profile()
        self._set_default_paths(force_empty_only=False)
        self._save_current_profile()
        self._log(f"[완료] 브랜드 추가: {name} ({UI_TYPE_LABELS[ui_type]})")

    def _on_brand_changed(self) -> None:
        self._load_brand_profile()
        self._set_default_paths(force_empty_only=False)
        self._refresh_schedule()

    def _on_run_date_changed(self, *_args) -> None:
        if self._syncing_default_paths:
            return
        self._syncing_default_paths = True
        try:
            self._set_default_paths(force_empty_only=True)
        finally:
            self._syncing_default_paths = False
        self.after_idle(self._refresh_schedule)

    def _load_brand_profile(self) -> None:
        self._loading_profile = True
        try:
            profile = self.profiles.get(self.brand_var.get().strip())
            if not profile:
                self.download_folder_var.set(_default_download_root())
                self.template_path_var.set("")
                self.login_command_var.set(_default_login_command())
                self.downloader_command_var.set(_default_downloader_command())
                self.spreadsheet_url_var.set("")
                self.spreadsheet_sheet_var.set("")
                self.spreadsheet_credentials_var.set("")
                self.spreadsheet_upload_mode_var.set("삭제 후 신규")
                self.categories_var.set("")
                self.google_categories_var.set("")
                self.rolling_days_var.set("7")
                self.today_offset_var.set("1")
                brand = self.brand_var.get().strip()
                self._select_tab_for_type(ui_type_for_brand(brand, self.profiles) if brand else UI_TYPE_OHYUN)
                return
            self.rules_path_var.set(str(resolve_app_path(profile.rules_path or self.rules_path_var.get())))
            self.download_folder_var.set(profile.download_folder or _default_download_root())
            self.template_path_var.set(profile.template_path)
            self.output_root_var.set(_normalize_output_root(profile.output_root))
            self.upload_csv_var.set(profile.upload_csv)
            self.login_command_var.set(profile.login_command or _default_login_command())
            self.downloader_command_var.set(profile.downloader_command or _default_downloader_command())
            self.spreadsheet_url_var.set(profile.spreadsheet_url)
            self.spreadsheet_sheet_var.set(profile.spreadsheet_sheet_name)
            self.spreadsheet_credentials_var.set(profile.spreadsheet_credentials_path)
            self.spreadsheet_upload_mode_var.set(_spreadsheet_upload_mode_label(profile.spreadsheet_upload_mode))
            self.categories_var.set(profile.categories)
            self.google_categories_var.set(profile.google_categories)
            self.rolling_days_var.set(str(profile.rolling_days or 7))
            self.today_offset_var.set(str(profile.today_offset if profile.today_offset is not None else 1))
            self._select_tab_for_type(ui_type_for_brand(profile.name, self.profiles))
            self._set_default_download_folder()
        finally:
            self._loading_profile = False

    def _profile_from_current_fields(self, brand: str) -> BrandProfile:
        ui_type = self._current_ui_type()
        category_mode = "single_sheet" if ui_type == UI_TYPE_ILRO else "category_sheets"
        sheet_mode = "rolling_day_sheets" if ui_type == UI_TYPE_TAEHA else "fixed_today_offset"
        try:
            rolling_days = int(self.rolling_days_var.get().strip() or "7")
        except ValueError:
            rolling_days = 7
        try:
            today_offset = int(self.today_offset_var.get().strip() or "1")
        except ValueError:
            today_offset = 1
        return BrandProfile(
            name=brand,
            rules_path=self.rules_path_var.get().strip(),
            download_folder=self.download_folder_var.get().strip(),
            template_path=self.template_path_var.get().strip(),
            output_root=self.output_root_var.get().strip() or str(DEFAULT_OUTPUT_ROOT),
            upload_csv=self.upload_csv_var.get().strip(),
            login_command=self.login_command_var.get().strip(),
            downloader_command=self.downloader_command_var.get().strip(),
            spreadsheet_url=self.spreadsheet_url_var.get().strip(),
            spreadsheet_sheet_name=self.spreadsheet_sheet_var.get().strip(),
            spreadsheet_credentials_path=self.spreadsheet_credentials_var.get().strip(),
            spreadsheet_upload_mode=_spreadsheet_upload_mode(self.spreadsheet_upload_mode_var.get()),
            category_mode=category_mode,
            sheet_mode=sheet_mode,
            categories=self.categories_var.get().strip(),
            google_categories=self.google_categories_var.get().strip(),
            rolling_days=rolling_days,
            today_offset=today_offset,
        )

    def _save_current_profile(self) -> None:
        brand = self.brand_var.get().strip()
        if not brand:
            messagebox.showerror("오류", "브랜드를 먼저 입력해 주세요.")
            return
        profile = self._profile_from_current_fields(brand)
        self.profiles[brand] = profile
        try:
            path = save_profiles(self.profiles)
        except OSError as exc:
            self._log(f"[경고] 브랜드 설정 저장 실패: {exc}")
            return
        self._refresh_brand_values()
        self._log(f"[완료] 브랜드 설정 저장: {path.resolve()} ({UI_TYPE_LABELS[self._current_ui_type()]})")

    def _set_default_paths(self, *, force_empty_only: bool) -> None:
        brand = self.brand_var.get().strip()
        if not brand:
            return
        run_date = self.run_date_var.get().strip() or None
        output_root = _normalize_output_root(self.output_root_var.get().strip())
        if self.output_root_var.get().strip() != output_root:
            self.output_root_var.set(output_root)
        template_path = self.template_path_var.get().strip()
        upload_csv = default_upload_csv_path(brand=brand, run_date=run_date, output_root=output_root)
        output_path = default_output_path(brand=brand, run_date=run_date, template_path=template_path, output_root=output_root)
        current_upload_csv = self.upload_csv_var.get().strip()
        current_output_path = self.output_path_var.get().strip()
        if (
            not force_empty_only
            or not current_upload_csv
            or _is_old_auto_output_path(current_upload_csv)
            or _is_current_auto_output_path(current_upload_csv, brand=brand, output_root=output_root)
        ):
            self.upload_csv_var.set(str(upload_csv))
        if (
            not force_empty_only
            or not current_output_path
            or _is_old_auto_output_path(current_output_path)
            or _is_current_auto_output_path(current_output_path, brand=brand, output_root=output_root)
        ):
            self.output_path_var.set(str(output_path))

    def _set_default_download_folder(self) -> None:
        default_root = _default_download_root()
        if not default_root:
            return
        current = self.download_folder_var.get().strip()
        if _bundled_downloader_config_path().exists() or not current or _is_packaged_placeholder_download_path(current):
            self.download_folder_var.set(default_root)

    def _choose_download_folder(self) -> None:
        selected = filedialog.askdirectory(title="다운로드 결과 상위 폴더")
        if selected:
            self.download_folder_var.set(selected)

    def _open_download_folder(self) -> None:
        self._set_default_download_folder()
        folder = Path(self.download_folder_var.get().strip() or _default_download_root())
        folder.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(["explorer", str(folder)])

    def _choose_rules_file(self) -> None:
        selected = filedialog.askopenfilename(filetypes=[("CSV files", "*.csv"), ("All files", "*.*")])
        if selected:
            self.rules_path_var.set(selected)
            self._refresh_brand_values()

    def _choose_output_root(self) -> None:
        selected = filedialog.askdirectory(title="브랜드별 결과 저장 루트")
        if selected:
            self.output_root_var.set(selected)
            self._set_default_paths(force_empty_only=False)

    def _choose_upload_csv_save(self) -> None:
        selected = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV files", "*.csv")])
        if selected:
            self.upload_csv_var.set(selected)

    def _choose_template(self) -> None:
        selected = filedialog.askopenfilename(filetypes=[("Excel files", "*.xlsx *.xlsb"), ("All files", "*.*")])
        if selected:
            self.template_path_var.set(selected)
            self._set_default_paths(force_empty_only=False)
            self._sync_output_suffix()

    def _choose_output_file(self) -> None:
        template_suffix = Path(self.template_path_var.get().strip()).suffix.lower()
        default_extension = ".xlsb" if template_suffix == ".xlsb" else ".xlsx"
        selected = filedialog.asksaveasfilename(defaultextension=default_extension, filetypes=[("Excel files", "*.xlsx *.xlsb"), ("All files", "*.*")])
        if selected:
            self.output_path_var.set(selected)

    def _choose_spreadsheet_credentials(self) -> None:
        selected = filedialog.askopenfilename(filetypes=[("JSON files", "*.json"), ("All files", "*.*")])
        if selected:
            self.spreadsheet_credentials_var.set(selected)

    def _run_process_folder(self) -> None:
        self._run_background(self._process_folder)

    def _run_template_update(self) -> None:
        self._run_background(self._template_update)

    def _run_spreadsheet_upload(self) -> None:
        self._run_background(self._spreadsheet_upload)

    def _run_all(self) -> None:
        self._run_background(lambda: (self._process_folder(), self._template_update(), self._spreadsheet_upload_if_configured()))

    def _run_login_bot(self) -> None:
        self._run_background(self._launch_login_bot)

    def _run_downloader(self) -> None:
        self._run_background(self._launch_downloader)

    def _run_register_schedule(self) -> None:
        self._run_background(self._register_windows_schedule)

    def _run_check_schedule(self) -> None:
        self._run_background(self._check_windows_schedule)

    def _run_apply_exchange_rate(self) -> None:
        if self._running:
            self._log("[안내] 이미 실행 중입니다. 완료 후 다시 눌러 주세요.")
            return
        self.exchange_rate_status_var.set("환율 조회 중...")

        def _fetch() -> None:
            try:
                rate = fetch_usd_krw_rate()
            except ExchangeRateError as exc:
                self._log(f"[환율] 자동 조회 실패: {exc}")
                self.after(0, self._prompt_manual_exchange_rate)
                return
            self.after(0, lambda: self._set_exchange_rate(rate, source="자동 조회"))

        threading.Thread(target=_fetch, daemon=True).start()

    def _prompt_manual_exchange_rate(self) -> None:
        value = simpledialog.askfloat(
            "환율 직접 입력",
            "자동 조회에 실패했습니다. 오늘 USD → KRW 환율을 직접 입력해 주세요.\n예: 1380.5",
            parent=self,
            minvalue=0.0,
        )
        if value is None:
            self.exchange_rate_status_var.set("환율 미적용 (USD 원본 그대로 사용)")
            self._log("[환율] 수동 입력이 취소되어 환율 변환을 적용하지 않습니다.")
            return
        self._set_exchange_rate(value, source="수동 입력")

    def _set_exchange_rate(self, rate: float, *, source: str) -> None:
        self._exchange_rate = rate
        today = date.today().strftime("%Y-%m-%d")
        self.exchange_rate_status_var.set(f"적용: 1USD = {rate:,.2f}원 ({source}, {today})")
        self._log(f"[환율] {source}로 USD→KRW 환율 {rate:,.2f}원 적용 ({today} 기준). raw 통화 코드가 KRW가 아닌 행의 총비용만 변환됩니다.")

    def _clear_exchange_rate(self) -> None:
        self._exchange_rate = None
        self.exchange_rate_status_var.set("환율 미적용 (USD 원본 그대로 사용)")
        self._log("[환율] 환율 변환을 해제했습니다.")

    def _open_index_editor(self) -> None:
        rules_path = self.rules_path_var.get().strip()
        if not rules_path:
            messagebox.showerror("오류", "규칙 파일을 먼저 선택해 주세요.")
            return
        rules_path = str(resolve_app_path(rules_path))
        self.rules_path_var.set(rules_path)
        if not Path(rules_path).exists():
            messagebox.showerror("오류", f"규칙 파일을 찾을 수 없습니다: {rules_path}")
            return
        script_path = Path(__file__).with_name("upload_rule_editor_gui.py")
        subprocess.Popen(
            [sys.executable, "-B", str(script_path), rules_path],
            cwd=Path(__file__).parent,
            close_fds=True,
        )
        self._log(f"[안내] 인덱스 규칙 편집기 실행: {rules_path}")

    def _refresh_schedule(self) -> None:
        try:
            self._set_default_paths(force_empty_only=True)
            run_date = self.run_date_var.get().strip() or None
            parse_time(self.start_time_var.get().strip() or None)
            window = self._download_window()
            folder_date = parse_date(run_date)
            self.folder_date_var.set(folder_date.strftime("%Y-%m-%d"))
            self.download_window_var.set(
                f"다운로드 기간 {window.start_yyyymmdd}~{window.end_yyyymmdd} / 폴더 {folder_date.strftime('%Y%m%d')}"
            )
        except Exception as exc:
            self.download_window_var.set(f"스케줄 오류: {exc}")

    def _process_folder(self) -> None:
        self._validate_file_inputs(require_template=False)
        self._refresh_schedule()
        try:
            result = self._process_folder_once()
        except FileNotFoundError as exc:
            self._log(f"[auto] raw file not found. Running downloader first: {exc}")
            result = self._run_downloader_until_raw_available()
        missing_dates = self._missing_expected_dates(result)
        if missing_dates:
            self._log(f"[auto] raw date missing ({', '.join(missing_dates)}). Running downloader first.")
            result = self._run_downloader_until_raw_available()
            missing_dates = self._missing_expected_dates(result)
            if missing_dates:
                raise FileNotFoundError(f"다운로드 후에도 누락된 날짜 데이터가 있습니다: {', '.join(missing_dates)}")
        if not result.raw_files or result.total_rows <= 0:
            raise ValueError("처리된 데이터가 없습니다. 다운로드 폴더와 실행 기준일을 확인해 주세요.")
        self._log(f"[완료] 업로드 CSV 생성: {result.output_path}")
        self._log(f"  raw 파일 수: {len(result.raw_files)}")
        self._log(f"  변환 행 수: {result.total_rows}")
        if result.duplicate_rows:
            self._log(f"  중복 의심 행 수: {result.duplicate_rows}")
        for category, count in sorted(result.category_counts.items(), key=lambda item: (-item[1], item[0])):
            self._log(f"  {category}: {count}")
        if result.date_counts:
            self._log("  날짜: " + ", ".join(f"{key}={value}" for key, value in sorted(result.date_counts.items())))

    def _process_folder_once(self):
        return process_download_folder(
            brand=self.brand_var.get().strip(),
            download_folder=self.download_folder_var.get().strip(),
            rules_path=str(resolve_app_path(self.rules_path_var.get().strip())),
            output_path=self.upload_csv_var.get().strip(),
            folder_date=self.folder_date_var.get().strip() or None,
            exchange_rate=self._exchange_rate,
        )

    def _run_downloader_if_configured(self) -> None:
        command = self.downloader_command_var.get().strip()
        if not command:
            raise FileNotFoundError("raw file not found and downloader command is empty.")
        self._run_external_command("downloader", command)

    def _launch_login_bot(self) -> None:
        self._launch_external_command("로그인 봇", self.login_command_var.get().strip())

    def _launch_downloader(self) -> None:
        self._prepare_bundled_downloader()
        self._launch_external_command("downloader", self.downloader_command_var.get().strip())

    def _run_downloader_until_raw_available(self):
        self._prepare_bundled_downloader()
        process = self._launch_external_command("downloader", self.downloader_command_var.get().strip())
        deadline = time.monotonic() + 1800
        last_log = 0.0
        while time.monotonic() < deadline:
            try:
                result = self._process_folder_once()
            except FileNotFoundError:
                if process.poll() is not None and process.returncode not in (0, None):
                    raise RuntimeError(f"downloader exited with code {process.returncode} before raw files were found.")
                now = time.monotonic()
                if now - last_log >= 15:
                    self._log("[auto] Waiting for downloader raw files...")
                    last_log = now
                time.sleep(5)
                continue
            missing_dates = self._missing_expected_dates(result)
            if missing_dates:
                now = time.monotonic()
                if now - last_log >= 15:
                    self._log(f"[auto] Waiting for missing raw dates: {', '.join(missing_dates)}")
                    last_log = now
                time.sleep(5)
                continue
            self._log("[auto] Raw files found after downloader launch.")
            return result
        raise TimeoutError("downloader raw files were not found within 30 minutes.")

    def _prepare_bundled_downloader(self) -> None:
        download_root = _default_download_root()
        if download_root:
            Path(download_root).mkdir(parents=True, exist_ok=True)
            self.download_folder_var.set(download_root)
        config_path = _bundled_downloader_config_path()
        if not config_path.exists():
            return
        try:
            data = json.loads(config_path.read_text(encoding="utf-8-sig"))
        except Exception as exc:
            self._log(f"[warning] downloader config read failed: {exc}")
            return
        if download_root:
            data["save_root_path"] = download_root
        try:
            window = self._download_window()
            data["last_run_period"] = {
                "start": window.start_date.strftime("%Y-%m-%d"),
                "end": window.end_date.strftime("%Y-%m-%d"),
            }
        except Exception as exc:
            self._log(f"[warning] downloader period prepare failed: {exc}")
        downloader_brand = _downloader_brand_name(self.brand_var.get().strip(), data)
        if downloader_brand:
            data["active_brand"] = downloader_brand
            data["brand_name"] = downloader_brand
            for brand in data.get("brands", []):
                if str(brand.get("name") or "").strip() == downloader_brand:
                    media = brand.get("media")
                    if isinstance(media, dict):
                        data["media"] = media
                    break
        _atomic_write_text(config_path, json.dumps(data, ensure_ascii=False, indent=2))
        self._log(f"[ready] downloader save folder: {download_root}")

    def _download_window(self):
        run_date = self.run_date_var.get().strip() or None
        if self.schedule_mode_var.get() == "공휴일 수동":
            if not self.custom_start_var.get().strip() or not self.custom_end_var.get().strip():
                self.download_window_var.set("수동 기간을 입력해 주세요")
                self.folder_date_var.set(parse_date(run_date).strftime("%Y-%m-%d"))
                raise ValueError("수동 기간을 입력해 주세요.")
            return custom_download_window(self.custom_start_var.get().strip(), self.custom_end_var.get().strip())
        return default_download_window(run_date)

    def _expected_download_dates(self) -> list[str]:
        window = self._download_window()
        current = window.start_date
        result: list[str] = []
        while current <= window.end_date:
            result.append(current.strftime("%Y%m%d"))
            current += timedelta(days=1)
        return result

    def _missing_expected_dates(self, result) -> list[str]:
        expected = self._expected_download_dates()
        available = set(getattr(result, "date_counts", {}) or {})
        return [date_key for date_key in expected if date_key not in available]

    def _template_update(self) -> None:
        ui_type = self._current_ui_type()
        if ui_type == UI_TYPE_ILRO and not self.template_path_var.get().strip():
            self._log("[안내] 일로형: 템플릿이 설정되지 않아 템플릿 반영 단계를 건너뜁니다 (스프레드시트 업로드만 사용).")
            return
        self._validate_file_inputs(require_template=True)
        self._refresh_schedule()
        rows_csv = Path(self.upload_csv_var.get().strip())
        if not rows_csv.exists():
            self._log(f"[안내] 업로드 CSV가 없어 먼저 생성합니다: {rows_csv}")
            self._process_folder()
        if not rows_csv.exists():
            raise FileNotFoundError(f"업로드 CSV 생성에 실패했습니다: {rows_csv}")
        with rows_csv.open("r", encoding="utf-8-sig", newline="") as file:
            rows = [dict(row) for row in csv.DictReader(file)]
        if not rows:
            raise ValueError("업로드 CSV에 데이터가 없습니다. 먼저 올바른 다운로드 폴더로 CSV를 생성해 주세요.")
        positive_rows = [row for row in rows if _positive_cost(row)]
        zero_cost_count = len(rows) - len(positive_rows)
        self._log(f"[안내] 템플릿 반영 대상: {len(positive_rows)}행 / 비용 0 제외: {zero_cost_count}행")
        for key, count in sorted(_media_category_counts(positive_rows).items(), key=lambda item: (-item[1], item[0])):
            self._log(f"  {key}: {count}")
        self._log("[진행] 템플릿 반영 시작")
        brand = self.brand_var.get().strip()
        rule = rule_for_profile(self._profile_from_current_fields(brand))
        result = write_brand_template(
            brand=brand,
            template_path=self.template_path_var.get().strip(),
            output_path=self.output_path_var.get().strip(),
            rows=rows,
            run_date=self.run_date_var.get().strip() or None,
            update_mode=_template_update_mode(self.template_update_mode_var.get()),
            category_mode=_template_category_mode(self.template_category_mode_var.get()),
            rule=rule,
        )
        if result.written_rows <= 0:
            raise ValueError(_zero_rows_diagnostic(result))
        self._log(f"[완료] 템플릿 반영: {result.output_path}")
        self._log(f"  반영 행 수: {result.written_rows}")
        self._log(f"  수정 시트: {', '.join(result.touched_sheets) if result.touched_sheets else '(없음)'}")

    def _spreadsheet_upload_if_configured(self) -> None:
        if not (
            self.spreadsheet_url_var.get().strip()
            and self.spreadsheet_sheet_var.get().strip()
            and self.spreadsheet_credentials_var.get().strip()
        ):
            self._log("[안내] 스프레드시트 설정이 비어 있어 업로드를 건너뜁니다.")
            return
        self._spreadsheet_upload()

    def _spreadsheet_upload(self) -> None:
        rows_csv = Path(self.upload_csv_var.get().strip())
        if not rows_csv.exists():
            self._log(f"[안내] 업로드 CSV가 없어 먼저 생성합니다: {rows_csv}")
            self._process_folder()
        if not rows_csv.exists():
            raise FileNotFoundError(f"업로드 CSV 생성에 실패했습니다: {rows_csv}")
        spreadsheet_url = self.spreadsheet_url_var.get().strip()
        sheet_name = self.spreadsheet_sheet_var.get().strip()
        credentials = self.spreadsheet_credentials_var.get().strip()
        if not spreadsheet_url:
            raise ValueError("스프레드시트 URL/ID를 입력해 주세요.")
        if not sheet_name:
            raise ValueError("업로드할 시트명을 입력해 주세요.")
        if not credentials or not Path(credentials).exists():
            raise FileNotFoundError("서비스 계정 인증 JSON 파일을 선택해 주세요.")
        self._save_current_profile()
        self._log("[진행] 스프레드시트 업로드 시작")
        result = upload_csv_to_google_sheet(
            csv_path=rows_csv,
            spreadsheet=spreadsheet_url,
            sheet_name=sheet_name,
            credentials_path=credentials,
            mode=_spreadsheet_upload_mode(self.spreadsheet_upload_mode_var.get()),
        )
        self._log(f"[완료] 스프레드시트 업로드: {result['sheet_name']}")
        self._log(f"  방식: {'기존 시트 누적' if result['mode'] == 'append' else '삭제 후 신규'}")
        self._log(f"  업로드 행 수: {result['rows']}")

    def _validate_file_inputs(self, *, require_template: bool) -> None:
        self._set_default_paths(force_empty_only=True)
        if not self.brand_var.get().strip():
            raise ValueError("브랜드를 입력해 주세요.")
        rules_path = self.rules_path_var.get().strip()
        if rules_path:
            rules_path = str(resolve_app_path(rules_path))
            self.rules_path_var.set(rules_path)
        download_folder = self.download_folder_var.get().strip()
        upload_csv = self.upload_csv_var.get().strip()
        template_path = self.template_path_var.get().strip()
        output_path = self.output_path_var.get().strip()
        if not rules_path:
            raise ValueError("규칙 파일을 선택해 주세요.")
        if not download_folder:
            raise ValueError("다운로드 폴더를 선택해 주세요.")
        if not upload_csv:
            raise ValueError("업로드 CSV 저장 경로를 입력해 주세요.")
        if not Path(rules_path).exists():
            raise FileNotFoundError("규칙 파일을 찾을 수 없습니다.")
        if not Path(download_folder).exists():
            if _is_default_download_root(download_folder):
                Path(download_folder).mkdir(parents=True, exist_ok=True)
            else:
                raise FileNotFoundError("다운로드 폴더를 찾을 수 없습니다.")
        if require_template and not template_path:
            raise ValueError("템플릿 파일을 선택해 주세요.")
        if require_template and not output_path:
            raise ValueError("결과 파일 저장 경로를 입력해 주세요.")
        if require_template and not Path(template_path).exists():
            raise FileNotFoundError("템플릿 파일을 찾을 수 없습니다.")
        if require_template:
            template_suffix = Path(template_path).suffix.lower()
            output_path = self._sync_output_suffix()
            output_suffix = Path(output_path).suffix.lower()
            if template_suffix == ".xlsb" and output_suffix != ".xlsb":
                raise ValueError("템플릿이 .xlsb이면 결과 파일도 .xlsb로 저장해 주세요.")

    def _sync_output_suffix(self) -> str:
        template_suffix = Path(self.template_path_var.get().strip()).suffix.lower()
        output_text = self.output_path_var.get().strip()
        if template_suffix != ".xlsb" or not output_text:
            return output_text
        output_path = Path(output_text)
        if output_path.suffix.lower() == ".xlsb":
            return output_text
        fixed = output_path.with_suffix(".xlsb")
        self.output_path_var.set(str(fixed))
        self._log(f"[안내] 결과 파일 확장자를 .xlsb로 자동 변경: {fixed}")
        return str(fixed)

    def _register_windows_schedule(self) -> None:
        self._validate_file_inputs(require_template=True)
        self._refresh_schedule()
        start_time = parse_time(self.start_time_var.get().strip() or None).strftime("%H:%M")
        config_path = self._write_schedule_config()
        task_name = self._schedule_task_name()
        script_path = Path(__file__).with_name("scheduled_upload_processor.py")
        command = f'"{sys.executable}" -B "{script_path}" "{config_path}"'
        result = subprocess.run(
            [
                "schtasks",
                "/Create",
                "/TN",
                task_name,
                "/TR",
                command,
                "/SC",
                "DAILY",
                "/ST",
                start_time,
                "/F",
            ],
            capture_output=True,
            text=True,
            encoding="mbcs",
            errors="replace",
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError((result.stderr or result.stdout or "작업 스케줄러 등록 실패").strip())
        self._log(f"[완료] 예약 등록: {task_name} / 매일 {start_time}")
        self._log(f"  설정 파일: {config_path}")

    def _check_windows_schedule(self) -> None:
        task_name = self._schedule_task_name()
        result = subprocess.run(
            ["schtasks", "/Query", "/TN", task_name, "/V", "/FO", "LIST"],
            capture_output=True,
            text=True,
            encoding="mbcs",
            errors="replace",
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(f"예약이 등록되어 있지 않습니다: {task_name}")
        output = result.stdout
        self._log(f"[확인] 예약 등록됨: {task_name}")
        for label in ("다음 실행 시간", "Next Run Time", "상태", "Status", "마지막 실행 시간", "Last Run Time", "마지막 결과", "Last Result"):
            line = _find_schedule_line(output, label)
            if line:
                self._log(f"  {line}")
        self._log("  PC가 켜져 있고 Windows에 예약 작업 실행 권한이 있으면 지정 시간에 자동 실행됩니다.")

    def _write_schedule_config(self) -> Path:
        config_path = Path(__file__).with_name("upload_processor_schedule.json")
        data = {
            "brand": self.brand_var.get().strip(),
            "download_folder": self.download_folder_var.get().strip(),
            "rules_path": self.rules_path_var.get().strip(),
            "upload_csv": self.upload_csv_var.get().strip(),
            "template_path": self.template_path_var.get().strip(),
            "output_path": self.output_path_var.get().strip(),
            "output_root": self.output_root_var.get().strip(),
            "login_command": self.login_command_var.get().strip(),
            "downloader_command": self.downloader_command_var.get().strip(),
            "schedule_mode": self.schedule_mode_var.get().strip(),
            "start_time": self.start_time_var.get().strip(),
            "custom_start": self.custom_start_var.get().strip(),
            "custom_end": self.custom_end_var.get().strip(),
        }
        _atomic_write_text(config_path, json.dumps(data, ensure_ascii=False, indent=2))
        return config_path.resolve()

    def _schedule_task_name(self) -> str:
        return f"BrandUploadProcessor_{self.brand_var.get().strip().replace(' ', '_')}"

    def _run_external_command(self, label: str, command: str) -> None:
        command = _normalize_external_command(command)
        if not command:
            raise ValueError(f"{label} 명령을 입력해 주세요.")
        self._save_current_profile()
        self._log(f"[시작] {label}: {command}")
        result = subprocess.run(
            command,
            shell=True,
            cwd=Path(__file__).parent,
            capture_output=True,
            text=True,
            encoding="mbcs",
            errors="replace",
            check=False,
        )
        if result.stdout.strip():
            self._log(result.stdout.strip())
        if result.returncode != 0:
            raise RuntimeError((result.stderr or result.stdout or f"{label} 실행 실패").strip())
        self._log(f"[완료] {label}")

    def _launch_external_command(self, label: str, command: str) -> subprocess.Popen:
        command = _normalize_external_command(command)
        if not command:
            raise ValueError(f"{label} command is empty.")
        self._save_current_profile()
        self._log(f"[start] {label}: {command}")
        process = subprocess.Popen(
            command,
            shell=True,
            cwd=Path(__file__).parent,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self._log(f"[started] {label} pid={process.pid}")
        return process

    def _run_background(self, fn) -> None:
        if self._running:
            self._log("[안내] 이미 실행 중입니다. 완료 후 다시 눌러 주세요.")
            return
        self._running = True
        self._operation_started_at = time.monotonic()
        self.status_var.set("실행 중 00:00")
        self._tick_elapsed()

        def _target() -> None:
            try:
                fn()
            except Exception as exc:
                message = str(exc)
                self._log(f"[오류] {message}")
                self.after(0, lambda message=message: messagebox.showerror("오류", message))
            finally:
                self._running = False
                elapsed = self._elapsed_text()
                self.after(0, lambda elapsed=elapsed: self.status_var.set(f"완료 {elapsed}"))

        threading.Thread(target=_target, daemon=True).start()

    def _tick_elapsed(self) -> None:
        if not self._running:
            return
        self.status_var.set(f"실행 중 {self._elapsed_text()}")
        self.after(1000, self._tick_elapsed)

    def _elapsed_text(self) -> str:
        if self._operation_started_at is None:
            return "00:00"
        elapsed = int(time.monotonic() - self._operation_started_at)
        return f"{elapsed // 60:02d}:{elapsed % 60:02d}"

    def _log(self, message: str) -> None:
        def _append() -> None:
            self.log_box.insert("end", message + "\n")
            self.log_box.see("end")

        self.after(0, _append)


def _find_schedule_line(output: str, label: str) -> str:
    label_folded = label.casefold()
    for line in output.splitlines():
        if line.strip().casefold().startswith(label_folded):
            return line.strip()
    return ""


def _positive_cost(row: dict[str, str]) -> bool:
    text = str(row.get("cost") or row.get("총비용") or "0").replace(",", "").strip()
    try:
        return float(text) > 0
    except ValueError:
        return False


def _media_category_counts(rows: list[dict[str, str]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        key = f"{row.get('media', '') or '(매체 없음)'} / {row.get('category', '') or '(분류 없음)'}"
        counts[key] = counts.get(key, 0) + 1
    return counts


def _zero_rows_diagnostic(result) -> str:
    lines = ["템플릿에 반영된 행이 없습니다."]
    if result.available_row_dates:
        lines.append(f"  업로드 CSV의 실제 일자: {', '.join(result.available_row_dates)}")
    else:
        lines.append("  업로드 CSV에서 유효한 일자를 찾지 못했습니다.")
    if result.expected_sheet_names:
        lines.append(f"  기대한 시트명({len(result.expected_sheet_names)}개): {', '.join(result.expected_sheet_names[:8])}" + (" ..." if len(result.expected_sheet_names) > 8 else ""))
    if result.missing_sheets:
        lines.append(f"  템플릿에 없는 시트({len(result.missing_sheets)}개): {', '.join(result.missing_sheets[:8])}" + (" ..." if len(result.missing_sheets) > 8 else ""))
        lines.append("  → 템플릿에 해당 일자 시트가 아직 없는지 확인해 주세요 (예: 오현은 매일 새 날짜 시트가 필요합니다).")
    else:
        lines.append("  → 시트는 모두 찾았지만 조건(일자/카테고리/캠페인유형)에 맞는 행이 없습니다. 실행 기준일을 확인해 주세요.")
    return "\n".join(lines)


def _normalize_output_root(value: str) -> str:
    text = str(value or "").strip()
    if not text or text.lower() in {"outputs", ".\\outputs", "./outputs"}:
        return str(DEFAULT_OUTPUT_ROOT)
    return text


def _is_old_auto_output_path(value: str) -> bool:
    text = str(value or "")
    normalized = text.replace("/", "\\").casefold()
    workspace_outputs = str(Path(__file__).parent / "outputs").replace("/", "\\").casefold()
    duplicated_outputs = str(DEFAULT_OUTPUT_ROOT / "outputs").replace("/", "\\").casefold()
    return workspace_outputs in normalized or duplicated_outputs in normalized


def _is_current_auto_output_path(value: str, *, brand: str, output_root: str) -> bool:
    if not value or not brand:
        return False
    text = str(value).replace("/", "\\").casefold()
    root = str(Path(output_root or DEFAULT_OUTPUT_ROOT)).replace("/", "\\").rstrip("\\").casefold()
    brand_part = f"\\{safe_name(brand).casefold()}\\"
    return bool(root and root in text and brand_part in text)


def _is_default_download_root(value: str) -> bool:
    text = str(value or "").replace("/", "\\").rstrip("\\").casefold()
    default = _default_download_root().replace("/", "\\").rstrip("\\").casefold()
    return bool(text and text == default)


def _default_bot_command(file_name: str) -> str:
    path = Path(__file__).resolve().parent.parent / "bots" / "report-downloader" / file_name
    return str(path) if path.exists() else ""


def _package_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _default_download_root() -> str:
    root = _package_root() / "downloads"
    return str(root)


def _bundled_downloader_config_path() -> Path:
    return _package_root() / "bots" / "report-downloader" / "ad_report_downloader" / "config.json"


def _is_packaged_placeholder_download_path(value: str) -> bool:
    text = str(value or "").replace("/", "\\").casefold()
    package = str(_package_root()).replace("/", "\\").casefold()
    return (
        "\\다운로드" in text
        or text.endswith("\\download")
        or text.endswith("\\downloads")
        or (package in text and "\\downloads" not in text)
    )


def _downloader_brand_name(app_brand: str, config: dict) -> str:
    desired = str(app_brand or "").strip()
    names = [str(item.get("name") or "").strip() for item in config.get("brands", []) if isinstance(item, dict)]
    if desired in names:
        return desired
    aliases = {
        "법무법인 오현": "법무법인 오현 - 데일리",
        "법무법인 태하": "법무법인 태하 - 데일리",
        "법무법인 일로": "법무법인 일로 - 데일리",
    }
    alias = aliases.get(desired)
    if alias in names:
        return alias
    for name in names:
        if desired and (name.startswith(desired) or desired.startswith(name)):
            return name
    return desired


def _default_login_command() -> str:
    return _default_bot_command("login.bat") or _default_bot_command("로그인.bat")


def _default_downloader_command() -> str:
    return _default_bot_command("run.bat")


def _normalize_external_command(command: str) -> str:
    text = str(command or "").strip()
    if text.endswith(" 실행"):
        text = text[: -len(" 실행")].strip()
    return text


def _atomic_write_text(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    """중단(강제종료/충돌 등)되어도 대상 파일이 손상되지 않도록 임시 파일에
    먼저 쓴 뒤 os.replace로 교체한다.

    write_text()를 바로 쓰면, 쓰기 도중 프로세스가 죽거나 다른 프로세스가
    같은 파일을 동시에 읽는 경우 config.json이 일부만 쓰인 채로 남아
    JSONDecodeError를 일으킬 수 있다(다운로더 봇 config.json에서 실제로
    이런 형태의 손상이 관측됨). os.replace는 같은 파일시스템 내에서
    원자적으로 동작하므로 이 문제를 막는다.
    """
    tmp_path = path.with_name(f"{path.name}.tmp{os.getpid()}")
    tmp_path.write_text(text, encoding=encoding)
    os.replace(tmp_path, path)


def _template_update_mode(value: str) -> str:
    return "append" if "누적" in str(value or "") else "replace"


def _template_category_mode(value: str) -> str:
    return "single_sheet" if "단일" in str(value or "") else "category_sheets"


def _spreadsheet_upload_mode(value: str) -> str:
    return "append" if "누적" in str(value or "") else "replace"


def _spreadsheet_upload_mode_label(value: str) -> str:
    return "기존 시트 누적" if str(value or "").casefold() == "append" else "삭제 후 신규"


def main() -> None:
    parser = argparse.ArgumentParser(description="브랜드 파일 가공 UI")
    parser.parse_args()
    app = UploadProcessorApp()
    app.mainloop()


if __name__ == "__main__":
    main()
