# --- attack_sequences.py ---

# Fast Smart Normal Attack sequence:
# 1. Click Battle, Find a Match, and Attack buttons
# 2. Scout enemy loot against thresholds (10s max Next wait, fast immediate skips)
# 3. Wait for battle troop bar, zoom out & pan bottom-right (down, s, d for 1s each)
# 4. Click Dragon card
# 5. Deploy: press 1 2 3 4 5 6 7 8 9 0 three times in loop
# 6. Deploy heroes randomly from keys 0-9
# 7. Wait for Return Home button, click it, wait 1s, and refresh home resources
MAIN_ATTACK_SEQUENCE = [
    ('click_image', 'templates/battle_btn.png', 25),
    ('wait', 0.4),
    ('click_image', 'templates/find_a_match_btn.png', 25),
    ('wait', 0.4),
    ('click_image', 'templates/attack_btn.png', 25),
    ('scout_loot',),
    ('wait_for_image', 'templates/dragon_card.png', 15),
    ('hold', 'down', 1),
    ('hold', 's', 1),
    ('hold', 'd', 1),
    ('click_image', 'templates/dragon_card.png', 15),
    ('wait', 0.2),
    # 1 2 3 4 5 6 7 8 9 0 (Cycle 1)
    ('press', '1'), ('press', '2'), ('press', '3'), ('press', '4'), ('press', '5'),
    ('press', '6'), ('press', '7'), ('press', '8'), ('press', '9'), ('press', '0'),
    # 1 2 3 4 5 6 7 8 9 0 (Cycle 2)
    ('press', '1'), ('press', '2'), ('press', '3'), ('press', '4'), ('press', '5'),
    ('press', '6'), ('press', '7'), ('press', '8'), ('press', '9'), ('press', '0'),
    # 1 2 3 4 5 6 7 8 9 0 (Cycle 3)
    ('press', '1'), ('press', '2'), ('press', '3'), ('press', '4'), ('press', '5'),
    ('press', '6'), ('press', '7'), ('press', '8'), ('press', '9'), ('press', '0'),
    ('wait', 0.2),
    ('deploy_heroes',),
    ('activate_hero_abilities', 10),
    ('click_image', 'templates/return_btn.png', 180),
    ('wait', 1),
    ('refresh_own_resources',),
]

# --- RANKED ATTACK SEQUENCE ---
# Direct ranked attack sequence (no Next button skipping)
RANKED_ATTACK_SEQUENCE = [
    ('click_image', 'templates/battle_btn.png', 25),
    ('wait', 0.4),
    ('click_image', 'templates/find_a_match_btn.png', 25),
    ('wait', 0.4),
    ('click_image', 'templates/attack_btn.png', 25),
    ('wait', 1),
    ('wait_for_image', 'templates/dragon_card.png', 45),
    ('hold', 'down', 1),
    ('hold', 's', 1),
    ('hold', 'd', 1),
    ('click_image', 'templates/dragon_card.png', 15),
    ('wait', 0.2),
    ('press', '1'), ('press', '2'), ('press', '3'), ('press', '4'), ('press', '5'),
    ('press', '6'), ('press', '7'), ('press', '8'), ('press', '9'), ('press', '0'),
    ('press', '1'), ('press', '2'), ('press', '3'), ('press', '4'), ('press', '5'),
    ('press', '6'), ('press', '7'), ('press', '8'), ('press', '9'), ('press', '0'),
    ('press', '1'), ('press', '2'), ('press', '3'), ('press', '4'), ('press', '5'),
    ('press', '6'), ('press', '7'), ('press', '8'), ('press', '9'), ('press', '0'),
    ('wait', 0.2),
    ('deploy_heroes',),
    ('activate_hero_abilities', 10),
    ('click_image', 'templates/return_btn.png', 180),
    ('wait', 1),
    ('refresh_own_resources',),
]
TROPHY_ATTACK_SEQUENCE = RANKED_ATTACK_SEQUENCE

# Sequence for the first part of a builder base attack
BUILDER_ATTACK_PART_1 = [
    ('press', 'f'), ('press', '4'), ('wait_for_image', 'templates/battle_machine_1.png', 10),
    ('hold', 's', 2), ('hold', 'down', 2), ('press', 'e'), ('press', '1'), ('press', 'r'),
    ('press', '1'), ('press', '1'), ('press', '1'), ('press', '1'), ('press', '1'),
    ('press', 'o'), ('press', '1')
]

# Sequence for the second part of a builder base attack
BUILDER_ATTACK_PART_2 = [
    ('hold', 's', 2), ('hold', 'down', 2), ('press', 'e'), ('press', '1'), ('press', 'r'),
    ('press', '1'), ('press', 't'), ('press', '1'), ('press', 'y'), ('press', '1'),
    ('press', 'u'), ('press', '1'), ('press', 'i'), ('press', '1'), ('press', 'o'),
    ('press', '1'), ('press', 'p'), ('press', '1'), ('press', 'l'),
    ('press', '1'), ('wait_for_image', 'templates/return.png', 150), ('press', 'g'),
    ('wait', 5), ('press', 'k'), ('click_image', 'templates/collect.png', 2), ('press', 'f')
]
