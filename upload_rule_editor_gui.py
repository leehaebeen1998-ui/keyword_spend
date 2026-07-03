from __future__ import annotations

import argparse
import base64
import csv
import errno
import io
import os
import subprocess
import tempfile
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk


HEADERS = ("브랜드", "매체", "순위", "규칙", "매칭값", "카테고리", "신뢰도", "사용", "메모")
MEDIA_VALUES = ("전체", "Naver", "Google SA")
RULE_TYPES = {
    0: ("계정번호", "계정번호"),
    1: ("지정 URL", "지정 URL"),
    2: ("캠페인명", "캠페인명"),
}


class UploadRuleEditor(tk.Tk):
    def __init__(self, rules_path: Path) -> None:
        super().__init__()
        self.title("브랜드 업로드 규칙")
        self.geometry("900x560")
        self.minsize(780, 480)

        self.rules_path = rules_path
        self.rows = self._read_rows()
        self.widgets: dict[int, dict[str, object]] = {}
        self.brand_var = tk.StringVar()
        self.editing_index_by_priority: dict[int, int | None] = {priority: None for priority in RULE_TYPES}

        self._build_header()
        self._build_brand_selector()
        self._build_tabs()
        self._set_initial_brand()
        self._refresh_all()

    def _build_header(self) -> None:
        frame = ttk.Frame(self, padding=(12, 10))
        frame.pack(fill="x")

        ttk.Label(frame, text="규칙 파일").pack(side="left")
        self.path_var = tk.StringVar(value=str(self.rules_path))
        ttk.Entry(frame, textvariable=self.path_var, state="readonly").pack(side="left", fill="x", expand=True, padx=8)
        ttk.Button(frame, text="열기", command=self._choose_file).pack(side="left")
        ttk.Button(frame, text="저장", command=self._save_rows).pack(side="left", padx=(6, 0))
        ttk.Button(frame, text="다른 이름", command=self._save_as).pack(side="left", padx=(6, 0))

    def _build_brand_selector(self) -> None:
        frame = ttk.Frame(self, padding=(12, 0, 12, 10))
        frame.pack(fill="x")

        ttk.Label(frame, text="브랜드").pack(side="left")
        self.brand_combo = ttk.Combobox(
            frame,
            textvariable=self.brand_var,
            values=self._brand_values(),
            width=28,
        )
        self.brand_combo.pack(side="left", padx=(8, 0))
        self.brand_combo.bind("<<ComboboxSelected>>", lambda _event: self._refresh_all())
        self.brand_combo.bind("<Return>", lambda _event: self._refresh_all())
        ttk.Button(frame, text="브랜드 적용", command=self._refresh_all).pack(side="left", padx=(6, 0))
        ttk.Button(frame, text="브랜드 추가", command=self._add_brand).pack(side="left", padx=(6, 0))

    def _build_tabs(self) -> None:
        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        for priority, (label, match_label) in RULE_TYPES.items():
            tab = ttk.Frame(notebook, padding=12)
            notebook.add(tab, text=f"{priority} {label}")
            self._build_tab(tab, priority, label, match_label)

    def _build_tab(self, parent: ttk.Frame, priority: int, label: str, match_label: str) -> None:
        form = ttk.LabelFrame(parent, text=f"{priority}순위 - {label}", padding=12)
        form.pack(fill="x")
        form.columnconfigure(1, weight=1)
        form.columnconfigure(3, weight=1)

        match_var = tk.StringVar()
        media_var = tk.StringVar(value="전체")
        category_var = tk.StringVar()
        confidence_var = tk.StringVar(value="1")
        memo_var = tk.StringVar()

        ttk.Label(form, text=match_label).grid(row=0, column=0, sticky="w")
        ttk.Entry(form, textvariable=match_var).grid(row=0, column=1, sticky="ew", padx=(8, 16))
        ttk.Label(form, text="카테고리").grid(row=0, column=2, sticky="w")
        ttk.Entry(form, textvariable=category_var).grid(row=0, column=3, sticky="ew", padx=(8, 0))

        ttk.Label(form, text="매체").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Combobox(form, textvariable=media_var, values=MEDIA_VALUES, width=12, state="readonly").grid(row=1, column=1, sticky="w", padx=(8, 16), pady=(8, 0))
        ttk.Label(form, text="신뢰도").grid(row=1, column=2, sticky="w", pady=(8, 0))
        ttk.Entry(form, textvariable=confidence_var, width=10).grid(row=1, column=3, sticky="w", padx=(8, 0), pady=(8, 0))

        ttk.Label(form, text="메모").grid(row=2, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(form, textvariable=memo_var).grid(row=2, column=1, columnspan=3, sticky="ew", padx=(8, 0), pady=(8, 0))

        buttons = ttk.Frame(form)
        buttons.grid(row=3, column=0, columnspan=4, sticky="e", pady=(10, 0))
        ttk.Button(buttons, text="규칙 저장", command=lambda: self._add_rule(priority)).pack(side="left")
        ttk.Button(buttons, text="수정 저장", command=lambda: self._update_rule(priority)).pack(side="left", padx=(6, 0))
        ttk.Button(buttons, text="입력 초기화", command=lambda: self._clear(priority)).pack(side="left", padx=(6, 0))

        table_frame = ttk.LabelFrame(parent, text="저장된 규칙", padding=8)
        table_frame.pack(fill="both", expand=True, pady=(12, 0))
        columns = ("no", "brand", "media", "match", "category", "confidence", "enabled", "memo")
        tree = ttk.Treeview(table_frame, columns=columns, show="headings", height=10)
        for column, text, width in (
            ("no", "번호", 60),
            ("brand", "브랜드", 160),
            ("media", "매체", 90),
            ("match", "매칭값", 220),
            ("category", "카테고리", 120),
            ("confidence", "신뢰도", 80),
            ("enabled", "사용", 60),
            ("memo", "메모", 220),
        ):
            tree.heading(column, text=text)
            tree.column(column, width=width, anchor="center" if column in {"no", "confidence", "enabled"} else "w")
        tree.pack(side="left", fill="both", expand=True)
        tree.bind("<Double-1>", lambda _event, p=priority: self._load_selected_rule(p))
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")

        bottom = ttk.Frame(parent)
        bottom.pack(fill="x", pady=(8, 0))
        ttk.Button(bottom, text="선택 규칙 삭제", command=lambda: self._delete_selected(priority)).pack(side="right")
        ttk.Button(bottom, text="선택 규칙 불러오기", command=lambda: self._load_selected_rule(priority)).pack(side="right", padx=(0, 6))

        self.widgets[priority] = {
            "match": match_var,
            "media": media_var,
            "category": category_var,
            "confidence": confidence_var,
            "memo": memo_var,
            "tree": tree,
        }

    def _add_brand(self) -> None:
        name = simpledialog.askstring("브랜드 추가", "추가할 브랜드명을 입력해 주세요.", parent=self)
        if not name:
            return
        name = name.strip()
        if not name:
            return
        self.brand_var.set(name)
        self.brand_combo.configure(values=self._brand_values())
        self._refresh_all()

    def _add_rule(self, priority: int) -> None:
        widget = self.widgets[priority]
        brand = self.brand_var.get().strip()
        match_value = self._get_var(widget, "match").get().strip()
        media = self._get_var(widget, "media").get().strip() or "전체"
        category = self._get_var(widget, "category").get().strip()
        confidence = self._get_var(widget, "confidence").get().strip() or "1"
        memo = self._get_var(widget, "memo").get().strip()
        if not brand or not match_value or not category:
            messagebox.showwarning("입력 필요", "브랜드, 매칭값, 카테고리를 입력해 주세요.")
            return
        label = RULE_TYPES[priority][0]
        self.rows.append(
            {
                "브랜드": brand,
                "매체": "" if media == "전체" else media,
                "순위": str(priority),
                "규칙": label,
                "매칭값": match_value,
                "카테고리": category,
                "신뢰도": confidence,
                "사용": "O",
                "메모": memo,
            }
        )
        self._clear(priority)
        self._refresh_brand_values()
        self._refresh_all()

    def _update_rule(self, priority: int) -> None:
        row_index = self.editing_index_by_priority.get(priority)
        if row_index is None:
            messagebox.showwarning("선택 필요", "수정할 규칙을 더블클릭하거나 선택 후 불러오세요.")
            return
        if row_index < 0 or row_index >= len(self.rows):
            messagebox.showwarning("선택 오류", "선택한 규칙을 찾을 수 없습니다.")
            self.editing_index_by_priority[priority] = None
            return

        widget = self.widgets[priority]
        brand = self.brand_var.get().strip()
        match_value = self._get_var(widget, "match").get().strip()
        media = self._get_var(widget, "media").get().strip() or "전체"
        category = self._get_var(widget, "category").get().strip()
        confidence = self._get_var(widget, "confidence").get().strip() or "1"
        memo = self._get_var(widget, "memo").get().strip()
        if not brand or not match_value or not category:
            messagebox.showwarning("입력 필요", "브랜드, 매칭값, 카테고리를 입력해 주세요.")
            return

        self.rows[row_index] = {
            "브랜드": brand,
            "매체": "" if media == "전체" else media,
            "순위": str(priority),
            "규칙": RULE_TYPES[priority][0],
            "매칭값": match_value,
            "카테고리": category,
            "신뢰도": confidence,
            "사용": "O",
            "메모": memo,
        }
        self._clear(priority)
        self._refresh_brand_values()
        self._refresh_all()

    def _load_selected_rule(self, priority: int) -> None:
        tree = self._get_tree(priority)
        selected = tree.selection()
        if not selected:
            return
        no = int(tree.item(selected[0])["values"][0])
        row_index = no - 1
        if row_index < 0 or row_index >= len(self.rows):
            return
        row = self.rows[row_index]
        self.editing_index_by_priority[priority] = row_index
        self.brand_var.set(str(row.get("브랜드", "")))
        widget = self.widgets[priority]
        self._get_var(widget, "match").set(str(row.get("매칭값", "")))
        self._get_var(widget, "media").set(str(row.get("매체", "") or "전체"))
        self._get_var(widget, "category").set(str(row.get("카테고리", "")))
        self._get_var(widget, "confidence").set(str(row.get("신뢰도", "1") or "1"))
        self._get_var(widget, "memo").set(str(row.get("메모", "")))

    def _delete_selected(self, priority: int) -> None:
        tree = self._get_tree(priority)
        selected = tree.selection()
        if not selected:
            return
        no = int(tree.item(selected[0])["values"][0])
        del self.rows[no - 1]
        self.editing_index_by_priority[priority] = None
        self._refresh_all()

    def _clear(self, priority: int) -> None:
        widget = self.widgets[priority]
        for key in ("match", "category", "memo"):
            self._get_var(widget, key).set("")
        self._get_var(widget, "media").set("전체")
        self._get_var(widget, "confidence").set("1")
        self.editing_index_by_priority[priority] = None

    def _refresh_all(self) -> None:
        selected_brand = self.brand_var.get().strip()
        for priority in RULE_TYPES:
            tree = self._get_tree(priority)
            for item in tree.get_children():
                tree.delete(item)
            for index, row in enumerate(self.rows, start=1):
                if str(row.get("순위", "")) != str(priority):
                    continue
                if selected_brand and str(row.get("브랜드", "")).strip() != selected_brand:
                    continue
                tree.insert(
                    "",
                    "end",
                    values=(
                        index,
                        row.get("브랜드", ""),
                        row.get("매체", "") or "전체",
                        row.get("매칭값", ""),
                        row.get("카테고리", ""),
                        row.get("신뢰도", ""),
                        row.get("사용", ""),
                        row.get("메모", ""),
                    ),
                )

    def _choose_file(self) -> None:
        selected = filedialog.askopenfilename(filetypes=[("CSV files", "*.csv"), ("All files", "*.*")])
        if not selected:
            return
        self.rules_path = Path(selected)
        self.path_var.set(str(self.rules_path))
        self.rows = self._read_rows()
        self._refresh_brand_values()
        self._set_initial_brand()
        self._refresh_all()

    def _save_as(self) -> None:
        selected = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV files", "*.csv")])
        if not selected:
            return
        self.rules_path = Path(selected)
        self.path_var.set(str(self.rules_path))
        self._save_rows()

    def _read_rows(self) -> list[dict[str, str]]:
        if not self.rules_path.exists():
            return []
        with self.rules_path.open("r", encoding="utf-8-sig", newline="") as file:
            return [dict(row) for row in csv.DictReader(file)]

    def _save_rows(self) -> None:
        try:
            saved_path = _write_upload_rule_rows(self.rules_path, self.rows)
        except OSError as exc:
            messagebox.showerror("저장 실패", str(exc))
            return
        if saved_path != self.rules_path:
            self.rules_path = saved_path
            self.path_var.set(str(self.rules_path))
            messagebox.showwarning("사본 저장 완료", f"원본 파일을 덮어쓸 수 없어 사본으로 저장했습니다.\n{self.rules_path}")
            return
        messagebox.showinfo("저장 완료", f"규칙을 저장했습니다.\n{self.rules_path}")

    def _brand_values(self) -> list[str]:
        values = sorted({str(row.get("브랜드", "")).strip() for row in self.rows if str(row.get("브랜드", "")).strip()})
        defaults = ["법무법인 태하", "법무법인 오현"]
        for brand in reversed(defaults):
            if brand not in values:
                values.insert(0, brand)
        return values

    def _refresh_brand_values(self) -> None:
        self.brand_combo["values"] = self._brand_values()

    def _set_initial_brand(self) -> None:
        values = self._brand_values()
        current = self.brand_var.get().strip()
        if current in values:
            return
        self.brand_var.set(values[0] if values else "")

    def _get_var(self, widget: dict[str, object], key: str) -> tk.StringVar:
        value = widget[key]
        if not isinstance(value, tk.StringVar):
            raise TypeError(key)
        return value

    def _get_tree(self, priority: int) -> ttk.Treeview:
        value = self.widgets[priority]["tree"]
        if not isinstance(value, ttk.Treeview):
            raise TypeError("tree")
        return value


def main() -> None:
    parser = argparse.ArgumentParser(description="브랜드 업로드 규칙 편집기")
    parser.add_argument("rules", nargs="?", default="examples/brand-upload-rules.example.csv")
    args = parser.parse_args()
    app = UploadRuleEditor(Path(args.rules))
    app.mainloop()


def _write_upload_rule_rows(path: Path, rows: list[dict[str, str]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = io.StringIO(newline="")
    writer = csv.DictWriter(content, fieldnames=list(HEADERS), extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return _write_text(path, content.getvalue())


def _write_text(path: Path, content: str) -> Path:
    try:
        _write_text_atomic(path, content)
        return path
    except OSError as exc:
        first_error = exc

    try:
        with open(os.fspath(path), "w", encoding="utf-8-sig", newline="") as file:
            file.write(content)
        return path
    except OSError as exc:
        first_error = first_error if first_error else exc

    try:
        _write_text_low_level(path, content)
        return path
    except OSError:
        pass

    try:
        _write_text_with_powershell(path, content, first_error)
        return path
    except OSError as exc:
        return _write_text_fallback_copy(path, content, exc)


def _write_text_atomic(path: Path, content: str) -> None:
    directory = path.parent
    with tempfile.NamedTemporaryFile("w", encoding="utf-8-sig", newline="", delete=False, dir=directory, suffix=".tmp") as file:
        file.write(content)
        temp_path = Path(file.name)
    try:
        os.replace(os.fspath(temp_path), os.fspath(path))
    except OSError:
        try:
            temp_path.unlink()
        except OSError:
            pass
        raise


def _write_text_low_level(path: Path, content: str) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    descriptor = os.open(os.fspath(path), flags, 0o666)
    try:
        data = content.encode("utf-8-sig")
        while data:
            written = os.write(descriptor, data)
            data = data[written:]
    finally:
        os.close(descriptor)


def _write_text_with_powershell(path: Path, content: str, original_error: OSError) -> None:
    command = (
        "$target = $env:UPLOAD_RULE_TARGET_PATH; "
        "$dir = [System.IO.Path]::GetDirectoryName($target); "
        "if ($dir) { [System.IO.Directory]::CreateDirectory($dir) | Out-Null }; "
        "$base64 = [Console]::In.ReadToEnd(); "
        "$bytes = [Convert]::FromBase64String($base64); "
        "[System.IO.File]::WriteAllBytes($target, $bytes)"
    )
    encoded = base64.b64encode(content.encode("utf-8-sig")).decode("ascii")
    env = os.environ.copy()
    env["UPLOAD_RULE_TARGET_PATH"] = os.fspath(path)
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", command],
        input=encoded,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        check=False,
    )
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "").strip()
        raise OSError(f"{original_error}\nPowerShell fallback failed: {message}")


def _write_text_fallback_copy(path: Path, content: str, original_error: OSError) -> Path:
    safe_name = f"{path.stem}.saved{path.suffix or '.csv'}"
    fallback = Path(tempfile.gettempdir()) / safe_name
    try:
        with open(os.fspath(fallback), "w", encoding="utf-8-sig", newline="") as file:
            file.write(content)
        return fallback
    except OSError as exc:
        raise OSError(f"{original_error}\nFallback copy failed: {exc}") from exc


if __name__ == "__main__":
    main()
