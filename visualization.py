from sim import simulate_crit_distribution
from utils import calculate_team_buffs
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np

def get_crit_summary(team, team_buffs):
    """Return per-character crit-rate contributions and the team total."""
    rows = []
    for char in team:
        personal = sum(v for btype, v in char.buffs if btype == "crit_rate")
        rows.append((char.name, personal))
    team_total = min(team_buffs.get("crit_rate", 0), 1.0)
    return rows, team_total


def print_crit_summary(team, team_buffs):
    """Print a concise crit-rate table for the team."""
    rows, team_total = get_crit_summary(team, team_buffs)
    print("\n" + "=" * 70)
    print("CRIT RATE SUMMARY")
    print("=" * 70)
    print(f"  {'Character':<30} {'Crit Rate Contribution':>22}")
    print(f"  {'-'*30} {'-'*22}")
    for name, rate in rows:
        char = next(c for c in team if c.name == name)
        temp_cr = char.temp_buffs.get("crit_rate", 0) / 2
        display = f"{rate*100:.1f}%  (+{temp_cr*100:.1f}% self)" if temp_cr > 0 else f"{rate*100:.1f}%"
        if rate > 0 or temp_cr > 0:
            print(f"  {name:<30} {display:>22}")
    print(f"  {'':30} {'─'*22}")
    print(f"  {'TEAM TOTAL (capped at 100%)':<30} {team_total*100:>20.1f}%")


def plot_crit_distribution(sequence, team_buffs, title_suffix=""):
    """
    Simulate crit outcomes and display:
      • A histogram of total damage as % of full-crit damage
      • Vertical threshold lines at 70 / 80 / 90 %
      • Probability annotations for each threshold
    """
    fracs, full_dmg, crit_rate = simulate_crit_distribution(sequence, team_buffs)

    if len(fracs) == 0:
        print("  (No attackers in sequence – skipping distribution plot)")
        return

    pct = fracs * 100  # express as percentages

    fig, ax = plt.subplots(figsize=(9, 5))
    ax.hist(pct, bins=80, color="#4a90d9", edgecolor="white", linewidth=0.3, alpha=0.85, density=True)

    thresholds = [70, 80, 90]
    colours    = ["#e74c3c", "#e67e22", "#2ecc71"]
    for thresh, col in zip(thresholds, colours):
        prob = (pct >= thresh).mean() * 100
        ax.axvline(thresh, color=col, linewidth=1.8, linestyle="--")
        ax.text(thresh + 0.3, ax.get_ylim()[1] * 0.97,
                f"≥{thresh}%\n{prob:.1f}% chance",
                color=col, fontsize=8.5, va="top", fontweight="bold")

    ax.set_xlabel("Damage as % of Full Crit Damage", fontsize=11)
    ax.set_ylabel("Probability Density", fontsize=11)
    ax.set_title(
        f"Crit Damage Distribution  –  Team Crit Rate: {crit_rate*100:.1f}%"
        + (f"  |  {title_suffix}" if title_suffix else ""),
        fontsize=12, fontweight="bold"
    )
    ax.xaxis.set_major_formatter(mticker.PercentFormatter())
    ax.set_xlim(max(0, pct.min() - 2), 102)

    # Annotate median & expected value
    median_pct = float(np.median(pct))
    mean_pct   = float(np.mean(pct))
    ax.axvline(median_pct, color="white", linewidth=1.2, linestyle=":")
    ax.text(median_pct - 0.5, ax.get_ylim()[1] * 0.55,
            f"Median\n{median_pct:.1f}%",
            color="white", fontsize=8, ha="right")

    fig.tight_layout()
    plt.show()
    print(f"\n  [Distribution stats]  "
          f"Mean: {mean_pct:.1f}%  |  Median: {median_pct:.1f}%  |  "
          f"P(≥90%): {(pct>=90).mean()*100:.1f}%  |  "
          f"P(≥80%): {(pct>=80).mean()*100:.1f}%  |  "
          f"P(≥70%): {(pct>=70).mean()*100:.1f}%")


def print_results(results):
    for idx, result in enumerate(results):
        print(f"\n{'='*70}")
        print(f"TEAM #{idx+1}")
        print(f"{'='*70}")
        print(f"Damage: {result['damage']:,.0f}")
        print(f"Chain: {result['chain']:.1f}")
        print(f"\nTeam: {', '.join(c.name for c in result['team'])}")
        print(f"\nRotation: {' → '.join(c.name for c in result['sequence'])}")
        
        print("\nGear Assignments (by Base Character):")
        
        # Group characters by base name
        base_chars = {}
        for char in result['team']:
            if char.hits > 0:
                base_name = char.get_base_character()
                if base_name not in base_chars:
                    base_chars[base_name] = []
                base_chars[base_name].append(char)
        
        for base_name, costumes in base_chars.items():
            if base_name in result['gear_assignment']:
                gear_dict = result['gear_assignment'][base_name]
                equipped = [g for g in gear_dict.values() if g is not None]
                
                if equipped:
                    costume_names = ', '.join(c.name for c in costumes)
                    print(f"\n  {base_name} ({costumes[0].damage_type}):")
                    if len(costumes) > 1:
                        print(f"    Costumes: {costume_names}")
                    for slot in ["weapon", "armor", "head", "accessory", "glove"]:
                        gear = gear_dict[slot]
                        if gear:
                            stats = []
                            if gear.flat_atk > 0:
                                stats.append(f"+{gear.flat_atk} ATK")
                            if gear.flat_matk > 0:
                                stats.append(f"+{gear.flat_matk} MATK")
                            if gear.atk_percent > 0:
                                stats.append(f"+{gear.atk_percent*100:.0f}% ATK")
                            if gear.matk_percent > 0:
                                stats.append(f"+{gear.matk_percent*100:.0f}% MATK")
                            if gear.crit_dmg > 0:
                                stats.append(f"+{gear.crit_dmg*100:.0f}% CRIT")
                            
                            # Mark exclusive gear
                            exclusive_tag = " [EXCLUSIVE]" if gear.exclusive_for else ""
                            print(f"    [{slot.upper():9}] {gear.name}{exclusive_tag}: {', '.join(stats)}")
                            
        # ── Crit rate summary + probability distribution ──────────────────────
        team_buffs = calculate_team_buffs(result['team'])
        print_crit_summary(result['team'], team_buffs)
        print(f"\n  Generating crit damage distribution for Team #{idx+1}...")
        plot_crit_distribution(result['sequence'], team_buffs,
                               title_suffix=f"Team #{idx+1}")