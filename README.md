# BD2 LN Gear & Team Optimizer

A Python tool for optimizing team composition and gear assignments in Last Night mode of **Brown Dust 2**. It models the game's damage formula — including chain count, crit rate, ATK/MATK buffs, and the support bonus multiplier — and uses a two-stage search (simulated annealing → beam search) to find the highest-damage team and gear loadout.

---

## Requirements

- Python 3.9+
- `pyyaml`, `numpy`, `matplotlib`

```bash
pip install pyyaml numpy matplotlib
```

---

## Project Layout

```
├── main.py            # Entry point — run this
├── sim.py             # Damage engine, optimization algorithms
├── character.py       # Character class (stats + gear management)
├── gear.py            # Gear class (raw, from_rarity, from_preset constructors)
├── utils.py           # Shared helpers (buff calculation, rotation logic)
├── visualization.py   # Console output + HTML report generation
├── config.py          # Global config (support_bonus)
└── data/
    ├── data.py        # YAML loader
    └── data.yaml      # Your roster and gear pool ← edit this
```

---

## Quick Start

1. Edit `data/data.yaml` to reflect your actual characters and gear (see [YAML Reference](YAML_REFERENCE.md)).
2. Run:

```bash
python main.py
```

3. On first run you will be prompted to enter your **support bonus** if one is not already saved in `data.yaml`. It is saved automatically for future runs.

4. Choose an optimization mode when prompted.

---

## Optimization Modes

### Mode 1 — Fixed Team: Optimize Gear Only

Skips team search entirely and optimizes gear assignments for a predetermined team. Edit the `fixed_team` variable in `main.py` to set your team before running.

**When to use:** You already know which characters you want and just need the best gear distribution.

**Speed:** Fast — typically a few seconds.

### Mode 2 — Full Optimization: Team + Gear

Runs a two-stage search:

1. **Stage 1 — Simulated Annealing** explores the team composition space, evaluating many candidate teams with lightweight gear assignment at each step.
2. **Stage 2 — Beam Search** takes the best team from Stage 1 and does a thorough gear assignment search.

When prompted for a preset:

| Preset | Stage 1 | Best for |
|---|---|---|
| Fast | Quick SA sweep | Iterating quickly, large rosters |
| Balanced | Moderate SA | Daily use (recommended) |
| Thorough | Full SA + wider beam | Final optimization before a raid |

**When to use:** You have flexibility in team composition and want the globally best result.

**Speed:** Minutes — varies with roster and gear pool size.

### Mode 3 — Update Support Bonus

Changes the stored support bonus without re-running optimization.

---

## Output

After optimization completes, the tool prints results to the console and generates an HTML report in `reports/`. The report includes:

- Total damage and chain count
- Team composition and attack rotation
- Gear assignments per character with stat breakdowns
- A damage contribution chart (bar chart per team member)
- A crit distribution histogram showing the probability of hitting various damage thresholds

---

## Known Issues & Limitations

### Unimplemented costumes

- Only costumes that depend on ATK, MATK, and enemy HP are implemented. 
- DS Luvencia's variable skill ratio when chain_count is a multiple of 3 is not implemented.

### Unimplemented buff types

The following buff types can be listed on characters in `data.yaml` but are not yet read by the damage engine: `property_dmg`, `energy_guard`, `heal`, `barrier`. They are counted toward NH Nebris's `buff_count` ratio calculation but do not otherwise affect damage output. They are placeholders for future implementation.