from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
import threading
import time
import tkinter as tk
from datetime import date
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from index_classifier.download_folder_processor import process_download_folder
from index_classifier.brand_template_writer import write_brand_template
from index_classifier.schedule_rules import custom_download_window, default_download_window, parse_date, parse_time
from index_classifier.brand_settings import (
    BrandProfile,
    DEFAULT_OUTPUT_ROOT,
    brand_names,
    default_output_path,
    default_upload_csv_path,
    ensure_directory,
    load_profiles,
    save_profiles,
)


class UploadProcessorApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("브랜드 파일 가공")
        self.geometry("900x620")
        self.minsize(820, 520)

        self.profiles = load_profiles()
        self.brand_var = tk.StringVar(value="법무법인 태하")
        self.download_folder_var = tk.StringVar()
        self.rules_path_var = tk.StringVar(value="examples\\brand-upload-rules.example.csv")
        self.output_root_var = tk.StringVar(value=str(DEFAULT_OUTPUT_ROOT))
        self.upload_csv_var = tk.StringVar()
        self.template_path_var = tk.StringVar()
        self.output_path_var = tk.StringVar()
        self.run_date_var = tk.StringVar(value=date.today().strftime("%Y-%m-%d"))
        self.login_command_var = tk.StringVar()
        self.downloader_command_var = tk.StringVar()
        self.schedule_mode_var = tk.StringVar(value="일반")
        self.start_time_var = tk.StringVar(value="08:00")
        self.custom_start_var = tk.StringVar()
        self.custom_end_var = tk.StringVar()
        self.folder_date_var = tk.StringVar()
        self.download_window_var = tk.StringVar()
        self.status_var = tk.StringVar(value="대기")
        self._running = False
        self._operation_started_at: float | None = None

        self._build()
        self._load_brand_profile()
        self._set_default_paths(force_empty_only=True)
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
        self._path_row(outer, row, "다운로드 폴더", self.download_folder_var, self._choose_download_folder)
        row += 1
        self._path_row(outer, row, "규칙 파일", self.rules_path_var, self._choose_rules_file, extra_text="인덱스 열기", extra_command=self._open_index_editor)
        row += 1
        self._path_row(outer, row, "출력 루트", self.output_root_var, self._choose_output_root)
        row += 1
        self._path_row(outer, row, "업로드 CSV", self.upload_csv_var, self._choose_upload_csv_save)

        row += 1
        ttk.Separator(outer).grid(row=row, column=0, columnspan=3, sticky="ew", pady=12)

        row += 1
        self._path_row(outer, row, "템플릿", self.template_path_var, self._choose_template)
        row += 1
        self._path_row(outer, row, "결과 파일", self.output_path_var, self._choose_output_file)
        row += 1
        ttk.Label(outer, text="실행 기준일").grid(row=row, column=0, sticky="w", pady=4)
        ttk.Entry(outer, textvariable=self.run_date_var).grid(row=row, column=1, sticky="ew", pady=4)
        ttk.Label(outer, text="비우면 오늘").grid(row=row, column=2, sticky="w", padx=(8, 0), pady=4)

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
        name = simpledialog.askstring("브랜드 추가", "추가할 브랜드명을 입력해 주세요.", parent=self)
        if not name:
            return
        name = name.strip()
        if not name:
            return
        self.profiles.setdefault(name, BrandProfile(name=name))
        self.brand_var.set(name)
        self._refresh_brand_values()
        self._load_brand_profile()
        self._set_default_paths(force_empty_only=False)
        self._save_current_profile()
        self._log(f"[완료] 브랜드 추가: {name}")

    def _on_brand_changed(self) -> None:
        self._load_brand_profile()
        self._set_default_paths(force_empty_only=False)
        self._refresh_schedule()

    def _load_brand_profile(self) -> None:
        profile = self.profiles.get(self.brand_var.get().strip())
        if not profile:
            self.download_folder_var.set("")
            self.template_path_var.set("")
            self.login_command_var.set("")
            self.downloader_command_var.set("")
            return
        self.rules_path_var.set(profile.rules_path or self.rules_path_var.get())
        self.download_folder_var.set(profile.download_folder)
        self.template_path_var.set(profile.template_path)
        self.output_root_var.set(_normalize_output_root(profile.output_root))
        self.upload_csv_var.set(profile.upload_csv)
        self.login_command_var.set(profile.login_command)
        self.downloader_command_var.set(profile.downloader_command)

    def _save_current_profile(self) -> None:
        brand = self.brand_var.get().strip()
        if not brand:
            messagebox.showerror("오류", "브랜드를 먼저 입력해 주세요.")
            return
        self.profiles[brand] = BrandProfile(
            name=brand,
            rules_path=self.rules_path_var.get().strip(),
            download_folder=self.download_folder_var.get().strip(),
            template_path=self.template_path_var.get().strip(),
            output_root=self.output_root_var.get().strip() or str(DEFAULT_OUTPUT_ROOT),
            upload_csv=self.upload_csv_var.get().strip(),
            login_command=self.login_command_var.get().strip(),
            downloader_command=self.downloader_command_var.get().strip(),
        )
        try:
            path = save_profiles(self.profiles)
        except OSError as exc:
            self._log(f"[경고] 브랜드 설정 저장 실패: {exc}")
            return
        self._refresh_brand_values()
        self._log(f"[완료] 브랜드 설정 저장: {path.resolve()}")

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
        if not force_empty_only or not self.upload_csv_var.get().strip() or _is_old_auto_output_path(self.upload_csv_var.get()):
            self.upload_csv_var.set(str(upload_csv))
        if not force_empty_only or not self.output_path_var.get().strip() or _is_old_auto_output_path(self.output_path_var.get()):
            self.output_path_var.set(str(output_path))

    def _choose_download_folder(self) -> None:
        selected = filedialog.askdirectory(title="다운로드 결과 상위 폴더")
        if selected:
            self.download_folder_var.set(selected)

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

    def _run_process_folder(self) -> None:
        self._run_background(self._process_folder)

    def _run_template_update(self) -> None:
        self._run_background(self._template_update)

    def _run_all(self) -> None:
        self._run_background(lambda: (self._process_folder(), self._template_update()))

    def _run_login_bot(self) -> None:
        self._run_background(lambda: self._run_external_command("로그인 봇", self.login_command_var.get().strip()))

    def _run_downloader(self) -> None:
        self._run_background(self._launch_downloader)

    def _run_register_schedule(self) -> None:
        self._run_background(self._register_windows_schedule)

    def _run_check_schedule(self) -> None:
        self._run_background(self._check_windows_schedule)

    def _open_index_editor(self) -> None:
        rules_path = self.rules_path_var.get().strip()
        if not rules_path:
            messagebox.showerror("오류", "규칙 파일을 먼저 선택해 주세요.")
            return
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
            if self.schedule_mode_var.get() == "공휴일 수동":
                if not self.custom_start_var.get().strip() or not self.custom_end_var.get().strip():
                    self.download_window_var.set("수동 기간을 입력해 주세요")
                    self.folder_date_var.set(parse_date(run_date).strftime("%Y-%m-%d"))
                    return
                window = custom_download_window(self.custom_start_var.get().strip(), self.custom_end_var.get().strip())
            else:
                window = default_download_window(run_date)
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
        if not result.raw_files or result.total_rows <= 0:
            raise ValueError("처리된 데이터가 없습니다. 다운로드 폴더와 실행 기준일을 확인해 주세요.")
        self._log(f"[완료] 업로드 CSV 생성: {result.output_path}")
        self._log(f"  raw 파일 수: {len(result.raw_files)}")
        self._log(f"  변환 행 수: {result.total_rows}")
        if result.duplicate_rows:
            self._log(f"  중복 의심 행 수: {result.duplicate_rows}")
        for category, count in sorted(result.category_counts.items(), key=lambda item: (-item[1], item[0])):
            self._log(f"  {category}: {count}")

    def _process_folder_once(self):
        return process_download_folder(
            brand=self.brand_var.get().strip(),
            download_folder=self.download_folder_var.get().strip(),
            rules_path=self.rules_path_var.get().strip(),
            output_path=self.upload_csv_var.get().strip(),
            folder_date=self.folder_date_var.get().strip() or None,
        )

    def _run_downloader_if_configured(self) -> None:
        command = self.downloader_command_var.get().strip()
        if not command:
            raise FileNotFoundError("raw file not found and downloader command is empty.")
        self._run_external_command("downloader", command)

    def _launch_downloader(self) -> None:
        self._launch_external_command("downloader", self.downloader_command_var.get().strip())

    def _run_downloader_until_raw_available(self):
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
            self._log("[auto] Raw files found after downloader launch.")
            return result
        raise TimeoutError("downloader raw files were not found within 30 minutes.")

    def _template_update(self) -> None:
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
        result = write_brand_template(
            brand=self.brand_var.get().strip(),
            template_path=self.template_path_var.get().strip(),
            output_path=self.output_path_var.get().strip(),
            rows=rows,
            run_date=self.run_date_var.get().strip() or None,
        )
        if result.written_rows <= 0:
            raise ValueError("템플릿에 반영된 행이 없습니다. 실행 기준일, 시트명, 카테고리 규칙을 확인해 주세요.")
        self._log(f"[완료] 템플릿 반영: {result.output_path}")
        self._log(f"  반영 행 수: {result.written_rows}")
        self._log(f"  수정 시트: {', '.join(result.touched_sheets) if result.touched_sheets else '(없음)'}")

    def _validate_file_inputs(self, *, require_template: bool) -> None:
        self._set_default_paths(force_empty_only=True)
        if not self.brand_var.get().strip():
            raise ValueError("브랜드를 입력해 주세요.")
        rules_path = self.rules_path_var.get().strip()
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
        config_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
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


def _normalize_external_command(command: str) -> str:
    text = str(command or "").strip()
    if text.endswith(" 실행"):
        text = text[: -len(" 실행")].strip()
    return text


def main() -> None:
    parser = argparse.ArgumentParser(description="브랜드 파일 가공 UI")
    parser.parse_args()
    app = UploadProcessorApp()
    app.mainloop()


if __name__ == "__main__":
    main()
