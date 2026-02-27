import yaml
from pathlib import Path

from gear import Gear
from character import Character
from sim import optimize_team_with_beam_search, beam_search_gear_optimization, evaluate_team_with_gear
from visualization import print_results
from data.data import _load_data
from utils import determine_prefilter_k

# Load data — path is relative to this script's location
_DATA_FILE = Path.cwd() / "data" / "data.yaml"
roster, gear_pool = _load_data(_DATA_FILE)

# # --- EXECUTION ---

print("=" * 70)
print("TEAM + GEAR OPTIMIZATION")
print("=" * 70)
print("\nChoose optimization mode:")
print("1. FIXED TEAM: Optimize gear for a predetermined team (fast)")
print("2. BEAM SEARCH: Optimize both team and gear (recommended)")
print("=" * 70)

mode = input("\nEnter choice (1/2): ").strip()

if mode == "1":
    print("\n📋 Optimizing gear for fixed team...")
    print("   (Edit 'fixed_team' variable in code to customize)\n")
    
    # Use a subset as fixed team - CUSTOMIZE THIS!
    fixed_team = roster[:20]
    
    print(f"Team: {', '.join(c.name for c in fixed_team)}\n")
    
    print("Method: Beam Search with Gear Pre-filtering")
    prefilter_k = determine_prefilter_k(len(gear_pool))
    
    best_assignment, best_damage = beam_search_gear_optimization(
        fixed_team, gear_pool, beam_width=200, prefilter_top_k=prefilter_k
    )
    
    # Get final sequence with BEST rotation (force hill climbing)
    print("  Optimizing final rotation...")
    _, chain, sequence = evaluate_team_with_gear(fixed_team, best_assignment, force_best_rotation=True)
    
    print("\n" + "=" * 70)
    print("RESULTS")
    print("=" * 70)
    print_results([{'team': fixed_team, 
               'sequence': sequence,
               'gear_assignment': best_assignment,
               'damage': best_damage,
               'chain': chain}])

elif mode == "2":
    print("\n🚀 Running full beam search optimization...\n")
    
    # Define core characters that are almost always optimal
    core_character_names = ["OM Liberta", "Bride Rafi", "Shrine Granadair"]
    fixed_core = [c for c in roster if c.name in core_character_names]
    
    if len(fixed_core) < len(core_character_names):
        missing = set(core_character_names) - {c.name for c in fixed_core}
        print(f"⚠️  Warning: Core characters not found in roster: {missing}")
    
    results = optimize_team_with_beam_search(
        roster, gear_pool,
        team_size=20,
        beam_width=200,
        fixed_core=fixed_core
    )
    
    print("\n" + "=" * 70)
    print("TOP RESULTS")
    print("=" * 70)
    
    print_results(results)
else:
    print("Invalid choice!")