from pathlib import Path
import yaml
from character import Character
from gear import Gear

def _load_data(yaml_path: str):
    """
    Load roster and gear_pool from a YAML file.

    Returns
    -------
    roster : list[Character]
    gear_pool : list[Gear]
    support_bonus : float or None
    """
    if not Path(yaml_path).exists():
        raise FileNotFoundError(
            f"Data file not found: '{yaml_path}'\n"
            "Make sure data.yaml is in the same folder as this script, "
            "or pass a full path."
        )

    with open(yaml_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    # ── Build roster ──────────────────────────────────────────────────────────
    roster_out = []
    for entry in data.get("roster", []):
        # buffs: YAML list of single-key dicts → list of (buff_type, value) tuples
        raw_buffs = entry.get("buffs") or []
        buffs = [(k, v) for item in raw_buffs for k, v in item.items()]

        char = Character(
            name          = entry["name"],
            damage_type   = entry["damage_type"],
            atk           = entry.get("atk", 0),
            crit_dmg      = entry.get("crit_dmg", 1),
            ratio_per_hit = entry.get("ratio_per_hit", 0),
            hits          = entry.get("hits", 0),
            buffs         = buffs,
            temp_buffs    = entry.get("temp_buffs") or {},
        )
        roster_out.append(char)

    # ── Build gear_pool ───────────────────────────────────────────────────────
    # Three construction modes are detected by which keys are present:
    #
    #   preset    → Gear.from_preset()   requires: preset, rank, refine
    #   from_rarity → Gear.from_rarity() requires: name, slot, rarity, rank,
    #                                               refine, primary_stats
    #   raw (default) → Gear()           requires: name, slot + any stat fields
    #
    # "refine" in YAML maps to the refine_level parameter.
    gear_out = []
    for i, entry in enumerate(data.get("gear_pool", []), start=1):
        try:
            if "preset" in entry:
                # ── from_preset mode ──────────────────────────────────────────
                gear = Gear.from_preset(
                    preset         = entry["preset"],
                    rank           = entry["rank"],
                    refine_level   = entry["refine"],
                    secondary_stats= entry.get("secondary_stats"),
                    exclusive_for  = entry.get("exclusive_for"),
                )

            elif "rarity" in entry:
                # ── from_rarity mode ──────────────────────────────────────────
                gear = Gear.from_rarity(
                    name           = entry["name"],
                    slot           = entry["slot"],
                    rarity         = entry["rarity"],
                    rank           = entry["rank"],
                    refine_level   = entry["refine"],
                    primary_stats  = entry.get("primary_stats"),
                    secondary_stats= entry.get("secondary_stats"),
                    exclusive_for  = entry.get("exclusive_for"),
                )

            else:
                # ── raw mode (pre-computed stats) ─────────────────────────────
                gear = Gear(
                    name          = entry["name"],
                    slot          = entry["slot"],
                    flat_atk      = entry.get("flat_atk", 0),
                    flat_matk     = entry.get("flat_matk", 0),
                    atk_percent   = entry.get("atk_percent", 0),
                    matk_percent  = entry.get("matk_percent", 0),
                    crit_dmg      = entry.get("crit_dmg", 0),
                    exclusive_for = entry.get("exclusive_for"),
                )

            gear_out.append(gear)

        except (KeyError, ValueError) as exc:
            label = entry.get("name") or entry.get("preset") or f"entry #{i}"
            raise ValueError(f"gear_pool entry '{label}': {exc}") from exc

    support_bonus = data.get("support_bonus", None)
    print(f"Loaded {len(roster_out)} characters and {len(gear_out)} gear pieces from '{yaml_path}'")
    return roster_out, gear_out, support_bonus