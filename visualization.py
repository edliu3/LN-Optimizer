from sim import simulate_crit_distribution, _hits_data
from utils import calculate_team_buffs
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import yaml
import base64
from io import BytesIO
from datetime import datetime
from pathlib import Path
import config

def format_damage(damage):
    """Format damage number with B/M/K suffixes."""
    if damage >= 1e9:
        return f"{damage/1e9:.2f}B"
    elif damage >= 1e6:
        return f"{damage/1e6:.1f}M"
    elif damage >= 1e3:
        return f"{damage/1e3:.0f}K"
    else:
        return f"{damage:.0f}"

def get_crit_summary(team, team_buffs):
    """Return per-character crit-rate contributions and the team total."""
    rows = []
    for char in team:
        personal = sum(v for btype, v in char.buffs if btype == "crit_rate")
        rows.append((char.name, personal))
    team_total = min(team_buffs.get("crit_rate", 0) + 0.1, 1.0)
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
        display = f"{rate*100/2:.1f}%  (+{temp_cr*100/2:.1f}% self)" if temp_cr > 0 else f"{rate*100/2:.1f}%"
        if rate > 0 or temp_cr > 0:
            print(f"  {name:<30} {display:>22}")
    print(f"  {'':30} {'─'*22}")
    print(f"  {'TEAM TOTAL (capped at 100%)':<30} {team_total*100:>20.1f}%")


def print_results(results):
    for idx, result in enumerate(results):
        print(f"\n{'='*70}")
        print(f"TEAM #{idx+1}")
        print(f"{'='*70}")
        print(f"Damage: {result['damage']:,.0f}")
        print(f"Chain Count: {result['chain']:.1f}")
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


def plot_damage_contribution_html(sequence, team_buffs, support_bonus=None):
    """
    Generate horizontal bar chart showing damage contribution by each team member.
    Returns tuple of (base64_image, damage_data)
    """
    # Use config support_bonus if not provided
    if support_bonus is None:
        support_bonus = config.support_bonus
    # Calculate damage for each character
    damage_data = []
    hits_data = _hits_data(sequence, team_buffs, support_bonus)

    for char in sequence:
        if char.hits > 0:  # Only include characters that deal damage
            hit_indices = [i for i, hit in enumerate(hits_data) if hit[0] == char.name]
            # Calculate expected damage (assumed crit)
            expected_damage = sum(hit[1] for i, hit in enumerate(hits_data) if i in hit_indices)
            
            damage_data.append({
                'name': char.name,
                'damage': expected_damage,
                'percentage': 0,  # Will be calculated after total is known
                'damage_type': char.damage_type
            })
    
    if not damage_data:
        return None, {}
    
    # Sort by damage descending
    damage_data.sort(key=lambda x: x['damage'], reverse=True)
    
    # Calculate percentages
    total_damage = sum(item['damage'] for item in damage_data)
    for item in damage_data:
        item['percentage'] = (item['damage'] / total_damage) * 100
    
    # Create horizontal bar chart
    fig, ax = plt.subplots(figsize=(10, max(4, len(damage_data) * 0.6)))
    
    names = [item['name'] for item in damage_data]
    damages = [item['damage'] for item in damage_data]
    percentages = [item['percentage'] for item in damage_data]
    
    # Create color map based on damage type
    colors = ['#e74c3c' if item['damage_type'] == 'ATK' else '#3498db' for item in damage_data]
    
    bars = ax.barh(range(len(names)), damages, color=colors, alpha=0.8, edgecolor='white', linewidth=0.5)
    
    # Customize the chart
    ax.set_yticks(range(len(names)))
    ax.set_yticklabels(names)
    ax.set_xlabel('Expected Damage Contribution', fontsize=11)
    ax.set_title('Team Damage Contribution by Member', fontsize=12, fontweight='bold', pad=20)
    
    # Add damage values and percentages on bars
    for i, (bar, damage, pct) in enumerate(zip(bars, damages, percentages)):
        width = bar.get_width()
        ax.text(width + max(damages) * 0.01, bar.get_y() + bar.get_height()/2,
                f'{format_damage(damage)} ({pct:.1f}%)',
                ha='left', va='center', fontsize=9, fontweight='bold')
    
    # Invert y-axis to show highest damage at top
    ax.invert_yaxis()
    
    # Add grid for better readability
    ax.grid(axis='x', alpha=0.3, linestyle='--')
    
    # Adjust layout to prevent label cutoff
    plt.tight_layout()
    
    # Convert plot to base64 string
    buffer = BytesIO()
    fig.savefig(buffer, format='png', dpi=150, bbox_inches='tight')
    buffer.seek(0)
    image_base64 = base64.b64encode(buffer.getvalue()).decode()
    plt.close(fig)
    
    return image_base64, damage_data


def plot_crit_distribution_html(sequence, team_buffs, support_bonus=None):
    """
    Generate crit distribution plot as HTML base64 string.
    Returns tuple of (base64_image, stats_dict)
    """
    # Use config support_bonus if not provided
    if support_bonus is None:
        support_bonus = config.support_bonus
    fracs, full_dmg, crit_rate = simulate_crit_distribution(sequence, team_buffs, support_bonus=support_bonus)

    if len(fracs) == 0:
        return None, {}

    pct = fracs * 100  # express as percentages

    fig, ax = plt.subplots(figsize=(9, 5))
    ax.hist(pct, bins=80, color="#4a90d9", edgecolor="white", linewidth=0.3, alpha=0.85, density=True)

    thresholds = [70, 80, 90]
    colours    = ["#e74c3c", "#e67e22", "#2ecc71"]
    for thresh, col in zip(thresholds, colours):
        prob = (pct >= thresh).mean() * 100
        dmg_at_thresh = full_dmg * (thresh / 100)
        dmg_str = format_damage(dmg_at_thresh)
        ax.axvline(thresh, color=col, linewidth=1.8, linestyle="--")
        ax.text(thresh + 0.3, ax.get_ylim()[1] * 0.97,
                f"≥{thresh}%\n{prob:.1f}% chance\n{dmg_str} dmg",
                color=col, fontsize=8.5, va="top", fontweight="bold")

    ax.set_xlabel("Damage as % of Full Crit Damage", fontsize=11)
    ax.set_ylabel("Probability Density", fontsize=11)
    ax.set_title(
        f"Crit Damage Distribution  –  Team Crit Rate: {crit_rate*100:.1f}%"
        + (f"  | Max: {format_damage(full_dmg)}"),
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
    
    # Convert plot to base64 string
    buffer = BytesIO()
    fig.savefig(buffer, format='png', dpi=150, bbox_inches='tight')
    buffer.seek(0)
    image_base64 = base64.b64encode(buffer.getvalue()).decode()
    plt.close(fig)
    
    # Calculate stats
    stats = {
        'mean': mean_pct,
        'median': median_pct,
        'p90': (pct>=90).mean()*100,
        'p80': (pct>=80).mean()*100,
        'p70': (pct>=70).mean()*100,
        'full_dmg': full_dmg,
        'p90_dmg': full_dmg * 0.90,
        'p80_dmg': full_dmg * 0.80,
        'p70_dmg': full_dmg * 0.70,
        'crit_rate': crit_rate
    }
    
    return image_base64, stats


def format_crit_summary_html(team, team_buffs):
    """Generate HTML table for crit rate summary."""
    rows, team_total = get_crit_summary(team, team_buffs)
    
    # Build character lookup dict for O(1) access instead of O(n²) search
    char_by_name = {c.name: c for c in team}
    
    html_content = """
    <div class="crit-summary">
        <h3>CRIT RATE SUMMARY</h3>
        <table class="crit-table">
            <thead>
                <tr>
                    <th>Character</th>
                    <th>Crit Rate Contribution</th>
                </tr>
            </thead>
            <tbody>
    """
    
    for name, rate in rows:
        char = char_by_name[name]  # O(1) lookup instead of O(n) search
        temp_cr = char.temp_buffs.get("crit_rate", 0) / 2
        display = f"{rate*100/2:.1f}%  (+{temp_cr*100/2:.1f}% self)" if temp_cr > 0 else f"{rate*100/2:.1f}%"
        if rate > 0 or temp_cr > 0:
            html_content += f"""
                <tr>
                    <td>{name}</td>
                    <td>{display}</td>
                </tr>
            """
    
    html_content += f"""
            </tbody>
            <tfoot>
                <tr class="total-row">
                    <td>TEAM TOTAL (capped at 100%)</td>
                    <td>{team_total*100:.1f}%</td>
                </tr>
            </tfoot>
        </table>
    </div>
    """
    
    return html_content


def generate_html_report(results, data_file_path, output_file=None, support_bonus=None):
    """
    Generate comprehensive HTML report with simulation inputs and outputs.
    
    Args:
        results: List of result dictionaries from optimization
        data_file_path: Path to data.yaml file
        output_file: Optional output file path (auto-generated if None)
    """
    # Use config support_bonus if not provided
    if support_bonus is None:
        support_bonus = config.support_bonus
    if output_file is None:
        timestamp = datetime.now().strftime("%Y%m%d")
        max_damage = results[0]['damage']
        output_file = Path.cwd() / "reports" / f"{format_damage(max_damage)}_{timestamp}.html"
    
    # Load input data and prepare for export
    yaml_base64 = ""
    try:
        with open(data_file_path, 'r', encoding='utf-8') as f:
            yaml_content = f.read()
        yaml_base64 = base64.b64encode(yaml_content.encode('utf-8')).decode('utf-8')
    except Exception as e:
        print(f"Warning: Could not load data.yaml for export: {e}")
    
    # Generate HTML content
    html_content = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>LN Optimization Report - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</title>
    <style>
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            line-height: 1.6;
            margin: 0;
            padding: 20px;
            background-color: #f5f5f5;
            color: #333;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            background: white;
            padding: 30px;
            border-radius: 10px;
            box-shadow: 0 0 20px rgba(0,0,0,0.1);
        }}
        h1 {{
            color: #2c3e50;
            border-bottom: 3px solid #3498db;
            padding-bottom: 10px;
        }}
        h2 {{
            color: #34495e;
            margin-top: 30px;
            border-left: 4px solid #3498db;
            padding-left: 15px;
        }}
        h3 {{
            color: #2980b9;
            margin-top: 25px;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin: 15px 0;
            background: white;
            box-shadow: 0 2px 5px rgba(0,0,0,0.1);
        }}
        th, td {{
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid #ddd;
        }}
        th {{
            background-color: #3498db;
            color: white;
            font-weight: bold;
        }}
        tr:nth-child(even) {{
            background-color: #f8f9fa;
        }}
        .team-result {{
            margin: 30px 0;
            padding: 20px;
            border: 2px solid #ecf0f1;
            border-radius: 8px;
            background: #fafafa;
        }}
        .damage-highlight {{
            font-size: 1.2em;
            font-weight: bold;
            color: #27ae60;
        }}
        .plot-container {{
            text-align: center;
            margin: 20px 0;
            padding: 20px;
            background: white;
            border-radius: 8px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }}
        .plot-container img {{
            max-width: 100%;
            height: auto;
            border-radius: 5px;
        }}
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin: 20px 0;
        }}
        .stat-card {{
            background: #ecf0f1;
            padding: 15px;
            border-radius: 5px;
            text-align: center;
        }}
        .stat-value {{
            font-size: 1.5em;
            font-weight: bold;
            color: #2c3e50;
        }}
        .stat-label {{
            color: #7f8c8d;
            font-size: 0.9em;
        }}
        .crit-table .total-row {{
            background-color: #3498db !important;
            color: white;
            font-weight: bold;
        }}
        .gear-item {{
            margin: 5px 0;
            padding: 8px;
            background: #f8f9fa;
            border-left: 3px solid #3498db;
        }}
        .exclusive-tag {{
            background: #e74c3c;
            color: white;
            padding: 2px 6px;
            border-radius: 3px;
            font-size: 0.8em;
        }}
        .rotation {{
            background: #e8f4f8;
            padding: 10px;
            border-radius: 5px;
            font-family: monospace;
            margin: 10px 0;
        }}
        .export-section {{
            margin: 20px 0;
            padding: 15px;
            background: #f8f9fa;
            border: 1px solid #dee2e6;
            border-radius: 5px;
        }}
        .export-button {{
            background: #28a745;
            color: white;
            padding: 10px 20px;
            border: none;
            border-radius: 5px;
            cursor: pointer;
            font-size: 14px;
            font-weight: bold;
        }}
        .export-button:hover {{
            background: #218838;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>LN Optimization Report</h1>
        <p><strong>Generated:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        
        <div class="export-section">
            <h3>Export Input Data</h3>
            <p>Download the original data.yaml file used for this optimization to recover or modify your saved inputs.</p>
            <button class="export-button" onclick="downloadDataYaml()">
                📥 Download data.yaml
            </button>
        </div>
        
        <h2>Optimization Results</h2>
    """
    
    for idx, result in enumerate(results):
        html_content += f"""
        <div class="team-result">
            <h2>TEAM #{idx+1}</h2>
            <div class="stats-grid">
                <div class="stat-card">
                    <div class="stat-value">{format_damage(result['damage'])}</div>
                    <div class="stat-label">Total Damage</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">{result['chain']:.1f}</div>
                    <div class="stat-label">Chain Count</div>
                </div>
            </div>
            
            <h3>Team Composition</h3>
            <p><strong>Team:</strong> {', '.join(c.name for c in result['team'])}</p>
            <div class="rotation">
                <strong>Rotation:</strong> {' → '.join(c.name for c in result['sequence'])}
            </div>
            
            <h3>Damage Contribution by Team Member</h3>
        """
        
        # Compute team_buffs once and reuse for all operations
        team_buffs = calculate_team_buffs(result['team'])
        
        # Add damage contribution chart
        damage_plot_base64, damage_data = plot_damage_contribution_html(result['sequence'], team_buffs, support_bonus)
        
        if damage_plot_base64:
            html_content += f"""
            <div class="plot-container">
                <img src="data:image/png;base64,{damage_plot_base64}" alt="Damage Contribution Chart">
            </div>
            """
        else:
            html_content += "<p><em>No damage dealers in team – skipping contribution chart</em></p>"
        
        # Add gear assignments
        html_content += "<h3>Gear Assignments (by Base Character)</h3>"
        
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
                    html_content += f"""
                    <div class="gear-item">
                        <strong>{base_name} ({costumes[0].damage_type})</strong>
                    """
                    if len(costumes) > 1:
                        html_content += f"<br><em>Costumes: {costume_names}</em>"
                    
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
                            
                            exclusive_tag = f' <span class="exclusive-tag">EXCLUSIVE</span>' if gear.exclusive_for else ''
                            html_content += f"""
                            <br><strong>[{slot.upper()}]</strong> {gear.name}{exclusive_tag}: {', '.join(stats)}
                            """
                    
                    html_content += "</div>"
        
        # Add crit analysis
        html_content += format_crit_summary_html(result['team'], team_buffs)
        
        # Add plot
        html_content += "<h3>Crit Damage Distribution</h3>"
        plot_base64, plot_stats = plot_crit_distribution_html(result['sequence'], team_buffs, support_bonus)
        
        if plot_base64:
            html_content += f"""
            <div class="plot-container">
                <img src="data:image/png;base64,{plot_base64}" alt="Crit Distribution Plot">
            </div>
            """
            
            if plot_stats:
                html_content += f"""
                <div class="stats-grid">
                    <div class="stat-card">
                        <div class="stat-value">{format_damage(plot_stats['full_dmg'] * plot_stats['mean'] / 100)}</div>
                        <div class="stat-label">Mean Damage</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-value">{format_damage(plot_stats['full_dmg'] * plot_stats['median'] / 100)}</div>
                        <div class="stat-label">Median Damage</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-value">{format_damage(plot_stats['full_dmg'])}</div>
                        <div class="stat-label">Full Damage</div>
                    </div>
                </div>
                """
        else:
            html_content += "<p><em>No attackers in sequence – skipping distribution plot</em></p>"
        
        html_content += "</div>"
    
    html_content += f"""
    </div>
    
    <script>
        function downloadDataYaml() {{
            const yamlContent = atob('{yaml_base64}');
            const blob = new Blob([yamlContent], {{ type: 'text/yaml;charset=utf-8' }});
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = 'data.yaml';
            document.body.appendChild(a);
            a.click();
            window.URL.revokeObjectURL(url);
            document.body.removeChild(a);
        }}
    </script>
</body>
</html>
    """
    
    # Write HTML file
    try:
        # Ensure reports directory exists
        output_file.parent.mkdir(parents=True, exist_ok=True)
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(html_content)
        print(f"HTML report generated: {output_file}")
        return output_file
    except Exception as e:
        print(f"Error writing HTML report: {e}")
        return None