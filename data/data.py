from pathlib import Path
import yaml
from character.character import Character
from gear import Gear
import csv

def load_character_stats(csv_path):
    """Load character stats from CSV file."""
    character_stats = {}
    
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            character_stats[row['enName']] = {
                'base_atk': int(row['maxlevel_atk']) if row['maxlevel_atk'] else 0,
                'engraving_atk': float(row['engraving_atk']) if row['engraving_atk'] else 0.0,
                'crit_rate': float(row['maxlevel_cr']) / 100.0 if row['maxlevel_cr'] else 0.0  # Convert % to decimal
            }
    
    return character_stats

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

    # Load character stats from CSV
    csv_path = Path(yaml_path).parent.parent / "character" / "character_stats.csv"
    char_stats = load_character_stats(csv_path)

    # ── Build roster ──────────────────────────────────────────────────────────
    roster_out = []
    for entry in data.get("roster", []):
        # Only process characters that have costumes, but also include base characters without costumes
        costumes = entry.get("costumes", [])
        base_character = None
        
        if not costumes:
            # Get crit_rate from CSV if available
            crit_rate = 0.1  # default
            if entry['name'] in char_stats:
                crit_rate = char_stats[entry['name']]['crit_rate']
            
            # Create base character without costumes if it matches our target
            base_character = Character(
                name          = entry['name'],
                damage_type   = entry.get('damage_type', 'ATK'),
                atk           = entry.get('atk', 0),
                crit_dmg      = entry.get('crit_dmg', 0.5),
                ratio_per_hit = 0,
                hits          = 0,
                buffs         = [],
                temp_buffs    = entry.get('temp_buffs', {}),
                domain        = entry.get('domain', {}),
                base_flat_atk = 0,
                base_atk_percent = 0,
                crit_rate     = crit_rate,
            )
            roster_out.append(base_character)
            continue  # Skip to next character
        
        # Get base character stats from CSV
        base_name = entry['name']
        base_flat_atk = 0
        base_atk_percent = 0
        
        if base_name in char_stats:
            base_stats = char_stats[base_name]
            base_flat_atk = base_stats['engraving_atk'] if entry.get('is_atk_engraved', False) else 0.0
            yaml_atk = entry.get('atk', 0)
            if yaml_atk > 0 and (base_stats['base_atk'] + base_flat_atk) > 0:
                base_atk_percent = (yaml_atk / (base_stats['base_atk'] + base_flat_atk)) - 1
        
        # Process costumes only (skip base character)
        for costume in costumes:
            costume_name = f"{costume['name']} {entry['name']}"
            costume_data = {
                "name": costume_name,
                "damage_type": costume["damage_type"],
                "atk": entry.get("atk", 0),  # Use base character's ATK
                "crit_dmg": entry.get("crit_dmg", 0.5),  # Use base character's crit_dmg
                "ratio_per_hit": costume.get("ratio_per_hit", 0),
                "hits": costume.get("hits", 0),
                "temp_buffs": costume.get("temp_buffs", {}),
                "domain": entry.get("domain", {}),
            }
            
            # Add costume buffs if present
            costume_buffs = []
            if 'buffs' in costume:
                raw_buffs = costume['buffs']
                costume_buffs = [(k, v) for item in raw_buffs for k, v in item.items()]
            
            # Get crit_rate from CSV if available
            crit_rate = 0.1  # default
            if base_name in char_stats:
                crit_rate = char_stats[base_name]['crit_rate']
            
            # Create costume character with base modifiers
            costume_char = Character(
                name          = costume_data["name"],
                damage_type   = costume_data["damage_type"],
                atk           = base_stats['base_atk'] if base_name in char_stats else entry.get("atk", 0),
                crit_dmg      = costume_data["crit_dmg"],
                ratio_per_hit = costume_data["ratio_per_hit"],
                hits          = costume_data["hits"],
                buffs         = costume_buffs,  # Use costume buffs
                temp_buffs    = costume_data["temp_buffs"],
                domain        = costume_data["domain"],
                base_flat_atk = base_flat_atk,
                base_atk_percent = base_atk_percent,
                crit_rate     = crit_rate,
            )
            roster_out.append(costume_char)

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
                    crit_rate     = entry.get("crit_rate", 0),
                    exclusive_for = entry.get("exclusive_for"),
                )

            gear_out.append(gear)

        except (KeyError, ValueError) as exc:
            label = entry.get("name") or entry.get("preset") or f"entry #{i}"
            raise ValueError(f"gear_pool entry '{label}': {exc}") from exc

    support_bonus = data.get("support_bonus", None)
    print(f"Loaded {len(roster_out)} characters and {len(gear_out)} gear pieces from '{yaml_path}'")
    return roster_out, gear_out, support_bonus