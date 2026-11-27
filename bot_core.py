# --- bot_core.py ---

import datetime
import os
import random
import threading
import time

import pyautogui

import attack_loops
from utils import (
    KEY_PERCENT_MAP,
    adb_keyevent,
    adb_pinch_zoom,
    adb_swipe,
    adb_tap,
    capture_game_bgr,
    ensure_bluestacks_active,
    ensure_touch_daemon,
    find_image_multi_scale,
    find_image_with_score,
    get_adb_resolution,
    get_scaled_point,
    inspect_screen_templates,
    is_adb_ready,
    read_game_resources,
)

# Priority order for state detection during interruption recovery
RECOVERY_TEMPLATE_SPECS = [
    ("templates/build_close_btn.png", 0.72),
    ("templates/left_panel_close_btn.png", 0.72),
    ("templates/return_btn.png", 0.70),
    ("templates/surrender_btn.png", 0.70),
    ("templates/next_btn.png", 0.66),
    ("templates/end_battle_btn.png", 0.70),
    ("templates/dragon_card.png", 0.70),
    ("templates/attack_btn.png", 0.70),
    ("templates/find_a_match_btn.png", 0.70),
    ("templates/battle_btn.png", 0.70),
]


def meets_loot_threshold(enemy_gold, enemy_elixir, enemy_dark, thresholds):
    """Checks whether scouted enemy loot satisfies the user's configured thresholds."""
    mg = int(thresholds.get("min_gold", 0))
    me = int(thresholds.get("min_elixir", 0))
    md = int(thresholds.get("min_dark", 0))
    match_any = bool(thresholds.get("match_any", False))

    if match_any:
        active = []
        if mg > 0:
            active.append(enemy_gold >= mg)
        if me > 0:
            active.append(enemy_elixir >= me)
        if md > 0:
            active.append(enemy_dark >= md)
        return any(active) if active else True

    return (enemy_gold >= mg) and (enemy_elixir >= me) and (enemy_dark >= md)


class KeyBot:
    def __init__(self, status_callback, resource_callback=None, log_callback=None):
        self.running = False
        self._stopped_by_user = False
        self.thread = None
        self.status_callback = status_callback
        self.resource_callback = resource_callback
        self.log_callback = log_callback
        self.background_mode = False
        self.params = {}
        self.last_failure_reason = ""
        self._deployed_heroes = []
        self._thresh_lock = threading.Lock()
        self._log_lock = threading.Lock()
        self.log_path = os.path.abspath("clash_trainer.log")
        self.loot_thresholds = {
            "min_gold": 500000,
            "min_elixir": 500000,
            "min_dark": 0,
            "match_any": False,
            "wall_min": 1500000,
        }

    def _append_log_file(self, line):
        with self._log_lock:
            try:
                if os.path.exists(self.log_path) and os.path.getsize(self.log_path) > 300_000:
                    with open(self.log_path, "r", encoding="utf-8", errors="ignore") as rf:
                        tail = rf.readlines()[-400:]
                    with open(self.log_path, "w", encoding="utf-8") as wf:
                        wf.writelines(tail)
                with open(self.log_path, "a", encoding="utf-8") as wf:
                    wf.write(line + "\n")
            except Exception:
                pass

    def log(self, message, update_status=True):
        """Records a timestamped event to clash_trainer.log, Log window, and Status label."""
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {message}"
        self._append_log_file(line)
        if self.log_callback:
            try:
                self.log_callback(line)
            except Exception:
                pass
        if update_status and self.status_callback:
            try:
                self.status_callback(message)
            except Exception:
                pass

    def set_background_mode(self, enabled):
        new_mode = bool(enabled)
        was_bg = self.background_mode
        self.background_mode = new_mode
        if self.running and was_bg and not new_mode:
            ensure_bluestacks_active(self.log)

    def set_loot_thresholds(self, min_gold=None, min_elixir=None, min_dark=None, match_any=None, wall_min=None):
        """Updates active loot and wall thresholds safely (takes effect immediately)."""
        with self._thresh_lock:
            if min_gold is not None:
                self.loot_thresholds["min_gold"] = max(0, int(min_gold))
            if min_elixir is not None:
                self.loot_thresholds["min_elixir"] = max(0, int(min_elixir))
            if min_dark is not None:
                self.loot_thresholds["min_dark"] = max(0, int(min_dark))
            if match_any is not None:
                self.loot_thresholds["match_any"] = bool(match_any)
            if wall_min is not None:
                self.loot_thresholds["wall_min"] = max(0, int(wall_min))

    def get_loot_thresholds(self):
        with self._thresh_lock:
            return dict(self.loot_thresholds)

    def get_wall_min_resource(self):
        with self._thresh_lock:
            return int(self.loot_thresholds.get("wall_min", 1500000))

    def interruptible_sleep(self, seconds):
        """Sleeps cleanly in small slices so Stop requests respond almost instantly."""
        end_time = time.time() + max(0.0, float(seconds))
        while self.running and time.time() < end_time:
            time.sleep(min(0.05, max(0.0, end_time - time.time())))
        return self.running

    def start(self, attack_type, reps=1, is_infinite=False, attacks_per_upgrade=10, background_mode=None):
        if self.running:
            self.log("Automation is already running.")
            return

        if background_mode is not None:
            self.background_mode = bool(background_mode)

        if self.background_mode:
            if not is_adb_ready(force_refresh=True, try_connect=True):
                self.log("ADB not found! Start BlueStacks with ADB enabled, or untick Background Mode.")
                return

        self.running = True
        self._stopped_by_user = False
        self.last_failure_reason = ""
        self._deployed_heroes = []
        self.params = {
            "attack_type": attack_type,
            "reps": reps,
            "is_infinite": is_infinite,
            "attacks_per_upgrade": attacks_per_upgrade,
        }
        self.thread = threading.Thread(target=self.run_automation, daemon=True)
        self.thread.start()
        mode_tag = "Background (ADB)" if self.background_mode else "Foreground"
        self.log(f"Automation '{attack_type}' started [{mode_tag}].")

    def stop(self):
        if self.running:
            self._stopped_by_user = True
            self.running = False
            self.log("Stop signal received! Halting automation...")

    def _emit_resources(self, resources, skipped=None):
        if self.resource_callback and resources is not None:
            try:
                self.resource_callback(resources, skipped)
            except Exception:
                pass

    def click_coords(self, coords):
        """Dispatches a tap or click using the active control mode."""
        if self.background_mode:
            return adb_tap(coords[0], coords[1])
        pyautogui.click(coords)
        return True

    def _perform_adb_hold(self, key, duration_sec):
        """Translates keyboard holds (zoom/pan/list scroll) into Android touch gestures."""
        w, h = get_adb_resolution()
        k = str(key).lower()
        attack_gesture = duration_sec >= 0.8

        if k == 'down':
            repeats = 2 if attack_gesture else 1
            adb_pinch_zoom(zoom_in=False, repeats=repeats, duration_ms=340)
            self.log(f"ADB zoomed out ({repeats}x pinch)")
            return True
        if k == 'up':
            repeats = 2 if attack_gesture else 1
            adb_pinch_zoom(zoom_in=True, repeats=repeats, duration_ms=340)
            self.log(f"ADB zoomed in ({repeats}x spread)")
            return True
        if k == '[':
            x = int(w * 0.868)
            adb_swipe(x, int(h * 0.70), x, int(h * 0.36), duration_ms=260, steps=16)
            self.log("ADB scrolled build list down")
            return True
        if k == ']':
            x = int(w * 0.868)
            adb_swipe(x, int(h * 0.36), x, int(h * 0.70), duration_ms=260, steps=16)
            self.log("ADB scrolled build list up")
            return True

        if k == 's':
            x1 = x2 = int(w * 0.50)
            y1, y2 = (int(h * 0.72), int(h * 0.18)) if attack_gesture else (int(h * 0.62), int(h * 0.42))
        elif k == 'w':
            x1 = x2 = int(w * 0.50)
            y1, y2 = (int(h * 0.20), int(h * 0.72)) if attack_gesture else (int(h * 0.40), int(h * 0.60))
        elif k == 'd':
            y1 = y2 = int(h * 0.50)
            x1, x2 = (int(w * 0.80), int(w * 0.20)) if attack_gesture else (int(w * 0.64), int(w * 0.40))
        elif k == 'a':
            y1 = y2 = int(h * 0.50)
            x1, x2 = (int(w * 0.20), int(w * 0.80)) if attack_gesture else (int(w * 0.36), int(w * 0.60))
        else:
            x1 = x2 = int(w * 0.50)
            y1, y2 = int(h * 0.60), int(h * 0.35)

        repeats = 2 if attack_gesture else 1
        swipe_ms = 220 if attack_gesture else 260
        for i in range(repeats):
            if not self.running:
                return False
            adb_swipe(x1, y1, x2, y2, duration_ms=swipe_ms, steps=16)
            if i + 1 < repeats:
                self.interruptible_sleep(0.05)

        self.log(f"ADB camera gesture '{key}' ({repeats}x)")
        return True

    def _find_step_index(self, sequence, target_action):
        """Finds step index inside sequence matching either an action name or template path."""
        for i, act in enumerate(sequence):
            if act[0] == target_action or (len(act) >= 2 and act[1] == target_action):
                return i
        return None

    def recover_sequence_step(self, sequence):
        """
        Inspects all known UI templates against the live screen when interrupted and
        returns the target sequence index to resume from, or None if screen is unknown.
        """
        if not self.running:
            return None

        for probe in range(2):
            use_bg = self.background_mode
            matches = inspect_screen_templates(RECOVERY_TEMPLATE_SPECS, self.log, background_mode=use_bg)
            if not matches:
                self.last_failure_reason = "Recovery scan could not capture game view."
                return None

            top_scores = sorted(
                ((os.path.basename(k), v[1]) for k, v in matches.items()),
                key=lambda item: item[1],
                reverse=True,
            )[:4]
            diag = ", ".join(f"{name}={score:.2f}" for name, score in top_scores)
            self.log(f"Recovery template scan #{probe + 1}: {diag}")

            # Dismiss accidental drawers or popups first before deciding state
            for close_tpl in ("templates/build_close_btn.png", "templates/left_panel_close_btn.png"):
                close_coords, close_score = matches.get(close_tpl, (None, 0.0))
                if close_coords:
                    self.log(f"Recovery: closing overlay '{os.path.basename(close_tpl)}' (score={close_score:.2f}).")
                    self.click_coords(close_coords)
                    if not self.interruptible_sleep(0.5):
                        return None
                    break
            else:
                # Route cleanly by detected screen state
                if matches.get("templates/return_btn.png", (None, 0.0))[0]:
                    idx = self._find_step_index(sequence, "templates/return_btn.png")
                    if idx is not None:
                        self.log("Recovery: detected Return Home button -> finishing current battle.")
                        return idx

                if matches.get("templates/surrender_btn.png", (None, 0.0))[0]:
                    idx = self._find_step_index(sequence, "templates/return_btn.png")
                    if idx is not None:
                        self.log("Recovery: battle active (Surrender visible) -> waiting for Return Home.")
                        return idx

                if matches.get("templates/next_btn.png", (None, 0.0))[0]:
                    idx = self._find_step_index(sequence, "scout_loot")
                    if idx is None:
                        idx = self._find_step_index(sequence, "templates/dragon_card.png")
                    if idx is not None:
                        self.log("Recovery: detected Next button -> resuming scouting/attack.")
                        return idx

                if matches.get("templates/end_battle_btn.png", (None, 0.0))[0] or matches.get("templates/dragon_card.png", (None, 0.0))[0]:
                    idx = self._find_step_index(sequence, "templates/dragon_card.png")
                    if idx is not None:
                        self.log("Recovery: detected battle troop bar -> resuming deployment.")
                        return idx

                if matches.get("templates/attack_btn.png", (None, 0.0))[0]:
                    idx = self._find_step_index(sequence, "templates/attack_btn.png")
                    if idx is not None:
                        self.log("Recovery: detected Attack button -> resuming from Attack.")
                        return idx

                if matches.get("templates/find_a_match_btn.png", (None, 0.0))[0]:
                    idx = self._find_step_index(sequence, "templates/find_a_match_btn.png")
                    if idx is not None:
                        self.log("Recovery: detected Find a Match button -> resuming matchmaking.")
                        return idx

                if matches.get("templates/battle_btn.png", (None, 0.0))[0]:
                    idx = self._find_step_index(sequence, "templates/battle_btn.png")
                    if idx is not None:
                        self.log("Recovery: back at Home Village -> restarting attack cycle.")
                        return idx

                # No known state recognized: try Esc / Back once to dismiss unknown dialogs
                if probe == 0:
                    self.log(f"Recovery: no button matched ({diag}). Pressing Back/Esc and waiting 2s...")
                    self.execute_action(('press', 'esc'))
                    if not self.interruptible_sleep(2.0):
                        return None
                    continue

            if probe == 0 and not self.interruptible_sleep(0.3):
                return None

        return None

    def _scout_and_match_enemy(self):
        """
        Polls rapidly for Next (10s max per base), reads enemy & own resources as soon
        as Next appears, updates the live UI tracker, and clicks Next immediately if below target.
        """
        max_skips = 150
        skipped = 0

        while self.running and skipped <= max_skips:
            use_bg = self.background_mode
            self.log(f"Searching for match{f' (skipped {skipped})' if skipped else ''}...")

            next_coords = None
            best_score = 0.0
            best_scale = 1.0
            start_wait = time.time()
            while self.running and time.time() - start_wait < 10.0:
                next_coords, val, sc = find_image_with_score(
                    'templates/next_btn.png',
                    self.log,
                    confidence=0.68,
                    background_mode=use_bg,
                )
                if val > best_score:
                    best_score = val
                    best_scale = sc
                if next_coords:
                    break
                if not self.interruptible_sleep(0.20):
                    return False

            if not self.running:
                return False

            if not next_coords:
                dragon_coords, d_val, _ = find_image_with_score(
                    'templates/dragon_card.png',
                    self.log,
                    confidence=0.70,
                    background_mode=use_bg,
                )
                if dragon_coords:
                    self.log("Attack bar visible without Next button; proceeding with attack.")
                    return True
                self.last_failure_reason = (
                    f"Timeout (10s) waiting for 'next_btn.png' (best={best_score:.2f}@{best_scale:.2f}, "
                    f"dragon_card={d_val:.2f})"
                )
                self.log(self.last_failure_reason)
                return False

            if not self.interruptible_sleep(0.22):
                return False

            resources = None
            for attempt in range(3):
                if not self.running:
                    return False
                img_bgr = capture_game_bgr(background_mode=use_bg)
                resources = read_game_resources(img_bgr, include_enemy=True, background_mode=use_bg)
                if resources and ((resources.get("enemy_gold") or 0) > 0 or (resources.get("enemy_elixir") or 0) > 0):
                    break
                if attempt < 2 and not self.interruptible_sleep(0.25):
                    return False

            if not resources:
                resources = {
                    "enemy_gold": 0,
                    "enemy_elixir": 0,
                    "enemy_dark": 0,
                    "own_gold": 0,
                    "own_elixir": 0,
                    "own_dark": 0,
                }

            self._emit_resources(resources, skipped)
            eg = int(resources.get("enemy_gold") or 0)
            ee = int(resources.get("enemy_elixir") or 0)
            ed = int(resources.get("enemy_dark") or 0)
            thresholds = self.get_loot_thresholds()

            if meets_loot_threshold(eg, ee, ed, thresholds):
                self.log(
                    f"Target matched! Loot G: {eg:,} | E: {ee:,} | DE: {ed:,} (Skipped: {skipped})"
                )
                return True

            skipped += 1
            self.log(
                f"Skip #{skipped}: G {eg:,} | E {ee:,} | DE {ed:,} below threshold. Pressing Next..."
            )
            self.click_coords(next_coords)
            if not self.interruptible_sleep(0.55):
                return False

        self.last_failure_reason = f"Reached max skip limit ({max_skips}) without matching loot."
        self.log(self.last_failure_reason)
        return False

    def _deploy_heroes(self, use_bg):
        """Deploys available heroes randomly across keys 0-9 and saves card slots for ability triggers."""
        heroes = [
            ("Minion Prince", "templates/minion_price_card.png"),
            ("Archer Queen", "templates/queen_card.png"),
            ("Royal Champion", "templates/royal_champ_card.png"),
            ("Grand Warden", "templates/warden_card.png"),
        ]
        shuffled_heroes = list(heroes)
        random.shuffle(shuffled_heroes)
        deploy_keys = ['0', '1', '2', '3', '4', '5', '6', '7', '8', '9']
        self._deployed_heroes = []

        self.log("Deploying heroes randomly from keys 0-9...")
        for name, hero_img in shuffled_heroes:
            if not self.running:
                return False
            mode_text = "in background" if use_bg else "on screen"
            self.log(f"Locating {name} {mode_text}...")
            coords = None
            start_find = time.time()
            while time.time() - start_find < 2.0:
                if not self.running:
                    return False
                coords = find_image_multi_scale(
                    hero_img,
                    self.log,
                    confidence=0.7,
                    background_mode=use_bg,
                )
                if coords:
                    break
                if not self.interruptible_sleep(0.25):
                    return False

            if coords:
                self.log(f"Selecting {name} at {coords}...")
                self.click_coords(coords)
                if not self.interruptible_sleep(0.10):
                    return False
                chosen_keys = random.sample(deploy_keys, k=random.randint(2, 3))
                for key in chosen_keys:
                    if not self.running:
                        return False
                    if use_bg:
                        pt = get_scaled_point(key)
                        adb_tap(pt[0], pt[1])
                        self.log(f"Deployed {name} at key '{key}' ({pt[0]}, {pt[1]})")
                    else:
                        pyautogui.press(key)
                        self.log(f"Deployed {name} with key '{key}'")
                    if not self.interruptible_sleep(0.08):
                        return False
                self._deployed_heroes.append((name, hero_img, coords))
            else:
                self.log(f"{name} card not found, skipping...")
            if not self.interruptible_sleep(0.08):
                return False

        return True

    def _activate_hero_abilities(self, delay_sec, use_bg):
        """
        Waits delay_sec into the attack (stopping early if Return Home already appeared),
        then re-taps every deployed hero card to trigger their abilities.
        """
        if not self._deployed_heroes:
            self.log("No heroes deployed; skipping ability activation.")
            return True

        self.log(f"Waiting {delay_sec}s before triggering abilities for {len(self._deployed_heroes)} heroes...")
        end_wait = time.time() + max(0.0, float(delay_sec))
        while self.running and time.time() < end_wait:
            # Stop waiting early if battle already finished within the delay window
            ret_coords = find_image_multi_scale(
                'templates/return_btn.png',
                self.log,
                confidence=0.70,
                background_mode=use_bg,
            )
            if ret_coords:
                self.log("Battle ended before ability timer elapsed; skipping ability clicks.")
                return True
            step = min(0.8, max(0.05, end_wait - time.time()))
            if not self.interruptible_sleep(step):
                return False

        if not self.running:
            return False

        if find_image_multi_scale('templates/return_btn.png', self.log, confidence=0.70, background_mode=use_bg):
            self.log("Battle ended right at ability trigger; moving to Return Home.")
            return True

        self.log("Activating hero abilities now...")
        for name, hero_img, saved_coords in self._deployed_heroes:
            if not self.running:
                return False
            # Try lower-confidence template match first (due to glowing border), fallback to exact card coords
            card_pt = find_image_multi_scale(hero_img, self.log, confidence=0.58, background_mode=use_bg)
            target_pt = card_pt if card_pt else saved_coords
            self.click_coords(target_pt)
            self.log(f"Activated {name} ability at {target_pt}")
            if not self.interruptible_sleep(0.10):
                return False

        return True

    def execute_action(self, action_tuple):
        if not self.running:
            return False

        action_type = action_tuple[0]
        use_bg = self.background_mode

        try:
            if action_type == 'press':
                key = action_tuple[1]
                if use_bg:
                    if key in KEY_PERCENT_MAP:
                        pt = get_scaled_point(key)
                        adb_tap(pt[0], pt[1])
                        self.log(f"ADB deployed at key '{key}' ({pt[0]}, {pt[1]})")
                    elif key == 'o':
                        w, h = get_adb_resolution()
                        adb_tap(w // 2, h // 2)
                    else:
                        adb_keyevent(key)
                        self.log(f"ADB keyevent: '{key}'")
                else:
                    pyautogui.press(key)
                    self.log(f"Pressed key: '{key}'")

            elif action_type == 'hold':
                key = action_tuple[1]
                duration_sec = action_tuple[2]
                if use_bg:
                    self._perform_adb_hold(key, duration_sec)
                else:
                    self.log(f"Holding key '{key}' for {duration_sec}s...")
                    pyautogui.keyDown(key)
                    try:
                        completed = self.interruptible_sleep(duration_sec)
                    finally:
                        try:
                            pyautogui.keyUp(key)
                        except Exception:
                            pass
                    # Allow BlueStacks KeyMapper ResetDelay (~75ms) to release virtual zoom/pan pointers
                    time.sleep(0.10)
                    if not completed:
                        return False

            elif action_type == 'wait':
                self.log(f"Waiting for {action_tuple[1]}s...")
                return self.interruptible_sleep(action_tuple[1])

            elif action_type == 'scout_loot':
                return self._scout_and_match_enemy()

            elif action_type == 'refresh_own_resources':
                img_bgr = capture_game_bgr(background_mode=use_bg)
                res = read_game_resources(img_bgr, include_enemy=False, background_mode=use_bg)
                if res:
                    self._emit_resources(res, None)
                    self.log(
                        f"Your loot - G: {res['own_gold']:,} | E: {res['own_elixir']:,} | DE: {res['own_dark']:,}"
                    )
                return True

            elif action_type == 'deploy_heroes':
                return self._deploy_heroes(use_bg)

            elif action_type == 'activate_hero_abilities':
                delay = action_tuple[1] if len(action_tuple) > 1 else 10
                return self._activate_hero_abilities(delay, use_bg)

            elif action_type in ('wait_for_image', 'click_image'):
                verb = "Clicking" if action_type == 'click_image' else "Waiting for"
                image_path, timeout = action_tuple[1], action_tuple[2]
                img_name = os.path.basename(image_path)
                self.log(f"{verb} '{img_name}' (max {timeout}s)...")
                best_score = 0.0
                best_scale = 1.0
                start_time = time.time()
                while time.time() - start_time < timeout:
                    if not self.running:
                        return False
                    coords, val, sc = find_image_with_score(
                        image_path,
                        self.log,
                        confidence=0.70,
                        background_mode=use_bg,
                    )
                    if val > best_score:
                        best_score = val
                        best_scale = sc
                    if coords:
                        self.log(f"Image '{img_name}' FOUND (conf={val:.2f}@{sc:.2f}) at {coords}")
                        if action_type == 'click_image':
                            self.click_coords(coords)
                            if use_bg:
                                self.log(f"ADB tapped '{img_name}' at ({coords[0]}, {coords[1]})")
                            else:
                                self.interruptible_sleep(0.05)
                        return True
                    if not self.interruptible_sleep(0.25):
                        return False
                self.last_failure_reason = (
                    f"Timeout ({timeout}s) finding '{img_name}' (best={best_score:.2f}@{best_scale:.2f}, need >=0.70)"
                )
                self.log(self.last_failure_reason)
                return False

        except Exception as e:
            self.last_failure_reason = f"Exception on action {action_tuple}: {e}"
            self.log(self.last_failure_reason)
            return False

        time.sleep(0.02)
        return self.running

    def wait_before_loop(self):
        self.log("Starting cycle in 1s...")
        if not self.interruptible_sleep(1):
            return False

        if self.running and not self.background_mode:
            ensure_bluestacks_active(self.log)
        return self.running

    def run_automation(self):
        try:
            if self.background_mode:
                if not is_adb_ready(force_refresh=True, try_connect=True):
                    self.last_failure_reason = "ADB offline (enable ADB in BlueStacks or untick Background Mode)."
                    self.log(self.last_failure_reason)
                    return
                if ensure_touch_daemon():
                    self.log("Background Mode active (fast ADB touch engine ready).")
                else:
                    self.log("Background Mode active (standard ADB input ready).")
            else:
                self.log("Foreground Mode active (desktop mouse and keyboard).")

            attack_type = self.params.get("attack_type")
            reps = self.params.get("reps")
            is_infinite = self.params.get("is_infinite")

            if attack_type == 'normal':
                attack_loops.run_normal_attack(self, reps, is_infinite)
            elif attack_type in ('ranked', 'trophy'):
                attack_loops.run_ranked_attack(self, reps, is_infinite)
            elif attack_type == 'walls':
                attacks_per_upgrade = self.params.get("attacks_per_upgrade")
                attack_loops.run_walls_attack(self, attacks_per_upgrade, reps, is_infinite)
            elif attack_type == 'builder':
                attack_loops.run_builder_attack(self, reps, is_infinite)

        except Exception as e:
            self.last_failure_reason = f"Automation thread error: {e}"
            self.log(self.last_failure_reason)
            import traceback
            traceback.print_exc()
        finally:
            was_user_stop = self._stopped_by_user
            self.running = False
            if was_user_stop:
                self.log("Automation stopped by user.")
            elif self.last_failure_reason:
                self.log(f"Stopped due to error: {self.last_failure_reason}")
            else:
                self.log("Automation completed all cycles cleanly.")
