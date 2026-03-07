import yaml
from pathlib import Path

import config
from gear import Gear
from character.character import Character
from sim import (
    optimize_team_with_beam_search, 
    adaptive_gear_assignment,
    evaluate_team_with_gear,
    optimize_for_threshold
)
from visualization import print_results, generate_html_report
from data.data import _load_data
from utils import determine_prefilter_k

# Load data — path is relative to this script's location
_DATA_FILE = Path.cwd() / "data" / "data.yaml"

# Check for support bonus in data.yaml
with open(_DATA_FILE, 'r', encoding='utf-8') as f:
    data_content = yaml.safe_load(f)

support_bonus = data_content.get('support_bonus', None)
nh_nebris_ratio_multiplier = data_content.get('nh_nebris_ratio_multiplier', None)
if support_bonus is None:
    print("\n" + "=" * 70)
    print("SUPPORT BONUS CONFIGURATION")
    print("=" * 70)
    print("Support bonus is a global multiplier on all damage/hits.")
    print("Enter either a percentage (100-1500%) or a decimal (1-15)")
    print("=" * 70)
    
    while True:
        user_input = input("\nEnter support bonus: ").strip()
        
        # Try to parse as percentage first (ends with % or > 15)
        if user_input.endswith('%'):
            try:
                percent_value = float(user_input.rstrip('%'))
                if 100 <= percent_value <= 1500:
                    support_bonus = percent_value / 100
                    break
                else:
                    print("Percentage must be between 100% and 1500%")
            except ValueError:
                print("Invalid percentage format")
        else:
            try:
                decimal_value = float(user_input)
                if 1 <= decimal_value <= 15:
                    support_bonus = decimal_value
                    break
                else:
                    print("Decimal must be between 1 and 15")
            except ValueError:
                print("Invalid decimal format")
    
    # Add support bonus to data.yaml while preserving comments
    with open(_DATA_FILE, 'r', encoding='utf-8') as f:
        yaml_lines = f.readlines()
    
    # Check if support_bonus already exists
    support_bonus_exists = False
    fallback_used = False
    
    for i, line in enumerate(yaml_lines):
        if line.strip().startswith('support_bonus:'):
            # Update existing support_bonus line
            yaml_lines[i] = f"support_bonus: {support_bonus}\n"
            support_bonus_exists = True
            break
    
    if not support_bonus_exists:
        # Find where to insert the support bonus (after the header comments, before roster)
        insert_line = None
        for i, line in enumerate(yaml_lines):
            if line.strip().startswith('roster:'):
                insert_line = i
                break
        
        if insert_line is not None:
            # Insert support bonus before roster with proper formatting
            yaml_lines.insert(insert_line, f"support_bonus: {support_bonus}\n")
            yaml_lines.insert(insert_line, "\n")  # Add blank line before
        else:
            # Fallback: use the original method if we can't find the right place
            data_content['support_bonus'] = support_bonus
            with open(_DATA_FILE, 'w', encoding='utf-8') as f:
                yaml.dump(data_content, f, default_flow_style=False, sort_keys=False)
            print(f"\nSupport bonus set to {support_bonus:.2f}x and saved to data.yaml")
            # Skip the rest of the preservation logic since we used fallback
            fallback_used = True
    
    if not fallback_used:
        # Write back to file preserving all formatting
        with open(_DATA_FILE, 'w', encoding='utf-8') as f:
            f.writelines(yaml_lines)
    
    print(f"\nSupport bonus set to {support_bonus:.2f}x and saved to data.yaml")

roster, gear_pool, support_bonus = _load_data(_DATA_FILE)

# Set global values in config
config.set_support_bonus(support_bonus)
if nh_nebris_ratio_multiplier is not None:
    config.set_nh_nebris_ratio_multiplier(nh_nebris_ratio_multiplier)

# Display current support bonus
print(f"\nCurrent support bonus: {support_bonus:.2f}x ({(support_bonus*100+100):.0f}% increase)")

# # --- EXECUTION ---

print("=" * 70)
print("TEAM + GEAR OPTIMIZATION")
print("=" * 70)
print("\nChoose optimization mode:")
print("1. FIXED TEAM: Optimize gear for a predetermined team (fast)")
print("2. FULL OPTIMIZATION: Optimize both team and gear (recommended)")
print("3. THRESHOLD OPTIMIZATION: Maximize probability to exceed damage target")
print("4. UPDATE SUPPORT BONUS: Change the global damage multiplier")
print("=" * 70)

mode = input("\nEnter choice (1/2/3/4): ").strip()

if mode == "1":
    print("\n📋 Optimizing gear for fixed team...")
    print("   (Edit 'fixed_team' variable in code to customize)\n")
    
    # Use a subset as fixed team - CUSTOMIZE THIS!
    fixed_team = roster[:20]
    
    print(f"Team: {', '.join(c.name for c in fixed_team)}\n")
    
    prefilter_k = determine_prefilter_k(len(gear_pool))
    
    best_assignment, best_damage = adaptive_gear_assignment(
        fixed_team, gear_pool, prefilter_top_k=prefilter_k,
        max_iterations=500, temperature=100, cooling_rate=0.975
    )
    
    # Get final sequence with BEST rotation (force hill climbing)
    print("  Optimizing final rotation...")
    _, chain, sequence = evaluate_team_with_gear(fixed_team, best_assignment)
    
    print("\n" + "=" * 70)
    print("RESULTS")
    print("=" * 70)
    results = [{'team': fixed_team, 
               'sequence': sequence,
               'gear_assignment': best_assignment,
               'damage': best_damage,
               'chain': chain}]
    
    print_results(results)
    
    # Generate HTML report
    print("\n" + "=" * 70)
    print("GENERATING HTML REPORT...")
    print("=" * 70)
    html_file = generate_html_report(results, _DATA_FILE)
    if html_file:
        print(f"HTML report saved to: {html_file}")

elif mode == "2":
    print("\n🚀 Running full team + gear optimization...\n")
    
    print("\nChoose optimization preset:")
    print("1. Fast (quick team search)")
    print("2. Balanced (recommended)")
    print("3. Thorough (best results)")
    
    preset_choice = input("\nEnter choice (1-3): ").strip()
    
    preset_map = {
        "1": "fast",
        "2": "balanced",
        "3": "thorough"
    }
    
    gear_preset = preset_map.get(preset_choice, "fast")
    
    print(f"\nUsing Adaptive SA with {gear_preset} preset")
    
    # Define core characters that are almost always optimal
    core_character_names = ["OM Liberta", "Bride Refithea", "Shrine Granadair"]
    fixed_core = [c for c in roster if c.name in core_character_names]
    
    if len(fixed_core) < len(core_character_names):
        missing = set(core_character_names) - {c.name for c in fixed_core}
        print(f"⚠️  Warning: Core characters not found in roster: {missing}")
    
    results = optimize_team_with_beam_search(
        roster, gear_pool,
        team_size=20,
        beam_width=400,
        fixed_core=fixed_core,
        gear_method="adaptive_sa",
        gear_preset=gear_preset
    )
    
    print("\n" + "=" * 70)
    print("TOP RESULTS")
    print("=" * 70)
    
    print_results(results)
    
    # Generate HTML report
    print("\n" + "=" * 70)
    print("GENERATING HTML REPORT...")
    print("=" * 70)
    html_file = generate_html_report(results, _DATA_FILE)
    if html_file:
        print(f"HTML report saved to: {html_file}")
elif mode == "3":
    print("\n" + "=" * 70)
    print("THRESHOLD OPTIMIZATION")
    print("=" * 70)
    print("This mode optimizes your team to maximize the probability")
    print("of exceeding a specific damage threshold.")
    print("=" * 70)
    
    # Get threshold from user
    while True:
        try:
            threshold_input = input("\nEnter damage threshold in millions (e.g., 40 for 40M): ").strip()
            threshold = float(threshold_input.replace(',', '')) * 1000000  # Convert millions to actual damage
            if threshold > 0:
                break
            else:
                print("Threshold must be greater than 0")
        except ValueError:
            print("Please enter a valid number")
    
    print(f"\n🎯 Target threshold: {threshold:,.0f} damage")
    
    # Choose optimization preset
    print("\nChoose optimization preset:")
    print("1. Fast (quick team search)")
    print("2. Balanced (recommended)")
    print("3. Thorough (best results)")
    
    preset_choice = input("\nEnter choice (1-3): ").strip()
    
    preset_map = {
        "1": "fast",
        "2": "balanced",
        "3": "thorough"
    }
    
    gear_preset = preset_map.get(preset_choice, "fast")
    
    print(f"\nUsing Adaptive SA with {gear_preset} preset")
    
    # Define core characters that are almost always optimal
    core_character_names = ["OM Liberta", "Bride Refithea", "Shrine Granadair"]
    fixed_core = [c for c in roster if c.name in core_character_names]
    
    if len(fixed_core) < len(core_character_names):
        missing = set(core_character_names) - {c.name for c in fixed_core}
        print(f"⚠️  Warning: Core characters not found in roster: {missing}")
    
    # Run threshold optimization
    results = optimize_for_threshold(
        roster, gear_pool, threshold,
        team_size=20,
        beam_width=400,
        fixed_core=fixed_core,
        gear_preset=gear_preset
    )
    
    print("\n" + "=" * 70)
    print("THRESHOLD OPTIMIZATION RESULTS")
    print("=" * 70)
    
    # Custom print function for threshold results
    for idx, result in enumerate(results):
        print(f"\n{'='*70}")
        print(f"TEAM #{idx+1}")
        print(f"{'='*70}")
        print(f"Threshold: {result['threshold']:,.0f} damage")
        print(f"Success Probability: {result['threshold_probability']*100:.2f}%")
        print(f"Expected Damage: {result['damage']:,.0f}")
        print(f"Chain Count: {result['chain']:.1f}")
        print(f"\nTeam: {', '.join(c.name for c in result['team'])}")
        print(f"\nRotation: {' → '.join(c.name for c in result['sequence'])}")
        
        # Show gear assignments (abbreviated)
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
        
        # Show crit rate summary
        from utils import calculate_team_buffs
        from visualization import print_crit_summary
        team_buffs = calculate_team_buffs(result['team'])
        print_crit_summary(result['team'], team_buffs)
    
    # Generate HTML report
    print("\n" + "=" * 70)
    print("GENERATING HTML REPORT...")
    print("=" * 70)
    html_file = generate_html_report(results, _DATA_FILE)
    if html_file:
        print(f"HTML report saved to: {html_file}")
        
elif mode == "4":
    print("\n" + "=" * 70)
    print("UPDATE SUPPORT BONUS")
    print("=" * 70)
    print(f"Current support bonus: {support_bonus:.2f}x ({(support_bonus*100):.0f}% increase)")
    print("Support bonus is a global multiplier on all damage/hits.")
    print("Enter either a percentage (100-1500%) or a decimal (1-15)")
    print("=" * 70)
    
    while True:
        user_input = input(f"\nEnter new support bonus (current: {support_bonus:.2f}): ").strip()
        
        if not user_input:
            print("No change made.")
            break
        
        # Try to parse as percentage first (ends with % or > 15)
        if user_input.endswith('%'):
            try:
                percent_value = float(user_input.rstrip('%'))
                if 100 <= percent_value <= 1500:
                    new_support_bonus = percent_value / 100
                    break
                else:
                    print("Percentage must be between 100% and 1500%")
            except ValueError:
                print("Invalid percentage format")
        else:
            try:
                decimal_value = float(user_input)
                if 1 <= decimal_value <= 15:
                    new_support_bonus = decimal_value
                    break
                else:
                    print("Decimal must be between 1 and 15")
            except ValueError:
                print("Invalid decimal format")
    
    if user_input:  # Only update if user entered something
        # Update support bonus in data.yaml while preserving comments
        with open(_DATA_FILE, 'r', encoding='utf-8') as f:
            yaml_lines = f.readlines()
        
        # Check if support_bonus already exists
        support_bonus_exists = False
        fallback_used = False
        
        for i, line in enumerate(yaml_lines):
            if line.strip().startswith('support_bonus:'):
                # Update existing support_bonus line
                yaml_lines[i] = f"support_bonus: {new_support_bonus}\n"
                support_bonus_exists = True
                break
        
        if not support_bonus_exists:
            # Find where to insert the support bonus (after the header comments, before roster)
            insert_line = None
            for i, line in enumerate(yaml_lines):
                if line.strip().startswith('roster:'):
                    insert_line = i
                    break
            
            if insert_line is not None:
                # Insert support bonus before roster with proper formatting
                yaml_lines.insert(insert_line, f"support_bonus: {new_support_bonus}\n")
                yaml_lines.insert(insert_line, "\n")  # Add blank line before
            else:
                # Fallback: use the original method if we can't find the right place
                data_content = yaml.safe_load(open(_DATA_FILE, 'r', encoding='utf-8'))
                data_content['support_bonus'] = new_support_bonus
                with open(_DATA_FILE, 'w', encoding='utf-8') as f:
                    yaml.dump(data_content, f, default_flow_style=False, sort_keys=False)
                print(f"\nSupport bonus updated to {new_support_bonus:.2f}x and saved to data.yaml")
                # Skip the rest of the preservation logic since we used fallback
                fallback_used = True
        
        if not fallback_used:
            # Write back to file preserving all formatting
            with open(_DATA_FILE, 'w', encoding='utf-8') as f:
                f.writelines(yaml_lines)
        
        print(f"\nSupport bonus updated from {support_bonus:.2f}x to {new_support_bonus:.2f}x and saved to data.yaml")
        
        # Reload data with new support bonus
        roster, gear_pool, support_bonus = _load_data(_DATA_FILE)
        config.set_support_bonus(support_bonus)
        print(f"Current support bonus: {support_bonus:.2f}x ({(support_bonus*100):.0f}% increase)")
else:
    print("Invalid choice!")
