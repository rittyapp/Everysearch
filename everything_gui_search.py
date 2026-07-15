"""
Everything 検索補助ツール
- / _ / 半角スペース / 全角スペース のゆらぎを吸収して Everything HTTP サーバーへ検索を依頼する
"""

from __future__ import annotations

import base64
import datetime as dt
import json
import os
import re
import sys
import webbrowser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def _fix_tcl_tk_paths() -> None:
    """
    複数バージョンの Python が混在すると、環境変数 TCL_LIBRARY / TK_LIBRARY が
    別バージョンを指したままになり、tkinter の初期化に失敗することがある。
    実行中の Python 配下の tcl/tk を優先する。
    """
    base = Path(sys.prefix)
    tcl = base / "tcl" / "tcl8.6"
    tk_dir = base / "tcl" / "tk8.6"
    if tcl.is_dir():
        os.environ["TCL_LIBRARY"] = str(tcl)
    if tk_dir.is_dir():
        os.environ["TK_LIBRARY"] = str(tk_dir)


_fix_tcl_tk_paths()

import tkinter as tk  # noqa: E402
from tkinter import filedialog, messagebox, ttk  # noqa: E402

# =========================
# 設定
# =========================
def _runtime_dir() -> Path:
    """書き込み可能なアプリ配置フォルダ（EXE の隣 / スクリプトの隣）。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _resource_dir() -> Path:
    """同梱リソース（ICO 等）。onefile EXE 時は展開先 _MEIPASS。"""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parent


APP_DIR = _runtime_dir()
RESOURCE_DIR = _resource_dir()
SETTINGS_PATH = APP_DIR / "settings.json"
ICON_PATH = RESOURCE_DIR / "everysearch.ico"
if not ICON_PATH.is_file():
    # 開発時・同梱漏れ時は実行フォルダも探す
    alt = APP_DIR / "everysearch.ico"
    if alt.is_file():
        ICON_PATH = alt

DEFAULT_SETTINGS = {
    "host": "127.0.0.1",
    "port": 8888,
    "user": "",
    "password": "",
    # 初期は空（全体検索）。特定フォルダはユーザーが指定／履歴から選択
    "search_folder": "",
    "folder_history": [],
}

EVERYTHING_DOWNLOAD_URL = "https://www.voidtools.com/"

MAX_RESULTS = 200
DISPLAY_LIMIT = 100
FOLDER_HISTORY_MAX = 20

_FILETIME_EPOCH_DIFF = 116444736000000000

# ---------- デザイン ----------
UI = {
    "bg": "#F3F5F9",
    "surface": "#FFFFFF",
    "surface_2": "#F8FAFC",
    "border": "#E2E8F0",
    "text": "#0F172A",
    "text_muted": "#64748B",
    "primary": "#2563EB",
    "primary_hover": "#1D4ED8",
    "primary_text": "#FFFFFF",
    "secondary": "#EEF2FF",
    "secondary_text": "#3730A3",
    "select": "#BFDBFE",
    "heading": "#F1F5F9",
    "accent_line": "#DBEAFE",
}

COLOR_FOLDER = "#FEF9C3"
COLOR_DWG = "#DBEAFE"
COLOR_DXF = "#E5E7EB"
COLOR_PDF = "#FECACA"
COLOR_EXCEL = "#BBF7D0"
COLOR_OTHER = "#FFFFFF"

TYPE_SORT_ORDER = {
    "folder": 0,
    "pdf": 1,
    "dwg": 2,
    "dxf": 3,
    "excel": 4,
    "other": 9,
}

TYPE_LABELS = {
    "folder": "フォルダ",
    "pdf": "PDF",
    "dwg": "DWG",
    "dxf": "DXF",
    "excel": "Excel",
    "other": "その他",
}

# 種類フィルタの表示順（タグ, ラベル, 色）
TYPE_FILTER_ITEMS = (
    ("folder", "フォルダ", COLOR_FOLDER),
    ("dwg", "DWG", COLOR_DWG),
    ("dxf", "DXF", COLOR_DXF),
    ("pdf", "PDF", COLOR_PDF),
    ("excel", "Excel", COLOR_EXCEL),
    ("other", "その他", COLOR_OTHER),
)

# 非表示（オフ）時のチップ色
FILTER_OFF_BG = "#94A3B8"
FILTER_OFF_FG = "#F8FAFC"

# PowerShell 程度の読みやすさを意識した大きめフォント
FONT_UI = ("Yu Gothic UI", 13)
FONT_UI_BOLD = ("Yu Gothic UI", 13, "bold")
FONT_TITLE = ("Yu Gothic UI", 18, "bold")
FONT_SMALL = ("Yu Gothic UI", 12)
FONT_MONO = ("Consolas", 12)
FONT_ENTRY = ("Yu Gothic UI", 13)
FONT_TREE = ("Yu Gothic UI", 13)
FONT_TREE_HEAD = ("Yu Gothic UI", 13, "bold")


# =========================
# 設定ファイル
# =========================
def normalize_folder_history(raw) -> list[str]:
    """履歴を引用符付きパスのリストに正規化する（新しい順・重複なし）。"""
    if not isinstance(raw, list):
        return []
    seen = set()
    result = []
    for item in raw:
        q = quote_folder_path(str(item) if item is not None else "")
        if not q:
            continue
        key = strip_folder_quotes(q).lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(q)
        if len(result) >= FOLDER_HISTORY_MAX:
            break
    return result


def load_settings() -> dict:
    data = dict(DEFAULT_SETTINGS)
    data["folder_history"] = list(DEFAULT_SETTINGS["folder_history"])
    if SETTINGS_PATH.is_file():
        try:
            loaded = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                for k in DEFAULT_SETTINGS:
                    if k in loaded:
                        data[k] = loaded[k]
        except (OSError, json.JSONDecodeError, TypeError):
            pass
    # 既定フォルダに引用符が無い場合は付ける
    data["search_folder"] = quote_folder_path(data.get("search_folder", "") or "")
    data["folder_history"] = normalize_folder_history(data.get("folder_history", []))
    # 現在の対象フォルダが履歴に無ければ先頭へ（空は追加しない）
    current = data["search_folder"]
    if current:
        data["folder_history"] = normalize_folder_history(
            [current] + data["folder_history"]
        )
    try:
        data["port"] = int(data.get("port", 8888))
    except (TypeError, ValueError):
        data["port"] = 8888
    return data


def save_settings(settings: dict) -> None:
    payload = {
        "host": str(settings.get("host", "127.0.0.1")).strip() or "127.0.0.1",
        "port": int(settings.get("port", 8888)),
        "user": str(settings.get("user", "")),
        "password": str(settings.get("password", "")),
        "search_folder": quote_folder_path(settings.get("search_folder", "")),
        "folder_history": normalize_folder_history(settings.get("folder_history", [])),
    }
    SETTINGS_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def strip_folder_quotes(folder: str) -> str:
    """前後の " または ' を外したパスを返す。"""
    f = (folder or "").strip()
    if len(f) >= 2 and f[0] == f[-1] and f[0] in "\"'":
        return f[1:-1].strip()
    return f


def quote_folder_path(folder: str) -> str:
    """
    表示・保存用に "パス" 形式にする。
    空欄はそのまま（全体検索）。
    """
    f = strip_folder_quotes(folder)
    if not f:
        return ""
    return f'"{f}"'


# =========================
# 検索語変換
# =========================
# 区切り文字のゆらぎ: - / _ / 半角スペース / 全角スペース を同一視
_FULLWIDTH_SPACE = "\u3000"
_FLEX_SEPARATORS = frozenset(("-", "_", " ", _FULLWIDTH_SPACE))
# Everything の regex は文字クラス内の「生スペース」を解釈できないことがあるため
# \x20（半角）と \x{3000}（全角）で明示する
_FLEX_SEPARATOR_CLASS = r"[-_\x20\x{3000}]"


def to_flexible_regex(text: str) -> str:
    """
    入力中のゆらぎを同一視する正規表現へ変換する。

    区切りとして次をすべて同一視する:
      - ハイフン `-`
      - アンダースコア `_`
      - 半角スペース
      - 全角スペース

    先頭固定（^）は付けない。
    そのため「694 1056」で「TES694-1056」など、途中一致もヒットする。

    例:
      TES757_0200_AA_00  -> TES757[-_\\x20\\x{3000}]0200...
      TES757 1055        -> TES757[-_\\x20\\x{3000}]1055
      694 1056           -> 694[-_\\x20\\x{3000}]1056
        （TES694-1056 / TES694_1056 などにもヒット）
    """
    parts = []
    for ch in text.strip():
        if ch in _FLEX_SEPARATORS:
            parts.append(_FLEX_SEPARATOR_CLASS)
        else:
            parts.append(re.escape(ch))
    return "".join(parts)


# =========================
# 表示用ヘルパー
# =========================
def format_size(size_value) -> str:
    if size_value in (None, "", "-"):
        return ""
    try:
        size = int(size_value)
    except (TypeError, ValueError):
        return ""
    if size < 0:
        return ""
    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"


def filetime_to_datetime(filetime_value):
    if filetime_value in (None, "", "0", 0):
        return None
    try:
        ft = int(filetime_value)
    except (TypeError, ValueError):
        return None
    if ft <= 0:
        return None
    try:
        seconds = (ft - _FILETIME_EPOCH_DIFF) / 10_000_000
        return dt.datetime.fromtimestamp(seconds)
    except (OSError, OverflowError, ValueError):
        return None


def format_datetime(filetime_value) -> str:
    d = filetime_to_datetime(filetime_value)
    if not d:
        return ""
    return d.strftime("%Y-%m-%d %H:%M")


def classify_type(item_type: str, name: str) -> str:
    if (item_type or "").lower() == "folder":
        return "folder"
    ext = Path(name).suffix.lower()
    if ext == ".dwg":
        return "dwg"
    if ext == ".dxf":
        return "dxf"
    if ext == ".pdf":
        return "pdf"
    if ext in {".xls", ".xlsx", ".xlsm", ".xlsb", ".xlt", ".xltx", ".xltm"}:
        return "excel"
    return "other"


def type_display_label(tag: str, name: str) -> str:
    if tag == "folder":
        return "フォルダ"
    if tag == "other":
        ext = Path(name).suffix.lower()
        return ext.lstrip(".").upper() if ext else "その他"
    return TYPE_LABELS.get(tag, tag.upper())


# =========================
# Everything HTTP 問い合わせ
# =========================
def search_everything(
    query_regex: str,
    search_folder: str = "",
    host: str = "127.0.0.1",
    port: int = 8888,
    user: str = "",
    password: str = "",
):
    """
    Everything HTTP サーバーへ問い合わせる（JSON）。
    path: で配下に限定し、regex: で -/_ ゆらぎを吸収する。
    """
    folder = strip_folder_quotes(search_folder)
    if folder:
        # Everything 向け: path:"実パス" （引用符はここで必ず付ける）
        search_query = f'path:"{folder}" regex:{query_regex}'
    else:
        search_query = f"regex:{query_regex}"

    params = {
        "search": search_query,
        "json": 1,
        "count": MAX_RESULTS,
        "path_column": 1,
        "size_column": 1,
        "date_modified_column": 1,
    }

    url = f"http://{host}:{int(port)}/?{urlencode(params)}"
    req = Request(url)

    if user or password:
        token = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
        req.add_header("Authorization", f"Basic {token}")

    with urlopen(req, timeout=15) as res:
        data = res.read().decode("utf-8", errors="replace")
        return json.loads(data)


def parse_results(data):
    results = []

    for item in data.get("results", []):
        path = item.get("path", "") or ""
        name = item.get("name", "") or ""
        item_type = item.get("type", "") or ""

        if path and name:
            fullpath = os.path.join(path, name)
        elif name:
            fullpath = name
        else:
            continue

        size_raw = item.get("size", "")
        date_raw = item.get("date_modified", "")
        date_dt = filetime_to_datetime(date_raw)
        tag = classify_type(item_type, name)

        try:
            size_num = int(size_raw) if size_raw not in (None, "") else -1
        except (TypeError, ValueError):
            size_num = -1

        results.append(
            {
                "fullpath": fullpath,
                "name": name,
                "path": path,
                "type": item_type,
                "tag": tag,
                "type_text": type_display_label(tag, name),
                "type_sort": (
                    TYPE_SORT_ORDER.get(tag, 9),
                    type_display_label(tag, name).lower(),
                    name.lower(),
                ),
                "size_raw": size_num,
                "size_text": format_size(size_raw) if item_type != "folder" else "",
                "date_raw": date_dt.timestamp() if date_dt else -1.0,
                "date_text": format_datetime(date_raw),
            }
        )

    return results


# =========================
# UI部品
# =========================
class TypeFilterChip(tk.Frame):
    """
    種類の表示/非表示を切り替えるチップ。
    オン: 本来の色 / オフ: ダークアウトして一覧から除外
    """

    def __init__(
        self,
        master,
        text: str,
        tag: str,
        active_bg: str,
        command=None,
        **kwargs,
    ):
        super().__init__(master, bg=UI["surface"], **kwargs)
        self.tag = tag
        self.active_bg = active_bg
        self.command = command
        self.enabled = True

        self.label = tk.Label(
            self,
            text=text,
            bg=active_bg,
            fg=UI["text"],
            font=FONT_SMALL,
            padx=10,
            pady=4,
            cursor="hand2",
        )
        self.label.pack()
        self.configure(highlightbackground=UI["border"], highlightthickness=1)

        for w in (self, self.label):
            w.bind("<Button-1>", self._on_click)

        self._refresh_look()

    def _on_click(self, _event=None):
        self.set_enabled(not self.enabled)
        if self.command:
            self.command(self.tag, self.enabled)

    def set_enabled(self, enabled: bool):
        self.enabled = bool(enabled)
        self._refresh_look()

    def _refresh_look(self):
        if self.enabled:
            self.label.configure(bg=self.active_bg, fg=UI["text"])
            self.configure(highlightbackground=UI["border"], highlightthickness=1)
        else:
            # ダークアウト（非表示）
            self.label.configure(bg=FILTER_OFF_BG, fg=FILTER_OFF_FG)
            self.configure(highlightbackground="#64748B", highlightthickness=1)


class ModernButton(tk.Label):
    def __init__(
        self,
        master,
        text: str,
        command=None,
        variant: str = "secondary",
        **kwargs,
    ):
        self.command = command
        self._enabled = True
        colors = self._palette(variant)
        super().__init__(
            master,
            text=text,
            bg=colors["bg"],
            fg=colors["fg"],
            font=FONT_UI_BOLD if variant == "primary" else FONT_UI,
            padx=16,
            pady=9,
            cursor="hand2",
            **kwargs,
        )
        self._colors = colors
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_click)

    @staticmethod
    def _palette(variant: str):
        if variant == "primary":
            return {
                "bg": UI["primary"],
                "fg": UI["primary_text"],
                "hover": UI["primary_hover"],
            }
        if variant == "ghost":
            return {
                "bg": UI["surface"],
                "fg": UI["text"],
                "hover": UI["surface_2"],
            }
        return {
            "bg": UI["secondary"],
            "fg": UI["secondary_text"],
            "hover": "#E0E7FF",
        }

    def _on_enter(self, _e=None):
        if self._enabled:
            self.configure(bg=self._colors["hover"])

    def _on_leave(self, _e=None):
        if self._enabled:
            self.configure(bg=self._colors["bg"])

    def _on_click(self, _e=None):
        if self._enabled and self.command:
            self.command()


# =========================
# GUI
# =========================
class EverythingSearchApp:
    SORT_KEYS = {
        "path": "fullpath",
        "type": "type_sort",
        "size": "size_raw",
        "date": "date_raw",
    }
    SORT_LABELS = {
        "path": "パス",
        "type": "種類",
        "size": "サイズ",
        "date": "更新日時",
    }
    SORT_DEFAULT_ASC = {
        "path": True,
        "type": True,
        "size": False,
        "date": False,
    }

    def __init__(self, root):
        self.root = root
        self.root.title("Everysearch")
        self.root.geometry("1240x780")
        # 下部ボタン＋検索欄が隠れない程度の最小サイズ
        self.root.minsize(960, 520)
        self.root.configure(bg=UI["bg"])

        self.settings = load_settings()
        self._setup_styles()

        self.all_results = []
        self.display_results = []
        self.total_results = 0
        self.sort_column = "path"
        self.sort_ascending = True
        # 種類フィルタ（True = 表示）
        self.type_visible = {tag: True for tag, _label, _color in TYPE_FILTER_ITEMS}
        self.type_filter_chips = {}
        self.folder_history_open = False

        self.create_widgets()
        self.entry.focus_set()

    # ----- connection helpers -----
    def _conn(self):
        return {
            "host": self.settings.get("host", "127.0.0.1"),
            "port": int(self.settings.get("port", 8888)),
            "user": self.settings.get("user", ""),
            "password": self.settings.get("password", ""),
        }

    def _setup_styles(self):
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure("App.TNotebook", background=UI["bg"], borderwidth=0)
        style.configure(
            "App.TNotebook.Tab",
            font=FONT_UI_BOLD,
            padding=(18, 10),
            background=UI["surface_2"],
            foreground=UI["text_muted"],
        )
        style.map(
            "App.TNotebook.Tab",
            background=[("selected", UI["surface"])],
            foreground=[("selected", UI["text"])],
        )

        style.configure(
            "Search.TEntry",
            fieldbackground="#FFFFFF",
            foreground=UI["text"],
            insertcolor=UI["text"],
            bordercolor=UI["border"],
            lightcolor=UI["primary"],
            darkcolor=UI["border"],
            padding=10,
            font=FONT_ENTRY,
        )
        style.map(
            "Search.TEntry",
            fieldbackground=[("focus", "#FFFFFF")],
            bordercolor=[("focus", UI["primary"])],
        )

        style.configure(
            "Settings.TEntry",
            fieldbackground="#FFFFFF",
            foreground=UI["text"],
            insertcolor=UI["text"],
            bordercolor=UI["border"],
            lightcolor=UI["primary"],
            darkcolor=UI["border"],
            padding=10,
            font=FONT_ENTRY,
        )

        style.configure(
            "Results.Treeview",
            background=UI["surface"],
            fieldbackground=UI["surface"],
            foreground=UI["text"],
            rowheight=36,
            borderwidth=0,
            font=FONT_TREE,
        )
        style.configure(
            "Results.Treeview.Heading",
            background=UI["heading"],
            foreground=UI["text"],
            relief="flat",
            borderwidth=0,
            font=FONT_TREE_HEAD,
            padding=10,
        )
        style.map(
            "Results.Treeview",
            background=[("selected", UI["select"])],
            foreground=[("selected", UI["text"])],
        )
        style.map(
            "Results.Treeview.Heading",
            background=[("active", UI["accent_line"])],
        )

        style.configure(
            "Modern.Vertical.TScrollbar",
            background=UI["border"],
            troughcolor=UI["surface_2"],
            bordercolor=UI["surface_2"],
            arrowcolor=UI["text_muted"],
            relief="flat",
        )
        style.configure(
            "Modern.Horizontal.TScrollbar",
            background=UI["border"],
            troughcolor=UI["surface_2"],
            bordercolor=UI["surface_2"],
            arrowcolor=UI["text_muted"],
            relief="flat",
        )

    def _card_shell(self, parent, **pack_kwargs) -> tk.Frame:
        outer = tk.Frame(parent, bg=UI["bg"])
        outer.pack(**pack_kwargs)
        shell = tk.Frame(
            outer,
            bg=UI["surface"],
            highlightbackground=UI["border"],
            highlightthickness=1,
        )
        shell.pack(fill="both", expand=True)
        card = tk.Frame(shell, bg=UI["surface"])
        card.pack(fill="both", expand=True, padx=16, pady=14)
        return card

    def create_widgets(self):
        # ヘッダ（タイトルのみ）
        header = tk.Frame(self.root, bg=UI["bg"])
        header.pack(fill="x", padx=20, pady=(16, 6))
        tk.Label(
            header,
            text="Everysearch",
            bg=UI["bg"],
            fg=UI["text"],
            font=FONT_TITLE,
        ).pack(side="left")

        # タブ
        self.notebook = ttk.Notebook(self.root, style="App.TNotebook")
        self.notebook.pack(fill="both", expand=True, padx=16, pady=(0, 12))

        self.search_tab = tk.Frame(self.notebook, bg=UI["bg"])
        self.settings_tab = tk.Frame(self.notebook, bg=UI["bg"])
        self.help_tab = tk.Frame(self.notebook, bg=UI["bg"])
        self.notebook.add(self.search_tab, text="  検索  ")
        self.notebook.add(self.settings_tab, text="  接続設定  ")
        self.notebook.add(self.help_tab, text="  使い方  ")

        self._build_search_tab()
        self._build_settings_tab()
        self._build_help_tab()

    def _build_search_tab(self):
        parent = self.search_tab

        # 先にフッターを bottom 固定 → ウィンドウを縮めてもボタンが隠れない
        footer_outer = tk.Frame(parent, bg=UI["bg"])
        footer_outer.pack(side="bottom", fill="x", padx=8, pady=(0, 8))
        footer_shell = tk.Frame(
            footer_outer,
            bg=UI["surface"],
            highlightbackground=UI["border"],
            highlightthickness=1,
        )
        footer_shell.pack(fill="x")
        footer = tk.Frame(footer_shell, bg=UI["surface"])
        footer.pack(fill="x", padx=16, pady=12)

        top_footer = tk.Frame(footer, bg=UI["surface"])
        top_footer.pack(fill="x")

        legend = tk.Frame(top_footer, bg=UI["surface"])
        legend.pack(side="left", fill="x", expand=True)
        tk.Label(
            legend,
            text="種類フィルタ",
            bg=UI["surface"],
            fg=UI["text_muted"],
            font=FONT_SMALL,
        ).pack(side="left", padx=(0, 8))
        for tag, text, color in TYPE_FILTER_ITEMS:
            chip = TypeFilterChip(
                legend,
                text=text,
                tag=tag,
                active_bg=color,
                command=self.on_type_filter_toggle,
            )
            chip.pack(side="left", padx=(0, 6))
            self.type_filter_chips[tag] = chip

        actions = tk.Frame(top_footer, bg=UI["surface"])
        actions.pack(side="right")
        ModernButton(
            actions,
            text="選択ファイルを開く",
            command=self.open_selected,
            variant="primary",
        ).pack(side="left", padx=(0, 8))
        ModernButton(
            actions, text="選択フォルダを開く", command=self.open_selected_folder
        ).pack(side="left", padx=(0, 8))
        ModernButton(
            actions, text="パスをコピー", command=self.copy_selected_path, variant="ghost"
        ).pack(side="left")

        self.regex_var = tk.StringVar(value="変換後正規表現:  —")
        tk.Label(
            footer,
            textvariable=self.regex_var,
            bg=UI["surface"],
            fg=UI["text_muted"],
            font=FONT_MONO,
            anchor="w",
        ).pack(fill="x", pady=(10, 0))

        # 検索カード（上部）
        search_card = self._card_shell(parent, side="top", fill="x", padx=8, pady=(8, 6))

        row1 = tk.Frame(search_card, bg=UI["surface"])
        row1.pack(fill="x")
        tk.Label(
            row1,
            text="検索",
            bg=UI["surface"],
            fg=UI["text_muted"],
            font=FONT_UI,
            width=10,
            anchor="w",
        ).pack(side="left")
        self.keyword_var = tk.StringVar()
        self.entry = ttk.Entry(
            row1, textvariable=self.keyword_var, style="Search.TEntry"
        )
        self.entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.entry.bind("<Return>", lambda _e: self.on_search())
        # 検索文字クリア（フォルダ欄の × と同じ見た目）
        ModernButton(
            row1, text="×", command=self.clear_search_keyword, variant="ghost"
        ).pack(side="left", padx=(0, 6))
        ModernButton(
            row1, text="検索", command=self.on_search, variant="primary"
        ).pack(side="left")

        row2 = tk.Frame(search_card, bg=UI["surface"])
        row2.pack(fill="x", pady=(12, 0))
        tk.Label(
            row2,
            text="対象フォルダ",
            bg=UI["surface"],
            fg=UI["text_muted"],
            font=FONT_UI,
            width=10,
            anchor="w",
        ).pack(side="left")
        self.folder_var = tk.StringVar(
            value=quote_folder_path(self.settings.get("search_folder", ""))
        )
        self.folder_entry = ttk.Entry(
            row2, textvariable=self.folder_var, style="Search.TEntry"
        )
        self.folder_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.folder_entry.bind("<FocusIn>", self._on_folder_entry_focus)
        self.folder_entry.bind("<Button-1>", self._on_folder_entry_click)
        self.folder_entry.bind("<Down>", self._on_folder_entry_down)
        self.folder_entry.bind("<Escape>", lambda _e: self.hide_folder_history())

        # 履歴閉時: 入力クリア / 履歴開時: 一覧を閉じる
        self.folder_clear_btn = ModernButton(
            row2, text="×", command=self.on_folder_clear_or_close, variant="ghost"
        )
        self.folder_clear_btn.pack(side="left", padx=(0, 6))
        ModernButton(
            row2, text="フォルダ選択…", command=self.browse_folder
        ).pack(side="left")

        # 履歴ドロップダウン（対象フォルダの下に表示）
        self.history_panel = tk.Frame(
            search_card,
            bg=UI["surface"],
            highlightbackground=UI["border"],
            highlightthickness=1,
        )
        # pack は表示時のみ
        self.history_list_frame = tk.Frame(self.history_panel, bg=UI["surface"])
        self.history_list_frame.pack(fill="both", expand=True, padx=4, pady=4)
        self.history_empty_label = tk.Label(
            self.history_list_frame,
            text="履歴はまだありません",
            bg=UI["surface"],
            fg=UI["text_muted"],
            font=FONT_SMALL,
            anchor="w",
        )

        # 件数
        self.info_var = tk.StringVar(value="型番・図番を入力して検索してください")
        info_bar = tk.Frame(parent, bg=UI["bg"])
        info_bar.pack(side="top", fill="x", padx=16, pady=(0, 4))
        tk.Label(
            info_bar,
            textvariable=self.info_var,
            bg=UI["bg"],
            fg=UI["text_muted"],
            font=FONT_SMALL,
            anchor="w",
        ).pack(fill="x")

        # 結果テーブル（残り領域を占有。縮小時はここだけが縮む）
        result_outer = tk.Frame(parent, bg=UI["bg"])
        result_outer.pack(side="top", fill="both", expand=True, padx=8, pady=(0, 6))
        result_card = tk.Frame(
            result_outer,
            bg=UI["surface"],
            highlightbackground=UI["border"],
            highlightthickness=1,
        )
        result_card.pack(fill="both", expand=True)
        table_wrap = tk.Frame(result_card, bg=UI["surface"])
        table_wrap.pack(fill="both", expand=True, padx=1, pady=1)

        columns = ("type", "name", "path", "size", "date")
        self.tree = ttk.Treeview(
            table_wrap,
            columns=columns,
            show="headings",
            selectmode="browse",
            style="Results.Treeview",
        )
        self.tree.heading("type", text="種類", command=lambda: self.toggle_sort("type"))
        self.tree.heading("name", text="名前", command=lambda: self.toggle_sort("path"))
        self.tree.heading("path", text="場所", command=lambda: self.toggle_sort("path"))
        self.tree.heading("size", text="サイズ", command=lambda: self.toggle_sort("size"))
        self.tree.heading(
            "date", text="更新日時", command=lambda: self.toggle_sort("date")
        )

        self.tree.column("type", width=90, anchor="center", stretch=False, minwidth=80)
        self.tree.column("name", width=300, anchor="w", stretch=True, minwidth=180)
        self.tree.column("path", width=420, anchor="w", stretch=True, minwidth=200)
        self.tree.column("size", width=100, anchor="e", stretch=False, minwidth=80)
        self.tree.column("date", width=150, anchor="center", stretch=False, minwidth=120)

        for tag, color in (
            ("folder", COLOR_FOLDER),
            ("dwg", COLOR_DWG),
            ("dxf", COLOR_DXF),
            ("pdf", COLOR_PDF),
            ("excel", COLOR_EXCEL),
            ("other", COLOR_OTHER),
        ):
            self.tree.tag_configure(tag, background=color)

        yscroll = ttk.Scrollbar(
            table_wrap,
            orient="vertical",
            command=self.tree.yview,
            style="Modern.Vertical.TScrollbar",
        )
        xscroll = ttk.Scrollbar(
            table_wrap,
            orient="horizontal",
            command=self.tree.xview,
            style="Modern.Horizontal.TScrollbar",
        )
        self.tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        table_wrap.rowconfigure(0, weight=1)
        table_wrap.columnconfigure(0, weight=1)

        self.tree.bind("<Double-Button-1>", self.open_selected)
        self.tree.bind("<Return>", self.open_selected)

        self._update_heading_labels()

    def _build_settings_tab(self):
        parent = self.settings_tab
        card = self._card_shell(parent, fill="both", expand=True, padx=8, pady=8)

        tk.Label(
            card,
            text="Everything HTTP サーバー接続",
            bg=UI["surface"],
            fg=UI["text"],
            font=FONT_UI_BOLD,
            anchor="w",
        ).pack(fill="x", pady=(0, 4))
        tk.Label(
            card,
            text="Everything が別 PC で動いている場合は、そのホスト名または IP を指定してください。",
            bg=UI["surface"],
            fg=UI["text_muted"],
            font=FONT_SMALL,
            anchor="w",
            justify="left",
        ).pack(fill="x", pady=(0, 16))

        form = tk.Frame(card, bg=UI["surface"])
        form.pack(fill="x")

        self.host_var = tk.StringVar(value=str(self.settings.get("host", "127.0.0.1")))
        self.port_var = tk.StringVar(value=str(self.settings.get("port", 8888)))
        self.user_var = tk.StringVar(value=str(self.settings.get("user", "")))
        self.password_var = tk.StringVar(value=str(self.settings.get("password", "")))

        fields = [
            ("ホスト / IP", self.host_var, False),
            ("ポート", self.port_var, False),
            ("ユーザー名（任意）", self.user_var, False),
            ("パスワード（任意）", self.password_var, True),
        ]
        for i, (label, var, is_password) in enumerate(fields):
            row = tk.Frame(form, bg=UI["surface"])
            row.pack(fill="x", pady=(0, 12))
            tk.Label(
                row,
                text=label,
                bg=UI["surface"],
                fg=UI["text_muted"],
                font=FONT_UI,
                width=18,
                anchor="w",
            ).pack(side="left")
            entry = ttk.Entry(
                row,
                textvariable=var,
                style="Settings.TEntry",
                show="●" if is_password else "",
            )
            entry.pack(side="left", fill="x", expand=True)

        btn_row = tk.Frame(card, bg=UI["surface"])
        btn_row.pack(fill="x", pady=(8, 0))
        ModernButton(
            btn_row, text="設定を保存", command=self.save_connection_settings, variant="primary"
        ).pack(side="left", padx=(0, 8))
        ModernButton(
            btn_row, text="接続テスト", command=self.test_connection
        ).pack(side="left")

        self.settings_status_var = tk.StringVar(
            value=f"現在: {self.settings.get('host')}:{self.settings.get('port')}"
        )
        tk.Label(
            card,
            textvariable=self.settings_status_var,
            bg=UI["surface"],
            fg=UI["text_muted"],
            font=FONT_SMALL,
            anchor="w",
        ).pack(fill="x", pady=(16, 0))

        tip = (
            "ヒント:\n"
            "・Everything → ツール → オプション → HTTP サーバー を有効にする\n"
            "・他 PC から使う場合は、ファイアウォールでポートを許可する\n"
            "・設定は settings.json に保存されます"
        )
        tk.Label(
            card,
            text=tip,
            bg=UI["surface"],
            fg=UI["text_muted"],
            font=FONT_SMALL,
            anchor="w",
            justify="left",
        ).pack(fill="x", pady=(20, 0))

    def _build_help_tab(self):
        parent = self.help_tab
        card = self._card_shell(parent, fill="both", expand=True, padx=8, pady=8)

        tk.Label(
            card,
            text="Everysearch の使い方",
            bg=UI["surface"],
            fg=UI["text"],
            font=FONT_UI_BOLD,
            anchor="w",
        ).pack(fill="x", pady=(0, 8))

        usage = (
            "【このアプリでできること】\n"
            "・型番・図番の検索で、- と _、半角スペースと全角スペースの違いを気にせず検索できます\n"
            "・例: 「694 1056」→ TES694-1056 / TES694_1056 などにもヒット\n"
            "・例: 「TES757_0200」→ TES757-0200 にもヒット\n"
            "\n"
            "【準備（初回のみ）】\n"
            "1. Everything をインストールして起動する（下のリンクから入手）\n"
            "2. Everything → ツール → オプション → HTTP サーバー を有効にする\n"
            "   （ポートは通常 8888）\n"
            "3. ブラウザで http://127.0.0.1:8888/ が開けば OK\n"
            "\n"
            "【検索の手順】\n"
            "1. 「検索」タブで型番・図番を入力する\n"
            "2. 対象フォルダは空欄のままで全体検索、必要ならパスを指定\n"
            "   （\"\\\\サーバー\\共有\\フォルダ\" のようにダブルクォート付き推奨）\n"
            "3. 検索ボタンまたは Enter で実行\n"
            "4. 結果を選んで「選択ファイルを開く」またはダブルクリック\n"
            "\n"
            "【便利な操作】\n"
            "・列ヘッダをクリック → 並び替え（種類 / 名前 / 場所 / サイズ / 日時）\n"
            "・下の「種類フィルタ」をクリック → その種類の表示/非表示\n"
            "・対象フォルダ入力欄 → 履歴から過去のフォルダを選択\n"
            "・接続設定タブ → Everything が別 PC のときのホスト/ポート\n"
        )
        tk.Label(
            card,
            text=usage,
            bg=UI["surface"],
            fg=UI["text"],
            font=FONT_SMALL,
            anchor="nw",
            justify="left",
        ).pack(fill="both", expand=True, pady=(0, 12))

        link_box = tk.Frame(card, bg=UI["surface_2"], highlightbackground=UI["border"], highlightthickness=1)
        link_box.pack(fill="x", pady=(4, 0))
        inner = tk.Frame(link_box, bg=UI["surface_2"])
        inner.pack(fill="x", padx=12, pady=12)

        tk.Label(
            inner,
            text="Everything のダウンロード",
            bg=UI["surface_2"],
            fg=UI["text"],
            font=FONT_UI_BOLD,
            anchor="w",
        ).pack(fill="x")
        tk.Label(
            inner,
            text="公式サイト（voidtools）から最新版を入手できます。",
            bg=UI["surface_2"],
            fg=UI["text_muted"],
            font=FONT_SMALL,
            anchor="w",
        ).pack(fill="x", pady=(4, 8))

        link_row = tk.Frame(inner, bg=UI["surface_2"])
        link_row.pack(fill="x")
        link_label = tk.Label(
            link_row,
            text=EVERYTHING_DOWNLOAD_URL,
            bg=UI["surface_2"],
            fg=UI["primary"],
            font=FONT_UI,
            cursor="hand2",
            anchor="w",
        )
        link_label.pack(side="left", fill="x", expand=True)
        link_label.bind("<Button-1>", lambda _e: self.open_everything_download())
        ModernButton(
            link_row,
            text="サイトを開く",
            command=self.open_everything_download,
            variant="primary",
        ).pack(side="right")

    def open_everything_download(self):
        try:
            webbrowser.open(EVERYTHING_DOWNLOAD_URL)
        except Exception as e:
            messagebox.showerror(
                "開けませんでした",
                f"ブラウザを開けませんでした。\n{EVERYTHING_DOWNLOAD_URL}\n\n{e}",
            )

    # ----- folder history -----
    def get_folder_history(self) -> list[str]:
        return normalize_folder_history(self.settings.get("folder_history", []))

    def set_folder_history(self, history: list[str], persist: bool = True):
        self.settings["folder_history"] = normalize_folder_history(history)
        if persist:
            try:
                save_settings(self.settings)
            except OSError:
                pass

    def add_folder_to_history(self, folder: str, persist: bool = True):
        """使ったフォルダを履歴の先頭へ（空は追加しない）。"""
        q = quote_folder_path(folder)
        if not q:
            return
        history = [q] + [
            h
            for h in self.get_folder_history()
            if strip_folder_quotes(h).lower() != strip_folder_quotes(q).lower()
        ]
        self.set_folder_history(history, persist=persist)
        if self.folder_history_open:
            self._rebuild_history_list()

    def _on_folder_entry_focus(self, _event=None):
        # フォーカス時に履歴を開く
        self.root.after(50, self.show_folder_history)

    def _on_folder_entry_click(self, _event=None):
        self.root.after(10, self.show_folder_history)

    def _on_folder_entry_down(self, _event=None):
        self.show_folder_history()
        return "break"

    def show_folder_history(self):
        if self.folder_history_open:
            self._rebuild_history_list()
            return
        self.folder_history_open = True
        self.history_panel.pack(fill="x", pady=(8, 0))
        self._rebuild_history_list()
        self._update_folder_clear_btn_look()

    def hide_folder_history(self):
        if not self.folder_history_open:
            return
        self.folder_history_open = False
        self.history_panel.pack_forget()
        self._update_folder_clear_btn_look()

    def _update_folder_clear_btn_look(self):
        # 見た目は同じ ×。ツールチップ代わりに title 相当の状態は info で補足しない
        pass

    def _rebuild_history_list(self):
        for child in self.history_list_frame.winfo_children():
            child.destroy()

        history = self.get_folder_history()
        if not history:
            tk.Label(
                self.history_list_frame,
                text="履歴はまだありません（検索やフォルダ選択で追加されます）",
                bg=UI["surface"],
                fg=UI["text_muted"],
                font=FONT_SMALL,
                anchor="w",
            ).pack(fill="x", padx=6, pady=6)
            return

        # スクロール可能な領域
        canvas = tk.Canvas(
            self.history_list_frame,
            bg=UI["surface"],
            highlightthickness=0,
            height=min(220, 36 * min(len(history), 6) + 8),
        )
        scrollbar = ttk.Scrollbar(
            self.history_list_frame,
            orient="vertical",
            command=canvas.yview,
            style="Modern.Vertical.TScrollbar",
        )
        inner = tk.Frame(canvas, bg=UI["surface"])
        inner.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        window_id = canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        if len(history) > 6:
            scrollbar.pack(side="right", fill="y")

        def _on_canvas_configure(event, wid=window_id):
            canvas.itemconfigure(wid, width=event.width)

        canvas.bind("<Configure>", _on_canvas_configure)

        for path in history:
            row = tk.Frame(inner, bg=UI["surface"])
            row.pack(fill="x", pady=1)

            path_btn = tk.Label(
                row,
                text=path,
                bg=UI["surface"],
                fg=UI["text"],
                font=FONT_SMALL,
                anchor="w",
                cursor="hand2",
                padx=8,
                pady=6,
            )
            path_btn.pack(side="left", fill="x", expand=True)

            del_btn = tk.Label(
                row,
                text=" × ",
                bg=UI["surface"],
                fg="#B91C1C",
                font=FONT_UI_BOLD,
                cursor="hand2",
                padx=6,
                pady=4,
            )
            del_btn.pack(side="right")

            def _hover_in(e, w=path_btn, r=row, d=del_btn):
                w.configure(bg=UI["accent_line"])
                r.configure(bg=UI["accent_line"])
                d.configure(bg=UI["accent_line"])

            def _hover_out(e, w=path_btn, r=row, d=del_btn):
                w.configure(bg=UI["surface"])
                r.configure(bg=UI["surface"])
                d.configure(bg=UI["surface"])

            def _select(e, p=path):
                self.select_folder_history(p)

            def _delete(e, p=path):
                self.delete_folder_history(p)
                return "break"

            for w in (path_btn, row):
                w.bind("<Enter>", _hover_in)
                w.bind("<Leave>", _hover_out)
                w.bind("<Button-1>", _select)
            del_btn.bind("<Enter>", _hover_in)
            del_btn.bind("<Leave>", _hover_out)
            del_btn.bind("<Button-1>", _delete)

    def select_folder_history(self, path: str):
        self.folder_var.set(quote_folder_path(path))
        self.add_folder_to_history(path)
        self.hide_folder_history()
        self.folder_entry.focus_set()

    def delete_folder_history(self, path: str):
        key = strip_folder_quotes(path).lower()
        history = [
            h
            for h in self.get_folder_history()
            if strip_folder_quotes(h).lower() != key
        ]
        self.set_folder_history(history)
        # 削除したパスが入力中と同じならクリアはしない（ユーザーが意図した入力を守る）
        self._rebuild_history_list()

    def on_folder_clear_or_close(self):
        """
        履歴リスト表示中 → リストを閉じる
        リスト非表示 → 対象フォルダを空にして全体検索用にする
        """
        if self.folder_history_open:
            self.hide_folder_history()
            return
        self.folder_var.set("")
        self.settings["search_folder"] = ""
        try:
            save_settings(self.settings)
        except OSError:
            pass
        self.info_var.set("対象フォルダをクリアしました（空欄＝全体検索）")

    # ----- folder browse -----
    def browse_folder(self):
        self.hide_folder_history()
        initial = strip_folder_quotes(self.folder_var.get())
        # filedialog は UNC を初期ディレクトリにできない場合がある
        kwargs = {"title": "検索対象フォルダを選択"}
        if initial and Path(initial).exists():
            kwargs["initialdir"] = initial
        chosen = filedialog.askdirectory(**kwargs)
        if chosen:
            # Windows パス区切りをそのまま / から \ に
            chosen = os.path.normpath(chosen)
            quoted = quote_folder_path(chosen)
            self.folder_var.set(quoted)
            self.add_folder_to_history(quoted)

    # ----- settings actions -----
    def save_connection_settings(self):
        host = self.host_var.get().strip() or "127.0.0.1"
        port_text = self.port_var.get().strip()
        try:
            port = int(port_text)
            if not (1 <= port <= 65535):
                raise ValueError
        except ValueError:
            messagebox.showerror("入力エラー", "ポートは 1〜65535 の数値で指定してください。")
            return

        self.settings["host"] = host
        self.settings["port"] = port
        self.settings["user"] = self.user_var.get()
        self.settings["password"] = self.password_var.get()
        self.settings["search_folder"] = quote_folder_path(self.folder_var.get())
        # 現在のフォルダも履歴へ
        if self.settings["search_folder"]:
            self.add_folder_to_history(self.settings["search_folder"], persist=False)

        try:
            save_settings(self.settings)
        except OSError as e:
            messagebox.showerror("保存失敗", f"設定ファイルを保存できませんでした。\n{e}")
            return

        self.settings_status_var.set(f"保存しました: {host}:{port}")
        messagebox.showinfo("保存完了", f"接続設定を保存しました。\n{host}:{port}")

    def test_connection(self):
        host = self.host_var.get().strip() or "127.0.0.1"
        try:
            port = int(self.port_var.get().strip())
        except ValueError:
            messagebox.showerror("入力エラー", "ポートは数値で指定してください。")
            return
        user = self.user_var.get()
        password = self.password_var.get()
        try:
            data = search_everything(
                query_regex="^$",
                search_folder="",
                host=host,
                port=port,
                user=user,
                password=password,
            )
            # 空に近い regex でも応答があれば接続OK
            total = data.get("totalResults", 0)
            self.settings_status_var.set(f"接続成功: {host}:{port}（応答あり / total={total}）")
            messagebox.showinfo(
                "接続成功",
                f"Everything に接続できました。\n{host}:{port}",
            )
        except Exception as e:
            self.settings_status_var.set(f"接続失敗: {host}:{port}")
            messagebox.showerror(
                "接続失敗",
                f"接続できませんでした。\n{host}:{port}\n\n{e}",
            )

    # ----- search / sort -----
    def clear_search_keyword(self):
        """検索文字列をクリアする。"""
        self.keyword_var.set("")
        self.entry.focus_set()
        self.info_var.set("検索文字列をクリアしました")

    def on_search(self):
        keyword = self.keyword_var.get().strip()
        if not keyword:
            messagebox.showwarning("入力不足", "検索文字列を入力してください。")
            return

        # 表示フォルダは常に引用符付きに正規化（空は空のまま＝全体検索）
        folder_now = quote_folder_path(self.folder_var.get())
        self.folder_var.set(folder_now)
        self.hide_folder_history()

        regex = to_flexible_regex(keyword)
        self.regex_var.set(f"変換後正規表現:  {regex}")

        self._clear_tree()
        self.all_results = []
        self.display_results = []
        self.info_var.set("検索中…")
        self.root.update_idletasks()

        conn = self._conn()
        try:
            data = search_everything(
                regex,
                folder_now,
                host=conn["host"],
                port=conn["port"],
                user=conn["user"],
                password=conn["password"],
            )
            self.all_results = parse_results(data)
            self.total_results = int(data.get("totalResults", len(self.all_results)))
            self.apply_sort_and_display()

            # 直近のフォルダを設定・履歴に残す
            self.settings["search_folder"] = folder_now
            if folder_now:
                self.add_folder_to_history(folder_now)
            else:
                try:
                    save_settings(self.settings)
                except OSError:
                    pass

        except HTTPError as e:
            messagebox.showerror(
                "HTTPエラー",
                f"Everything サーバーへの接続で HTTP エラーが発生しました。\n{e}",
            )
            self.info_var.set("検索失敗")
        except URLError as e:
            messagebox.showerror(
                "接続エラー",
                "Everything サーバーに接続できませんでした。\n"
                f"ホスト: {conn['host']}:{conn['port']}\n"
                "「接続設定」タブの内容と、Everything の HTTP サーバーを確認してください。\n"
                f"{e}",
            )
            self.info_var.set("検索失敗")
        except Exception as e:
            messagebox.showerror("エラー", f"予期しないエラーが発生しました。\n{e}")
            self.info_var.set("検索失敗")

    def toggle_sort(self, column: str):
        if self.sort_column == column:
            self.sort_ascending = not self.sort_ascending
        else:
            self.sort_column = column
            self.sort_ascending = self.SORT_DEFAULT_ASC.get(column, True)
        self._update_heading_labels()
        if self.all_results:
            self.apply_sort_and_display()

    def _update_heading_labels(self):
        labels = {
            "type": "種類",
            "name": "名前",
            "path": "場所",
            "size": "サイズ",
            "date": "更新日時",
        }
        arrow = " ↑" if self.sort_ascending else " ↓"
        active = {
            "type": self.sort_column == "type",
            "name": self.sort_column == "path",
            "path": self.sort_column == "path",
            "size": self.sort_column == "size",
            "date": self.sort_column == "date",
        }
        for col, base in labels.items():
            self.tree.heading(col, text=base + (arrow if active[col] else ""))

    def on_type_filter_toggle(self, tag: str, enabled: bool):
        """種類フィルタのオン/オフ。オフの種類は一覧から除外する。"""
        self.type_visible[tag] = enabled
        if self.all_results:
            self.apply_sort_and_display()
        else:
            self._update_info_label()

    def apply_sort_and_display(self):
        key = self.SORT_KEYS.get(self.sort_column, "fullpath")
        reverse = not self.sort_ascending

        filtered = [
            r
            for r in self.all_results
            if self.type_visible.get(r.get("tag", "other"), True)
        ]
        sorted_results = sorted(
            filtered,
            key=lambda r: (r.get(key, ""), r.get("fullpath", "")),
            reverse=reverse,
        )
        self.display_results = sorted_results[:DISPLAY_LIMIT]
        self._populate_tree(self.display_results)
        self._update_info_label()

    def _clear_tree(self):
        for item_id in self.tree.get_children():
            self.tree.delete(item_id)

    def _populate_tree(self, results):
        self._clear_tree()
        for row in results:
            self.tree.insert(
                "",
                tk.END,
                values=(
                    row["type_text"],
                    row["name"],
                    row["path"],
                    row["size_text"],
                    row["date_text"],
                ),
                tags=(row["tag"],),
            )

    def _update_info_label(self):
        shown = len(self.display_results)
        fetched = len(self.all_results)
        total = self.total_results
        direction = "昇順" if self.sort_ascending else "降順"
        col = self.SORT_LABELS.get(self.sort_column, self.sort_column)

        visible_tags = [t for t, on in self.type_visible.items() if on]
        hidden_count = sum(
            1
            for r in self.all_results
            if not self.type_visible.get(r.get("tag", "other"), True)
        )

        if total > fetched:
            base = f"{total} 件中 {fetched} 件取得"
        else:
            base = f"{total} 件ヒット"

        parts = [base, f"{col}{direction}"]
        if hidden_count:
            parts.append(f"種類フィルタで {hidden_count} 件非表示")
        if shown < (fetched - hidden_count) or shown < fetched:
            parts.append(f"上位 {shown} 件を表示")
        if not visible_tags:
            parts.append("すべての種類が非表示")
        self.info_var.set("  ·  ".join(parts))

    def _selected_row(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("未選択", "項目を選択してください。")
            return None
        idx = self.tree.index(sel[0])
        if idx < 0 or idx >= len(self.display_results):
            return None
        return self.display_results[idx]

    def get_selected_path(self):
        row = self._selected_row()
        if not row:
            return None
        return row["fullpath"]

    def open_selected(self, _event=None):
        path = self.get_selected_path()
        if not path:
            return
        try:
            os.startfile(path)
        except Exception as e:
            messagebox.showerror("オープン失敗", f"ファイルを開けませんでした。\n{e}")

    def open_selected_folder(self):
        row = self._selected_row()
        if not row:
            return
        path = row["fullpath"]
        try:
            folder = path if row["type"] == "folder" else os.path.dirname(path)
            os.startfile(folder)
        except Exception as e:
            messagebox.showerror(
                "フォルダオープン失敗", f"フォルダを開けませんでした。\n{e}"
            )

    def copy_selected_path(self):
        path = self.get_selected_path()
        if not path:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(path)
        self.info_var.set(f"パスをコピーしました: {path}")


def main():
    root = tk.Tk()
    try:
        from ctypes import windll

        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    # ウィンドウ／タスクバー用アイコン
    if ICON_PATH.is_file():
        try:
            root.iconbitmap(default=str(ICON_PATH))
        except Exception:
            try:
                root.iconbitmap(str(ICON_PATH))
            except Exception:
                pass
    EverythingSearchApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
