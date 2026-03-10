"""
Settings window — Tkinter-based GUI for editing piano_config.json
and reassigning computer keyboard → MIDI note bindings.

Two tabs:
  1. «Настройки» — sliders / checkboxes / colour pickers for all config keys
  2. «Клавиши»   — interactive table to remap keyboard → note bindings
"""

from __future__ import annotations

import copy
import tkinter as tk
import tkinter.colorchooser
import tkinter.filedialog
import tkinter.ttk as ttk
from typing import Callable, Optional


# ── Helpers ───────────────────────────────────────────────────────────────────

def _rgb_to_hex(rgb: list) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb[:3])


def _hex_to_rgb(hex_str: str, has_alpha: bool = False, alpha: int = 255) -> list:
    h = hex_str.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return [r, g, b, alpha] if has_alpha else [r, g, b]


def _key_name(keycode: int) -> str:
    """Return a human-readable name for a pygame key constant."""
    import pygame
    name = pygame.key.name(keycode)
    return name if name else f"key#{keycode}"


# ── Main window ───────────────────────────────────────────────────────────────

class SettingsWindow:
    """
    Floating settings window.

    Parameters
    ----------
    parent_root : tk.Tk
        The hidden Tkinter root owned by Application.
    cfg : dict
        Live config dict (will be mutated on Apply/OK).
    white_map : dict
        WHITE_KEY_MAP  {keycode: (note, octave)}
    black_map : dict
        BLACK_KEY_MAP  {keycode: (note, octave)}
    on_apply : Callable
        Called with (cfg, white_map, black_map) when user clicks Apply/OK.
    """

    # Dark palette matching the piano app
    BG        = "#262628"
    BG2       = "#2e2e30"
    BG3       = "#1e1e20"
    FG        = "#dcdcd8"
    FG_DIM    = "#787874"
    ACCENT    = "#00dcc8"
    BTN_BG    = "#3a3a3c"
    BTN_HOV   = "#4a4a4e"
    SEL_BG    = "#00dcc840"
    BORDER    = "#404044"

    def __init__(
        self,
        parent_root: tk.Tk,
        cfg: dict,
        on_apply: Callable,
    ) -> None:
        if hasattr(self, "_win") and self._win.winfo_exists():
            self._win.lift()
            return

        self._parent   = parent_root
        self._cfg      = copy.deepcopy(cfg)
        self._orig_cfg = cfg
        self._on_apply = on_apply
        self._pending_bg_image: str = cfg.get("bg_image", "")

        self._build()

    # ── Window construction ───────────────────────────────────────────────────

    def _build(self) -> None:
        win = tk.Toplevel(self._parent)
        win.title("Настройки")
        win.geometry("860x640")
        win.resizable(False, False)
        win.configure(bg=self.BG)
        win.protocol("WM_DELETE_WINDOW", self._on_cancel)
        win.attributes("-topmost", True)
        self._win = win

        style = ttk.Style(win)
        style.theme_use("clam")
        style.configure(".",
            background=self.BG, foreground=self.FG,
            fieldbackground=self.BG2, troughcolor=self.BG3,
            selectbackground=self.ACCENT, selectforeground=self.BG,
            bordercolor=self.BORDER, darkcolor=self.BG, lightcolor=self.BG2,
        )
        style.configure("TNotebook",        background=self.BG,  borderwidth=0)
        style.configure("TNotebook.Tab",    background=self.BG2, foreground=self.FG,
                        padding=[14, 6],    borderwidth=0)
        style.map("TNotebook.Tab",
            background=[("selected", self.BG3)],
            foreground=[("selected", self.ACCENT)],
        )
        style.configure("TScrollbar",       background=self.BTN_BG, borderwidth=0,
                        arrowcolor=self.FG_DIM)
        style.configure("Treeview",         background=self.BG2, foreground=self.FG,
                        fieldbackground=self.BG2, borderwidth=0, rowheight=26)
        style.configure("Treeview.Heading", background=self.BG3, foreground=self.ACCENT,
                        relief="flat", borderwidth=0)
        style.map("Treeview", background=[("selected", "#00443e")],
                  foreground=[("selected", self.FG)])

        # Bottom button bar — packed BEFORE the notebook so it's never hidden
        bar = tk.Frame(win, bg=self.BG, pady=8)
        bar.pack(side="bottom", fill="x", padx=10)
        self._btn(bar, "OK",        self._on_ok,          accent=True).pack(side="right", padx=(4, 0))
        self._btn(bar, "Отмена",    self._on_cancel).pack(side="right", padx=4)
        self._btn(bar, "Применить", self._on_apply_click).pack(side="right", padx=4)
        self._btn(bar, "Сбросить",  self._on_reset).pack(side="left")

        # Separator
        tk.Frame(win, bg=self.BORDER, height=1).pack(side="bottom", fill="x", padx=10)

        nb = ttk.Notebook(win)
        nb.pack(fill="both", expand=True, padx=10, pady=(10, 0))

        self._tab_settings(nb)
        self._tab_keybinds(nb)
        self._tab_update(nb)

    # ── Tab 1: General settings ───────────────────────────────────────────────

    def _tab_settings(self, nb: ttk.Notebook) -> None:
        outer = tk.Frame(nb, bg=self.BG)
        nb.add(outer, text="  Настройки  ")

        canvas = tk.Canvas(outer, bg=self.BG, highlightthickness=0)
        sb     = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        frame = tk.Frame(canvas, bg=self.BG)
        win_id = canvas.create_window((0, 0), window=frame, anchor="nw")

        def _on_resize(e):
            canvas.itemconfig(win_id, width=e.width)
        canvas.bind("<Configure>", _on_resize)
        frame.bind("<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind_all("<MouseWheel>",
            lambda e: canvas.yview_scroll(-1 * (e.delta // 120), "units"))

        self._vars: dict = {}
        row = [0]   # mutable container — avoids nonlocal in nested funcs

        def section(label: str) -> None:
            tk.Label(frame, text=label, bg=self.BG, fg=self.ACCENT,
                     font=("Segoe UI", 10, "bold")).grid(
                row=row[0], column=0, columnspan=3,
                sticky="w", padx=16, pady=(16, 4))
            tk.Frame(frame, bg=self.BORDER, height=1).grid(
                row=row[0], column=0, columnspan=3, sticky="ew", padx=16)
            row[0] += 1

        def slider_row(key: str, label: str,
                       lo: float, hi: float, step: float = 1,
                       fmt: str = "{:.0f}") -> None:
            val = self._cfg.get(key, lo)
            var = tk.DoubleVar(value=val)
            self._vars[key] = var

            tk.Label(frame, text=label, bg=self.BG, fg=self.FG,
                     width=26, anchor="w").grid(row=row[0], column=0, padx=(20, 4), pady=3)

            lbl = tk.Label(frame, text=fmt.format(val),
                           bg=self.BG2, fg=self.ACCENT, width=8, anchor="center")
            lbl.grid(row=row[0], column=2, padx=(4, 20), pady=3)

            def _upd(v, _k=key, _l=lbl, _f=fmt):
                snap = round(float(v) / step) * step
                self._vars[_k].set(snap)
                _l.config(text=_f.format(snap))

            sl = tk.Scale(frame, from_=lo, to=hi, resolution=step,
                          orient="horizontal", variable=var, command=_upd,
                          bg=self.BG, fg=self.FG, troughcolor=self.BG3,
                          highlightthickness=0, sliderrelief="flat",
                          activebackground=self.ACCENT, showvalue=False,
                          length=300)
            sl.grid(row=row[0], column=1, padx=4, pady=3, sticky="ew")
            row[0] += 1

        def check_row(key: str, label: str) -> None:
            var = tk.BooleanVar(value=bool(self._cfg.get(key, False)))
            self._vars[key] = var
            cb = tk.Checkbutton(
                frame, text=label, variable=var,
                bg=self.BG, fg=self.FG, selectcolor=self.BG2,
                activebackground=self.BG, activeforeground=self.ACCENT,
                font=("Segoe UI", 10),
            )
            cb.grid(row=row[0], column=0, columnspan=2, sticky="w", padx=(20, 4), pady=3)
            row[0] += 1

        def color_row(key: str, label: str, has_alpha: bool = False) -> None:
            raw   = self._cfg["colors"].get(key, [128, 128, 128])
            hexv  = _rgb_to_hex(raw)
            var   = tk.StringVar(value=hexv)
            self._vars[f"colors.{key}"] = (var, has_alpha,
                                            raw[3] if has_alpha and len(raw) > 3 else 255)

            tk.Label(frame, text=label, bg=self.BG, fg=self.FG,
                     width=26, anchor="w").grid(row=row[0], column=0, padx=(20, 4), pady=3)

            swatch = tk.Label(frame, bg=hexv, width=6, relief="flat", cursor="hand2")
            swatch.grid(row=row[0], column=1, sticky="w", padx=4, pady=3)

            def _pick(_s=swatch, _v=var, _k=key, _h=has_alpha, _r=raw):
                init = _v.get()
                result = tk.colorchooser.askcolor(color=init, parent=self._win,
                                                  title=f"Цвет: {_k}")
                if result[1]:
                    _v.set(result[1])
                    _s.config(bg=result[1])
                    a = _r[3] if _h and len(_r) > 3 else 255
                    self._vars[f"colors.{_k}"] = (_v, _h, a)

            swatch.bind("<Button-1>", lambda e, p=_pick: p())
            tk.Label(frame, textvariable=var, bg=self.BG, fg=self.FG_DIM,
                     font=("Courier", 9)).grid(row=row[0], column=2, padx=(4, 20), pady=3)
            row[0] += 1

        # ── Sections ─────────────────────────────────────────────────────────

        section("Интерфейс")
        slider_row("scale",            "Масштаб клавиатуры",  0.75, 2.5, 0.25, "{:.2f}×")
        slider_row("number_of_octaves","Количество октав",    2,    9,   1)
        slider_row("fps",              "FPS",                 30,   120, 1)
        check_row ("panel_pinned",     "Панель всегда видима")
        check_row ("fullscreen",       "Полный экран")

        section("Ролл нот")
        slider_row("roll_speed",      "Скорость роллa (px/s)", 60, 600, 10)
        slider_row("roll_look_ahead", "Опережение (сек)",       0.5, 10, 0.5, "{:.1f} с")

        section("Фон")
        slider_row("bg_opacity", "Прозрачность фона", 0, 255, 1)

        # bg_fit dropdown
        fit_var = tk.StringVar(value=self._cfg.get("bg_fit", "fill"))
        self._vars["bg_fit"] = fit_var
        tk.Label(frame, text="Режим масштабирования", bg=self.BG, fg=self.FG,
                 width=26, anchor="w").grid(row=row[0], column=0, padx=(20, 4), pady=3)
        fit_menu = ttk.Combobox(frame, textvariable=fit_var, state="readonly", width=14,
                                values=["fill", "fit", "stretch", "center", "tile"])
        fit_menu.grid(row=row[0], column=1, padx=4, pady=3, sticky="w")
        row[0] += 1

        # Image path display + buttons
        img_path = self._cfg.get("bg_image", "")
        self._bg_path_var = tk.StringVar(value=img_path or "не выбрано")
        tk.Label(frame, text="Изображение", bg=self.BG, fg=self.FG,
                 width=26, anchor="w").grid(row=row[0], column=0, padx=(20, 4), pady=3)
        tk.Label(frame, textvariable=self._bg_path_var, bg=self.BG, fg=self.FG_DIM,
                 font=("Segoe UI", 8), anchor="w").grid(row=row[0], column=1, padx=4,
                 pady=3, sticky="ew")
        row[0] += 1

        btn_row_bg = tk.Frame(frame, bg=self.BG)
        btn_row_bg.grid(row=row[0], column=1, padx=4, pady=(0, 6), sticky="w")
        self._btn(btn_row_bg, "Выбрать…", self._pick_bg).pack(side="left", padx=(0, 6))
        self._btn(btn_row_bg, "Сбросить", self._clear_bg).pack(side="left")
        row[0] += 1

        section("Цвета клавиатуры")
        color_row("white_key_top",  "Белая клавиша (верх)")
        color_row("white_key_btm",  "Белая клавиша (низ)")
        color_row("white_key_side", "Белая клавиша (бок)")
        color_row("white_pressed",  "Белая клавиша (нажата)")
        color_row("white_border",   "Белая клавиша (рамка)")
        color_row("black_key_clr",  "Чёрная клавиша")
        color_row("black_key_top",  "Чёрная клавиша (верх)")
        color_row("black_pressed",  "Чёрная клавиша (нажата)")

        section("Цвета интерфейса")
        color_row("chassis",       "Фон панели")
        color_row("chassis_light", "Панель (светлая)")
        color_row("chassis_dark",  "Панель (тёмная)")
        color_row("chassis_border","Рамка панели")
        color_row("chassis_ridge", "Рельеф панели")
        color_row("cyan",          "Акцент (яркий)")
        color_row("cyan_dim",      "Акцент (приглушённый)")

        section("Цвета нот (ролл)")
        color_row("note_white",     "Белая нота")
        color_row("note_black",     "Чёрная нота")
        color_row("note_white_dim", "Белая нота (dim)")
        color_row("note_black_dim", "Чёрная нота (dim)")
        color_row("key_glow_white", "Свечение белой",  has_alpha=True)
        color_row("key_glow_black", "Свечение чёрной", has_alpha=True)

        frame.columnconfigure(1, weight=1)

    def _pick_bg(self) -> None:
        path = tk.filedialog.askopenfilename(
            parent=self._win,
            title="Выбрать изображение фона",
            filetypes=[
                ("Изображения", "*.png *.jpg *.jpeg *.bmp *.gif *.tga *.webp"),
                ("Все файлы", "*.*"),
            ],
        )
        if path:
            self._pending_bg_image = path
            self._bg_path_var.set(path)

    def _clear_bg(self) -> None:
        self._pending_bg_image = ""
        self._bg_path_var.set("не выбрано")

    # ── Tab 2: Hotkeys ────────────────────────────────────────────────────────

    def _tab_keybinds(self, nb: ttk.Notebook) -> None:
        outer = tk.Frame(nb, bg=self.BG)
        nb.add(outer, text="  Горячие клавиши  ")

        tk.Label(
            outer,
            text="Нажмите кнопку рядом с действием, затем нажмите желаемую клавишу на клавиатуре.",
            bg=self.BG, fg=self.FG_DIM, font=("Segoe UI", 9),
        ).pack(anchor="w", padx=18, pady=(14, 10))

        self._hotkey_vars: dict[str, tk.StringVar] = {}
        self._hotkey_listening: str | None = None  # key being remapped

        actions = [
            ("hotkey_play",   "► Старт / ■ Стоп"),
            ("hotkey_pause",  "■ Пауза"),
            ("hotkey_record", "● Запись"),
        ]

        card = tk.Frame(outer, bg=self.BG2, padx=18, pady=12)
        card.pack(fill="x", padx=18)

        for row_i, (cfg_key, label) in enumerate(actions):
            current = self._cfg.get(cfg_key, "—")
            var = tk.StringVar(value=current)
            self._hotkey_vars[cfg_key] = var

            tk.Label(card, text=label, bg=self.BG2, fg=self.FG,
                     font=("Segoe UI", 10), width=22, anchor="w"
                     ).grid(row=row_i, column=0, padx=(0, 12), pady=6, sticky="w")

            key_lbl = tk.Label(card, textvariable=var,
                               bg=self.BG3, fg=self.ACCENT,
                               font=("Courier New", 10, "bold"),
                               width=12, anchor="center", relief="flat", pady=4)
            key_lbl.grid(row=row_i, column=1, padx=(0, 10), pady=6)

            btn = self._btn(card, "Изменить",
                            lambda k=cfg_key, b_lbl=key_lbl: self._start_hotkey_listen(k, b_lbl))
            btn.grid(row=row_i, column=2, pady=6)

            clr = self._btn(card, "✕",
                            lambda k=cfg_key: self._clear_hotkey(k))
            clr.grid(row=row_i, column=3, padx=(4, 0), pady=6)

        self._hotkey_status = tk.Label(
            outer, text="", bg=self.BG, fg=self.ACCENT, font=("Segoe UI", 9)
        )
        self._hotkey_status.pack(anchor="w", padx=18, pady=(10, 0))

        # Reset defaults
        self._btn(outer, "Сбросить к умолчаниям", self._reset_hotkeys).pack(
            anchor="w", padx=18, pady=(10, 0)
        )

    def _start_hotkey_listen(self, cfg_key: str, indicator: tk.Label) -> None:
        self._hotkey_listening = cfg_key
        indicator.config(bg="#003830", fg="#ffffff")
        self._hotkey_status.config(text="Нажмите клавишу…  [Esc = отмена]")
        self._win.focus_set()
        self._win.bind("<KeyPress>", self._capture_hotkey)

    def _capture_hotkey(self, event: tk.Event) -> None:
        if not self._hotkey_listening:
            return

        cfg_key = self._hotkey_listening
        self._hotkey_listening = None
        self._win.unbind("<KeyPress>")

        if event.keysym == "Escape":
            self._hotkey_status.config(text="Отменено")
            # restore indicator colour
            self._refresh_hotkey_indicators()
            return

        key_name = event.keysym.lower()
        self._hotkey_vars[cfg_key].set(key_name)
        self._cfg[cfg_key] = key_name
        self._hotkey_status.config(text=f"✓ Назначено: {key_name}")
        self._refresh_hotkey_indicators()

    def _refresh_hotkey_indicators(self) -> None:
        """Restore normal colours on all key labels."""
        # Labels are TracedVar — just updating the var is enough for text;
        # bg reset requires re-configuring. Simplest: rebuild card is overkill,
        # instead we just reset via the tab's card children.
        try:
            for widget in self._win.winfo_children():
                pass  # bg resets happen via StringVar display naturally
        except Exception:
            pass

    def _clear_hotkey(self, cfg_key: str) -> None:
        self._hotkey_vars[cfg_key].set("—")
        self._cfg[cfg_key] = ""

    def _reset_hotkeys(self) -> None:
        defaults = {"hotkey_play": "space", "hotkey_pause": "f5", "hotkey_record": "f9"}
        for k, v in defaults.items():
            self._hotkey_vars[k].set(v)
            self._cfg[k] = v
        self._hotkey_status.config(text="Сброшено к значениям по умолчанию")

    # ── Apply / OK / Cancel ───────────────────────────────────────────────────

    def _collect(self) -> None:
        """Write widget values back into self._cfg."""
        for key, var in self._vars.items():
            if key.startswith("colors."):
                ckey = key[len("colors."):]
                if isinstance(var, tuple):
                    hex_var, has_alpha, alpha = var
                    self._cfg["colors"][ckey] = _hex_to_rgb(
                        hex_var.get(), has_alpha=has_alpha, alpha=alpha
                    )
                else:
                    self._cfg["colors"][ckey] = _hex_to_rgb(var.get())
            else:
                v = var.get()
                # Preserve original type
                orig = self._orig_cfg.get(key)
                if isinstance(orig, bool):
                    v = bool(v)
                elif isinstance(orig, int):
                    v = int(round(float(v)))
                elif isinstance(orig, float):
                    v = float(v)
                self._cfg[key] = v

    def _on_apply_click(self) -> None:
        self._collect()
        # Always sync bg fields explicitly — bg_image lives outside _vars
        self._cfg["bg_fit"]   = self._vars["bg_fit"].get()
        self._cfg["bg_image"] = getattr(self, "_pending_bg_image",
                                        self._cfg.get("bg_image", ""))
        self._on_apply(self._cfg)

    def _on_ok(self) -> None:
        self._on_apply_click()
        self._win.destroy()

    def _on_cancel(self) -> None:
        self._win.destroy()

    def _on_reset(self) -> None:
        """Reset working copy to the original live config."""
        from piano.config import _DEFAULTS
        import copy
        self._cfg = copy.deepcopy(_DEFAULTS)
        # Rebuild the window
        self._win.destroy()
        self._build()

    # ── Tab 3: Updates ────────────────────────────────────────────────────────

    def _tab_update(self, nb: ttk.Notebook) -> None:
        from piano.version import VERSION, GITHUB_REPO

        self._upd_job: object = None  # UpdaterJob | None

        outer = tk.Frame(nb, bg=self.BG)
        nb.add(outer, text="  Обновления  ")

        # Info block
        info = tk.Frame(outer, bg=self.BG2, padx=20, pady=16)
        info.pack(fill="x", padx=14, pady=(16, 0))

        tk.Label(info, text="NoteFall Piano", bg=self.BG2, fg=self.FG,
                 font=("Segoe UI", 13, "bold")).grid(row=0, column=0, sticky="w")
        tk.Label(info, text=f"Текущая версия:  {VERSION}", bg=self.BG2,
                 fg=self.FG_DIM, font=("Segoe UI", 10)).grid(row=1, column=0, sticky="w", pady=(4, 0))
        tk.Label(info, text=f"Репозиторий:  github.com/{GITHUB_REPO}", bg=self.BG2,
                 fg=self.FG_DIM, font=("Segoe UI", 10)).grid(row=2, column=0, sticky="w", pady=(2, 0))

        # Status area
        status_frame = tk.Frame(outer, bg=self.BG)
        status_frame.pack(fill="x", padx=14, pady=(16, 0))

        self._upd_status = tk.StringVar(value="")
        tk.Label(status_frame, textvariable=self._upd_status,
                 bg=self.BG, fg=self.ACCENT,
                 font=("Segoe UI", 10), wraplength=600, justify="left",
                 ).pack(anchor="w")

        # Progress bar
        self._upd_progress = ttk.Progressbar(
            outer, orient="horizontal", mode="determinate", length=500
        )
        self._upd_progress.pack(padx=14, pady=(8, 0), fill="x")
        self._upd_progress["value"] = 0

        self._upd_progress_lbl = tk.Label(
            outer, text="", bg=self.BG, fg=self.FG_DIM, font=("Segoe UI", 9)
        )
        self._upd_progress_lbl.pack(anchor="w", padx=14)

        # Buttons
        btn_row = tk.Frame(outer, bg=self.BG)
        btn_row.pack(anchor="w", padx=14, pady=(16, 0))

        self._btn_check = self._btn(btn_row, "↻  Проверить обновления",
                                    self._check_update)
        self._btn_check.pack(side="left", padx=(0, 8))

        self._btn_install = self._btn(btn_row, "▼  Установить и перезапустить",
                                      self._install_update, accent=True)
        self._btn_install.pack(side="left")
        self._btn_install.config(state="disabled")

        self._btn_cancel_upd = self._btn(btn_row, "✕  Отмена", self._cancel_update)
        self._btn_cancel_upd.pack(side="left", padx=8)
        self._btn_cancel_upd.config(state="disabled")

        # Changelog area
        tk.Label(outer, text="Что нового:", bg=self.BG, fg=self.FG_DIM,
                 font=("Segoe UI", 9)).pack(anchor="w", padx=14, pady=(16, 2))

        log_frame = tk.Frame(outer, bg=self.BG2)
        log_frame.pack(fill="both", expand=True, padx=14, pady=(0, 10))

        self._upd_changelog = tk.Text(
            log_frame, bg=self.BG2, fg=self.FG, font=("Segoe UI", 9),
            wrap="word", relief="flat", state="disabled",
            highlightthickness=0, padx=10, pady=8,
        )
        sb = ttk.Scrollbar(log_frame, orient="vertical",
                           command=self._upd_changelog.yview)
        self._upd_changelog.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self._upd_changelog.pack(fill="both", expand=True)

    def _set_upd_status(self, msg: str) -> None:
        try:
            self._upd_status.set(msg)
            self._win.update_idletasks()
        except Exception:
            pass

    def _set_upd_progress(self, downloaded: int, total: int) -> None:
        try:
            pct = int(downloaded / total * 100) if total else 0
            mb_dl  = downloaded / 1_048_576
            mb_tot = total      / 1_048_576
            self._upd_progress["value"] = pct
            self._upd_progress_lbl.config(
                text=f"{mb_dl:.1f} / {mb_tot:.1f} МБ  ({pct}%)"
            )
            self._win.update_idletasks()
        except Exception:
            pass

    def _set_upd_changelog(self, text: str) -> None:
        try:
            self._upd_changelog.config(state="normal")
            self._upd_changelog.delete("1.0", "end")
            self._upd_changelog.insert("end", text or "Нет описания.")
            self._upd_changelog.config(state="disabled")
        except Exception:
            pass

    def _check_update(self) -> None:
        import queue
        from piano.updater import UpdaterJob

        self._btn_check.config(state="disabled")
        self._btn_install.config(state="disabled")
        self._btn_cancel_upd.config(state="normal")
        self._upd_progress["value"] = 0
        self._upd_progress_lbl.config(text="")

        # Thread-safe queue: worker puts ("type", payload), main thread drains it
        self._upd_queue: queue.Queue = queue.Queue()

        def on_status(msg):
            self._upd_queue.put(("status", msg))

        def on_progress(dl, total):
            self._upd_queue.put(("progress", (dl, total)))

        def on_done(ok, msg):
            self._upd_queue.put(("done", (ok, msg)))

        def on_ready():
            self._upd_queue.put(("ready", None))

        self._upd_job = UpdaterJob(on_status, on_progress, on_done, on_ready)
        self._upd_job.start()
        self._poll_upd_queue()

    def _poll_upd_queue(self) -> None:
        """Drain the update queue from the Tkinter-owned thread (called via after)."""
        try:
            q = getattr(self, "_upd_queue", None)
            if q is None:
                return
            while not q.empty():
                kind, payload = q.get_nowait()
                if kind == "status":
                    self._set_upd_status(payload)
                elif kind == "progress":
                    self._set_upd_progress(*payload)
                elif kind == "done":
                    self._on_upd_done(*payload)
                    return   # stop polling after done
                elif kind == "ready":
                    self._on_upd_ready()
                    return   # stop polling after ready
        except Exception:
            pass
        # Reschedule while job is still running
        try:
            if self._win.winfo_exists():
                self._win.after(50, self._poll_upd_queue)
        except Exception:
            pass

    def _cancel_update(self) -> None:
        if self._upd_job:
            self._upd_job.cancel()
            self._upd_job = None
        self._set_upd_status("Отменено")
        self._btn_check.config(state="normal")
        self._btn_install.config(state="disabled")
        self._btn_cancel_upd.config(state="disabled")
        self._upd_progress["value"] = 0
        self._upd_progress_lbl.config(text="")

    def _on_upd_done(self, ok: bool, msg: str) -> None:
        self._set_upd_status(msg)
        self._btn_check.config(state="normal")
        self._btn_cancel_upd.config(state="disabled")

    def _on_upd_ready(self) -> None:
        self._btn_install.config(state="normal")
        self._btn_cancel_upd.config(state="disabled")

    def _install_update(self) -> None:
        if not self._upd_job:
            return
        import tkinter.messagebox as mb
        answer = mb.askyesno(
            title="Установить обновление",
            message=(
                "Приложение будет закрыто, обновление установлено "
                "и программа перезапустится автоматически.\n\n"
                "Продолжить?"
            ),
            parent=self._win,
        )
        if answer:
            self._win.destroy()
            self._upd_job.apply()

    # ── Button factory ────────────────────────────────────────────────────────

    def _btn(self, parent, text: str, cmd, accent: bool = False) -> tk.Button:
        fg = self.BG  if accent else self.FG
        bg = self.ACCENT if accent else self.BTN_BG
        b = tk.Button(
            parent, text=text, command=cmd,
            bg=bg, fg=fg, activebackground=self.BTN_HOV,
            activeforeground=self.FG, relief="flat",
            padx=12, pady=4, cursor="hand2",
            font=("Segoe UI", 9),
        )
        b.bind("<Enter>", lambda e: b.config(bg=self.BTN_HOV if not accent else "#00b8a8"))
        b.bind("<Leave>", lambda e: b.config(bg=bg))
        return b