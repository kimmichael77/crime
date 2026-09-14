"""Tkinter GUI — cross-platform (Windows / macOS / Linux).

세 개 탭:
  1. 판결문 코딩 — 판결문 → AI 추출 → 검토 → xlsx upsert
  2. 자료 라이브러리 — 선행연구·판례·법조문 등록·검색·목록
  3. 노트북 QA — 라이브러리 자료 안에서만 답하는 대화형 조수 (NotebookLM 스타일)
     + 섹션 초안 생성 · 다듬기 · 저장

Tkinter는 파이썬 표준 라이브러리이므로 Windows/macOS 모두 별도 설치 필요 없음.
"""

from __future__ import annotations

import os
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Optional

from . import analyzer, data_summary, drafter, extractor, notebook
from . import pdf_reader, writing_project as wp, xlsx_io
from .codebook import FIELDS, FIELDS_BY_NAME, is_hypothetical
from .library import Library, Source, KIND_CHOICES, seed_from_proposal


DEFAULT_XLSX = Path.cwd() / "data" / "coding_sheet.xlsx"
DEFAULT_PROJECT = Path.cwd() / "thesis_project"


class PaperWriterApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title("박사논문 워크벤치 v0.2 — 코딩 · 자료 · 노트북 · 초안")
        root.geometry("1500x950")

        # 세션 상태
        self.workbook: Optional[xlsx_io.Workbook] = None
        self.judgment_text: str = ""
        self.judgment_path: Optional[Path] = None
        self.form_vars: dict[str, tk.Variable] = {}
        self.notes_widget: Optional[tk.Text] = None

        self.project: Optional[wp.Project] = None
        self.project_dir: Optional[Path] = None
        self.library: Optional[Library] = None

        self.msg_queue: "queue.Queue[tuple[str, object]]" = queue.Queue()
        self._draft_target_key: Optional[str] = None

        self._build_menu()
        self._build_tabs()
        self._poll_queue()

    # ---------- Menu ----------

    def _build_menu(self) -> None:
        menubar = tk.Menu(self.root)

        filem = tk.Menu(menubar, tearoff=0)
        filem.add_command(label="논문 프로젝트 열기/만들기...", command=self._open_project)
        filem.add_command(label="코딩시트(.xlsx) 열기...", command=self._open_workbook)
        filem.add_command(label="판결문 파일 열기...", command=self._open_judgment)
        filem.add_separator()
        filem.add_command(label="종료", command=self.root.quit)
        menubar.add_cascade(label="파일", menu=filem)

        helpm = tk.Menu(menubar, tearoff=0)
        helpm.add_command(label="사용법", command=self._show_help)
        helpm.add_command(label="정보", command=self._show_about)
        menubar.add_cascade(label="도움말", menu=helpm)

        self.root.config(menu=menubar)

    def _build_tabs(self) -> None:
        self.tabs = ttk.Notebook(self.root)
        self.tabs.pack(fill=tk.BOTH, expand=True)

        self.coding_tab = ttk.Frame(self.tabs, padding=6)
        self.library_tab = ttk.Frame(self.tabs, padding=6)
        self.notebook_tab = ttk.Frame(self.tabs, padding=6)
        self.draft_tab = ttk.Frame(self.tabs, padding=6)

        self.tabs.add(self.coding_tab, text="1. 판결문 코딩")
        self.tabs.add(self.library_tab, text="2. 자료 라이브러리")
        self.tabs.add(self.notebook_tab, text="3. 노트북 QA")
        self.tabs.add(self.draft_tab, text="4. 섹션 초안")

        self._build_coding_tab(self.coding_tab)
        self._build_library_tab(self.library_tab)
        self._build_notebook_tab(self.notebook_tab)
        self._build_draft_tab(self.draft_tab)

        self.status = tk.StringVar(value="준비됨. 파일 메뉴에서 프로젝트와 코딩시트를 여세요.")
        ttk.Label(self.root, textvariable=self.status,
                  relief=tk.SUNKEN, anchor=tk.W).pack(fill=tk.X, side=tk.BOTTOM)

    # ---------- Coding Tab ----------

    def _build_coding_tab(self, parent: ttk.Frame) -> None:
        paned = ttk.PanedWindow(parent, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)

        left = ttk.Frame(paned, padding=6)
        paned.add(left, weight=3)

        top = ttk.Frame(left)
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

        ttk.Label(left, text="판결문 원문",
                  font=("TkDefaultFont", 10, "bold")).pack(anchor=tk.W, pady=(6, 2))

        wrap = ttk.Frame(left)
        wrap.pack(fill=tk.BOTH, expand=True)
        self.text_view = tk.Text(wrap, wrap="word", height=25)
        vsb = ttk.Scrollbar(wrap, orient=tk.VERTICAL, command=self.text_view.yview)
        self.text_view.configure(yscrollcommand=vsb.set)
        self.text_view.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        right = ttk.Frame(paned, padding=6)
        paned.add(right, weight=4)
        ttk.Label(right, text="코딩 폼 (AI 초안 → 검토·수정)",
                  font=("TkDefaultFont", 10, "bold")).pack(anchor=tk.W)

        canvas = tk.Canvas(right, highlightthickness=0)
        vsb2 = ttk.Scrollbar(right, orient=tk.VERTICAL, command=canvas.yview)
        canvas.configure(yscrollcommand=vsb2.set)
        vsb2.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        inner = ttk.Frame(canvas)
        window = canvas.create_window((0, 0), window=inner, anchor="nw")

        def _on_frame(event):
            canvas.configure(scrollregion=canvas.bbox("all"))
        inner.bind("<Configure>", _on_frame)

        def _on_canvas(event):
            canvas.itemconfigure(window, width=event.width)
        canvas.bind("<Configure>", _on_canvas)

        self._build_coding_form_fields(inner)

    def _build_coding_form_fields(self, parent: ttk.Frame) -> None:
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
            computed = " (자동)" if f.computed else ""
            ttk.Label(parent, text=f"{f.name}{marker}{computed}").grid(
                row=row, column=0, sticky="w", padx=(4, 8), pady=1)

            if f.name == "coding_note":
                widget = tk.Text(parent, height=4, width=44, wrap="word")
                widget.grid(row=row, column=1, sticky="ew", padx=2, pady=1)
                self.notes_widget = widget
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

            ttk.Label(parent, text=f.definition[:38], foreground="#666").grid(
                row=row, column=2, sticky="w", padx=2)
            row += 1

        parent.grid_columnconfigure(1, weight=1)

    # ---------- Library Tab ----------

    def _build_library_tab(self, parent: ttk.Frame) -> None:
        top = ttk.Frame(parent)
        top.pack(fill=tk.X, pady=(0, 4))

        self.project_lbl = ttk.Label(top, text="프로젝트: (미지정) — 파일 메뉴에서 열거나 만드세요")
        self.project_lbl.pack(side=tk.LEFT)
        ttk.Button(top, text="프로젝트 열기/만들기",
                   command=self._open_project).pack(side=tk.RIGHT, padx=2)

        controls = ttk.LabelFrame(parent, text="자료 등록", padding=6)
        controls.pack(fill=tk.X, pady=4)

        self.lib_form: dict[str, tk.Variable] = {}
        fields = [
            ("id", "자료 ID (예: 조혜민-2025)"),
            ("title", "제목"),
            ("authors", "저자"),
            ("year", "연도"),
            ("citation", "본문 인용 (예: 조혜민(2025))"),
            ("reference", "참고문헌 서지정보"),
            ("tags", "태그(쉼표)"),
            ("summary", "요약(선택)"),
        ]
        for i, (key, label) in enumerate(fields):
            ttk.Label(controls, text=label).grid(row=i, column=0, sticky="w", padx=4, pady=1)
            v = tk.StringVar()
            ent = ttk.Entry(controls, textvariable=v, width=60)
            ent.grid(row=i, column=1, sticky="ew", padx=4, pady=1)
            self.lib_form[key] = v

        ttk.Label(controls, text="종류").grid(row=len(fields), column=0, sticky="w", padx=4)
        self.lib_kind = tk.StringVar(value="선행연구")
        ttk.Combobox(controls, textvariable=self.lib_kind, values=KIND_CHOICES,
                     state="readonly", width=20).grid(row=len(fields), column=1, sticky="w", padx=4)

        self.lib_file_path = tk.StringVar()
        ttk.Label(controls, text="원본 파일(선택)").grid(row=len(fields) + 1, column=0, sticky="w", padx=4)
        filerow = ttk.Frame(controls)
        filerow.grid(row=len(fields) + 1, column=1, sticky="ew", padx=4)
        ttk.Entry(filerow, textvariable=self.lib_file_path, width=48).pack(side=tk.LEFT)
        ttk.Button(filerow, text="찾아보기",
                   command=self._pick_lib_file).pack(side=tk.LEFT, padx=4)

        btns = ttk.Frame(controls)
        btns.grid(row=len(fields) + 2, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        ttk.Button(btns, text="등록",
                   command=self._library_add).pack(side=tk.LEFT, padx=2)
        ttk.Button(btns, text="연구계획서 시드",
                   command=self._library_seed).pack(side=tk.LEFT, padx=2)
        ttk.Button(btns, text="선택 삭제",
                   command=self._library_delete).pack(side=tk.LEFT, padx=2)

        controls.grid_columnconfigure(1, weight=1)

        # 목록
        ttk.Label(parent, text="등록된 자료",
                  font=("TkDefaultFont", 10, "bold")).pack(anchor=tk.W, pady=(8, 2))
        search_row = ttk.Frame(parent)
        search_row.pack(fill=tk.X)
        self.lib_search = tk.StringVar()
        ttk.Entry(search_row, textvariable=self.lib_search, width=40).pack(side=tk.LEFT, padx=2)
        ttk.Button(search_row, text="검색",
                   command=self._library_refresh).pack(side=tk.LEFT, padx=2)
        ttk.Button(search_row, text="새로고침",
                   command=lambda: (self.lib_search.set(""), self._library_refresh())).pack(side=tk.LEFT, padx=2)

        cols = ("id", "kind", "year", "authors", "title", "tags")
        self.lib_tree = ttk.Treeview(parent, columns=cols, show="headings", height=18)
        for c, w in zip(cols, (140, 90, 60, 140, 380, 200)):
            self.lib_tree.heading(c, text=c)
            self.lib_tree.column(c, width=w, anchor="w")
        self.lib_tree.pack(fill=tk.BOTH, expand=True, pady=4)

    # ---------- Notebook QA Tab ----------

    def _build_notebook_tab(self, parent: ttk.Frame) -> None:
        top = ttk.Frame(parent)
        top.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(top, text="대화 이름").pack(side=tk.LEFT)
        self.chat_name = tk.StringVar(value="default")
        ttk.Entry(top, textvariable=self.chat_name, width=20).pack(side=tk.LEFT, padx=4)
        ttk.Label(top, text="  |  선택 자료 pinning(자료ID 쉼표):").pack(side=tk.LEFT)
        self.pinned_ids = tk.StringVar()
        ttk.Entry(top, textvariable=self.pinned_ids, width=40).pack(side=tk.LEFT, padx=4)

        ttk.Label(parent, text="대화 (자료 안에서만 답합니다)",
                  font=("TkDefaultFont", 10, "bold")).pack(anchor=tk.W)

        wrap = ttk.Frame(parent)
        wrap.pack(fill=tk.BOTH, expand=True)
        self.chat_view = tk.Text(wrap, wrap="word", height=20)
        vsb = ttk.Scrollbar(wrap, orient=tk.VERTICAL, command=self.chat_view.yview)
        self.chat_view.configure(yscrollcommand=vsb.set)
        self.chat_view.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        bottom = ttk.Frame(parent)
        bottom.pack(fill=tk.X, pady=(6, 0))
        self.question_var = tk.StringVar()
        ttk.Entry(bottom, textvariable=self.question_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)
        ttk.Button(bottom, text="질문",
                   command=self._notebook_ask).pack(side=tk.LEFT, padx=2)
        ttk.Button(bottom, text="주제 브리핑",
                   command=self._notebook_briefing).pack(side=tk.LEFT, padx=2)

    # ---------- Draft Tab ----------

    def _build_draft_tab(self, parent: ttk.Frame) -> None:
        paned = ttk.PanedWindow(parent, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)

        left = ttk.Frame(paned, padding=4)
        paned.add(left, weight=2)
        ttk.Label(left, text="논문 목차 (선택하면 오른쪽에서 편집)",
                  font=("TkDefaultFont", 10, "bold")).pack(anchor=tk.W)
        self.section_tree = ttk.Treeview(left, columns=("status", "pages"),
                                         show="tree headings", height=28)
        self.section_tree.heading("#0", text="섹션")
        self.section_tree.heading("status", text="상태")
        self.section_tree.heading("pages", text="쪽")
        self.section_tree.column("#0", width=280)
        self.section_tree.column("status", width=60, anchor="center")
        self.section_tree.column("pages", width=40, anchor="e")
        self.section_tree.pack(fill=tk.BOTH, expand=True, pady=4)
        self.section_tree.bind("<<TreeviewSelect>>", lambda e: self._section_selected())

        ttk.Button(left, text="전체 이어붙여 draft_paper.md 생성",
                   command=self._compile_draft).pack(fill=tk.X, pady=2)

        right = ttk.Frame(paned, padding=4)
        paned.add(right, weight=5)

        self.section_title_lbl = ttk.Label(right, text="(섹션 선택)",
                                           font=("TkDefaultFont", 11, "bold"))
        self.section_title_lbl.pack(anchor=tk.W)

        notes = ttk.LabelFrame(right, text="연구자 노트 · 이 섹션에서 강조할 지시", padding=4)
        notes.pack(fill=tk.X, pady=4)
        self.section_notes_widget = tk.Text(notes, height=4, wrap="word")
        self.section_notes_widget.pack(fill=tk.X)

        btns = ttk.Frame(right)
        btns.pack(fill=tk.X, pady=2)
        self.xlsx_for_data = tk.StringVar()
        ttk.Label(btns, text="결과 섹션용 xlsx:").pack(side=tk.LEFT)
        ttk.Entry(btns, textvariable=self.xlsx_for_data, width=40).pack(side=tk.LEFT, padx=2)
        ttk.Button(btns, text="찾아보기",
                   command=self._pick_xlsx_for_data).pack(side=tk.LEFT, padx=2)
        ttk.Button(btns, text="초안 생성",
                   command=self._draft_generate).pack(side=tk.LEFT, padx=8)
        self.revise_var = tk.StringVar()
        ttk.Entry(btns, textvariable=self.revise_var, width=30).pack(side=tk.LEFT, padx=2)
        ttk.Button(btns, text="수정 지시 반영",
                   command=self._draft_revise).pack(side=tk.LEFT, padx=2)

        ttk.Label(right, text="현재 초안",
                  font=("TkDefaultFont", 10, "bold")).pack(anchor=tk.W, pady=(6, 2))
        wrap = ttk.Frame(right)
        wrap.pack(fill=tk.BOTH, expand=True)
        self.draft_widget = tk.Text(wrap, wrap="word")
        vsb = ttk.Scrollbar(wrap, orient=tk.VERTICAL, command=self.draft_widget.yview)
        self.draft_widget.configure(yscrollcommand=vsb.set)
        self.draft_widget.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        savebar = ttk.Frame(right)
        savebar.pack(fill=tk.X, pady=(4, 0))
        ttk.Button(savebar, text="수동 편집 저장 (새 버전으로)",
                   command=self._draft_save_manual).pack(side=tk.LEFT, padx=2)

    # ---------- Project loading ----------

    def _open_project(self) -> None:
        d = filedialog.askdirectory(
            title="논문 프로젝트 폴더 선택 (없으면 새로 만들 위치를 고르세요)",
            initialdir=str(DEFAULT_PROJECT.parent),
        )
        if not d:
            return
        self.project_dir = Path(d)
        self.project = wp.load_or_create(self.project_dir)
        if self.library:
            self.library.close()
        self.library = Library(self.project_dir)
        self.project_lbl.config(text=f"프로젝트: {self.project_dir}  |  {self.project.title}")
        self._library_refresh()
        self._section_tree_refresh()
        self.status.set(
            f"프로젝트 열림. 자료 {len(self.library.all())}건, 섹션 {len(self.project.sections)}개."
        )

    # ---------- Coding actions ----------

    def _open_workbook(self) -> None:
        path = filedialog.askopenfilename(
            title="코딩시트(.xlsx) 선택",
            filetypes=[("Excel workbook", "*.xlsx"), ("All", "*.*")],
        )
        if not path:
            return
        try:
            self.workbook = xlsx_io.Workbook(path)
        except Exception as exc:
            messagebox.showerror("코딩시트 열기 실패", str(exc))
            return
        self.workbook_lbl.config(text=f"코딩시트: {path}")
        self.status.set(f"코딩시트 열림. 현재 {len(self.workbook.all_case_ids())}건 코딩 완료.")
        self._update_coding_buttons()

    def _open_judgment(self) -> None:
        path = filedialog.askopenfilename(
            title="판결문 파일 선택",
            filetypes=[
                ("판결문", "*.pdf *.docx *.txt *.md"),
                ("PDF", "*.pdf"), ("DOCX", "*.docx"), ("Text", "*.txt *.md"),
                ("All", "*.*"),
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
        self.status.set(f"판결문 로드됨 ({len(text):,}자).")
        self._update_coding_buttons()

    def _update_coding_buttons(self) -> None:
        state = tk.NORMAL if (self.workbook and self.judgment_text) else tk.DISABLED
        self.extract_btn.config(state=state)
        self.save_btn.config(state=tk.NORMAL if self.workbook else tk.DISABLED)

    def _run_extract(self) -> None:
        if not self.judgment_text or not self.workbook:
            return
        if not os.environ.get("ANTHROPIC_API_KEY"):
            messagebox.showerror("API 키 필요",
                                 "ANTHROPIC_API_KEY 환경변수가 필요합니다.")
            return
        self.extract_btn.config(state=tk.DISABLED)
        self.status.set("AI 코딩 초안 추출 중...")
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

    def _fill_coding_form(self, row: dict) -> None:
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
            self.notes_widget.insert("1.0", row.get("coding_note", "") or "")

    def _read_coding_form(self) -> dict:
        row: dict = {}
        for name, var in self.form_vars.items():
            text_val = var.get().strip()
            if not text_val:
                row[name] = None
                continue
            field = FIELDS_BY_NAME[name]
            if field.choices:
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
        row = self._read_coding_form()
        if not row.get("case_id"):
            messagebox.showwarning("저장 불가", "case_id가 비어 있습니다.")
            return
        row = analyzer.compute_all(row)
        self._fill_coding_form(row)
        try:
            r = self.workbook.upsert(row)
            self.workbook.save(backup=True)
        except Exception as exc:
            messagebox.showerror("저장 실패", str(exc))
            return
        self.status.set(f"저장 완료 — case_id={row['case_id']} (행 {r}). .bak 생성됨.")

    # ---------- Library actions ----------

    def _pick_lib_file(self) -> None:
        path = filedialog.askopenfilename(
            title="원본 파일 선택",
            filetypes=[("자료", "*.pdf *.docx *.txt *.md"), ("All", "*.*")],
        )
        if path:
            self.lib_file_path.set(path)

    def _library_add(self) -> None:
        if not self.library:
            messagebox.showwarning("프로젝트 필요", "먼저 논문 프로젝트를 열거나 만드세요.")
            return
        year_txt = self.lib_form["year"].get().strip()
        try:
            year = int(year_txt) if year_txt else None
        except ValueError:
            messagebox.showwarning("입력 오류", "연도는 숫자여야 합니다.")
            return
        source = Source(
            id=self.lib_form["id"].get().strip() or "unnamed",
            title=self.lib_form["title"].get().strip(),
            authors=self.lib_form["authors"].get().strip(),
            year=year,
            kind=self.lib_kind.get(),
            tags=self.lib_form["tags"].get().strip(),
            citation=self.lib_form["citation"].get().strip(),
            reference=self.lib_form["reference"].get().strip(),
            summary=self.lib_form["summary"].get().strip(),
        )
        try:
            self.library.add(source,
                             source_file=self.lib_file_path.get() or None,
                             extract_text=True)
        except Exception as exc:
            messagebox.showerror("등록 실패", str(exc))
            return
        for v in self.lib_form.values():
            v.set("")
        self.lib_file_path.set("")
        self._library_refresh()
        self.status.set(f"자료 등록 완료 — {source.id}")

    def _library_seed(self) -> None:
        if not self.library:
            return
        seed_from_proposal(self.library)
        self._library_refresh()
        self.status.set("연구계획서 참고문헌 시드 완료.")

    def _library_delete(self) -> None:
        if not self.library:
            return
        sel = self.lib_tree.selection()
        if not sel:
            return
        for iid in sel:
            self.library.delete(iid)
        self._library_refresh()

    def _library_refresh(self) -> None:
        for row in self.lib_tree.get_children():
            self.lib_tree.delete(row)
        if not self.library:
            return
        query = self.lib_search.get().strip()
        items = self.library.search(query=query) if query else self.library.all()
        for s in items:
            self.lib_tree.insert("", "end", iid=s.id,
                                 values=(s.id, s.kind, s.year or "",
                                         s.authors[:20], s.title, s.tags))

    # ---------- Notebook actions ----------

    def _append_chat(self, text: str) -> None:
        self.chat_view.insert(tk.END, text)
        self.chat_view.see(tk.END)

    def _notebook_ask(self) -> None:
        if not self.library or not self.project_dir:
            messagebox.showwarning("프로젝트 필요", "먼저 논문 프로젝트를 열거나 만드세요.")
            return
        q = self.question_var.get().strip()
        if not q:
            return
        pins = [p.strip() for p in self.pinned_ids.get().split(",") if p.strip()]
        self._append_chat(f"\n\n[나] {q}\n\n[Claude] ")
        self.question_var.set("")

        def worker():
            try:
                answer, used = notebook.ask(
                    self.project_dir, self.library, q,
                    conversation_name=self.chat_name.get() or "default",
                    pinned_source_ids=pins or None,
                    on_delta=lambda t: self.msg_queue.put(("chat_delta", t)),
                )
                self.msg_queue.put(("chat_end", used))
            except Exception as exc:
                self.msg_queue.put(("error", str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def _notebook_briefing(self) -> None:
        if not self.library or not self.project_dir:
            messagebox.showwarning("프로젝트 필요", "먼저 논문 프로젝트를 열거나 만드세요.")
            return
        topic = self.question_var.get().strip()
        if not topic:
            messagebox.showinfo("주제 입력", "브리핑 주제를 질문란에 입력하세요.")
            return
        self._append_chat(f"\n\n[주제 브리핑] {topic}\n\n[Claude] ")
        self.question_var.set("")

        def worker():
            try:
                text = notebook.briefing(
                    self.project_dir, self.library, topic,
                    on_delta=lambda t: self.msg_queue.put(("chat_delta", t)),
                )
                self.msg_queue.put(("chat_end", []))
            except Exception as exc:
                self.msg_queue.put(("error", str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    # ---------- Draft tab actions ----------

    def _section_tree_refresh(self) -> None:
        for row in self.section_tree.get_children():
            self.section_tree.delete(row)
        if not self.project:
            return
        for s in self.project.sections:
            self.section_tree.insert("", "end", iid=s.key,
                                     text=s.title,
                                     values=(s.status, s.estimated_pages))

    def _section_selected(self) -> None:
        if not self.project:
            return
        sel = self.section_tree.selection()
        if not sel:
            return
        key = sel[0]
        self._draft_target_key = key
        section = wp.section_by_key(self.project, key)
        self.section_title_lbl.config(text=f"{section.title}  (~{section.estimated_pages}쪽, 상태: {section.status})")
        self.section_notes_widget.delete("1.0", tk.END)
        self.section_notes_widget.insert("1.0", section.notes or "")
        body = wp.read_section(self.project, key)
        self.draft_widget.delete("1.0", tk.END)
        self.draft_widget.insert("1.0", body)

    def _pick_xlsx_for_data(self) -> None:
        path = filedialog.askopenfilename(
            title="결과 섹션용 코딩시트",
            filetypes=[("Excel workbook", "*.xlsx")],
        )
        if path:
            self.xlsx_for_data.set(path)

    def _draft_generate(self) -> None:
        if not (self.project and self.library and self._draft_target_key):
            messagebox.showwarning("선택 필요", "왼쪽에서 섹션을 하나 고르세요.")
            return
        # 노트 저장
        section = wp.section_by_key(self.project, self._draft_target_key)
        section.notes = self.section_notes_widget.get("1.0", tk.END).strip()
        wp.save(self.project)

        data_md = ""
        if self.xlsx_for_data.get():
            try:
                summary = data_summary.summarize(self.xlsx_for_data.get())
                data_md = data_summary.to_markdown(summary)
            except Exception as e:
                messagebox.showwarning("통계 계산 실패", str(e))

        self.draft_widget.delete("1.0", tk.END)
        self.status.set(f"초안 생성 중 — {section.title} ...")

        def worker():
            try:
                drafter.draft_section(
                    self.project, self.library, self._draft_target_key,
                    data_summary_md=data_md,
                    on_delta=lambda t: self.msg_queue.put(("draft_delta", t)),
                )
                self.msg_queue.put(("draft_end", None))
            except Exception as exc:
                self.msg_queue.put(("error", str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def _draft_revise(self) -> None:
        if not (self.project and self.library and self._draft_target_key):
            messagebox.showwarning("선택 필요", "섹션을 선택하고 수정 지시를 입력하세요.")
            return
        instruction = self.revise_var.get().strip()
        if not instruction:
            messagebox.showinfo("지시 필요", "수정 지시사항을 입력하세요.")
            return
        section = wp.section_by_key(self.project, self._draft_target_key)
        section.notes = self.section_notes_widget.get("1.0", tk.END).strip()
        wp.save(self.project)

        data_md = ""
        if self.xlsx_for_data.get():
            try:
                summary = data_summary.summarize(self.xlsx_for_data.get())
                data_md = data_summary.to_markdown(summary)
            except Exception:
                pass

        self.status.set("초안 수정 중...")
        self.draft_widget.delete("1.0", tk.END)

        def worker():
            try:
                drafter.revise_section(
                    self.project, self.library, self._draft_target_key,
                    revision_instruction=instruction,
                    data_summary_md=data_md,
                    on_delta=lambda t: self.msg_queue.put(("draft_delta", t)),
                )
                self.msg_queue.put(("draft_end", None))
            except Exception as exc:
                self.msg_queue.put(("error", str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def _draft_save_manual(self) -> None:
        if not (self.project and self._draft_target_key):
            return
        body = self.draft_widget.get("1.0", tk.END).rstrip() + "\n"
        wp.write_section(self.project, self._draft_target_key, body, version=True)
        self._section_tree_refresh()
        self.status.set("현재 초안을 새 버전으로 저장했습니다.")

    def _compile_draft(self) -> None:
        if not (self.project and self.library):
            return
        out = wp.compile_full_draft(self.project)
        refs = self.library.bibliography()
        ref_out = wp.compile_references(self.project, refs)
        self.status.set(f"draft_paper.md 및 references.md 생성 완료. → {out}")

    # ---------- Queue poll ----------

    def _poll_queue(self) -> None:
        try:
            while True:
                kind, payload = self.msg_queue.get_nowait()
                if kind == "status_delta":
                    self.status.set("AI 추출 중... " + str(payload)[-40:].replace("\n", " "))
                elif kind == "extracted":
                    self._fill_coding_form(payload)
                    self.status.set(f"초안 추출 완료 — case_id={payload.get('case_id')}.")
                    self.extract_btn.config(state=tk.NORMAL)
                elif kind == "chat_delta":
                    self._append_chat(str(payload))
                elif kind == "chat_end":
                    used = payload or []
                    if used:
                        self._append_chat(f"\n\n[사용한 자료: {', '.join(used)}]\n")
                elif kind == "draft_delta":
                    self.draft_widget.insert(tk.END, str(payload))
                    self.draft_widget.see(tk.END)
                elif kind == "draft_end":
                    self._section_tree_refresh()
                    self.status.set("초안 생성/수정 완료. 새 버전으로 저장되었습니다.")
                elif kind == "error":
                    messagebox.showerror("오류", str(payload))
                    self.status.set("오류 발생.")
                    self.extract_btn.config(state=tk.NORMAL)
        except queue.Empty:
            pass
        self.root.after(120, self._poll_queue)

    # ---------- Help ----------

    def _show_help(self) -> None:
        messagebox.showinfo(
            "사용법",
            "1. 파일 → 논문 프로젝트 열기/만들기\n"
            "2. '자료 라이브러리' 탭에서 [연구계획서 시드]로 시작, 이후 선행연구/판례/법조문을 등록\n"
            "3. '판결문 코딩' 탭에서 xlsx와 판결문을 열고 AI 초안 추출 → 검토 → 저장\n"
            "4. '노트북 QA' 탭에서 라이브러리 자료에 대해 자유롭게 질문 (자료 안에서만 답합니다)\n"
            "5. '섹션 초안' 탭에서 섹션 선택 → 초안 생성 → 수정 지시 반영\n"
            "6. [전체 이어붙여 draft_paper.md 생성]으로 지금까지 확정된 섹션을 한 파일로 뽑기"
        )

    def _show_about(self) -> None:
        messagebox.showinfo(
            "정보",
            "박사논문 워크벤치 v0.2\n"
            "딥페이크 디지털 성범죄 양형 결정요인 연구\n\n"
            "1. 판결문 코딩 · 2. 자료 라이브러리 · 3. 노트북 QA · 4. 섹션 초안\n"
            "AI: Claude Opus 5 (adaptive thinking, streaming)"
        )


def main() -> None:
    root = tk.Tk()
    PaperWriterApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
