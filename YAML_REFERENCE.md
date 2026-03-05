# data.yaml Reference

This file defines your Brown Dust 2 roster and gear pool. The optimizer reads it on every run.

---

## Top-Level Structure

```yaml
support_bonus: 4.0      # Optional — set once via the CLI prompt; auto-saved

nh_nebris_ratio_multiplier: 0.15 # Required - How much each buff increases NH Nebris damage (0.15-0.30)

roster:
  - ...                 # Character entries

gear_pool:
  - ...                 # Gear entries
```

---

## `support_bonus`

Stored as a decimal. Applied in the damage formula as `× (1 + value)`, so `4.0` means your base damage is multiplied by **5×** total.

| You type | Stored as | Effective multiplier |
|---|---|---|
| `400%` | `4.0` | 5× |
| `4.0` | `4.0` | 5× |
| `1.0` | `1.0` | 2× |

You can also update this value by running `main.py` and choosing **Mode 3**.

---

## `roster` — Character Entries

Each character needs these fields:

| Field | Type | Required | Description |
|---|---|---|---|
| `name` | string | ✅ | Full in-game display name including costume prefix (e.g. `"WPQ Wilhelmina"`) |
| `damage_type` | string | ✅ | `ATK`, `MATK`, or `Max HP` |
| `atk` | number | attackers only | Base ATK or MATK stat |
| `crit_dmg` | number | attackers only | Base crit damage **as a decimal above 0** — e.g. `0.75` means +75% crit damage (total crit mult becomes `1.75`) |
| `ratio_per_hit` | number | attackers only | Damage ratio per individual hit |
| `hits` | integer | attackers only | Number of hits in the skill |
| `buffs` | list | optional | Team-wide buffs this character provides (see below) |
| `temp_buffs` | mapping | optional | Self-only buffs (see below) |
| `domain` | mapping | optional | Team-wide buffs that don't count for buff_count (see below) |

These values are for a 'naked' character without gear, but they are hard to standardize as they depend on which costume is bonded, total collection bonus %, and potential nodes. Remember to use the gear presets to easily save your current loadouts before data entry.

### `buffs` — Team-Wide Buffs

```yaml
buffs:
  - ATK%: 0.6      # +60% ATK to all ATK characters
  - ATK%: 0.5      # second ATK% buff — stacks additively, counted separately
  - MATK%: 0.5
  - overall: 1.2   # +120% overall damage (multiplied in)
  - crit_rate: 0.3 # +30% crit rate
  - crit_dmg: 0.75 # +75% crit damage
  - chain_count: 1 # +1 chain count per hit
```

**Supported buff types and how they are applied:**

| Buff type | Effect |
|---|---|
| `ATK%` | Adds to the team ATK% multiplier |
| `MATK%` | Same as ATK% but for MATK characters |
| `overall` | Stacks additively into the overall damage multiplier |
| `crit_rate` | Adds to the team crit rate pool |
| `crit_dmg` | Adds to all characters' crit damage |
| `chain_count` | Increases how much the chain counter advances per hit |
| `property_dmg` | ⚠️ Placeholder — parsed but not applied to damage besides NH Nebris's skill |
| `energy_guard` | ⚠️ Placeholder — parsed but not applied to damage |
| `heal` | ⚠️ Placeholder — parsed but not applied to damage |
| `barrier` | ⚠️ Placeholder — parsed but not applied to damage |

> **ATK%/MATK% halving explained:** Each buffer's contribution is divided by 2 due to 50% pressure from LN mode. If a character provides `ATK%: 0.8`, the team receives `+0.4` to the ATK% multiplier.

### `domain` — Team-Wide Buffs (Excluded from buff_count)

`domain` is a plain mapping (dict) similar to `temp_buffs`. These provide team-wide buffs like regular `buffs`, but **do not count toward NH Nebris's buff_count calculation**. This is used for characters who apply both damage and team buffs (like RL Olivier).

```yaml
domain:
  MATK%: 0.6      # +60% MATK to all MATK characters
  ATK%: 0.5        # +50% ATK to all ATK characters
  overall: 1.2       # +120% overall damage
  crit_rate: 0.3     # +30% crit rate
  crit_dmg: 0.75     # +75% crit damage
  chain_count: 1    # +1 chain count per hit
```

**Key difference from `buffs`:** Domain buffs apply to the team but are excluded from NH Nebris's buff_count calculation, making them ideal for hybrid attacker/buffer characters.

### `temp_buffs` — Self-Only Buffs

`temp_buffs` are any buffs applied by a costume immediately before attacking (Ex. PoV Lathel gains 50% atk before his 750% of ATK hit). 

These apply only to the character itself and are also halved before use.

```yaml
temp_buffs:
  ATK%: 0.5        # Self ATK% (halved: +0.25 effective)
  MATK%: 0.5
  crit_rate: 0.5   # Self crit rate (halved: +0.25 effective)
  crit_dmg: 0.5
  chain_count: 1
```

### Special Characters

**NH Nebris** — `ratio_per_hit` is the base value. The actual value used in damage calculation is `base_value` + (`nh_nebris_ratio_multiplier` × `buff_count`), where `buff_count` is the total number of buff entries across all team members' `buffs` lists. **Note:** `domain` buffs are excluded from this count.

**DS Luvencia** - should have higher `ratio_per_hit` when `chain_count` is a multiple of 3 (NOT IMPLEMENTED).

### Buffer vs Attacker: Quick Reference

```yaml
# Hybrid Attacker/Buffer — with domain buffs
- name: "RL Olivier"
  damage_type: MATK
  atk: 378
  crit_dmg: 1
  ratio_per_hit: 0.5
  hits: 6
  domain:
    MATK%: 0.6      # +60% MATK to team (doesn't count for Nebris)

# Pure buffer — no damage stats needed
- name: "Shrine Granadair"
  damage_type: MATK
  buffs:
    - overall: 1.2

# Attacker — no buffs needed
- name: "Bride Eclipse"
  damage_type: MATK
  atk: 565
  crit_dmg: 0.642
  ratio_per_hit: 5.5
  hits: 1

```

### Commenting Out Characters

Prefix with `#` to temporarily exclude a character without deleting their entry:

```yaml
  # - name: "RRH Rou"
  #   damage_type: ATK
  #   buffs:
  #     - crit_rate: 0.3
```

---

## `gear_pool` — Gear Entries

Three construction modes are supported. The loader detects which mode to use based on which keys are present.

---

### Mode 1: `preset` — Named Gear with Computed Stats

Easiest option to enter gear stats for UR gear. For example, if you want to enter Evil Dragon's Blade at rank UR IV and refine level 19, you would use (assuming a flat atk and 2 crit_dmg substats):

```yaml
- preset: EDB           # shorthand (case-insensitive) or full name
  rank: 4               # 1–5
  refine: 19            # 0–24
  secondary_stats:      # optional; count limit depends on refine level (see below)
    - crit_dmg
    - crit_dmg
    - flat_atk
```

**Available presets:**

| Shorthand | Full Name | Slot | Primary Stats |
|---|---|---|---|
| `EDB` | Evil Dragon's Blade | weapon | `flat_atk` + `crit_dmg` |
| `HoT` | Hammer of Thunder | weapon | `flat_atk` + `atk_percent` |
| `TGF` | Travel God's Friend | weapon | `flat_matk` + `crit_dmg` |
| `EoD` | Eye of the Destroyer | weapon | `flat_matk` + `matk_percent` |
| `VT` | Venomous Touch | accessory | `crit_dmg` × 2 |
| `PA` | Prime Authority | glove | `flat_atk` + `atk_percent` |
| `DSP` | Dragon Scale's Protection | glove | `flat_matk` + `matk_percent` |
| `GKSA` | God-King's Silver Arm | glove | `atk_percent` × 2 |
| `SoT` | Shackle of Treachery | glove | `matk_percent` × 2 |

---

### Mode 2: `rarity` — Custom Named Gear with Computed Stats

Use this when gear is not a preset but you know its rarity, rank, refine level, and stat types. Stat values are computed from the game's internal tables.

```yaml
- name: "My custom sword"       # displayed in output and HTML report
  slot: weapon                  # weapon / head / armor / accessory / glove
  rarity: UR                    # UR / SR / R
  rank: 3                       # 1–5
  refine: 15                    # 0–24
  primary_stats:                # exactly 2 stat names
    - flat_matk
    - crit_dmg
  secondary_stats:              # 0–3 stat names depending on refine level
    - matk_percent
  exclusive_for: null           # optional
```

**`primary_stats` and `secondary_stats`** accept these stat names:

`flat_atk`, `flat_matk`, `atk_percent`, `matk_percent`, `flat_hp`, `hp_percent`, `crit_rate`, `crit_dmg`

> **Note:** `flat_hp` and `hp_percent` are parsed but do not affect damage calculations (they have no damage-relevant column in the stat tables for ATK/MATK characters).

---

### Mode 3: Raw — Pre-Computed Stats

Use this for EX gear that has 3 primary stats, check the refinements window and enter the full stats.

```yaml
- name: "Wilhelmina SR15"
  slot: weapon
  flat_atk: 62
  atk_percent: 0.4858    # express as decimal (0.4858 = 48.58%)
  crit_dmg: 0.126        # express as decimal (0.126 = +12.6% crit damage)
  exclusive_for: "Wilhelmina"
```

All stat fields are optional and default to `0` if omitted.

| Field | Type | Description |
|---|---|---|
| `flat_atk` | integer | Flat ATK added |
| `flat_matk` | integer | Flat MATK added |
| `atk_percent` | decimal | ATK% multiplier increase |
| `matk_percent` | decimal | MATK% multiplier increase |
| `crit_dmg` | decimal | Crit damage increase |
| `exclusive_for` | string or null | Base character name (last word of costume name) |

---

### `exclusive_for` — Locking Gear to a Character

Setting `exclusive_for` means the gear can only be assigned to one specific character (matched by the last word of their name). For example, `exclusive_for: "Wilhelmina"` matches `"WPQ Wilhelmina"`, `"IM Wilhelmina"`, and `"FQ Wilhelmina"`.

Exclusive gear **requires `rank: 5`** when using preset or from_rarity mode (it corresponds to EX rank in-game). Attempting to create exclusive gear at rank 1–4 raises an error at load time.

Exclusive gear is automatically pre-assigned before the optimizer runs. It is not included in the general gear pool.

---

## Complete Examples

```yaml
# ── Attacker with self-buff ───────────────────────────────────────────────────
- name: "WPQ Wilhelmina"
  damage_type: ATK
  atk: 602
  crit_dmg: 1.027
  ratio_per_hit: 0.45
  hits: 9
  temp_buffs:
    chain_count: 1      # she buffs herself to add 1 extra chain per hit

# ── Buffer with two same-type buffs ──────────────────────────────────────────
- name: "H Lathel"
  damage_type: ATK
  buffs:
    - ATK%: 0.9
    - ATK%: 0.6         # second ATK% buff counted separately for Nebris

# ── Preset weapon ─────────────────────────────────────────────────────────────
- preset: EDB
  rank: 4
  refine: 19
  secondary_stats:
    - flat_atk
    - atk_percent
    - atk_percent

# ── Custom armor (from_rarity) — note: armor can omit primary_stats ───────────
- name: "IA UR4 armor"
  slot: armor
  rarity: UR
  rank: 4
  refine: 9 # doesn't matter past 9 for 3 substats
  secondary_stats:
    - crit_dmg
    - crit_dmg

# ── Exclusive weapon (raw) ────────────────────────────────────────────────────
- name: "Nebris UR21 exclusive"
  slot: weapon
  flat_atk: 104
  atk_percent: 1.2436
  crit_dmg: 0.18
  exclusive_for: "Nebris"   # only assigns to characters named "* Nebris"
```
