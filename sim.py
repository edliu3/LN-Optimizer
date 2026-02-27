from math import floor, comb
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
                                           prefilter_top_k=5, initial_assignment=None,
                                           iteration_multiplier=1.0):
    """
    Search across all gear assignments to maximize damage.

    beam_width: Number of assignments to keep in memory at each step.
    depth_limit: Maximum number of characters to assign gear to.
    prefilter_top_k: Number of top gear items to consider for each slot.
    initial_assignment: Optional starting assignment from Stage 1 (e.g., greedy/SA result)
    iteration_multiplier: Multiplier for default iteration count (default gear count * multiplier)
    """
    # Filter out buffer characters
    attackers = [c for c in team if c.hits > 0]
    
    # Get unique base characters
    base_characters = get_unique_base_characters(team)
    unique_bases = list(base_characters.values())

    # Pre-assign exclusive gear
    exclusive_assignment, remaining_gear = apply_exclusive_gear(team, gear_pool)
    
    # If we have an initial assignment from Stage 1, merge it with exclusive gear
    if initial_assignment is not None:
        # Start with a copy of the initial assignment
        start_assignment = shallow_copy_assignment(initial_assignment)
        # Ensure exclusive gear is still assigned (Stage 1 might have missed some)
        for base_name, slots in exclusive_assignment.items():
            for slot, gear in slots.items():
                if gear is not None and start_assignment.get(base_name, {}).get(slot) is None:
                    start_assignment[base_name][slot] = gear
        # Calculate which gear is already used in the initial assignment
        used_gear_in_initial = set()
        for base_name, slots in start_assignment.items():
            for slot, gear in slots.items():
                if gear is not None:
                    used_gear_in_initial.add(gear)
        # Remaining gear is everything in the pool not already used
        remaining_gear = [g for g in gear_pool if g not in used_gear_in_initial and g.exclusive_for is None]
        initial_damage, _, _ = evaluate_team_with_gear(team, start_assignment)
        print(f"  Using Stage 1 assignment as starting point (damage: {initial_damage:,.0f})")
    else:
        start_assignment = exclusive_assignment
        initial_damage, _, _ = evaluate_team_with_gear(team, start_assignment)

    # Precompute gear eligibility for faster lookups
    eligibility = precompute_gear_eligibility(remaining_gear, base_characters)
    
    if prefilter_top_k > 0:
        filtered_remaining = prefilter_gear_for_team(
            team, remaining_gear, eligibility,
            top_k_per_slot=prefilter_top_k,
            baseline_assignment=start_assignment,
        )
    else:
        filtered_remaining = remaining_gear
    
    gear_by_slot = organize_gear_by_slot(filtered_remaining)
    slots = list(gear_by_slot.keys()) if gear_by_slot else []
    
    # Evaluate initial damage
    initial_damage, _, _ = evaluate_team_with_gear(team, start_assignment)
    
    # Priority queue: (negative_damage, counter, assignment, used_gear_set)
    counter = 0
    beam = [(-initial_damage, counter, start_assignment, frozenset(used_gear_in_initial if initial_assignment else []))]
    counter += 1
    
    print(f"  Starting beam search with {len(unique_bases)} unique base characters...")
    print(f"  Remaining gear pool: {len(remaining_gear)} pieces")
    
    if not remaining_gear:
        print(f"  All gear is exclusive - no optimization needed!")
        return start_assignment, initial_damage
    
    iteration = 0
    max_iterations = depth_limit if depth_limit else int(len(remaining_gear) * iteration_multiplier)
    
    best_ever = (-initial_damage, start_assignment)
    
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

def adaptive_gear_assignment(team, gear_pool, prefilter_top_k=5, max_iterations=50, 
                           temperature=100, cooling_rate=0.975):
    """
    Adaptive gear assignment that can escape local maxima using simulated annealing.
    Starts with greedy assignment then applies perturbations to find better solutions.
    """
    # Start with greedy assignment as baseline
    best_assignment, best_damage = greedy_gear_assignment(team, gear_pool, prefilter_top_k)
    
    # If team is small or gear pool is limited, greedy might be optimal
    if len(team) <= 5 or len(gear_pool) <= len(team) * 3:
        return best_assignment, best_damage
    
    current_assignment = shallow_copy_assignment(best_assignment)
    current_damage = best_damage
    
    temp = temperature
    stagnation_counter = 0
    
    for iteration in range(max_iterations):
        # Create perturbed assignment
        perturbed_assignment = shallow_copy_assignment(current_assignment)
        
        # More aggressive perturbations when stuck
        if stagnation_counter > 5:
            num_perturbations = min(5, max(2, int(temp / 25)))
        else:
            num_perturbations = min(3, max(1, int(temp / 50)))
        
        for _ in range(num_perturbations):
            # Find a character with assigned gear
            base_names = [name for name in perturbed_assignment.keys() 
                         if any(gear is not None for gear in perturbed_assignment[name].values())]
            
            if not base_names:
                break
                
            base_name = random.choice(base_names)
            char_slots = [slot for slot, gear in perturbed_assignment[base_name].items() 
                         if gear is not None]
            
            if not char_slots:
                continue
                
            slot_to_perturb = random.choice(char_slots)
            current_gear = perturbed_assignment[base_name][slot_to_perturb]
            
            # Find alternative gear for this slot
            base_character = next(c for c in team if c.get_base_character() == base_name)
            eligible_gear = [g for g in gear_pool 
                           if g.slot == slot_to_perturb and 
                              g != current_gear and
                              g.can_equip_to(base_name)]
            
            if eligible_gear:
                # More aggressive exploration when stuck
                if stagnation_counter > 5:
                    # Higher chance of random choice when stuck
                    if random.random() < 0.7:
                        new_gear = random.choice(eligible_gear)
                    else:
                        new_gear = max(eligible_gear, key=lambda g: g.stat_value_for_character(base_character))
                else:
                    # Normal exploration vs exploitation
                    if random.random() < temp / temperature:
                        new_gear = random.choice(eligible_gear)
                    else:
                        new_gear = max(eligible_gear, key=lambda g: g.stat_value_for_character(base_character))
                
                perturbed_assignment[base_name][slot_to_perturb] = new_gear
        
        # Evaluate perturbed assignment
        perturbed_damage, _, _ = evaluate_team_with_gear(team, perturbed_assignment)
        
        # Calculate acceptance probability
        damage_diff = perturbed_damage - current_damage
        
        if damage_diff > 0:
            # Always accept better solutions
            current_assignment = perturbed_assignment
            current_damage = perturbed_damage
            stagnation_counter = 0
            
            if perturbed_damage > best_damage:
                best_assignment = perturbed_assignment
                best_damage = perturbed_damage
                stagnation_counter = 0
        else:
            stagnation_counter += 1
            # Accept worse solutions with probability based on temperature
            if temp > 0 and random.random() < np.exp(damage_diff / temp):
                current_assignment = perturbed_assignment
                current_damage = perturbed_damage
                stagnation_counter = 0
        
        # Cool down
        temp *= cooling_rate
        
        # Early termination if no improvement for many iterations
        if stagnation_counter > 15:
            break
    
    return best_assignment, best_damage

def random_restart_gear_assignment(team, gear_pool, prefilter_top_k=5, restarts=10):
    """
    Random restart strategy that tries completely different gear assignments.
    Useful for finding diverse solutions that might be far from greedy optimum.
    """
    best_assignment, best_damage = greedy_gear_assignment(team, gear_pool, prefilter_top_k)
    
    for restart in range(restarts):
        # Create completely random assignment
        assignment, remaining_gear = apply_exclusive_gear(team, gear_pool)
        
        # Precompute gear eligibility
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
        unique_bases = list(base_characters.values())
        
        # Completely random assignment (no greedy bias)
        used_gear = set()
        
        # Randomize slot order for diversity
        random.shuffle(slots)
        
        for slot in slots:
            # Get all candidates for this slot
            candidates = []
            for base_char in unique_bases:
                base_name = base_char.get_base_character()
                if slot in gear_by_slot and assignment[base_name][slot] is None:
                    for gear in gear_by_slot[slot]:
                        if gear not in used_gear and base_name in eligibility.get(gear.name, set()):
                            candidates.append((base_name, gear))
            
            # Randomly assign gear (no sorting by value)
            if candidates:
                random.shuffle(candidates)
                base_name, gear = candidates[0]
                assignment[base_name][slot] = gear
                used_gear.add(gear)
        
        # Evaluate this random assignment
        damage, _, _ = evaluate_team_with_gear(team, assignment)
        
        if damage > best_damage:
            best_assignment = assignment
            best_damage = damage
    
    return best_assignment, best_damage

def stochastic_gear_assignment(team, gear_pool, prefilter_top_k=5, attempts=20):
    """
    Stochastic gear assignment that tries multiple random assignments and keeps the best.
    Useful for escaping local maxima when greedy gets stuck.
    """
    best_assignment, best_damage = greedy_gear_assignment(team, gear_pool, prefilter_top_k)
    
    # Try multiple stochastic attempts
    for attempt in range(attempts):
        # Create random assignment with some greedy guidance
        assignment, remaining_gear = apply_exclusive_gear(team, gear_pool)
        
        # Precompute gear eligibility
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
        unique_bases = list(base_characters.values())
        
        # Random assignment with bias towards high-value gear
        used_gear = set()
        
        for slot in slots:
            # Get candidates for this slot
            candidates = []
            for base_char in unique_bases:
                base_name = base_char.get_base_character()
                if slot in gear_by_slot and assignment[base_name][slot] is None:
                    for gear in gear_by_slot[slot]:
                        if gear not in used_gear and base_name in eligibility.get(gear.name, set()):
                            # Add randomness to selection
                            value = gear.stat_value_for_character(base_char) * random.uniform(0.7, 1.3)
                            candidates.append((value, base_name, gear))
            
            # Sort and assign, but with some randomness
            candidates.sort(key=lambda x: x[0], reverse=True)
            
            # Take top few candidates and randomly choose one
            if candidates:
                top_candidates = candidates[:min(3, len(candidates))]
                value, base_name, gear = random.choice(top_candidates)
                assignment[base_name][slot] = gear
                used_gear.add(gear)
        
        # Evaluate this assignment
        damage, _, _ = evaluate_team_with_gear(team, assignment)
        
        if damage > best_damage:
            best_assignment = assignment
            best_damage = damage
    
    return best_assignment, best_damage

def hill_climbing_gear_assignment(team, gear_pool, prefilter_top_k=5, 
                                   max_iterations=100, restarts=5,
                                   neighborhood_size=10):
    """
    Hill climbing with random restarts for gear assignment.
    
    Starts with greedy or random assignment, then iteratively improves
    by swapping gear pieces until local optimum is reached.
    
    Parameters:
    - team: List of characters in the team
    - gear_pool: Available gear pool
    - prefilter_top_k: Gear prefiltering parameter
    - max_iterations: Max iterations per hill climbing run
    - restarts: Number of random restarts
    - neighborhood_size: Number of neighbors to explore per iteration
    
    Returns:
    - best_assignment: Dict mapping base character -> slot -> gear
    - best_damage: Best damage achieved
    """
    # Precompute gear eligibility
    base_characters = get_unique_base_characters(team)
    eligibility = precompute_gear_eligibility(gear_pool, base_characters)
    
    def get_all_assignable_gear(assignment, used_gear):
        """Get list of all gear that can be assigned (not used, can equip to someone)."""
        assignable = []
        for gear in gear_pool:
            if gear in used_gear:
                continue
            if gear.exclusive_for is not None:
                continue  # Skip exclusive gear (already assigned)
            # Check if this gear can equip to any character in team
            eligible_bases = eligibility.get(gear.name, set())
            if eligible_bases:
                for base_name in eligible_bases:
                    if assignment.get(base_name, {}).get(gear.slot) is None:
                        assignable.append((base_name, gear.slot, gear))
                        break
        return assignable
    
    def generate_neighbor(assignment, used_gear):
        """Generate a neighbor by swapping gear pieces."""
        # Get currently assigned gear
        assigned_slots = []
        for base_name, slots in assignment.items():
            for slot, gear in slots.items():
                if gear is not None and gear.exclusive_for is None:
                    assigned_slots.append((base_name, slot, gear))
        
        if not assigned_slots:
            return None, used_gear
        
        # Pick a random slot to change
        base_name, slot, old_gear = random.choice(assigned_slots)
        
        # Find alternative gear for this slot
        base_char = base_characters.get(base_name)
        eligible_gear = [
            g for g in gear_pool 
            if g.slot == slot and g != old_gear and g not in used_gear
            and base_name in eligibility.get(g.name, set())
        ]
        
        if not eligible_gear:
            return None, used_gear
        
        # Pick best alternative
        new_gear = max(eligible_gear, key=lambda g: g.stat_value_for_character(base_char))
        
        # Create new assignment
        new_assignment = shallow_copy_assignment(assignment)
        new_assignment[base_name][slot] = new_gear
        
        new_used = used_gear - {old_gear} | {new_gear}
        
        return new_assignment, new_used
    
    def hill_climb(initial_assignment, initial_used, initial_damage):
        """Perform hill climbing from a starting point."""
        current_assignment = initial_assignment
        current_used = initial_used
        current_damage = initial_damage
        
        local_best_assignment = shallow_copy_assignment(current_assignment)
        local_best_damage = current_damage
        
        no_improvement_count = 0
        
        for iteration in range(max_iterations):
            improved = False
            
            # Explore neighborhood
            for _ in range(neighborhood_size):
                neighbor_assignment, neighbor_used = generate_neighbor(
                    current_assignment, current_used
                )
                
                if neighbor_assignment is None:
                    continue
                
                neighbor_damage, _, _ = evaluate_team_with_gear(team, neighbor_assignment)
                
                if neighbor_damage > current_damage:
                    current_assignment = neighbor_assignment
                    current_used = neighbor_used
                    current_damage = neighbor_damage
                    improved = True
                    
                    if neighbor_damage > local_best_damage:
                        local_best_assignment = shallow_copy_assignment(neighbor_assignment)
                        local_best_damage = neighbor_damage
            
            if not improved:
                no_improvement_count += 1
                if no_improvement_count >= 5:  # Stuck at local optimum
                    break
            else:
                no_improvement_count = 0
        
        return local_best_assignment, local_best_damage
    
    # Start with greedy as baseline
    best_assignment, best_damage = greedy_gear_assignment(team, gear_pool, prefilter_top_k)
    
    # Calculate used gear from best assignment
    best_used = set()
    for base_name, slots in best_assignment.items():
        for slot, gear in slots.items():
            if gear is not None:
                best_used.add(gear)
    
    # Hill climb from greedy solution
    greedy_hc_assignment, greedy_hc_damage = hill_climb(
        shallow_copy_assignment(best_assignment), 
        best_used.copy(),
        best_damage
    )
    
    if greedy_hc_damage > best_damage:
        best_assignment = greedy_hc_assignment
        best_damage = greedy_hc_damage
    
    # Random restarts
    for restart in range(restarts):
        # Create random initial assignment
        assignment, remaining = apply_exclusive_gear(team, gear_pool)
        
        # Random assignment of remaining gear
        used = set(g for g in gear_pool if g.exclusive_for is not None and 
                   any(assignment.get(base_name, {}).get(g.slot) == g 
                       for base_name in assignment.keys()))
        
        # Assign remaining gear randomly
        all_assignable = get_all_assignable_gear(assignment, used)
        random.shuffle(all_assignable)
        
        for base_name, slot, gear in all_assignable:
            if assignment[base_name][slot] is None and gear not in used:
                assignment[base_name][slot] = gear
                used.add(gear)
        
        # Evaluate random assignment
        damage, _, _ = evaluate_team_with_gear(team, assignment)
        
        # Hill climb from random start
        hc_assignment, hc_damage = hill_climb(
            shallow_copy_assignment(assignment),
            used.copy(),
            damage
        )
        
        if hc_damage > best_damage:
            best_assignment = hc_assignment
            best_damage = hc_damage
    
    return best_assignment, best_damage


def simulated_annealing_gear_assignment(team, gear_pool, prefilter_top_k=5,
                                        initial_temp=2000, min_temp=100,
                                        cooling_rate=0.95, iterations_per_temp=50):
    """
    Pure simulated annealing for gear assignment (not team selection).
    
    Treats gear assignment as a discrete optimization problem where:
    - State: complete gear assignment
    - Move: swap one gear piece to a different piece
    - Energy: negative damage (minimize to maximize damage)
    
    Parameters:
    - team: Fixed team of characters
    - gear_pool: Available gear
    - prefilter_top_k: Gear prefiltering parameter
    - initial_temp: Starting temperature
    - min_temp: Minimum temperature before stopping
    - cooling_rate: Temperature decay rate
    - iterations_per_temp: Iterations at each temperature level
    
    Returns:
    - best_assignment: Best gear assignment found
    - best_damage: Best damage achieved
    """
    # Precompute gear eligibility
    base_characters = get_unique_base_characters(team)
    eligibility = precompute_gear_eligibility(gear_pool, base_characters)
    
    # Start with greedy assignment
    current_assignment, current_damage = greedy_gear_assignment(
        team, gear_pool, prefilter_top_k
    )
    
    best_assignment = shallow_copy_assignment(current_assignment)
    best_damage = current_damage
    
    # Track used gear
    def get_used_gear(assignment):
        used = set()
        for slots in assignment.values():
            for gear in slots.values():
                if gear is not None:
                    used.add(gear)
        return used
    
    current_used = get_used_gear(current_assignment)
    
    temperature = initial_temp
    iteration = 0
    stagnation_counter = 0
    
    while temperature > min_temp:
        improved_this_temp = False
        
        for _ in range(iterations_per_temp):
            iteration += 1
            
            # Generate neighbor: swap one gear piece
            # Pick a random character with assigned gear
            assigned_chars = [
                name for name, slots in current_assignment.items()
                if any(g is not None and g.exclusive_for is None for g in slots.values())
            ]
            
            if not assigned_chars:
                break
            
            base_name = random.choice(assigned_chars)
            char_slots = [
                slot for slot, gear in current_assignment[base_name].items()
                if gear is not None and gear.exclusive_for is None
            ]
            
            if not char_slots:
                continue
            
            slot_to_change = random.choice(char_slots)
            old_gear = current_assignment[base_name][slot_to_change]
            base_char = base_characters.get(base_name)
            
            # Find alternative gear for this slot
            eligible_alternatives = [
                g for g in gear_pool
                if g.slot == slot_to_change and g != old_gear
                and g not in current_used
                and base_name in eligibility.get(g.name, set())
            ]
            
            if not eligible_alternatives:
                continue
            
            # Select new gear (mix of random and greedy based on temperature)
            if random.random() < temperature / initial_temp:
                # Random exploration
                new_gear = random.choice(eligible_alternatives)
            else:
                # Greedy exploitation
                new_gear = max(
                    eligible_alternatives,
                    key=lambda g: g.stat_value_for_character(base_char)
                )
            
            # Create neighbor assignment
            neighbor_assignment = shallow_copy_assignment(current_assignment)
            neighbor_assignment[base_name][slot_to_change] = new_gear
            
            # Update used gear
            neighbor_used = current_used - {old_gear} | {new_gear}
            
            # Evaluate neighbor
            neighbor_damage, _, _ = evaluate_team_with_gear(team, neighbor_assignment)
            
            # Calculate acceptance probability
            damage_diff = neighbor_damage - current_damage
            
            if damage_diff > 0:
                # Always accept better solutions
                current_assignment = neighbor_assignment
                current_damage = neighbor_damage
                current_used = neighbor_used
                improved_this_temp = True
                stagnation_counter = 0
                
                if neighbor_damage > best_damage:
                    best_assignment = shallow_copy_assignment(neighbor_assignment)
                    best_damage = neighbor_damage
            else:
                # Accept worse solutions with SA probability
                if temperature > 0 and random.random() < np.exp(damage_diff / temperature):
                    current_assignment = neighbor_assignment
                    current_damage = neighbor_damage
                    current_used = neighbor_used
                    stagnation_counter = 0
                else:
                    stagnation_counter += 1
            
            # Early termination check
            if stagnation_counter > iterations_per_temp * 3:
                return best_assignment, best_damage
        
        # Cool down
        temperature *= cooling_rate
        
        # Adaptive cooling: slow down if improving
        if improved_this_temp:
            temperature /= cooling_rate  # Slightly undo the cooling
    
    return best_assignment, best_damage


def tabu_search_gear_assignment(team, gear_pool, prefilter_top_k=5,
                                max_iterations=200, tabu_tenure=10,
                                aspiration_threshold=0.01):
    """
    Tabu search for gear assignment.
    
    Uses memory structure (tabu list) to prevent cycling and escape local optima.
    Aspiration criteria allows overriding tabu status for significantly better solutions.
    
    Parameters:
    - team: Fixed team of characters
    - gear_pool: Available gear
    - prefilter_top_k: Gear prefiltering parameter
    - max_iterations: Maximum number of iterations
    - tabu_tenure: Number of iterations a move stays tabu
    - aspiration_threshold: Percentage improvement needed to override tabu status
    
    Returns:
    - best_assignment: Best gear assignment found
    - best_damage: Best damage achieved
    """
    # Precompute gear eligibility
    base_characters = get_unique_base_characters(team)
    eligibility = precompute_gear_eligibility(gear_pool, base_characters)
    
    # Start with greedy assignment
    current_assignment, current_damage = greedy_gear_assignment(
        team, gear_pool, prefilter_top_k
    )
    
    best_assignment = shallow_copy_assignment(current_assignment)
    best_damage = current_damage
    
    # Track used gear
    def get_used_gear(assignment):
        used = set()
        for slots in assignment.values():
            for gear in slots.values():
                if gear is not None:
                    used.add(gear)
        return used
    
    current_used = get_used_gear(current_assignment)
    
    # Tabu list: stores recent moves as (base_name, slot, old_gear_name, new_gear_name)
    tabu_list = []
    
    def is_tabu(move, iteration):
        """Check if a move is in tabu list."""
        for tabu_move, expiry in tabu_list:
            if move == tabu_move and iteration < expiry:
                return True
        return False
    
    def add_to_tabu(move, iteration):
        """Add a move to tabu list with expiry."""
        nonlocal tabu_list
        tabu_list.append((move, iteration + tabu_tenure))
        # Clean up expired entries
        tabu_list = [(m, exp) for m, exp in tabu_list if exp > iteration]
    
    def generate_moves(assignment, used_gear):
        """Generate all possible single gear swaps."""
        moves = []
        
        for base_name, slots in assignment.items():
            base_char = base_characters.get(base_name)
            for slot, current_gear in slots.items():
                if current_gear is None or current_gear.exclusive_for is not None:
                    continue  # Skip empty slots and exclusive gear
                
                # Find alternatives
                alternatives = [
                    g for g in gear_pool
                    if g.slot == slot and g != current_gear and g not in used_gear
                    and base_name in eligibility.get(g.name, set())
                ]
                
                for new_gear in alternatives:
                    move = (base_name, slot, current_gear.name, new_gear.name)
                    moves.append((move, base_name, slot, current_gear, new_gear))
        
        return moves
    
    # Main tabu search loop
    for iteration in range(max_iterations):
        # Generate all possible moves
        moves = generate_moves(current_assignment, current_used)
        
        if not moves:
            break
        
        # Evaluate all moves
        move_evaluations = []
        for move_info in moves:
            move, base_name, slot, old_gear, new_gear = move_info
            
            # Create new assignment
            new_assignment = shallow_copy_assignment(current_assignment)
            new_assignment[base_name][slot] = new_gear
            
            # Evaluate
            damage, _, _ = evaluate_team_with_gear(team, new_assignment)
            move_evaluations.append((damage, move, new_assignment, old_gear, new_gear))
        
        # Sort by damage (descending)
        move_evaluations.sort(key=lambda x: x[0], reverse=True)
        
        # Select best non-tabu move (or tabu if aspiration criteria met)
        selected = None
        for damage, move, new_assignment, old_gear, new_gear in move_evaluations:
            is_move_tabu = is_tabu(move, iteration)
            
            # Aspiration: override tabu if significantly better than best
            if is_move_tabu:
                improvement = (damage - best_damage) / best_damage if best_damage > 0 else 0
                if improvement > aspiration_threshold:
                    selected = (damage, new_assignment, move, old_gear, new_gear)
                    break
            else:
                selected = (damage, new_assignment, move, old_gear, new_gear)
                break
        
        if selected is None:
            # All moves are tabu and don't meet aspiration criteria
            # Pick the least tabu or random move
            if move_evaluations:
                selected = move_evaluations[0]
                damage, move, new_assignment, old_gear, new_gear = selected
                selected = (damage, new_assignment, move, old_gear, new_gear)
            else:
                break
        
        damage, new_assignment, move, old_gear, new_gear = selected
        
        # Execute the move
        current_assignment = new_assignment
        current_damage = damage
        current_used = current_used - {old_gear} | {new_gear}
        
        # Add reverse move to tabu list
        reverse_move = (move[0], move[1], move[3], move[2])  # Swap old and new gear names
        add_to_tabu(reverse_move, iteration)
        
        # Update best if improved
        if damage > best_damage:
            best_assignment = shallow_copy_assignment(new_assignment)
            best_damage = damage
    
    return best_assignment, best_damage

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

def simulated_annealing_team_search(roster, gear_pool, team_size=20, 
                                   initial_temp=2500, cooling_rate=0.97, min_temp=1000,
                                   iterations_per_temp=400, fixed_core=None,
                                   gear_method="greedy", gear_preset="fast"):
    """
    Simulated annealing for team optimization.
    
    Parameters:
    - roster: Available characters to choose from
    - gear_pool: Available gear for evaluation
    - team_size: Size of the team to build
    - initial_temp: Starting temperature (default: 2500)
    - cooling_rate: Temperature decay rate (default: 0.96)
    - min_temp: Minimum temperature before stopping (default: 1000)
    - iterations_per_temp: Number of iterations at each temperature level
    - fixed_core: List of characters that are auto-includes
    - gear_method: Gear optimization method ("greedy", "adaptive_sa", "hill_climbing", "sa", "tabu")
    - gear_preset: Parameter preset for gear method ("fast", "balanced", "thorough")
    
    Returns:
    - List of (damage, team) tuples sorted by damage
    - Best assignment dict from stage 1
    """
    print(f"  Simulated annealing (temp={initial_temp}->{min_temp}, rate={cooling_rate}, gear={gear_method})...")
    
    prefilter_k = determine_prefilter_k(len(gear_pool))
    
    if fixed_core:
        available_roster = [c for c in roster if c not in fixed_core]
        slots_to_fill = team_size - len(fixed_core)
    else:
        available_roster = roster
        slots_to_fill = team_size
    
    # Create initial random team
    def create_random_team():
        remaining_chars = random.sample(available_roster, slots_to_fill)
        if fixed_core:
            return fixed_core + remaining_chars
        else:
            return remaining_chars
    
    current_team = create_random_team()
    current_assignment, current_damage = optimize_gear_for_team(
        current_team, gear_pool, 
        method=gear_method, 
        preset=gear_preset,
        prefilter_top_k=prefilter_k
    )
    
    best_team = current_team.copy()
    best_damage = current_damage
    best_assignment = shallow_copy_assignment(current_assignment)
    
    temperature = initial_temp
    iteration = 0
    stagnation_counter = 0
    last_best_damage = 0
    total_iterations_without_improvement = 0
    results = [(current_damage, current_team.copy())]
    
    while temperature > min_temp:
        print(f"    Temperature {temperature:.1f}: Best = {best_damage:,.0f}")
        
        # Check for stagnation and trigger random restart
        if best_damage == last_best_damage:
            stagnation_counter += 1
            total_iterations_without_improvement += 1
        else:
            stagnation_counter = 0
            last_best_damage = best_damage
            total_iterations_without_improvement = 0
        
        # Early termination if no improvement for many consecutive temperature levels
        if total_iterations_without_improvement > 12:
            print(f"    Early termination: No improvement for {total_iterations_without_improvement} temperature levels")
            break
        
        # If stuck for longer, try random restart gear assignment (less frequent)
        if stagnation_counter > 3:
            print(f"    Stagnation detected, trying random restart gear assignment...")
            restart_assignment, restart_damage = random_restart_gear_assignment(
                current_team, gear_pool, prefilter_top_k=prefilter_k, restarts=2
            )
            if restart_damage > current_damage:
                current_assignment = restart_assignment
                current_damage = restart_damage
                if restart_damage > best_damage:
                    best_team = current_team.copy()
                    best_damage = restart_damage
            stagnation_counter = 0
        
        for _ in range(iterations_per_temp):
            iteration += 1
            
            # Generate neighbor by swapping one character
            neighbor_team = current_team.copy()
            
            if fixed_core:
                # Find a non-core character to replace
                core_indices = [i for i, c in enumerate(neighbor_team) if c in fixed_core]
                non_core_indices = [i for i, c in enumerate(neighbor_team) if c not in fixed_core]
                
                if non_core_indices:
                    replace_idx = random.choice(non_core_indices)
                    char_to_replace = neighbor_team[replace_idx]
                    
                    # Find a character not in current team
                    available_for_swap = [c for c in available_roster if c not in neighbor_team]
                    if available_for_swap:
                        new_char = random.choice(available_for_swap)
                        neighbor_team[replace_idx] = new_char
            else:
                # Random swap
                replace_idx = random.randint(0, len(neighbor_team) - 1)
                char_to_replace = neighbor_team[replace_idx]
                
                available_for_swap = [c for c in available_roster if c not in neighbor_team]
                if available_for_swap:
                    new_char = random.choice(available_for_swap)
                    neighbor_team[replace_idx] = new_char
            
            # Evaluate neighbor team with selected gear method
            neighbor_assignment, neighbor_damage = optimize_gear_for_team(
                neighbor_team, gear_pool, 
                method=gear_method, 
                preset=gear_preset,
                prefilter_top_k=prefilter_k
            )
            
            # Calculate acceptance probability
            damage_diff = neighbor_damage - current_damage
            
            if damage_diff > 0:
                # Always accept better solutions
                current_team = neighbor_team
                current_damage = neighbor_damage
                current_assignment = neighbor_assignment
                
                if neighbor_damage > best_damage:
                    best_team = neighbor_team.copy()
                    best_damage = neighbor_damage
                    best_assignment = shallow_copy_assignment(neighbor_assignment)
            else:
                # Accept worse solutions with probability based on temperature
                if temperature > 0:
                    acceptance_prob = np.exp(damage_diff / temperature)
                    if random.random() < acceptance_prob:
                        current_team = neighbor_team
                        current_damage = neighbor_damage
                        current_assignment = neighbor_assignment
            
            # Store result periodically
            if iteration % 50 == 0:
                results.append((current_damage, current_team.copy(), shallow_copy_assignment(current_assignment)))
        
        # Cool down
        temperature *= cooling_rate
    
    print(f"    Final best damage: {best_damage:,.0f}")
    
    # Sort results by damage and return
    results.sort(reverse=True, key=lambda x: x[0])
    return results, best_assignment

GEAR_METHOD_PRESETS = {
    "fast": {  # For Stage 1 team evaluation
        "adaptive_sa": {"max_iterations": 10, "temperature": 50},
        "hill_climbing": {"max_iterations": 50, "restarts": 2},
        "sa": {"initial_temp": 500, "iterations_per_temp": 10},
        "tabu": {"max_iterations": 50, "tabu_tenure": 5},
    },
    "balanced": {  # For general use
        "adaptive_sa": {"max_iterations": 50, "temperature": 100},
        "hill_climbing": {"max_iterations": 100, "restarts": 5},
        "sa": {"initial_temp": 2000, "iterations_per_temp": 50},
        "tabu": {"max_iterations": 200, "tabu_tenure": 10},
    },
    "thorough": {  # For final optimization
        "adaptive_sa": {"max_iterations": 100, "temperature": 200},
        "hill_climbing": {"max_iterations": 200, "restarts": 10},
        "sa": {"initial_temp": 3000, "iterations_per_temp": 100},
        "tabu": {"max_iterations": 300, "tabu_tenure": 15},
    }
}

def optimize_gear_for_team(team, gear_pool, method="greedy", preset="balanced", 
                          prefilter_top_k=5, **kwargs):
    """
    Unified gear optimization interface.
    
    Parameters:
    - method: "greedy", "adaptive_sa", "hill_climbing", "sa", "tabu"
    - preset: "fast", "balanced", "thorough" - determines parameter defaults
    - prefilter_top_k: Gear prefiltering parameter
    - kwargs: Override specific parameters from preset
    
    Returns:
    - assignment: Dict mapping base character -> slot -> gear
    - damage: Best damage achieved
    """
    # Get preset parameters
    params = GEAR_METHOD_PRESETS.get(preset, {}).get(method, {})
    params.update(kwargs)  # Allow override
    
    # Call appropriate function
    if method == "greedy":
        return greedy_gear_assignment(team, gear_pool, prefilter_top_k)
    elif method == "adaptive_sa":
        return adaptive_gear_assignment(team, gear_pool, prefilter_top_k, **params)
    elif method == "hill_climbing":
        return hill_climbing_gear_assignment(team, gear_pool, prefilter_top_k, **params)
    elif method == "sa":
        return simulated_annealing_gear_assignment(team, gear_pool, prefilter_top_k, **params)
    elif method == "tabu":
        return tabu_search_gear_assignment(team, gear_pool, prefilter_top_k, **params)
    else:
        raise ValueError(f"Unknown gear optimization method: {method}")

def optimize_team_with_beam_search(roster, gear_pool, team_size=20, 
                                            beam_width=200,
                                            fixed_core=None, use_simulated_annealing=True,
                                            sa_initial_temp=2500, sa_cooling_rate=0.97, sa_min_temp=1000,
                                            bs_iteration_multiplier=5.0,
                                            gear_method="greedy", gear_preset="fast"):
    """
    Two-step optimization process:
    1. Find the best promising team using either random sampling or simulated annealing
    2. Assign gear using beam search for that single best team

    beam_width: Number of gear assignments to keep in beam search
    fixed_core: List of characters that are auto-includes (usually OM Liberta, Bride Refi, Shrine Granadair)
    use_simulated_annealing: If True, use simulated annealing instead of random sampling
    sa_initial_temp: Starting temperature for simulated annealing
    sa_cooling_rate: Temperature decay rate for simulated annealing
    sa_min_temp: Minimum temperature for simulated annealing
    bs_iteration_multiplier: Multiplier for beam search iterations (higher = more thorough search)
    gear_method: Gear optimization method ("greedy", "adaptive_sa", "hill_climbing", "sa", "tabu")
    gear_preset: Parameter preset for gear method ("fast", "balanced", "thorough")
    """
    # Calculate optimal sample_size based on total combinations
    if fixed_core:
        available_count = len(roster) - len(fixed_core)
        slots_to_fill = team_size - len(fixed_core)
        total_combinations = comb(available_count, slots_to_fill)
    else:
        total_combinations = comb(len(roster), team_size)
    
    print(f"  Total possible teams: {total_combinations:,}")
    
    # Calculate sample size for random sampling fallback
    sample_size = max(100, min(int(total_combinations * 0.2), 100000))
    
    # Determine pre-filtering aggressiveness based on gear pool size
    prefilter_k = determine_prefilter_k(len(gear_pool))
    
    print(" Stage 1: Finding promising teams...")
    
    if use_simulated_annealing:
        print(f"  Using simulated annealing (temp: {sa_initial_temp}, cooling: {sa_cooling_rate}, min: {sa_min_temp})")
        
        # Use simulated annealing to find promising teams
        quick_results, stage1_best_assignment = simulated_annealing_team_search(
            roster, gear_pool, team_size, 
            sa_initial_temp, sa_cooling_rate, sa_min_temp, 
            fixed_core=fixed_core,
            gear_method=gear_method,
            gear_preset=gear_preset
        )
    else:
        print(f"  Sample size (20% of combinations): {sample_size:,}")
        
        # Traditional random sampling
        # If there's a fixed core, adjust roster and team_size for sampling
        if fixed_core:
            available_roster = [c for c in roster if c not in fixed_core]
            slots_to_fill = team_size - len(fixed_core)
            print(f"  Fixed core: {', '.join(c.name for c in fixed_core)}")
            print(f"  Filling {slots_to_fill} remaining slots from {len(available_roster)} characters")
        else:
            available_roster = roster
            slots_to_fill = team_size
        
        quick_results = []
        stage1_best_assignment = None
        best_stage1_damage = 0
        
        for i in range(sample_size):
            # Sample remaining slots
            remaining_chars = random.sample(available_roster, slots_to_fill)
            
            # Combine with fixed core if present
            if fixed_core:
                team = fixed_core + remaining_chars
            else:
                team = remaining_chars
            
            assignment, damage = optimize_gear_for_team(
                team, gear_pool, 
                method=gear_method, 
                preset=gear_preset,
                prefilter_top_k=prefilter_k
            )
            quick_results.append((damage, team, assignment))
            
            # Track best assignment from stage 1
            if damage > best_stage1_damage:
                best_stage1_damage = damage
                stage1_best_assignment = shallow_copy_assignment(assignment)
            
            if (i + 1) % 500 == 0:
                print(f"  Sampled {i + 1}/{sample_size} teams...")
    
    # Sort and keep the best team
    quick_results.sort(reverse=True, key=lambda x: x[0])
    best_team = quick_results[0][1] if quick_results else []
    
    print(f"\n  Stage 2: Beam search optimization for the best team...\n")
    
    if not best_team:
        print("  No teams found in stage 1!")
        return []
    
    print(f"Best team from stage 1:")
    
    # Use beam search to find best gear assignment for the best team
    # Pass the Stage 1 best assignment as starting point
    best_assignment, best_damage = beam_search_gear_optimization(
        best_team, gear_pool, beam_width=beam_width, prefilter_top_k=prefilter_k,
        initial_assignment=stage1_best_assignment,
        iteration_multiplier=bs_iteration_multiplier
    )
    
    # Check for empty slots and fill with beam search optimization
    empty_count = sum(
        1 for base_name, slots in best_assignment.items()
        for slot, gear in slots.items()
        if gear is None
    )
    
    if empty_count > 0:
        print(f"  Found {empty_count} empty slots, filling with beam search...")
        best_assignment, filled_count, fill_damage = beam_search_fill_empty_slots(
            best_team, gear_pool, best_assignment, 
            beam_width=max(20, beam_width//4),  # Smaller beam for fill
            prefilter_top_k=0  # No filtering for fill phase - guarantee coverage
        )
        print(f"  Filled {filled_count} slots, damage: {fill_damage:,.0f}")
        best_damage = fill_damage
    
    # Get final sequence with BEST rotation
    print(f"  Optimizing final rotation...")
    damage, chain, sequence = evaluate_team_with_gear(best_team, best_assignment, force_best_rotation=True)
    
    final_results = [{
        'team': best_team,
        'sequence': sequence,
        'gear_assignment': best_assignment,
        'damage': damage,
        'chain': chain
    }]
    
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


def fill_empty_gear_slots(team, gear_pool, assignment):
    """
    Post-process to fill any empty gear slots with remaining available gear.
    
    This ensures all characters have gear in all slots, even if the optimizer
    skipped them in favor of higher-damage assignments.
    
    Parameters:
    - team: List of characters in the team
    - gear_pool: Full gear pool (used to find what's still available)
    - assignment: Current gear assignment dict
    
    Returns:
    - Updated assignment with empty slots filled
    - Number of slots filled
    """
    # Get unique base characters
    base_characters = get_unique_base_characters(team)
    
    # Find all gear currently assigned
    used_gear = set()
    for base_name, slots in assignment.items():
        for slot, gear in slots.items():
            if gear is not None:
                used_gear.add(gear)
    
    # Find remaining unused gear
    remaining_gear = [g for g in gear_pool if g not in used_gear]
    
    # Organize remaining gear by slot
    gear_by_slot = organize_gear_by_slot(remaining_gear)
    
    # Precompute eligibility for remaining gear
    eligibility = precompute_gear_eligibility(remaining_gear, base_characters)
    
    slots_filled = 0
    
    # Fill empty slots
    for base_char in base_characters.values():
        base_name = base_char.get_base_character()
        
        if base_name not in assignment:
            continue
            
        for slot, current_gear in assignment[base_name].items():
            if current_gear is not None:
                continue  # Slot already filled
                
            # Find eligible gear for this character and slot
            if slot not in gear_by_slot:
                continue
                
            eligible_gear = [
                g for g in gear_by_slot[slot]
                if g not in used_gear and base_name in eligibility.get(g.name, set())
            ]
            
            if not eligible_gear:
                continue
            
            # Assign the best gear by stat value for this character
            best_gear = max(eligible_gear, key=lambda g: g.stat_value_for_character(base_char))
            assignment[base_name][slot] = best_gear
            used_gear.add(best_gear)
            slots_filled += 1
    
    return assignment, slots_filled


def beam_search_fill_empty_slots(team, gear_pool, assignment, beam_width=50, prefilter_top_k=3):
    """
    Fill empty slots using beam search optimization on remaining gear only.
    
    This reuses the beam search function but only operates on empty slots
    with remaining available gear, ensuring optimal use of leftover pieces.
    
    Parameters:
    - team: List of characters in team
    - gear_pool: Full gear pool
    - assignment: Current assignment with some slots filled
    - beam_width: Beam width for optimization (smaller than full search)
    - prefilter_top_k: Prefiltering for remaining gear (smaller than full search)
    
    Returns:
    - Updated assignment with empty slots filled
    - Number of slots filled
    - Final damage after filling
    """
    # Get unique base characters
    base_characters = get_unique_base_characters(team)
    
    # Find all gear currently assigned
    used_gear = set()
    empty_slots = []
    
    for base_name, slots in assignment.items():
        for slot, gear in slots.items():
            if gear is not None:
                used_gear.add(gear)
            else:
                empty_slots.append((base_name, slot))
    
    if not empty_slots:
        return assignment, 0, 0
    
    # Find remaining unused gear
    remaining_gear = [g for g in gear_pool if g not in used_gear]
    
    print(f"  Beam search filling {len(empty_slots)} empty slots with {len(remaining_gear)} remaining gear...")
    
    # Create a focused assignment dict with only empty slots
    focused_assignment = {}
    for base_name in base_characters.values():
        base_name_str = base_name.get_base_character()
        if base_name_str in assignment:
            focused_assignment[base_name_str] = {}
            for slot, gear in assignment[base_name_str].items():
                if gear is None:
                    focused_assignment[base_name_str][slot] = None
                else:
                    focused_assignment[base_name_str][slot] = gear
    
    # Run beam search on remaining gear only
    # We'll use a modified version that only considers empty slots
    beam_assignment, beam_damage = _beam_search_empty_slots(
        team, remaining_gear, focused_assignment, empty_slots,
        beam_width=beam_width, prefilter_top_k=prefilter_top_k
    )
    
    # Merge beam search results back into original assignment
    slots_filled = 0
    unfilled_slots = []
    
    for base_name, slot in empty_slots:
        if (beam_assignment.get(base_name, {}).get(slot) is not None):
            assignment[base_name][slot] = beam_assignment[base_name][slot]
            slots_filled += 1
        else:
            unfilled_slots.append((base_name, slot))
    
    # Fallback: fill any remaining slots with simple greedy assignment
    if unfilled_slots:
        print(f"  Beam search couldn't fill {len(unfilled_slots)} slots, using greedy fallback...")
        assignment, greedy_filled = fill_empty_gear_slots(team, gear_pool, assignment)
        slots_filled += greedy_filled
    
    return assignment, slots_filled, beam_damage


def _beam_search_empty_slots(team, remaining_gear, assignment, empty_slots, beam_width=50, prefilter_top_k=3):
    """
    Internal beam search that only operates on specified empty slots.
    Optimizes assignment of remaining gear to empty slots using beam search.
    """
    # Get unique base characters
    base_characters = get_unique_base_characters(team)
    unique_bases = list(base_characters.values())
    
    # Precompute gear eligibility for remaining gear
    eligibility = precompute_gear_eligibility(remaining_gear, base_characters)
    
    # Prefilter remaining gear for efficiency
    if prefilter_top_k > 0:
        filtered_remaining = prefilter_gear_for_team(
            team, remaining_gear, eligibility,
            top_k_per_slot=prefilter_top_k,
            baseline_assignment=assignment,
        )
    else:
        filtered_remaining = remaining_gear
    
    gear_by_slot = organize_gear_by_slot(filtered_remaining)
    
    # Get unique slots that need filling
    slots_to_fill = list(set(slot for _, slot in empty_slots))
    
    # Initialize beam with current assignment
    initial_damage, _, _ = evaluate_team_with_gear(team, assignment)
    beam = [(-initial_damage, 0, assignment, frozenset())]
    
    max_iterations = len(slots_to_fill)  # One iteration per slot type
    best_ever = (-initial_damage, assignment)
    
    import heapq
    
    for iteration in range(max_iterations):
        next_beam = []
        
        # Expand each state in beam
        for neg_damage, _, current_assignment, used_gear in beam:
            current_damage = -neg_damage
            
            # Track best
            if current_damage > -best_ever[0]:
                best_ever = (neg_damage, current_assignment.copy())
            
            # Try assigning each unused gear to each empty slot
            for base_name, slot in empty_slots:
                if current_assignment[base_name][slot] is not None:
                    continue  # Slot already filled in this state
                    
                if slot not in gear_by_slot:
                    continue
                    
                for gear in gear_by_slot[slot]:
                    # Skip if gear already used
                    if gear in used_gear:
                        continue
                    
                    # Check eligibility
                    if base_name not in eligibility.get(gear.name, set()):
                        continue
                    
                    # Create new assignment
                    new_assignment = current_assignment.copy()
                    new_assignment[base_name] = new_assignment[base_name].copy()
                    new_assignment[base_name][slot] = gear
                    new_used_gear = used_gear | {gear}
                    
                    # Evaluate
                    new_damage, _, _ = evaluate_team_with_gear(team, new_assignment)
                    
                    # Add to next beam
                    heapq.heappush(next_beam, (-new_damage, len(next_beam), new_assignment, new_used_gear))
        
        # Keep only top beam_width candidates
        if next_beam:
            beam = heapq.nsmallest(beam_width, next_beam)
        else:
            break
    
    best_damage = -best_ever[0]
    best_assignment = best_ever[1]
    
    return best_assignment, best_damage
