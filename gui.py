# --- gui.py ---

from collections import deque
import os
import threading
import customtkinter as ctk

from utils import get_resource_path, is_adb_ready, read_game_resources, stop_touch_daemon


def _fmt_threshold(val):
    val = int(round(val))
    if val <= 0:
        return "Any"
    if val >= 1_000_000:
        m = val / 1_000_000.0
        return f"{m:.2f}".rstrip("0").rstrip(".") + "M"
    if val >= 1_000:
        if val % 1_000 == 0:
            return f"{val // 1_000}K"
        return f"{val / 1_000.0:.1f}K"
    return str(val)


class App(ctk.CTk):
    def __init__(self, bot):
        super().__init__()
        self.bot = bot
        self._closing = False
        self._log_buffer = deque(maxlen=400)
        self._log_win = None
        self._log_textbox = None

        self.title("Clash of Clans Trainer")
        self.geometry("480x660")
        self.resizable(False, False)

        icon_path = get_resource_path("icon.ico")
        if os.path.exists(icon_path):
            try:
                self.iconbitmap(icon_path)
            except Exception:
                pass

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.mode_map = {
            "Normal": {
                "type": "normal",
                "title": "Normal Attack",
                "desc": "Smart loot scouting, Next skipping, and dragon assault.",
                "button": "START NORMAL ATTACK",
                "has_sub_reps": False,
            },
            "Ranked": {
                "type": "ranked",
                "title": "Ranked Attack",
                "desc": "Direct ranked matchmaking, dragon deployment, and return.",
                "button": "START RANKED ATTACK",
                "has_sub_reps": False,
            },
            "Walls": {
                "type": "walls",
                "title": "Normal Attack + Walls",
                "desc": "Smart loot farming attacks followed by wall upgrades.",
                "button": "START WALLS AUTOMATION",
                "has_sub_reps": True,
            },
            "Builder": {
                "type": "builder",
                "title": "Builder Base Attack",
                "desc": "Two-stage Builder Base assault with resource collection.",
                "button": "START BUILDER ATTACK",
                "has_sub_reps": False,
            },
        }

        self._setup_ui()
        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.after(100, self._detect_initial_mode)

    def _setup_ui(self):
        # Header Title
        self.title_label = ctk.CTkLabel(
            self,
            text="Clash of Clans Trainer",
            font=ctk.CTkFont(size=19, weight="bold"),
            height=26,
        )
        self.title_label.pack(padx=18, pady=(10, 6))

        # Mode Selector
        self.mode_selector = ctk.CTkSegmentedButton(
            self,
            values=["Normal", "Ranked", "Walls", "Builder"],
            command=self._on_mode_change,
            height=28,
            font=ctk.CTkFont(size=12, weight="bold"),
        )
        self.mode_selector.pack(fill="x", padx=18, pady=(0, 8))
        self.mode_selector.set("Normal")

        # Mode & Execution Card
        self.card = ctk.CTkFrame(self, corner_radius=10, fg_color="#1C1E22")
        self.card.pack(fill="x", padx=18, pady=2)

        self.mode_title = ctk.CTkLabel(
            self.card,
            text="Normal Attack",
            font=ctk.CTkFont(size=14, weight="bold"),
            height=20,
        )
        self.mode_title.pack(anchor="w", padx=14, pady=(8, 0))

        self.mode_desc = ctk.CTkLabel(
            self.card,
            text="Smart loot scouting, Next skipping, and dragon assault.",
            font=ctk.CTkFont(size=11),
            text_color="#9BA1A6",
            height=16,
        )
        self.mode_desc.pack(anchor="w", padx=14, pady=(0, 4))

        self.controls_frame = ctk.CTkFrame(self.card, fg_color="transparent")
        self.controls_frame.pack(fill="x", padx=14, pady=(0, 4))
        self.controls_frame.grid_columnconfigure(1, weight=1)

        self.reps_label = ctk.CTkLabel(
            self.controls_frame, text="Loop Count:", font=ctk.CTkFont(size=12), height=24
        )
        self.reps_label.grid(row=0, column=0, padx=(0, 8), pady=2, sticky="w")

        self.reps_entry = ctk.CTkEntry(self.controls_frame, width=80, height=24)
        self.reps_entry.insert(0, "10")
        self.reps_entry.grid(row=0, column=1, padx=(0, 8), pady=2, sticky="ew")

        self.infinite_check = ctk.CTkCheckBox(
            self.controls_frame,
            text="Run Infinitely",
            font=ctk.CTkFont(size=12),
            checkbox_width=18,
            checkbox_height=18,
        )
        self.infinite_check.grid(row=0, column=2, pady=2, sticky="e")

        self.sub_reps_label = ctk.CTkLabel(
            self.controls_frame, text="Attacks before Upgrade:", font=ctk.CTkFont(size=12), height=24
        )
        self.sub_reps_entry = ctk.CTkEntry(self.controls_frame, width=80, height=24)
        self.sub_reps_entry.insert(0, "10")

        # Background Mode Toggle Row
        self.bg_frame = ctk.CTkFrame(self.card, corner_radius=8, fg_color="#141619", height=32)
        self.bg_frame.pack(fill="x", padx=14, pady=(2, 8))

        self.bg_mode_check = ctk.CTkCheckBox(
            self.bg_frame,
            text="Background Mode (ADB)",
            command=self._on_bg_mode_toggle,
            font=ctk.CTkFont(size=12, weight="bold"),
            checkbox_width=18,
            checkbox_height=18,
        )
        self.bg_mode_check.pack(side="left", padx=10, pady=5)

        self.bg_status_label = ctk.CTkLabel(
            self.bg_frame,
            text="Foreground",
            font=ctk.CTkFont(size=11),
            text_color="#9BA1A6",
            height=18,
        )
        self.bg_status_label.pack(side="right", padx=10, pady=5)

        # Live Resource Tracker Card
        self.tracker_card = ctk.CTkFrame(self, corner_radius=10, fg_color="#1C1E22")
        self.tracker_card.pack(fill="x", padx=18, pady=4)

        tracker_hdr = ctk.CTkFrame(self.tracker_card, fg_color="transparent")
        tracker_hdr.pack(fill="x", padx=14, pady=(7, 3))

        ctk.CTkLabel(
            tracker_hdr, text="Resource Tracker", font=ctk.CTkFont(size=13, weight="bold"), height=18
        ).pack(side="left")

        self.skip_label = ctk.CTkLabel(
            tracker_hdr, text="Skipped: 0", font=ctk.CTkFont(size=11), text_color="#9BA1A6", height=18
        )
        self.skip_label.pack(side="right")

        self.log_btn = ctk.CTkButton(
            tracker_hdr,
            text="Log",
            command=self._open_log_window,
            width=44,
            height=22,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color="#2C3E50",
            hover_color="#34495E",
        )
        self.log_btn.pack(side="right", padx=(0, 8))

        self.test_read_btn = ctk.CTkButton(
            tracker_hdr,
            text="Test Read",
            command=self._on_test_read_clicked,
            width=70,
            height=22,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color="#2C3E50",
            hover_color="#34495E",
        )
        self.test_read_btn.pack(side="right", padx=(0, 6))

        res_grid = ctk.CTkFrame(self.tracker_card, corner_radius=8, fg_color="#141619")
        res_grid.pack(fill="x", padx=14, pady=(0, 8))
        res_grid.grid_columnconfigure((1, 3), weight=1)

        ctk.CTkLabel(
            res_grid, text="Enemy Loot", font=ctk.CTkFont(size=11, weight="bold"), text_color="#CBD5E1", height=18
        ).grid(row=0, column=0, columnspan=2, padx=10, pady=(4, 1), sticky="w")
        ctk.CTkLabel(
            res_grid, text="Your Resources", font=ctk.CTkFont(size=11, weight="bold"), text_color="#CBD5E1", height=18
        ).grid(row=0, column=2, columnspan=2, padx=10, pady=(4, 1), sticky="w")

        self.res_labels = {}
        rows = [
            ("Gold", "#F1C40F", "enemy_gold", "own_gold", 1),
            ("Elixir", "#E86AF0", "enemy_elixir", "own_elixir", 2),
            ("Dark", "#A29BFE", "enemy_dark", "own_dark", 3),
        ]
        for caption, color, e_key, o_key, r in rows:
            pb = 4 if r == 3 else 1
            ctk.CTkLabel(
                res_grid, text=f"{caption}:", font=ctk.CTkFont(size=11), text_color=color, height=18, anchor="w"
            ).grid(row=r, column=0, padx=(10, 4), pady=(1, pb), sticky="w")
            e_val = ctk.CTkLabel(
                res_grid, text="--", font=ctk.CTkFont(size=12, weight="bold"), text_color="#F8FAFC", height=18, anchor="e"
            )
            e_val.grid(row=r, column=1, padx=(0, 14), pady=(1, pb), sticky="e")
            self.res_labels[e_key] = e_val

            ctk.CTkLabel(
                res_grid, text=f"{caption}:", font=ctk.CTkFont(size=11), text_color=color, height=18, anchor="w"
            ).grid(row=r, column=2, padx=(10, 4), pady=(1, pb), sticky="w")
            o_val = ctk.CTkLabel(
                res_grid, text="--", font=ctk.CTkFont(size=12, weight="bold"), text_color="#F8FAFC", height=18, anchor="e"
            )
            o_val.grid(row=r, column=3, padx=(0, 10), pady=(1, pb), sticky="e")
            self.res_labels[o_key] = o_val

        # Loot Threshold Sliders Card
        self.thresh_card = ctk.CTkFrame(self, corner_radius=10, fg_color="#1C1E22")
        self.thresh_card.pack(fill="x", padx=18, pady=4)

        thresh_hdr = ctk.CTkFrame(self.thresh_card, fg_color="transparent")
        thresh_hdr.pack(fill="x", padx=14, pady=(7, 3))

        ctk.CTkLabel(
            thresh_hdr, text="Loot Thresholds", font=ctk.CTkFont(size=13, weight="bold"), height=18
        ).pack(side="left")

        self.match_any_check = ctk.CTkCheckBox(
            thresh_hdr,
            text="Match Any (OR)",
            command=self._on_threshold_change,
            font=ctk.CTkFont(size=11),
            checkbox_width=16,
            checkbox_height=16,
        )
        self.match_any_check.pack(side="right")

        sliders_frame = ctk.CTkFrame(self.thresh_card, fg_color="transparent")
        sliders_frame.pack(fill="x", padx=14, pady=(0, 7))
        sliders_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            sliders_frame, text="Min Gold", font=ctk.CTkFont(size=11), text_color="#F1C40F", width=58, height=18, anchor="w"
        ).grid(row=0, column=0, pady=2, sticky="w")
        self.gold_slider = ctk.CTkSlider(
            sliders_frame, from_=0, to=2_500_000, number_of_steps=50, height=16, command=lambda _v: self._on_threshold_change()
        )
        self.gold_slider.set(500_000)
        self.gold_slider.grid(row=0, column=1, padx=8, pady=2, sticky="ew")
        self.gold_val_label = ctk.CTkLabel(
            sliders_frame, text="500K", font=ctk.CTkFont(size=11, weight="bold"), width=46, height=18, anchor="e"
        )
        self.gold_val_label.grid(row=0, column=2, pady=2, sticky="e")

        ctk.CTkLabel(
            sliders_frame, text="Min Elixir", font=ctk.CTkFont(size=11), text_color="#E86AF0", width=58, height=18, anchor="w"
        ).grid(row=1, column=0, pady=2, sticky="w")
        self.elixir_slider = ctk.CTkSlider(
            sliders_frame, from_=0, to=2_500_000, number_of_steps=50, height=16, command=lambda _v: self._on_threshold_change()
        )
        self.elixir_slider.set(500_000)
        self.elixir_slider.grid(row=1, column=1, padx=8, pady=2, sticky="ew")
        self.elixir_val_label = ctk.CTkLabel(
            sliders_frame, text="500K", font=ctk.CTkFont(size=11, weight="bold"), width=46, height=18, anchor="e"
        )
        self.elixir_val_label.grid(row=1, column=2, pady=2, sticky="e")

        ctk.CTkLabel(
            sliders_frame, text="Min Dark", font=ctk.CTkFont(size=11), text_color="#A29BFE", width=58, height=18, anchor="w"
        ).grid(row=2, column=0, pady=2, sticky="w")
        self.dark_slider = ctk.CTkSlider(
            sliders_frame, from_=0, to=25_000, number_of_steps=50, height=16, command=lambda _v: self._on_threshold_change()
        )
        self.dark_slider.set(0)
        self.dark_slider.grid(row=2, column=1, padx=8, pady=2, sticky="ew")
        self.dark_val_label = ctk.CTkLabel(
            sliders_frame, text="Any", font=ctk.CTkFont(size=11, weight="bold"), width=46, height=18, anchor="e"
        )
        self.dark_val_label.grid(row=2, column=2, pady=2, sticky="e")

        # Min Wall Resource Row (shown in Walls mode to prevent premature Gem prompts)
        self.wall_min_name_lbl = ctk.CTkLabel(
            sliders_frame, text="Min Wall", font=ctk.CTkFont(size=11), text_color="#2ECC71", width=58, height=18, anchor="w"
        )
        self.wall_min_slider = ctk.CTkSlider(
            sliders_frame, from_=0, to=10_000_000, number_of_steps=100, height=16, command=lambda _v: self._on_threshold_change()
        )
        self.wall_min_slider.set(1_500_000)
        self.wall_min_val_label = ctk.CTkLabel(
            sliders_frame, text="1.5M", font=ctk.CTkFont(size=11, weight="bold"), width=46, height=18, anchor="e"
        )

        # Start & Stop Buttons
        self.start_button = ctk.CTkButton(
            self,
            text="START NORMAL ATTACK",
            command=self._on_start_clicked,
            height=34,
            font=ctk.CTkFont(size=13, weight="bold"),
        )
        self.start_button.pack(fill="x", padx=18, pady=(6, 4))

        self.stop_button = ctk.CTkButton(
            self,
            text="STOP ALL AUTOMATION",
            command=self.bot.stop,
            height=30,
            fg_color="#D35400",
            hover_color="#B84300",
            font=ctk.CTkFont(size=13, weight="bold"),
        )
        self.stop_button.pack(fill="x", padx=18, pady=(0, 6))

        # Status Area
        self.status_frame = ctk.CTkFrame(self, corner_radius=8, fg_color="#141619")
        self.status_frame.pack(fill="both", expand=True, padx=18, pady=(0, 10))

        self.status_label = ctk.CTkLabel(
            self.status_frame,
            text="Status: Ready",
            font=ctk.CTkFont(size=12),
            wraplength=425,
            justify="center",
        )
        self.status_label.pack(expand=True, fill="both", padx=10, pady=6)

        self._on_threshold_change()

    def _open_log_window(self):
        """Opens or focuses the scrollable diagnostic activity log window."""
        if self._log_win is not None:
            try:
                if self._log_win.winfo_exists():
                    self._log_win.focus()
                    return
            except Exception:
                pass

        win = ctk.CTkToplevel(self)
        win.title("Trainer Activity Log")
        win.geometry("620x400")
        win.configure(fg_color="#141619")
        self._log_win = win

        top_bar = ctk.CTkFrame(win, fg_color="transparent")
        top_bar.pack(fill="x", padx=12, pady=(10, 4))

        ctk.CTkLabel(
            top_bar,
            text="Activity & Recovery Log (also saved to clash_trainer.log)",
            font=ctk.CTkFont(size=12, weight="bold"),
        ).pack(side="left")

        ctk.CTkButton(
            top_bar, text="Clear", width=56, height=24, command=self._clear_logs
        ).pack(side="right")

        ctk.CTkButton(
            top_bar, text="Copy All", width=72, height=24, command=self._copy_logs
        ).pack(side="right", padx=(0, 6))

        tb = ctk.CTkTextbox(win, font=ctk.CTkFont(family="Consolas", size=11), fg_color="#1C1E22")
        tb.pack(fill="both", expand=True, padx=12, pady=(2, 12))
        self._log_textbox = tb

        if self._log_buffer:
            tb.insert("end", "\n".join(self._log_buffer) + "\n")
            tb.see("end")
        tb.configure(state="disabled")

    def _clear_logs(self):
        self._log_buffer.clear()
        if self._log_textbox:
            try:
                if self._log_textbox.winfo_exists():
                    self._log_textbox.configure(state="normal")
                    self._log_textbox.delete("1.0", "end")
                    self._log_textbox.configure(state="disabled")
            except Exception:
                pass

    def _copy_logs(self):
        text = "\n".join(self._log_buffer)
        try:
            self.clipboard_clear()
            self.clipboard_append(text)
            self.update_status("Copied activity log to clipboard.")
        except Exception:
            pass

    def _append_log_ui(self, line):
        if self._closing:
            return
        self._log_buffer.append(line)
        if self._log_textbox:
            try:
                if self._log_textbox.winfo_exists():
                    self._log_textbox.configure(state="normal")
                    self._log_textbox.insert("end", line + "\n")
                    self._log_textbox.see("end")
                    self._log_textbox.configure(state="disabled")
            except Exception:
                pass

    def append_log(self, line):
        if self._closing:
            return
        if threading.current_thread() is threading.main_thread():
            self._append_log_ui(line)
        else:
            try:
                self.after(0, lambda ln=line: self._append_log_ui(ln))
            except Exception:
                pass

    def _on_threshold_change(self):
        min_gold = int(round(self.gold_slider.get() / 50_000) * 50_000)
        min_elixir = int(round(self.elixir_slider.get() / 50_000) * 50_000)
        min_dark = int(round(self.dark_slider.get() / 500) * 500)
        wall_min = int(round(self.wall_min_slider.get() / 100_000) * 100_000)
        match_any = bool(self.match_any_check.get())

        self.gold_val_label.configure(text=_fmt_threshold(min_gold))
        self.elixir_val_label.configure(text=_fmt_threshold(min_elixir))
        self.dark_val_label.configure(text=_fmt_threshold(min_dark))
        self.wall_min_val_label.configure(text=_fmt_threshold(wall_min))

        self.bot.set_loot_thresholds(
            min_gold=min_gold,
            min_elixir=min_elixir,
            min_dark=min_dark,
            match_any=match_any,
            wall_min=wall_min,
        )

    def _on_test_read_clicked(self):
        """Runs a passive single-frame OCR check (no clicks) for live human verification."""
        use_bg = bool(self.bg_mode_check.get())
        self.update_status("Reading resources from current game frame...")

        def worker():
            res = read_game_resources(None, include_enemy=True, background_mode=use_bg)
            if self._closing:
                return
            if not res:
                self.update_status("Test Read failed: could not capture game window.")
                return
            self.update_resources(res, None)
            eg = res.get("enemy_gold")
            ee = res.get("enemy_elixir")
            ed = res.get("enemy_dark")
            og = res.get("own_gold", 0)
            oe = res.get("own_elixir", 0)
            od = res.get("own_dark", 0)
            if eg is not None:
                msg = f"Test Read | Enemy G:{eg:,} E:{ee:,} DE:{ed:,} | Yours G:{og:,} E:{oe:,} DE:{od:,}"
            else:
                msg = f"Test Read | Yours G:{og:,} E:{oe:,} DE:{od:,} (No enemy loot on screen)"
            self.update_status(msg)

        threading.Thread(target=worker, daemon=True).start()

    def _detect_initial_mode(self):
        def worker():
            ready = is_adb_ready(force_refresh=True, try_connect=True)
            if self._closing:
                return
            self.after(0, lambda: self._apply_initial_adb_state(ready))

        threading.Thread(target=worker, daemon=True).start()

    def _apply_initial_adb_state(self, ready):
        if self._closing:
            return
        if ready:
            self.bg_mode_check.select()
            self.bot.set_background_mode(True)
            self.bg_status_label.configure(text="ADB Ready", text_color="#2ECC71")
            self.update_status("Ready (Background ADB detected and enabled)")
        else:
            self.bg_mode_check.deselect()
            self.bot.set_background_mode(False)
            self.bg_status_label.configure(text="Foreground", text_color="#9BA1A6")
            self.update_status("Ready (Foreground Mode)")

    def _on_bg_mode_toggle(self):
        enabled = bool(self.bg_mode_check.get())
        self.bot.set_background_mode(enabled)

        if not enabled:
            self.bg_status_label.configure(text="Foreground", text_color="#9BA1A6")
            self.update_status("Background Mode OFF (Foreground mouse and keyboard)")
            return

        self.bg_status_label.configure(text="Checking ADB...", text_color="#E5C07B")

        def worker():
            ready = is_adb_ready(force_refresh=True, try_connect=True)
            if self._closing:
                return
            self.after(0, lambda: self._on_adb_check_done(ready))

        threading.Thread(target=worker, daemon=True).start()

    def _on_adb_check_done(self, ready):
        if self._closing or not bool(self.bg_mode_check.get()):
            return
        if ready:
            self.bg_status_label.configure(text="ADB Ready", text_color="#2ECC71")
            self.update_status("Background Mode ON (ADB connected)")
        else:
            self.bg_status_label.configure(text="ADB Offline", text_color="#E67E22")
            self.update_status("Background Mode ON, but ADB is offline. Start BlueStacks with ADB enabled.")

    def _on_mode_change(self, mode_name):
        config = self.mode_map.get(mode_name, self.mode_map["Normal"])
        self.mode_title.configure(text=config["title"])
        self.mode_desc.configure(text=config["desc"])
        self.start_button.configure(text=config["button"])

        if config["has_sub_reps"]:
            self.reps_label.configure(text="Major Cycles:")
            self.sub_reps_label.grid(row=1, column=0, padx=(0, 8), pady=3, sticky="w")
            self.sub_reps_entry.grid(row=1, column=1, columnspan=2, pady=3, sticky="ew")
            self.wall_min_name_lbl.grid(row=3, column=0, pady=2, sticky="w")
            self.wall_min_slider.grid(row=3, column=1, padx=8, pady=2, sticky="ew")
            self.wall_min_val_label.grid(row=3, column=2, pady=2, sticky="e")
        else:
            self.reps_label.configure(text="Loop Count:")
            self.sub_reps_label.grid_forget()
            self.sub_reps_entry.grid_forget()
            self.wall_min_name_lbl.grid_forget()
            self.wall_min_slider.grid_forget()
            self.wall_min_val_label.grid_forget()

    def _on_start_clicked(self):
        selected_mode = self.mode_selector.get()
        config = self.mode_map.get(selected_mode, self.mode_map["Normal"])
        attack_type = config["type"]

        reps = 10
        try:
            reps = int(self.reps_entry.get())
            if reps <= 0:
                reps = 10
                self.update_status("Loops must be > 0. Defaulting to 10.")
        except ValueError:
            reps = 10
            self.update_status("Invalid loop count. Defaulting to 10.")

        sub_reps = 10
        if config["has_sub_reps"]:
            try:
                sub_reps = int(self.sub_reps_entry.get())
                if sub_reps <= 0:
                    sub_reps = 10
                    self.update_status("Attacks/upgrade must be > 0. Defaulting to 10.")
            except ValueError:
                sub_reps = 10
                self.update_status("Invalid attacks/upgrade count. Defaulting to 10.")

        self._on_threshold_change()
        is_infinite = bool(self.infinite_check.get())
        bg_mode = bool(self.bg_mode_check.get())
        self.bot.start(
            attack_type=attack_type,
            reps=reps,
            is_infinite=is_infinite,
            attacks_per_upgrade=sub_reps,
            background_mode=bg_mode,
        )

    def _apply_resources(self, resources, skipped=None):
        if self._closing or not resources:
            return
        try:
            if not self.winfo_exists():
                return
            for key, lbl in self.res_labels.items():
                val = resources.get(key)
                if val is not None:
                    lbl.configure(text=f"{int(val):,}")
            if skipped is not None:
                self.skip_label.configure(text=f"Skipped: {int(skipped)}")
        except Exception:
            pass

    def update_resources(self, resources, skipped=None):
        if self._closing or not resources:
            return
        data = dict(resources)
        if threading.current_thread() is threading.main_thread():
            self._apply_resources(data, skipped)
        else:
            try:
                self.after(0, lambda d=data, s=skipped: self._apply_resources(d, s))
            except Exception:
                pass

    def _set_status_text(self, message):
        if self._closing:
            return
        try:
            if self.winfo_exists():
                self.status_label.configure(text=f"Status: {message}")
        except Exception:
            pass

    def update_status(self, message):
        if self._closing:
            return
        if threading.current_thread() is threading.main_thread():
            self._set_status_text(message)
        else:
            try:
                self.after(0, lambda m=message: self._set_status_text(m))
            except Exception:
                pass

    def on_closing(self):
        self._closing = True
        self.bot.stop()
        stop_touch_daemon()
        if self._log_win:
            try:
                self._log_win.destroy()
            except Exception:
                pass
        self.destroy()
