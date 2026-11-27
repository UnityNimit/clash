# --- attack_loops.py ---

from attack_sequences import (
    BUILDER_ATTACK_PART_1,
    BUILDER_ATTACK_PART_2,
    MAIN_ATTACK_SEQUENCE,
    RANKED_ATTACK_SEQUENCE,
)
from utils import (
    capture_game_bgr,
    find_image_multi_scale,
    find_upgrade_buttons,
    find_upgrade_confirm_button,
    find_wall_in_build_list,
    read_game_resources,
)


def _run_sequence_with_recovery(bot, sequence):
    """
    Executes an attack sequence step-by-step. If a step times out or is interrupted
    (and the user has not clicked Stop), scans all templates to detect the current game
    screen and resumes cleanly from the matching step instead of stopping.
    """
    idx = 0
    recovery_attempts = 0
    max_recoveries = 8

    while bot.running and idx < len(sequence):
        action = sequence[idx]
        if bot.execute_action(action):
            recovery_attempts = 0
            idx += 1
            continue

        if not bot.running:
            return False

        recovery_attempts += 1
        if recovery_attempts > max_recoveries:
            bot.last_failure_reason = (
                f"Exceeded {max_recoveries} recovery attempts ({bot.last_failure_reason})."
            )
            bot.log(bot.last_failure_reason)
            return False

        bot.log(
            f"Step #{idx + 1} ({action[0]}) interrupted [{bot.last_failure_reason}]. "
            f"Attempting template recovery ({recovery_attempts}/{max_recoveries})..."
        )
        new_idx = bot.recover_sequence_step(sequence)
        if not bot.running:
            return False

        if new_idx is not None:
            bot.last_failure_reason = ""
            idx = new_idx
        else:
            bot.log("No known button matched during recovery; retrying in 2s...")
            if not bot.interruptible_sleep(2.0):
                return False

    return bot.running


def run_normal_attack(bot, reps, is_infinite):
    """Runs the smart normal attack sequence with automatic state recovery."""
    cycle_count = 0
    while bot.running and (is_infinite or cycle_count < reps):
        cycle_count += 1
        status = "Infinite Mode" if is_infinite else f"Cycle {cycle_count}/{reps}"
        bot.log(f"--- Starting Normal Attack ({status}) ---")

        if not bot.wait_before_loop():
            break

        bot.execute_action(('refresh_own_resources',))

        if not _run_sequence_with_recovery(bot, MAIN_ATTACK_SEQUENCE):
            return


def run_ranked_attack(bot, reps, is_infinite):
    """Runs the ranked attack sequence with automatic state recovery."""
    cycle_count = 0
    while bot.running and (is_infinite or cycle_count < reps):
        cycle_count += 1
        status = "Infinite Mode" if is_infinite else f"Cycle {cycle_count}/{reps}"
        bot.log(f"--- Starting Ranked Attack ({status}) ---")

        if not bot.wait_before_loop():
            break

        bot.execute_action(('refresh_own_resources',))

        if not _run_sequence_with_recovery(bot, RANKED_ATTACK_SEQUENCE):
            return


run_trophy_attack = run_ranked_attack


def _read_own_resources_reliable(bot, retries=3):
    """Reads Home Village Gold & Elixir cleanly, retrying briefly if HUD is still settling."""
    use_bg = bot.background_mode
    latest = {"own_gold": 0, "own_elixir": 0, "own_dark": 0}
    for attempt in range(retries):
        if not bot.running:
            return latest
        img_bgr = capture_game_bgr(background_mode=use_bg)
        res = read_game_resources(img_bgr, include_enemy=False, background_mode=use_bg)
        if res:
            latest = res
            if int(res.get("own_gold") or 0) > 0 or int(res.get("own_elixir") or 0) > 0:
                bot._emit_resources(res, None)
                return res
        if attempt + 1 < retries:
            bot.interruptible_sleep(0.4)
    bot._emit_resources(latest, None)
    return latest


def _has_enough_wall_resources(bot):
    """
    Verifies Gold or Elixir meets the user's configured Wall Min Resource threshold
    before attempting an upgrade so the bot never triggers a Gem purchase dialog.
    Returns (is_ready, own_gold, own_elixir, wall_min).
    """
    wall_min = bot.get_wall_min_resource()
    res = _read_own_resources_reliable(bot)
    own_gold = int(res.get("own_gold") or 0)
    own_elixir = int(res.get("own_elixir") or 0)
    if wall_min <= 0:
        return True, own_gold, own_elixir, wall_min
    return (max(own_gold, own_elixir) >= wall_min), own_gold, own_elixir, wall_min


def run_walls_attack(bot, attacks_per_upgrade, major_reps, is_infinite):
    """
    Runs N normal resource-farming attacks (plus any extra farming attacks needed
    to reach the user's Wall Min Resource threshold), then safely upgrades a wall,
    closes with build_close_btn, and repeats.
    """
    major_cycle_count = 0
    while bot.running and (is_infinite or major_cycle_count < major_reps):
        major_cycle_count += 1
        status = "Infinite Mode" if is_infinite else f"Major Cycle {major_cycle_count}/{major_reps}"
        bot.log(f"--- Starting Major Cycle ({status}) ---")

        # --- Attack Phase ---
        for i in range(attacks_per_upgrade):
            if not bot.running:
                return
            bot.log(f"Major Cycle {major_cycle_count} | Attack {i + 1}/{attacks_per_upgrade}")
            if not bot.wait_before_loop():
                return
            bot.execute_action(('refresh_own_resources',))
            if not _run_sequence_with_recovery(bot, MAIN_ATTACK_SEQUENCE):
                return

        if not bot.running:
            return

        # --- Resource Gate: Farm extra attacks until Gold or Elixir >= Wall Min ---
        extra_attacks = 0
        while bot.running:
            enough, own_gold, own_elixir, wall_min = _has_enough_wall_resources(bot)
            if enough:
                break
            extra_attacks += 1
            bot.log(
                f"Resources below Wall Min ({wall_min:,}): G {own_gold:,}, E {own_elixir:,}. "
                f"Farming extra attack #{extra_attacks} to avoid Gem shortfall..."
            )
            if not bot.wait_before_loop():
                return
            if not _run_sequence_with_recovery(bot, MAIN_ATTACK_SEQUENCE):
                return

        if not bot.running:
            return

        # --- Wall Upgrade Phase ---
        bot.log(f"--- {status} | Starting Wall Upgrade ---")
        result = _perform_wall_upgrade(bot)
        if not bot.running:
            return
        if result == "failed":
            bot.log("--- Retrying wall upgrade once after cleanup... ---")
            _close_build_ui(bot)
            result = _perform_wall_upgrade(bot)
            if not bot.running:
                return

        bot.last_failure_reason = ""
        if result == "ok":
            bot.log("--- Wall upgrade completed. Resuming attacks... ---")
        elif result == "insufficient":
            bot.log("--- Resources insufficient for wall upgrade (no Gems spent). Resuming farming. ---")
        else:
            bot.log("--- Could not complete wall upgrade this cycle. Resuming attacks. ---")


def run_builder_attack(bot, reps, is_infinite):
    """Runs the builder base attack sequence."""
    cycle_count = 0
    while bot.running and (is_infinite or cycle_count < reps):
        cycle_count += 1
        status = "Infinite Mode" if is_infinite else f"Cycle {cycle_count}/{reps}"
        bot.log(f"--- Starting Builder Attack ({status}) ---")

        if not bot.wait_before_loop():
            break

        for action in BUILDER_ATTACK_PART_1:
            if not bot.running or not bot.execute_action(action):
                return

        if not bot.running:
            return
        bot.log("Searching for Super Pekka card...")
        pekka_found = False
        while not pekka_found and bot.running:
            if find_image_multi_scale('templates/super_pekka_card.png', bot.log, background_mode=bot.background_mode):
                bot.log("Super Pekka card FOUND!")
                pekka_found = True
            else:
                bot.log("Pekka not found, pressing 'o' and waiting 24s...")
                bot.execute_action(('press', 'o'))
                if not bot.interruptible_sleep(24):
                    return

        if not bot.running:
            return

        for action in BUILDER_ATTACK_PART_2:
            if not bot.running or not bot.execute_action(action):
                return


def _close_build_ui(bot):
    """Closes any open Buildings drawer or upgrade dialog using build_close_btn.png."""
    use_bg = bot.background_mode
    for _ in range(2):
        if not bot.running:
            return
        close_coords = find_image_multi_scale(
            'templates/build_close_btn.png',
            bot.log,
            confidence=0.72,
            background_mode=use_bg,
        )
        if not close_coords:
            break
        bot.click_coords(close_coords)
        bot.log("Pressed build_close_btn.")
        if not bot.interruptible_sleep(0.35):
            return


def _perform_wall_upgrade(bot):
    """
    Executes the full Home Village wall upgrade flow:
    1. Measure own Gold & Elixir to pick the higher resource.
    2. Open Buildings & Heroes via build_btn.png (if not already open).
    3. Scroll down with '[' until 'Wall' / 'Wall x <N>' is detected, then click it.
    4. Detect 'Upgrade' buttons (1st=Gold, 2nd=Elixir) and press whichever resource is higher.
    5. Press Confirm button in the upgrade modal (aborting safely if insufficient resources).
    6. Close via build_close_btn.png.
    Returns 'ok', 'insufficient', or 'failed'.
    """
    use_bg = bot.background_mode

    img_bgr = capture_game_bgr(background_mode=use_bg)
    res = read_game_resources(img_bgr, include_enemy=False, background_mode=use_bg) or {}
    own_gold = int(res.get("own_gold") or 0)
    own_elixir = int(res.get("own_elixir") or 0)
    wall_min = bot.get_wall_min_resource()
    bot._emit_resources(res, None)
    bot.log(f"Wall check - Your Gold: {own_gold:,} | Elixir: {own_elixir:,} | Min Wall: {wall_min:,}")

    if wall_min > 0 and max(own_gold, own_elixir) < wall_min:
        bot.log(f"Aborting wall upgrade before build menu: Gold & Elixir < Wall Min ({wall_min:,}).")
        return "insufficient"

    already_open = find_image_multi_scale(
        'templates/build_close_btn.png',
        bot.log,
        confidence=0.72,
        background_mode=use_bg,
    )
    if not already_open:
        if not bot.execute_action(('click_image', 'templates/build_btn.png', 10)):
            bot.log("Failed to find build_btn to open upgrade list.")
            return "failed"
        if not bot.interruptible_sleep(0.6):
            return "failed"

        img_panel = capture_game_bgr(background_mode=use_bg)
        panel_res = read_game_resources(img_panel, include_enemy=False, background_mode=use_bg)
        if panel_res and (panel_res.get("own_gold", 0) > 0 or panel_res.get("own_elixir", 0) > 0):
            own_gold = int(panel_res["own_gold"])
            own_elixir = int(panel_res["own_elixir"])
            bot._emit_resources(panel_res, None)
            if wall_min > 0 and max(own_gold, own_elixir) < wall_min:
                bot.log(f"Panel resource check < Wall Min ({wall_min:,}); closing cleanly without spending gems.")
                _close_build_ui(bot)
                return "insufficient"

    bot.log("Scanning build list for Walls (scrolling with '[')...")
    wall_coords = None
    for attempt in range(20):
        if not bot.running:
            return "failed"
        wall_coords = find_wall_in_build_list(background_mode=use_bg)
        if wall_coords:
            bot.log(f"Found Wall entry at {wall_coords}; selecting...")
            bot.click_coords(wall_coords)
            break
        bot.log(f"Wall not visible yet, scrolling list with '[' ({attempt + 1}/20)...")
        bot.execute_action(('hold', '[', 0.35))
        if not bot.interruptible_sleep(0.35):
            return "failed"

    if not wall_coords:
        bot.log("Could not find 'Wall' in upgrade list.")
        _close_build_ui(bot)
        return "failed"

    if not bot.interruptible_sleep(0.75):
        return "failed"

    upgrade_btns = find_upgrade_buttons(background_mode=use_bg, check_affordable=True)
    if not upgrade_btns:
        bot.log("No 'Upgrade' buttons found after selecting Wall.")
        _close_build_ui(bot)
        return "failed"

    if len(upgrade_btns) >= 2:
        if own_elixir > own_gold:
            chosen_pt, is_aff = upgrade_btns[1]
            choice_label = f"Elixir (#2, {own_elixir:,} > {own_gold:,})"
            alt_pt, alt_aff = upgrade_btns[0]
        else:
            chosen_pt, is_aff = upgrade_btns[0]
            choice_label = f"Gold (#1, {own_gold:,} >= {own_elixir:,})"
            alt_pt, alt_aff = upgrade_btns[1]
        if not is_aff and alt_aff:
            chosen_pt, is_aff = alt_pt, True
            choice_label = f"Alternate affordable button ({choice_label} showed red cost)"
    else:
        chosen_pt, is_aff = upgrade_btns[0]
        choice_label = "Upgrade (#1)"

    if not is_aff:
        bot.log("Upgrade button shows red (insufficient resources). Closing without clicking to protect Gems.")
        _close_build_ui(bot)
        return "insufficient"

    bot.log(f"Clicking Wall {choice_label}...")
    bot.click_coords(chosen_pt)
    if not bot.interruptible_sleep(0.75):
        return "failed"

    confirm_pt, status = find_upgrade_confirm_button(background_mode=use_bg)
    if status == "insufficient":
        bot.log("Insufficient resources for wall upgrade (avoiding gem prompt).")
        _close_build_ui(bot)
        return "insufficient"

    if not confirm_pt:
        if not bot.interruptible_sleep(0.5):
            return "failed"
        confirm_pt, status = find_upgrade_confirm_button(background_mode=use_bg)
        if status == "insufficient":
            _close_build_ui(bot)
            return "insufficient"

    if not confirm_pt:
        bot.log("Upgrade confirm button not found.")
        _close_build_ui(bot)
        return "failed"

    bot.log("Confirming wall upgrade...")
    bot.click_coords(confirm_pt)
    if not bot.interruptible_sleep(0.5):
        return "failed"

    _close_build_ui(bot)
    return "ok"
