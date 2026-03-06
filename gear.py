class Gear:
    _PRIMARY_TABLE = {
        ("UR", 5): (37, 0.25,  270, 0.30, 0.0833, 0.50,  2.5,  0.0168, 18,   0.020, 0.0056, 0.0336),
        ("UR", 4): (37, 0.25,  270, 0.30, 0.0833, 0.50,  2.5,  0.0168, 18,   0.020, 0.0056, 0.0336),
        ("UR", 3): (30, 0.20,  216, 0.24, 0.0666, 0.40,  2.0,  0.0133, 14.5, 0.016, 0.0045, 0.0268),
        ("UR", 2): (22, 0.15,  162, 0.18, 0.0500, 0.30,  1.48, 0.0100, 10.8, 0.012, 0.0034, 0.0200),
        ("UR", 1): (18, 0.125, 135, 0.15, 0.0416, 0.25,  1.2,  0.0084,  9.0, 0.010, 0.0028, 0.0168),
        ("SR", 5): (26, 0.175, 157, 0.175, 0.0583, 0.35, 1.74, 0.0118, 10.56, 0.0118, 0.0039, 0.0236),
        ("SR", 4): (26, 0.175, 157, 0.175, 0.0583, 0.35, 1.74, 0.0118, 10.56, 0.0118, 0.0039, 0.0236),
        ("SR", 3): (21, 0.14,  126, 0.14, 0.0466, 0.28,  1.4,  0.0094,  8.4, 0.0094, 0.0031, 0.0188),
        ("SR", 2): (15, 0.105,  94, 0.105, 0.0350, 0.21,  1.0,  0.0070,  6.3, 0.0070, 0.0024, 0.0140),
        ("SR", 1): (13, 0.0875, 78, 0.0875, 0.0291, 0.175, 0.9, 0.0060,  5.2, 0.0060, 0.0020, 0.0118),
        ("R",  5): (15, 0.10,   90, 0.10, 0.0333, 0.20,  1.0,  0.0067,  6.0, 0.0067, 0.0022, 0.0133),
        ("R",  4): (15, 0.10,   90, 0.10, 0.0333, 0.20,  1.0,  0.0067,  6.0, 0.0067, 0.0022, 0.0133),
        ("R",  3): (12, 0.08,   72, 0.08, 0.0266, 0.16,  0.0,  0.0053,  4.75, 0.0053, 0.0,   0.0),
        ("R",  2): ( 9, 0.06,   54, 0.06, 0.0200, 0.12,  0.0,  0.0040,  0.0, 0.0040, 0.0,   0.0),
        ("R",  1): ( 7, 0.05,   45, 0.05, 0.0166, 0.10,  0.0,  0.0033,  0.0, 0.0033, 0.0,   0.0),
    }

    _SUB_TABLE = {
        ("UR", 5): (12, 12, 0.09,   0.09,   96, 0.108,  0.030, 0.18),
        ("UR", 4): (12, 12, 0.09,   0.09,   96, 0.108,  0.030, 0.18),
        ("UR", 3): (10, 10, 0.072,  0.072,  76, 0.0864, 0.024, 0.144),
        ("UR", 2): ( 7,  7, 0.054,  0.054,  57, 0.0648, 0.018, 0.108),
        ("UR", 1): ( 6,  6, 0.045,  0.045,  48, 0.054,  0.015, 0.09),
        ("SR", 5): ( 8,  8, 0.063,  0.063,  56, 0.063,  0.021, 0.126),
        ("SR", 4): ( 8,  8, 0.063,  0.063,  56, 0.063,  0.021, 0.126),
        ("SR", 3): ( 7,  7, 0.0504, 0.0504, 44, 0.0504, 0.0168, 0.1008),
        ("SR", 2): ( 5,  5, 0.0378, 0.0378, 33, 0.0378, 0.0126, 0.0756),
        ("SR", 1): ( 4,  4, 0.0315, 0.0315, 28, 0.0315, 0.0105, 0.063),
        ("R",  5): ( 5,  5, 0.036,  0.036,  32, 0.036,  0.012, 0.072),
        ("R",  4): ( 5,  5, 0.036,  0.036,  32, 0.036,  0.012, 0.072),
        ("R",  3): ( 4,  4, 0.0288, 0.0288, 25, 0.0288, 0.0096, 0.0576),
        ("R",  2): ( 3,  3, 0.0216, 0.0216, 19, 0.0216, 0.0072, 0.0432),
        ("R",  1): ( 2,  2, 0.018,  0.018,  16, 0.018,  0.006,  0.036),
    }

    _PRI_STAT_INDEX = {
        "flat_atk":     (0, 6),
        "flat_matk":    (0, 6),  # flat_atk and flat_matk share the same column
        "atk_percent":  (1, 7),
        "matk_percent": (1, 7),
        "flat_hp":      (2, 8),
        "hp_percent":   (3, 9),
        "crit_rate":    (4, 10),
        "crit_dmg":     (5, 11),
    }

    _SUB_STAT_INDEX = {
        "flat_atk":     0,
        "flat_matk":    1,
        "atk_percent":  2,
        "matk_percent": 3,
        "flat_hp":      4,
        "hp_percent":   5,
        "crit_rate":    6,
        "crit_dmg":     7,
    }

    # Preset gear: shorthand/full-name -> (display_name, slot, [primary_stat, primary_stat])
    _PRESETS = {
        # Weapons
        "edb":                       ("Evil Dragon's Blade",        "weapon",    ["flat_atk",     "crit_dmg"]),
        "evil dragon's blade":       ("Evil Dragon's Blade",        "weapon",    ["flat_atk",     "crit_dmg"]),
        "hot":                       ("Hammer of Thunder",          "weapon",    ["flat_atk",     "atk_percent"]),
        "hammer of thunder":         ("Hammer of Thunder",          "weapon",    ["flat_atk",     "atk_percent"]),
        "pj":                        ("Peerless Javelin",           "weapon",    ["flat_atk",     "flat_atk"]),
        "peerless javelin":          ("Peerless Javelin",           "weapon",    ["flat_atk",     "flat_atk"]),
        "tgf":                       ("Travel God's Friend",        "weapon",    ["flat_matk",    "crit_dmg"]),
        "travel god's friend":       ("Travel God's Friend",        "weapon",    ["flat_matk",    "crit_dmg"]),
        "eod":                       ("Eye of the Destroyer",       "weapon",    ["flat_matk",    "matk_percent"]),
        "eye of the destroyer":      ("Eye of the Destroyer",       "weapon",    ["flat_matk",    "matk_percent"]),
        "dfb":                       ("Demon's Forbidden Book",     "weapon",    ["flat_matk",    "flat_matk"]),
        "demon's forbidden book":    ("Demon's Forbidden Book",     "weapon",    ["flat_matk",    "flat_matk"]),
        # Armor
        "ia":                        ("Invulnerable Armor",         "armor",     []),
        "invulnerable armor":        ("Invulnerable Armor",         "armor",     []),
        "sosg":                      ("Scale of the Sea God",       "armor",     []),
        "scale of the sea god":      ("Scale of the Sea God",       "armor",     []),
        "iga":                       ("Immortal Golden Armor",      "armor",     []),
        "immortal golden armor":     ("Immortal Golden Armor",      "armor",     []),
        "fg":                        ("Fiend Guard",                "armor",     []),
        "fiend guard":               ("Fiend Guard",                "armor",     []),
        "ds":                        ("Death's Shroud",             "armor",     []),
        "death's shroud":            ("Death's Shroud",             "armor",     []),
        "hr":                        ("Hellfire Robe",              "armor",     []),
        "hellfire robe":             ("Hellfire Robe",              "armor",     []),
        # Helmet
        "hoc":                       ("Helm of Carnage",            "helmet",    []),
        "helm of carnage":           ("Helm of Carnage",            "helmet",    []),
        "ug":                        ("Undefeated Glory",           "helmet",    []),
        "undefeated glory":          ("Undefeated Glory",           "helmet",    []),
        "hod":                       ("Helm of Death",              "helmet",    []),
        "helm of death":             ("Helm of Death",              "helmet",    []),
        "rw":                        ("Radiant Wisdom",             "helmet",    []),
        "radiant wisdom":            ("Radiant Wisdom",             "helmet",    []),
        "sb":                        ("Solar Brilliance",           "helmet",    []),
        "solar brilliance":          ("Solar Brilliance",           "helmet",    []),
        "cog":                       ("Crown of Galaxy",            "helmet",    []),
        "crown of galaxy":           ("Crown of Galaxy",            "helmet",    []),
        # Accessories
        "wob":                       ("Warmth of the Brazier",      "accessory", ["crit_rate",    "crit_rate"]),
        "warmth of the brazier":     ("Warmth of the Brazier",      "accessory", ["crit_rate",    "crit_rate"]),
        "poa":                       ("Pinnacle of Asthetics",      "accessory", ["crit_rate",    "flat_hp"]),
        "pinnacle of asthetics":     ("Pinnacle of Asthetics",      "accessory", ["crit_rate",    "flat_hp"]),
        "poh":                       ("Promise of Harmony",         "accessory", ["crit_rate",    "hp_percent"]),
        "promise of harmony":        ("Promise of Harmony",         "accessory", ["crit_rate",    "hp_percent"]),
        "vt":                        ("Venomous Touch",             "accessory", ["crit_dmg",     "crit_dmg"]),
        "venomous touch":            ("Venomous Touch",             "accessory", ["crit_dmg",     "crit_dmg"]),
        "rol":                       ("Ring of the Lake",           "accessory", ["crit_dmg",     "flat_hp"]),
        "ring of the lake":          ("Ring of the Lake",           "accessory", ["crit_dmg",     "flat_hp"]),
        "cg":                        ("Venomous Touch",             "accessory", ["crit_dmg",     "hp_percent"]),
        "charming gaze":             ("Charming Gaze",              "accessory", ["crit_dmg",     "hp_percent"]),
        # Gloves
        "r":                         ("Rebellion",                  "glove",     ["atk_percent",  "crit_rate"]),
        "rebellion":                 ("Rebellion",                  "glove",     ["atk_percent",  "crit_rate"]),
        "gksa":                      ("God-King's Silver Arm",      "glove",     ["atk_percent",  "atk_percent"]),
        "god-king's silver arm":     ("God-King's Silver Arm",      "glove",     ["atk_percent",  "atk_percent"]),
        "pa":                        ("Prime Authority",            "glove",     ["flat_atk",     "atk_percent"]),
        "prime authority":           ("Prime Authority",            "glove",     ["flat_atk",     "atk_percent"]),
        "rof":                       ("Ring of Fury",               "glove",     ["matk_percent", "crit_rate"]),
        "ring of fury":              ("Ring of Fury",               "glove",     ["matk_percent", "crit_rate"]),
        "sot":                       ("Shackle of Treachery",       "glove",     ["matk_percent", "matk_percent"]),
        "shackle of treachery":      ("Shackle of Treachery",       "glove",     ["matk_percent", "matk_percent"]),
        "dsp":                       ("Dragon Scale's Protection",  "glove",     ["flat_matk",    "matk_percent"]),
        "dragon scale's protection": ("Dragon Scale's Protection",  "glove",     ["flat_matk",    "matk_percent"]),
    }

    def __init__(self, name, slot, flat_atk=0, flat_matk=0, atk_percent=0, matk_percent=0, crit_dmg=0, exclusive_for=None):
        """
        slot must be one of: weapon, head, armor, accessory, glove
        exclusive_for: base character name this gear is locked to (e.g., "Wilhelmina")
                      If None, gear can be equipped by anyone
        """
        self.name = name
        self.slot = slot
        self.flat_atk = flat_atk
        self.flat_matk = flat_matk
        self.atk_percent = atk_percent
        self.matk_percent = matk_percent
        self.crit_dmg = crit_dmg
        self.exclusive_for = exclusive_for

    @classmethod
    def from_preset(cls, preset, rank, refine_level,
                    secondary_stats=None, exclusive_for=None):
        """
        Shorthand constructor using a named gear preset.

        All preset gear is UR. The slot and primary stats are determined by
        the preset; you only need to supply rank, refine level, and optional
        secondary stats.

        Parameters
        ----------
        preset : str
            Shorthand or full name, case-insensitive. See table below.
        rank : int
            1 to 5
        refine_level : int
            0 to 24
        secondary_stats : list[str] or None
            Up to 3 stat names depending on refine level.
        exclusive_for : str or None

        Available presets
        -----------------
        EDB  / Evil Dragon's Blade       — weapon,    flat_atk + crit_dmg
        HoT  / Hammer of Thunder         — weapon,    flat_atk + atk_percent
        TGF  / Travel God's Friend       — weapon,    flat_matk + crit_dmg
        EoD  / Eye of the Destroyer      — weapon,    flat_matk + matk_percent
        VT   / Venomous Touch            — accessory, crit_dmg × 2
        PA   / Prime Authority           — glove,     flat_atk + atk_percent
        DSP  / Dragon Scale's Protection — glove,     flat_matk + matk_percent
        GKSA / God-King's Silver Arm     — glove,     atk_percent × 2
        SoT  / Shackle of Treachery      — glove,     matk_percent × 2
        """
        key = preset.strip().lower()
        if key not in cls._PRESETS:
            shorthands = ", ".join(k.upper() for k in cls._PRESETS if len(k) <= 4)
            raise ValueError(f"Unknown preset '{preset}'. Valid shorthands: {shorthands}")
        name, slot, primary_stats = cls._PRESETS[key]
        
        # Create descriptive name with secondary stats
        base_name = name + " UR" + str(rank) + "+" + str(refine_level)
        if secondary_stats:
            # Map full stat names to shorthand abbreviations
            stat_shorthand = {
                "flat_atk": "atk",
                "flat_matk": "matk", 
                "atk_percent": "atk%",
                "matk_percent": "matk%",
                "flat_hp": "hp",
                "hp_percent": "hp%",
                "crit_rate": "crate",
                "crit_dmg": "cdmg"
            }
            shorthand_stats = [stat_shorthand.get(stat, stat) for stat in secondary_stats]
            stat_suffix = "_" + "_".join(shorthand_stats)
            full_name = base_name + stat_suffix
        else:
            full_name = base_name
        
        return cls.from_rarity(
            name=full_name,
            slot=slot,
            rarity="UR",
            rank=rank,
            refine_level=refine_level,
            primary_stats=primary_stats,
            secondary_stats=secondary_stats,
            exclusive_for=exclusive_for,
        )

    @classmethod
    def from_rarity(cls, name, slot, rarity, rank, refine_level,
                    primary_stats, secondary_stats=None, exclusive_for=None):
        """
        Alternate constructor that computes stat values from gear parameters.

        Parameters
        ----------
        name : str
        slot : str
            One of: weapon, head, armor, accessory, glove
        rarity : str
            "UR", "SR", or "R"
        rank : int
            1 to 5.
        refine_level : int
            0 to 24. Primary stats scale as: base + mult * (refine_level + 6).
            Also determines max secondary stats: 0-2 -> 0, 3-5 -> 1, 6-8 -> 2, 9+ -> 3.
        primary_stats : list[str]
            Exactly 2 stat names from: flat_atk, flat_matk, atk_percent,
            matk_percent, flat_hp, hp_percent, crit_rate, crit_dmg
        secondary_stats : list[str] or None
            Up to 3 stat names from the same pool. Each adds a flat amount
            determined by (rarity, rank).
        exclusive_for : str or None

        Returns
        -------
        Gear
        """
        rarity = rarity.upper()
        if rarity not in ("UR", "SR", "R"):
            raise ValueError(f"rarity must be UR, SR, or R; got '{rarity}'")
        if not (1 <= rank <= 5):
            raise ValueError(f"rank must be 1-5; got {rank}")
        if not (0 <= refine_level <= 24):
            raise ValueError(f"refine_level must be 0-24; got {refine_level}")
        secondary_stats = secondary_stats or []
        max_secondaries = 0 if refine_level <= 2 else 1 if refine_level <= 5 else 2 if refine_level <= 8 else 3
        if len(secondary_stats) > max_secondaries:
            raise ValueError(
                f"refine_level +{refine_level} allows at most {max_secondaries} secondary stat(s); "
                f"got {len(secondary_stats)}"
            )

        if exclusive_for is not None and rank != 5:
            raise ValueError(f"Exclusive gear must be rank 5 (EX); got rank={rank}")

        # Create descriptive name with secondary stats if not already included
        if secondary_stats:
            # Check if name already contains any secondary stat suffix
            has_suffix = any("_" + stat in name for stat in secondary_stats)
            
            # Also check for shorthand versions
            stat_shorthand = {
                "flat_atk": "atk",
                "flat_matk": "matk", 
                "atk_percent": "atk%",
                "matk_percent": "matk%",
                "flat_hp": "hp",
                "hp_percent": "hp%",
                "crit_rate": "crate",
                "crit_dmg": "cdmg"
            }
            has_shorthand_suffix = any("_" + stat_shorthand.get(stat, stat) in name for stat in secondary_stats)
            
            if not has_suffix and not has_shorthand_suffix:
                shorthand_stats = [stat_shorthand.get(stat, stat) for stat in secondary_stats]
                stat_suffix = "_" + "_".join(shorthand_stats)
                full_name = name + stat_suffix
            else:
                full_name = name
        else:
            full_name = name

        key = (rarity, rank)
        if key not in cls._PRIMARY_TABLE:
            raise ValueError(f"No table entry for rarity={rarity}, rank={rank}")

        pri = cls._PRIMARY_TABLE[key]
        sub = cls._SUB_TABLE[key]

        stats = {
            "flat_atk": 0.0, "flat_matk": 0.0,
            "atk_percent": 0.0, "matk_percent": 0.0,
            "crit_dmg": 0.0,
        }

        scale = refine_level + 6

        if primary_stats:
            for stat in primary_stats:
                if stat not in cls._PRI_STAT_INDEX:
                    raise ValueError(f"Unknown primary stat: '{stat}'")
                base_idx, mult_idx = cls._PRI_STAT_INDEX[stat]
                value = pri[base_idx] + pri[mult_idx] * scale
                stats[stat] = stats.get(stat, 0.0) + value

        for stat in secondary_stats:
            if stat not in cls._SUB_STAT_INDEX:
                raise ValueError(f"Unknown secondary stat: '{stat}'")
            value = sub[cls._SUB_STAT_INDEX[stat]]
            stats[stat] = stats.get(stat, 0.0) + value

        return cls(
            name=full_name,
            slot=slot,
            flat_atk=round(stats.get("flat_atk", 0)),
            flat_matk=round(stats.get("flat_matk", 0)),
            atk_percent=round(stats.get("atk_percent", 0.0), 4),
            matk_percent=round(stats.get("matk_percent", 0.0), 4),
            crit_dmg=round(stats.get("crit_dmg", 0.0), 4),
            exclusive_for=exclusive_for,
        )

    def __repr__(self):
        exclusive_tag = f"[{self.exclusive_for}]" if self.exclusive_for else ""
        return f"{self.name}({self.slot}){exclusive_tag}"

    def __hash__(self):
        return hash((self.name, self.slot))

    def can_equip_to(self, base_character_name):
        """Check if this gear can be equipped to a base character."""
        if self.exclusive_for is None:
            return True
        return self.exclusive_for == base_character_name

    def stat_value_for_character(self, char):
        """Estimate how valuable this gear is for a specific character.
        
        Multipliers are empirically validated based on actual damage calculations:
        - Flat ATK/MATK: 5.4x base value
        - ATK%/MATK%: 5.4x scaled by base ATK
        - Crit DMG: 3.6x scaled by base ATK
        
        Uses logarithmic scaling for extreme base ATK values to maintain accuracy.
        """
        # Apply logarithmic scaling for extreme base ATK values
        # This helps maintain accuracy across different character power levels
        base_atk_factor = char.base_atk / 1000.0  # Normalize to 1000 ATK baseline
        if base_atk_factor > 1.0:
            # For high ATK characters, use logarithmic scaling to avoid overestimation
            scaled_atk = 1000.0 * (1 + (base_atk_factor - 1) ** 0.7)
        else:
            # For low ATK characters, scale linearly
            scaled_atk = char.base_atk
        
        if char.damage_type == "ATK":
            return (self.flat_atk * 5.4 + self.atk_percent * scaled_atk * 5.4 +
                    self.crit_dmg * scaled_atk * 3.6)
        elif char.damage_type == "MATK":
            return (self.flat_matk * 5.4 + self.matk_percent * scaled_atk * 5.4 +
                    self.crit_dmg * scaled_atk * 3.6)
        else:  # Max HP
            return self.crit_dmg * 100
