from math import floor, comb
from copy import deepcopy
import heapq
import numpy as np
from functools import lru_cache
import hashlib
import time
from utils import determine_prefilter_k, get_unique_base_characters, organize_gear_by_slot, calculate_damage_stats, calculate_crit_multiplier, initialize_gear_assignment, get_eligible_gear_for_character, get_attackers_and_buffers, calculate_chain_multiplier, calculate_team_buffs
import random

# Global cache for damage evaluations
_damage_cache = {}
_gear_eligibility_cache = {}
_character_stats_cache = {}

def clear_caches():
    """Clear all optimization caches."""
    global _damage_cache, _gear_eligibility_cache, _character_stats_cache
    _damage_cache.clear()
    _gear_eligibility_cache.clear()
    _character_stats_cache.clear()

def get_assignment_hash(gear_assignments):
    """Generate a hash key for gear assignments."""
    # Create a deterministic string representation
    items = []
    for base_name in sorted(gear_assignments.keys()):
        for slot in sorted(gear_assignments[base_name].keys()):
            gear = gear_assignments[base_name][slot]
            if gear is not None:
                items.append(f"{base_name}:{slot}:{gear.name}")
    
    return hashlib.md5('|'.join(items).encode()).hexdigest()

@lru_cache(maxsize=1000)
def cached_calculate_damage_stats(char_name, char_atk, char_damage_type, char_ratio, team_buffs_tuple):
    """Cached version of calculate_damage_stats."""
    # Convert tuple back to dict for calculation
    team_buffs = dict(team_buffs_tuple)
    
    if char_damage_type == "Max HP":
        atk = 50000
        damage_type_buff = 1
    elif char_damage_type == "MATK":
        atk = char_atk
        damage_type_buff = team_buffs.get('MATK%', 1) * 1.0  # Simplified temp_buffs
    else:  # ATK
        atk = char_atk
        damage_type_buff = team_buffs.get('ATK%', 1) * 1.0  # Simplified temp_buffs
    
    ratio = char_ratio
    # Skip special character case for simplicity in caching
    
    return atk, damage_type_buff, ratio

@lru_cache(maxsize=1000)
def cached_calculate_crit_multiplier(char_crit_dmg, team_crit_dmg_tuple):
    """Cached version of calculate_crit_multiplier."""
    team_crit_dmg = {'crit_dmg': team_crit_dmg_tuple[0]}  # Extract crit_dmg value
    return char_crit_dmg + team_crit_dmg.get('crit_dmg', 0)

def precompute_gear_eligibility(gear_pool, base_characters):
    """Precompute which gear can be equipped to which characters."""
    key = (len(gear_pool), tuple(sorted(base_characters.keys())))
    if key in _gear_eligibility_cache:
        return _gear_eligibility_cache[key]
    
    eligibility = {}
    for gear in gear_pool:
        eligibility[gear.name] = set()
        for base_name in base_characters.keys():
            if gear.can_equip_to(base_name):
                eligibility[gear.name].add(base_name)
    
    _gear_eligibility_cache[key] = eligibility
    return eligibility

def calculate_single_hit(char, team_buffs):
    """Calculates the damage of a single hit including all buffs and chain count."""
    # Use cached calculations
    char_key = (char.name, char.atk, char.damage_type, char.ratio_per_hit)
    buffs_key = tuple(sorted(team_buffs.items()))
    
    atk, damage_type_buff, ratio = cached_calculate_damage_stats(
        char.name, char.atk, char.damage_type, char.ratio_per_hit, buffs_key
    )
    
    crit_key = (team_buffs.get('crit_dmg', 0),)  # Just pass the crit_dmg value
    crit_mult = cached_calculate_crit_multiplier(char.crit_dmg, crit_key)
    
    total_single_hit = round(damage_type_buff * atk) * crit_mult * (team_buffs.get('overall', 1)) * ratio
    
    return floor(total_single_hit)

def calculate_actual_damage(sequence, current_team_buffs):
    """Calculates the total damage of a sequence."""
    if not sequence:
        return 0, 0
    
    # Vectorized per-character calculations
    char_data = []
    for char in sequence:
        single_hit = calculate_single_hit(char, current_team_buffs)
        chain_mult = calculate_chain_multiplier(current_team_buffs, char.temp_buffs)
        char_data.append((char.hits, single_hit, chain_mult))
    
    # Vectorized batch processing
    hits, single_hits, chain_mults = zip(*char_data)
    hits = np.array(hits)
    single_hits = np.array(single_hits)
    chain_mults = np.array(chain_mults)
    
    # Use NumPy for cumulative operations
    total_damage = 0
    current_chain = 0
    
    for i in range(len(sequence)):
        # Vectorized damage for all hits of this character
        char_hits = hits[i]
        if char_hits > 0:
            hit_chains = current_chain + np.arange(char_hits) * chain_mults[i]
            chain_bonuses = hit_chains * 0.1 + 1
            char_damage = (single_hits[i] * chain_bonuses).sum()
            total_damage += char_damage
            current_chain += char_hits * chain_mults[i]
    
    return total_damage, current_chain

def evaluate_team_with_gear(team, gear_assignments, force_best_rotation=False):
    """Assigns gear to characters and calculates the total damage."""
    # Check cache first
    assignment_hash = get_assignment_hash(gear_assignments)
    cache_key = (assignment_hash, force_best_rotation)
    
    if cache_key in _damage_cache:
        return _damage_cache[cache_key]
    
    # Create copies of characters and equip gear
    team_with_gear = []
    for char in team:
        char_copy = char.copy()
        char_copy.unequip_all_gear()
        
        # Get base character name to look up gear
        base_name = char.get_base_character()
        
        if base_name in gear_assignments:
            for slot, gear in gear_assignments[base_name].items():
                if gear is not None:
                    char_copy.equipped_gear[slot] = gear
            char_copy._recalculate_stats()
        team_with_gear.append(char_copy)
    
    # Calculate damage
    team_buffs = calculate_team_buffs(team_with_gear)
    buffers, attackers = get_attackers_and_buffers(team_with_gear)
    
    sequence = rotation_optimizer(team_buffs, attackers)
    
    full_sequence = buffers + sequence
    damage, chain = calculate_actual_damage(full_sequence, team_buffs)
    
    result = (damage, chain, full_sequence)
    _damage_cache[cache_key] = result
    return result

def beam_search_gear_optimization(team, gear_pool, beam_width=100, depth_limit=None, 
                                           prefilter_top_k=5):
    """
    Search across all gear assignments to maximize damage.

    beam_width: Number of assignments to keep in memory at each step.
    depth_limit: Maximum number of characters to assign gear to.
    prefilter_top_k: Number of top gear items to consider for each slot.
    """
    # Filter out buffer characters
    attackers = [c for c in team if c.hits > 0]
    
    # Get unique base characters
    base_characters = get_unique_base_characters(team)
    unique_bases = list(base_characters.values())

    # Pre-assign exclusive gear
    initial_assignment, remaining_gear = apply_exclusive_gear(team, gear_pool)
    
    # Precompute gear eligibility for faster lookups
    eligibility = precompute_gear_eligibility(remaining_gear, base_characters)
    
    if prefilter_top_k > 0:
        filtered_remaining = prefilter_gear_for_team(
            team, remaining_gear, eligibility,
            top_k_per_slot=prefilter_top_k,
            baseline_assignment=initial_assignment,
        )
    else:
        filtered_remaining = remaining_gear
    
    gear_by_slot = organize_gear_by_slot(filtered_remaining)
    slots = list(gear_by_slot.keys()) if gear_by_slot else []
    
    # Evaluate initial damage
    initial_damage, _, _ = evaluate_team_with_gear(team, initial_assignment)
    
    # Priority queue: (negative_damage, counter, assignment, used_gear_set)
    counter = 0
    beam = [(-initial_damage, counter, initial_assignment, frozenset())]
    counter += 1
    
    print(f"  Starting beam search with {len(unique_bases)} unique base characters...")
    print(f"  Remaining gear pool: {len(remaining_gear)} pieces")
    
    if not remaining_gear:
        print(f"  All gear is exclusive - no optimization needed!")
        return initial_assignment, initial_damage
    
    iteration = 0
    max_iterations = depth_limit if depth_limit else len(remaining_gear)
    
    best_ever = (-initial_damage, initial_assignment)
    
    while beam and iteration < max_iterations:
        iteration += 1
        next_beam = []
        
        # Expand each state in the beam
        for neg_damage, _, assignment, used_gear in beam:
            current_damage = -neg_damage
            
            # Track best
            if current_damage > -best_ever[0]:
                best_ever = (neg_damage, shallow_copy_assignment(assignment))
            
            # Try assigning each unused gear to each BASE character
            for slot in slots:
                if slot not in gear_by_slot:
                    continue
                    
                for gear in gear_by_slot[slot]:
                    # Skip if gear already used
                    if gear in used_gear:
                        continue
                    
                    # Use precomputed eligibility
                    eligible_chars = eligibility.get(gear.name, set())
                    
                    # Try assigning to each eligible base character
                    for base_char in unique_bases:
                        base_name = base_char.get_base_character()
                        
                        if base_name not in eligible_chars:
                            continue
                        
                        # Skip if this base character already has this slot filled
                        if assignment[base_name][slot] is not None:
                            continue
                        
                        # Create new assignment with shallow copy
                        new_assignment = shallow_copy_assignment(assignment)
                        new_assignment[base_name][slot] = gear
                        new_used_gear = used_gear | {gear}
                        
                        # Evaluate with caching
                        new_damage, _, _ = evaluate_team_with_gear(team, new_assignment)
                        
                        # Add to next beam
                        heapq.heappush(next_beam, (-new_damage, counter, new_assignment, new_used_gear))
                        counter += 1
        
        # Keep only top beam_width candidates
        beam = heapq.nsmallest(beam_width, next_beam)
        
        if iteration % 5 == 0 and beam:
            best_in_beam = -beam[0][0]
            print(f"  Iteration {iteration}/{max_iterations}: Best = {best_in_beam:,.0f}")
    
    best_damage = -best_ever[0]
    best_assignment = best_ever[1]
    
    return best_assignment, best_damage

def shallow_copy_assignment(assignment):
    """Create a shallow copy of assignment dict (much faster than deepcopy)."""
    new_assignment = {}
    for base_name, slots_dict in assignment.items():
        new_assignment[base_name] = dict(slots_dict)  # Shallow copy of inner dict
    return new_assignment

def prefilter_gear_for_team(team, remaining_gear, eligibility, top_k_per_slot,
                                     baseline_assignment=None):
    """
    Uses stat_value_for_character to give top candidates for gear for each slot.
    """
    base_characters = get_unique_base_characters(team)
    unique_bases = list(base_characters.values())

    gear_by_slot = organize_gear_by_slot(remaining_gear)
    gear_to_keep = set()

    # Main filter: top-k by heuristic
    for slot, gears in gear_by_slot.items():
        for char in unique_bases:
            base_name = char.get_base_character()
            
            # Use precomputed eligibility
            eligible = [g for g in gears if base_name in eligibility.get(g.name, set())]
            eligible.sort(key=lambda g: g.stat_value_for_character(char), reverse=True)
            
            for g in eligible[:top_k_per_slot]:
                gear_to_keep.add(g)

    # Floor guarantee: real damage delta for uncovered pairs (simplified)
    if baseline_assignment is not None:
        baseline_dmg, _, _ = evaluate_team_with_gear(team, baseline_assignment)
        
        for char in unique_bases:
            base_name = char.get_base_character()
            for slot, gears in gear_by_slot.items():
                eligible = [g for g in gears if base_name in eligibility.get(g.name, set())]

                # Only act if this char×slot has zero survivors in the filtered set
                if not eligible or any(g in gear_to_keep for g in eligible):
                    continue

                # Trial-equip each candidate and measure real damage delta
                best_gear, best_delta = None, -float("inf")
                for gear in eligible:
                    trial = shallow_copy_assignment(baseline_assignment)
                    trial[base_name][slot] = gear
                    trial_dmg, _, _ = evaluate_team_with_gear(team, trial)
                    delta = trial_dmg - baseline_dmg
                    if delta > best_delta:
                        best_delta, best_gear = delta, gear

                if best_gear is not None:
                    gear_to_keep.add(best_gear)

    return list(gear_to_keep)

def greedy_gear_assignment(team, gear_pool, prefilter_top_k=5):
    """
    Assigns gear to a team using a greedy algorithm based on the
    stat_value_for_character method.
    """
    assignment, remaining_gear = apply_exclusive_gear(team, gear_pool)
    
    # Precompute gear eligibility for faster lookups
    base_characters = get_unique_base_characters(team)
    eligibility = precompute_gear_eligibility(remaining_gear, base_characters)
    
    if prefilter_top_k > 0:
        filtered_remaining = prefilter_gear_for_team(
            team, remaining_gear, eligibility,
            top_k_per_slot=prefilter_top_k,
            baseline_assignment=assignment,
        )
    else:
        filtered_remaining = remaining_gear
    
    gear_by_slot = organize_gear_by_slot(filtered_remaining)
    slots = list(gear_by_slot.keys())
    attackers = [c for c in team if c.hits > 0]
    
    # Get unique base characters
    unique_bases = list(base_characters.values())
    
    # Pre-evaluate gear value for each BASE character
    gear_values = {}
    for base_char in unique_bases:
        base_name = base_char.get_base_character()
        gear_values[base_name] = {}
        for slot in slots:
            gear_values[base_name][slot] = []
            if slot in gear_by_slot:
                for gear in gear_by_slot[slot]:
                    # Use precomputed eligibility
                    if base_name in eligibility.get(gear.name, set()):
                        value = gear.stat_value_for_character(base_char)
                        gear_values[base_name][slot].append((value, gear))
                # Sort by value descending
                gear_values[base_name][slot].sort(key=lambda x: x[0], reverse=True)
    
    used_gear = set()
    
    # Assign gear slot by slot, prioritizing high-value assignments
    for slot in slots:
        # Get all (base_char, gear, value) tuples for this slot
        candidates = []
        for base_char in unique_bases:
            base_name = base_char.get_base_character()
            if slot in gear_values[base_name]:
                for value, gear in gear_values[base_name][slot]:
                    if gear not in used_gear:
                        candidates.append((value, base_name, gear))
        
        # Sort by value and assign greedily
        candidates.sort(key=lambda x: x[0], reverse=True)
        
        for value, base_name, gear in candidates:
            if gear not in used_gear and assignment[base_name][slot] is None:
                assignment[base_name][slot] = gear
                used_gear.add(gear)
    
    # Evaluate final damage
    damage, _, _ = evaluate_team_with_gear(team, assignment)
    
    return assignment, damage

def optimize_team_with_beam_search(roster, gear_pool, team_size=20, 
                                            beam_width=200, num_teams_to_optimize=5,
                                            fixed_core=None):
    """
    Two-step optimization process:
    1. Randomly sample teams and use greedy gear assignment to rank them
    2. Get top teams (num_teams_to_optimize) and assign gear using beam search

    num_teams_to_optimize: Number of top teams to keep for beam search
    beam_width: Number of teams to keep in beam search
    fixed_core: List of characters that are auto-includes (usually OM Liberta, Bride Refi, Shrine Granadair)
    """
    # Calculate optimal sample_size based on total combinations
    if fixed_core:
        available_count = len(roster) - len(fixed_core)
        slots_to_fill = team_size - len(fixed_core)
        total_combinations = comb(available_count, slots_to_fill)
    else:
        total_combinations = comb(len(roster), team_size)
    
    sample_size = max(100, min(int(total_combinations * 0.2), 100000))
    
    print(f"  Total possible teams: {total_combinations:,}")
    print(f"  Sample size (20% of combinations): {sample_size:,}")
    
    # Determine pre-filtering aggressiveness based on gear pool size
    prefilter_k = determine_prefilter_k(len(gear_pool))
    
    # If there's a fixed core, adjust roster and team_size for sampling
    if fixed_core:
        available_roster = [c for c in roster if c not in fixed_core]
        slots_to_fill = team_size - len(fixed_core)
        print(f"  Fixed core: {', '.join(c.name for c in fixed_core)}")
        print(f"  Filling {slots_to_fill} remaining slots from {len(available_roster)} characters")
    else:
        available_roster = roster
        slots_to_fill = team_size
    
    print(" Stage 1: Finding promising teams...")
    
    # Sample random teams
    quick_results = []
    
    for i in range(sample_size):
        # Sample remaining slots
        remaining_chars = random.sample(available_roster, slots_to_fill)
        
        # Combine with fixed core if present
        if fixed_core:
            team = fixed_core + remaining_chars
        else:
            team = remaining_chars
        
        assignment, damage = greedy_gear_assignment(team, gear_pool, prefilter_top_k=prefilter_k)
        quick_results.append((damage, team))
        
        if (i + 1) % 500 == 0:
            print(f"  Sampled {i + 1}/{sample_size} teams...")
    
    # Sort and keep top teams
    quick_results.sort(reverse=True, key=lambda x: x[0])
    top_teams = [team for _, team in quick_results[:num_teams_to_optimize]]
    
    print(f"\n  Stage 2: Beam search optimization for top {num_teams_to_optimize} teams...\n")
    
    final_results = []
    
    for idx, team in enumerate(top_teams):
        print(f"Team {idx + 1}/{num_teams_to_optimize}:")
        
        # Use beam search to find best gear assignment for each team
        best_assignment, best_damage = beam_search_gear_optimization(
            team, gear_pool, beam_width=beam_width, prefilter_top_k=prefilter_k
        )
        
        # Get final sequence with BEST rotation
        print(f"  Optimizing final rotation...")
        damage, chain, sequence = evaluate_team_with_gear(team, best_assignment, force_best_rotation=True)
        
        final_results.append({
            'team': team,
            'sequence': sequence,
            'gear_assignment': best_assignment,
            'damage': damage,
            'chain': chain
        })
        
        print(f"  Final damage: {damage:,.0f}\n")
    
    return final_results

def _hits_data(sequence, team_buffs):
    """Helper function to get (crit_damage, non_crit_damage, crit_rate) for each hit"""
    if not sequence:
        return []
    
    # Pre-allocate arrays for all hits
    total_hits = sum(char.hits for char in sequence)
    crit_damage_arr = np.zeros(total_hits, dtype=np.float64)
    non_crit_damage_arr = np.zeros(total_hits, dtype=np.float64)
    crit_rate_arr = np.zeros(total_hits, dtype=np.float64)
    
    # Extract character data into arrays
    char_data = []
    hit_indices = []
    current_idx = 0
    
    team_crit_rate = min(team_buffs.get("crit_rate", 0), 1.0)
    overall_buff = team_buffs.get("overall", 1)
    
    for char in sequence:
        # Per-character effective rate: team base + personal temp buff (halved)
        char_crit_rate = min(
            team_crit_rate + char.temp_buffs.get("crit_rate", 0) / 2,
            1.0
        )
        
        chain_mult = calculate_chain_multiplier(team_buffs, char.temp_buffs)
        
        # Calculate character-specific damage stats
        atk, dtb, ratio = calculate_damage_stats(char, team_buffs)
        crit_mult = calculate_crit_multiplier(char, team_buffs)
        
        # Store character data for vectorized processing
        char_data.append({
            'atk': atk,
            'dtb': dtb,
            'ratio': ratio,
            'crit_mult': crit_mult,
            'crit_rate': char_crit_rate,
            'chain_mult': chain_mult,
            'hits': char.hits
        })
        
        hit_indices.append((current_idx, current_idx + char.hits))
        current_idx += char.hits
    
    # Vectorized calculation for all hits
    current_chain = 0
    for i, (start_idx, end_idx) in enumerate(hit_indices):
        data = char_data[i]
        num_hits = end_idx - start_idx
        
        # Create chain bonus array for this character's hits
        hit_numbers = np.arange(num_hits) + current_chain
        chain_bonuses = hit_numbers * 0.1 + 1
        
        # Vectorized damage calculations
        base_damage = np.floor(np.round(data['dtb'] * data['atk']) * overall_buff * data['ratio'] * chain_bonuses)
        crit_damage = np.floor(np.round(data['dtb'] * data['atk']) * data['crit_mult'] * overall_buff * data['ratio'] * chain_bonuses)
        
        # Assign to result arrays
        crit_damage_arr[start_idx:end_idx] = crit_damage
        non_crit_damage_arr[start_idx:end_idx] = base_damage
        crit_rate_arr[start_idx:end_idx] = data['crit_rate']
        
        # Update chain count
        current_chain += num_hits * data['chain_mult']
    
    # Convert back to list of tuples for compatibility
    return [(crit_damage_arr[i], non_crit_damage_arr[i], crit_rate_arr[i]) for i in range(total_hits)]

def simulate_crit_distribution(sequence, team_buffs, n_simulations=60_000):
    hdata = _hits_data(sequence, team_buffs)
    if not hdata:
        return np.array([]), 0, min(team_buffs.get("crit_rate", 0), 1.0)

    crit_arr     = np.array([h[0] for h in hdata], dtype=np.float64)
    non_crit_arr = np.array([h[1] for h in hdata], dtype=np.float64)
    rate_arr     = np.array([h[2] for h in hdata], dtype=np.float64)
    full_damage  = int(crit_arr.sum())

    rolls = np.random.random((n_simulations, len(hdata)))
    crits = rolls < rate_arr
    totals = (crits * crit_arr + ~crits * non_crit_arr).sum(axis=1)
    fractions = totals / full_damage

    team_crit_rate = min(team_buffs.get("crit_rate", 0), 1.0)
    return fractions, full_damage, team_crit_rate

def rotation_optimizer(current_buffs, team):
    """
    Optimized rotation algorithm based on key insight:
    
    HIGH DAMAGE-PER-HIT characters should go LATE to benefit from chain.
    LOW DAMAGE-PER-HIT characters should go EARLY to build chain.
    
    This is because total damage = sum of (damage_per_hit × chain_multiplier).
    The character with highest damage_per_hit benefits most from high chain.
    
    Strategy:
    1. Calculate damage per hit for each character using vectorized operations
    2. Sort by damage per hit (ascending)
    3. Low damage/hit first (chain builders), high damage/hit last (chain users)
    """
    if not team:
        return []
    
    # Extract character attributes using list comprehensions
    char_names = [char for char in team]
    char_hits = [char.hits for char in team]
    char_atks = [char.atk for char in team]
    char_damage_types = [char.damage_type for char in team]
    char_ratios = [char.ratio_per_hit for char in team]
    
    # Convert to NumPy arrays
    hits_arr = np.array(char_hits, dtype=np.int64)
    
    # Precompute team buffs for vectorized access
    buffs_key = tuple(sorted(current_buffs.items()))
    crit_key = (current_buffs.get('crit_dmg', 0),)
    
    # Vectorized damage calculation using list comprehension with caching
    damage_per_hit = []
    total_damage_potential = []
    
    for char, char_atk, char_damage_type, char_ratio in zip(char_names, char_atks, char_damage_types, char_ratios):
        # Use cached calculations for each character
        atk, damage_type_buff, ratio = cached_calculate_damage_stats(
            char.name, char_atk, char_damage_type, char_ratio, buffs_key
        )
        crit_mult = cached_calculate_crit_multiplier(char.crit_dmg, crit_key)
        
        single_hit = round(damage_type_buff * atk) * crit_mult * (current_buffs.get('overall', 1)) * ratio
        per_hit = floor(single_hit)
        damage_per_hit.append(per_hit)
        total_damage_potential.append(per_hit * char.hits)
    
    # Build priority list using conditional expression
    char_priorities = list(zip(damage_per_hit, total_damage_potential, char_names))
    
    # Sort by damage per hit (ascending): low damage/hit first, high damage/hit last
    # Tiebreaker: if same damage/hit, prefer higher total damage potential last
    char_priorities.sort(key=lambda x: (x[0], x[1]))
    
    # Return sorted sequence using list comprehension
    return [char for _, _, char in char_priorities]

def apply_exclusive_gear(team, gear_pool):
    """
    Pre-assign exclusive gear to their designated characters.
    
    Returns:
        initial_assignment: Dict with exclusive gear already assigned
        remaining_gear: List of non-exclusive gear still to be assigned
    """
    # Get unique base characters in team
    base_characters = get_unique_base_characters(team)
    
    # Organize gear by slot
    gear_by_slot = organize_gear_by_slot(gear_pool)
    
    slots = list(gear_by_slot.keys())
    
    # Initialize empty assignment
    initial_assignment = initialize_gear_assignment(base_characters, slots)
    
    # Track which gear is still available
    remaining_gear = []
    exclusive_count = 0
    
    # Assign exclusive gear automatically
    for gear in gear_pool:
        if gear.exclusive_for is not None:
            # This gear is exclusive to a specific character
            if gear.exclusive_for in initial_assignment:
                # Character is in the team, assign the gear
                base_name = gear.exclusive_for
                slot = gear.slot
                
                if initial_assignment[base_name][slot] is None:
                    initial_assignment[base_name][slot] = gear
                    exclusive_count += 1
                else:
                    # Slot already filled by another exclusive gear
                    print(f"  ⚠️  Warning: {base_name} has multiple exclusive {slot}s, keeping first one")
            # If character not in team, exclusive gear is ignored (not added to remaining)
        else:
            # Non-exclusive gear goes into the pool for optimization
            remaining_gear.append(gear)
    
    return initial_assignment, remaining_gear
