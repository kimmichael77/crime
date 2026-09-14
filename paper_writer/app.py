"""Tkinter GUI — cross-platform (Windows / macOS / Linux).

Layout:
+---------------------+-------------------------------+
| controls / status   |   coding form (scrollable)    |
| judgment text view  |                               |
+---------------------+-------------------------------+

Workflow:
  1. 코딩시트(.xlsx) 지정 → 없으면 사용자가 첨부한 v1.1 파일로 초기화
  2. 판결문 파일 로드 (.pdf/.docx/.txt/.md)
  3. AI 추출 → 폼에 초안 채우기 (스트리밍)
  4. 사람이 검토·수정
  5. 저장 → xlsx에 upsert + .bak 자동 생성

Tkinter는 파이썬 표준 라이브러리이므로 Windows/macOS 모두 별도 설치가 필요 없다.
"""

from __future__ import annotations

import os
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Optional

from . import analyzer, extractor, pdf_reader, xlsx_io
from .codebook import FIELDS, FIELDS_BY_NAME, coded_fields, is_hypothetical


DEFAULT_XLSX = Path.cwd() / "data" / "coding_sheet.xlsx"


class PaperWriterApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title("박사논문 판결문 코딩 워크벤치 v0.1")
        root.geometry("1400x900")

        self.workbook: Optional[xlsx_io.Workbook] = None
        self.judgment_text: str = ""
        self.judgment_path: Optional[Path] = None
        self.form_vars: dict[str, tk.Variable] = {}
        self.notes_widget: Optional[tk.Text] = None
        self.msg_queue: "queue.Queue[tuple[str, object]]" = queue.Queue()

        self._build_menu()
        self._build_main()
        self._poll_queue()

    # ---------- UI construction ----------

    def _build_menu(self) -> None:
        menubar = tk.Menu(self.root)
        filem = tk.Menu(menubar, tearoff=0)
        filem.add_command(label="코딩시트(.xlsx) 열기...", command=self._open_workbook)
        filem.add_command(label="판결문 파일 열기...", command=self._open_judgment)
        filem.add_separator()
        filem.add_command(label="종료", command=self.root.quit)
        menubar.add_cascade(label="파일", menu=filem)

        helpm = tk.Menu(menubar, tearoff=0)
        helpm.add_command(label="코딩북 v1.1 요약", command=self._show_codebook_help)
        helpm.add_command(label="정보", command=self._show_about)
        menubar.add_cascade(label="도움말", menu=helpm)
        self.root.config(menu=menubar)

    def _build_main(self) -> None:
        paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)

        left = ttk.Frame(paned, padding=6)
        paned.add(left, weight=3)
        self._build_left(left)

        right = ttk.Frame(paned, padding=6)
        paned.add(right, weight=4)
        self._build_form(right)

        self.status = tk.StringVar(value="준비됨. 상단 메뉴에서 코딩시트와 판결문을 여세요.")
        ttk.Label(self.root, textvariable=self.status,
                  relief=tk.SUNKEN, anchor=tk.W).pack(fill=tk.X, side=tk.BOTTOM)

    def _build_left(self, parent: ttk.Frame) -> None:
        top = ttk.Frame(parent)
        top.pack(fill=tk.X)

        self.workbook_lbl = ttk.Label(top, text="코딩시트: (미지정)")
        self.workbook_lbl.pack(anchor=tk.W)
        self.judgment_lbl = ttk.Label(top, text="판결문: (미지정)")
        self.judgment_lbl.pack(anchor=tk.W, pady=(2, 4))

        btnrow = ttk.Frame(top)
        btnrow.pack(fill=tk.X, pady=4)
        ttk.Button(btnrow, text="1. 코딩시트 열기",
                   command=self._open_workbook).pack(side=tk.LEFT, padx=2)
        ttk.Button(btnrow, text="2. 판결문 열기",
                   command=self._open_judgment).pack(side=tk.LEFT, padx=2)
        self.extract_btn = ttk.Button(btnrow, text="3. AI 코딩 초안 추출",
                                      command=self._run_extract, state=tk.DISABLED)
        self.extract_btn.pack(side=tk.LEFT, padx=2)
        self.save_btn = ttk.Button(btnrow, text="4. 저장",
                                   command=self._save_row, state=tk.DISABLED)
        self.save_btn.pack(side=tk.LEFT, padx=2)

        ttk.Label(parent, text="판결문 원문",
                  font=("TkDefaultFont", 10, "bold")).pack(anchor=tk.W, pady=(6, 2))

        wrap = ttk.Frame(parent)
        wrap.pack(fill=tk.BOTH, expand=True)
        self.text_view = tk.Text(wrap, wrap="word", height=25)
        vsb = ttk.Scrollbar(wrap, orient=tk.VERTICAL, command=self.text_view.yview)
        self.text_view.configure(yscrollcommand=vsb.set)
        self.text_view.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

    def _build_form(self, parent: ttk.Frame) -> None:
        ttk.Label(parent, text="코딩 폼 (AI 초안 → 검토·수정)",
                  font=("TkDefaultFont", 10, "bold")).pack(anchor=tk.W)

        canvas = tk.Canvas(parent, highlightthickness=0)
        vsb = ttk.Scrollbar(parent, orient=tk.VERTICAL, command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        inner = ttk.Frame(canvas)
        window = canvas.create_window((0, 0), window=inner, anchor="nw")

        def _on_frame(event):
            canvas.configure(scrollregion=canvas.bbox("all"))
        inner.bind("<Configure>", _on_frame)

        def _on_canvas(event):
            canvas.itemconfigure(window, width=event.width)
        canvas.bind("<Configure>", _on_canvas)

        # Bind mouse wheel scrolling to inner canvas
        def _wheel(e):
            canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", _wheel)

        self._build_form_fields(inner)

    def _build_form_fields(self, parent: ttk.Frame) -> None:
        row = 0
        current_category = None
        for f in FIELDS:
            if f.category != current_category:
                current_category = f.category
                ttk.Separator(parent, orient=tk.HORIZONTAL).grid(
                    row=row, column=0, columnspan=3, sticky="ew", pady=(6, 2))
                row += 1
                ttk.Label(parent, text=f"── {current_category} ──",
                          font=("TkDefaultFont", 9, "bold"),
                          foreground="#3060a0").grid(
                    row=row, column=0, columnspan=3, sticky="w")
                row += 1

            marker = " *" if is_hypothetical(f.name) else ""
            computed = " (자동계산)" if f.computed else ""
            label_text = f"{f.name}{marker}{computed}"
            ttk.Label(parent, text=label_text).grid(
                row=row, column=0, sticky="w", padx=(4, 8), pady=1)

            if f.name == "coding_note":
                widget = tk.Text(parent, height=4, width=44, wrap="word")
                widget.grid(row=row, column=1, sticky="ew", padx=2, pady=1)
                self.notes_widget = widget
                var = None
            elif f.choices:
                var = tk.StringVar()
                options = [""] + [f"{k} = {v}" for k, v in f.choices.items()]
                cb = ttk.Combobox(parent, textvariable=var, values=options,
                                  state="readonly", width=32)
                cb.grid(row=row, column=1, sticky="ew", padx=2, pady=1)
                self.form_vars[f.name] = var
            else:
                var = tk.StringVar()
                entry = ttk.Entry(parent, textvariable=var, width=34)
                entry.grid(row=row, column=1, sticky="ew", padx=2, pady=1)
                self.form_vars[f.name] = var

            if f.computed:
                # visually disabled but still displays value we set
                if isinstance(var, tk.StringVar):
                    pass  # value is set programmatically

            hint = ttk.Label(parent, text=f.definition[:38], foreground="#666")
            hint.grid(row=row, column=2, sticky="w", padx=2)
            row += 1

        parent.grid_columnconfigure(1, weight=1)

    # ---------- Actions ----------

    def _open_workbook(self) -> None:
        path = filedialog.askopenfilename(
            title="코딩시트(.xlsx) 선택",
            filetypes=[("Excel workbook", "*.xlsx"), ("All files", "*.*")],
            initialdir=str(DEFAULT_XLSX.parent) if DEFAULT_XLSX.parent.exists()
            else str(Path.cwd()),
        )
        if not path:
            return
        try:
            self.workbook = xlsx_io.Workbook(path)
        except Exception as exc:
            messagebox.showerror("코딩시트 열기 실패", str(exc))
            return
        self.workbook_lbl.config(text=f"코딩시트: {path}")
        self.status.set(
            f"코딩시트 열림. 현재 {len(self.workbook.all_case_ids())}건 코딩 완료."
        )
        self._update_button_state()

    def _open_judgment(self) -> None:
        path = filedialog.askopenfilename(
            title="판결문 파일 선택",
            filetypes=[
                ("판결문 파일", "*.pdf *.docx *.txt *.md"),
                ("PDF", "*.pdf"), ("DOCX", "*.docx"),
                ("Text", "*.txt *.md"), ("All", "*.*"),
            ],
        )
        if not path:
            return
        try:
            text = pdf_reader.read(path)
        except Exception as exc:
            messagebox.showerror("판결문 읽기 실패", str(exc))
            return
        self.judgment_text = text
        self.judgment_path = Path(path)
        self.judgment_lbl.config(text=f"판결문: {path}")
        self.text_view.delete("1.0", tk.END)
        self.text_view.insert("1.0", text)
        self.status.set(f"판결문 로드됨 ({len(text):,}자). AI 코딩 초안을 추출하세요.")
        self._update_button_state()

    def _update_button_state(self) -> None:
        state = tk.NORMAL if (self.workbook and self.judgment_text) else tk.DISABLED
        self.extract_btn.config(state=state)
        self.save_btn.config(state=tk.NORMAL if self.workbook else tk.DISABLED)

    def _run_extract(self) -> None:
        if not self.judgment_text or not self.workbook:
            return
        if not os.environ.get("ANTHROPIC_API_KEY"):
            messagebox.showerror(
                "API 키 필요",
                "ANTHROPIC_API_KEY 환경변수가 설정되어 있지 않습니다.\n\n"
                "Windows PowerShell:\n  setx ANTHROPIC_API_KEY \"sk-ant-...\"\n\n"
                "macOS 터미널:\n  export ANTHROPIC_API_KEY=\"sk-ant-...\"",
            )
            return

        self.extract_btn.config(state=tk.DISABLED)
        self.status.set("AI 추출 중... (스트리밍)")
        threading.Thread(target=self._extract_thread, daemon=True).start()

    def _extract_thread(self) -> None:
        try:
            case_id = self.workbook.next_case_id() if self.workbook else "DF-XXXX-XXX"
            row = extractor.extract(
                self.judgment_text,
                on_delta=lambda t: self.msg_queue.put(("status_delta", t)),
                case_id=case_id,
            )
            row = analyzer.compute_all(row)
            self.msg_queue.put(("extracted", row))
        except Exception as exc:
            self.msg_queue.put(("error", str(exc)))

    def _poll_queue(self) -> None:
        try:
            while True:
                kind, payload = self.msg_queue.get_nowait()
                if kind == "status_delta":
                    # Streaming heartbeat — keep the UI responsive.
                    self.status.set("AI 추출 중... " + str(payload)[-40:].replace("\n", " "))
                elif kind == "extracted":
                    self._fill_form(payload)
                    self.status.set(f"초안 추출 완료 — case_id={payload.get('case_id')}. 검토 후 저장하세요.")
                    self.extract_btn.config(state=tk.NORMAL)
                elif kind == "error":
                    messagebox.showerror("AI 추출 실패", str(payload))
                    self.status.set("오류 발생. 다시 시도할 수 있습니다.")
                    self.extract_btn.config(state=tk.NORMAL)
        except queue.Empty:
            pass
        self.root.after(120, self._poll_queue)

    def _fill_form(self, row: dict) -> None:
        for name, var in self.form_vars.items():
            v = row.get(name)
            if v is None:
                var.set("")
                continue
            field = FIELDS_BY_NAME[name]
            if field.choices and isinstance(v, (int, float)):
                v_int = int(round(v))
                label = field.choices.get(v_int, "")
                var.set(f"{v_int} = {label}" if label else str(v_int))
            else:
                var.set(str(v))
        if self.notes_widget is not None:
            self.notes_widget.delete("1.0", tk.END)
            note = row.get("coding_note", "") or ""
            self.notes_widget.insert("1.0", note)

    def _read_form(self) -> dict:
        row: dict = {}
        for name, var in self.form_vars.items():
            text_val = var.get().strip()
            if not text_val:
                row[name] = None
                continue
            field = FIELDS_BY_NAME[name]
            if field.choices:
                # combobox returns "1 = 실형"; take the code before "="
                code = text_val.split("=", 1)[0].strip()
                try:
                    row[name] = int(code)
                except ValueError:
                    row[name] = None
            elif field.kind == "int":
                try:
                    row[name] = int(round(float(text_val)))
                except ValueError:
                    row[name] = None
            elif field.kind == "float":
                try:
                    row[name] = float(text_val)
                except ValueError:
                    row[name] = None
            elif field.kind == "date":
                row[name] = text_val[:10]
            else:
                row[name] = text_val
        if self.notes_widget is not None:
            row["coding_note"] = self.notes_widget.get("1.0", tk.END).strip()
        return row

    def _save_row(self) -> None:
        if not self.workbook:
            return
        row = self._read_form()
        if not row.get("case_id"):
            messagebox.showwarning("저장 불가", "case_id가 비어 있습니다.")
            return
        # Recompute derived variables from the current form values before saving.
        row = analyzer.compute_all(row)
        self._fill_form(row)  # reflect computed values back into the form
        try:
            r = self.workbook.upsert(row)
            self.workbook.save(backup=True)
        except Exception as exc:
            messagebox.showerror("저장 실패", str(exc))
            return
        self.status.set(
            f"저장 완료 — case_id={row['case_id']} (행 {r}). 백업(.bak) 파일이 함께 생성되었습니다."
        )

    # ---------- Help dialogs ----------

    def _show_codebook_help(self) -> None:
        text = (
            "코딩북 v1.1 핵심 규칙\n\n"
            "[규칙 1] 판결문에 명시된 사항만 코딩. 미기재는 -99(수치) 또는 9(범주). "
            "추론한 변수는 inferred_vars에 기재하고 coding_note에 근거 명시.\n\n"
            "[규칙 2] 양형기준 관련 변수는 '허위영상물 등의 반포 등' 유형만 코딩. "
            "다른 죄 기준이 있어도 미기재 시 전부 결측. "
            "다수범죄 처리기준은 multi_offense_* 에 별도 기록(상대위치 계산에는 사용 안 함).\n\n"
            "자동계산 변수: guideline_deviation, deviation_direction, "
            "guideline_rel_position, area_rel_position, appeal_duration, law_period.\n"
            "부진정하향이탈 임계값: rel_position ≤ 0.15 (설정 파일에서 변경 가능)."
        )
        messagebox.showinfo("코딩북 v1.1", text)

    def _show_about(self) -> None:
        messagebox.showinfo(
            "정보",
            "박사논문 판결문 코딩 워크벤치 v0.1\n\n"
            "딥페이크 디지털 성범죄 양형 결정요인 연구용.\n"
            "Windows/macOS 크로스플랫폼 (Python + Tkinter).\n\n"
            "논문 저자: (연구자)\n"
            "AI 추출: Claude Opus 5",
        )


def main() -> None:
    root = tk.Tk()
    PaperWriterApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
