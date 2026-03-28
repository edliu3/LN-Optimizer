from math import floor, comb
import heapq
import numpy as np
from functools import lru_cache
import hashlib
from utils import determine_prefilter_k, get_unique_base_characters, organize_gear_by_slot, initialize_gear_assignment, get_attackers_and_buffers, calculate_chain_multiplier, calculate_team_buffs, calculate_character_max_hp
from character.character import Character
import random
import config

# Global cache for damage evaluations
_damage_cache = {}
_gear_eligibility_cache = {}

def clear_caches():
    """Clear all optimization caches."""
    global _damage_cache, _gear_eligibility_cache
    _damage_cache.clear()
    _gear_eligibility_cache.clear()

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
def cached_calculate_damage_stats(char_name, char_atk, char_damage_type, char_ratio, team_buffs_tuple, temp_atk_buff, temp_matk_buff, buff_count):
    """Cached version of calculate_damage_stats with proper temp_buffs handling."""
    # Convert tuple back to dict for calculation
    team_buffs = dict(team_buffs_tuple)
    
    if char_damage_type == "Enemy Max HP":
        atk = 50000
        damage_type_buff = 1
    elif char_damage_type == "MATK":
        atk = char_atk
        damage_type_buff = team_buffs.get('MATK%', 1) * (temp_matk_buff / 2)
    else:  # ATK
        atk = char_atk
        damage_type_buff = team_buffs.get('ATK%', 1) * (temp_atk_buff / 2)
    
    # Handle special character cases
    ratio = char_ratio
    if char_name == "NH Nebris":
        ratio = char_ratio + (config.NH_NEBRIS_RATIO_MULTIPLIER * buff_count)
    
    return atk, damage_type_buff, ratio

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

def calculate_single_hit(char, team_buffs, support_bonus=None):
    """Calculates damage of a single hit including all buffs and chain count."""
    # Use config support_bonus if not provided
    if support_bonus is None:
        support_bonus = config.support_bonus
    
    # Handle Own Max HP damage type separately since it needs actual character data
    if char.damage_type == "Own Max HP":
        # Calculate actual max_hp from character and gear
        max_hp = calculate_character_max_hp(char)
        crit_mult = char.crit_dmg + team_buffs.get('crit_dmg', 0) + char.temp_buffs.get('crit_dmg', 0) / 2
        ratio = char.ratio_per_hit
        
        total_single_hit = round(max_hp) * crit_mult * (team_buffs.get('overall', 1)) * ratio
        
        # Apply support bonus if provided
        if support_bonus is not None:
            total_single_hit *= (1 + support_bonus)
        
        return floor(total_single_hit)
    
    # Use cached calculations for other damage types
    buffs_key = tuple(sorted(team_buffs.items()))
    
    # Extract temp_buffs for caching
    temp_atk_buff = char.temp_buffs.get('ATK%', 2)
    temp_matk_buff = char.temp_buffs.get('MATK%', 2)
    buff_count = team_buffs.get('buff_count', 0)
    
    atk, damage_type_buff, ratio = cached_calculate_damage_stats(
        char.name, char.atk, char.damage_type, char.ratio_per_hit, buffs_key,
        temp_atk_buff, temp_matk_buff, buff_count
    )
    
    temp_crit_dmg_buff = char.temp_buffs.get('crit_dmg', 0) / 2
    crit_mult = char.crit_dmg + team_buffs.get('crit_dmg', 0) + temp_crit_dmg_buff
    
    total_single_hit = round(damage_type_buff * atk) * crit_mult * (team_buffs.get('overall', 1)) * ratio
    
    # Apply support bonus if provided
    if support_bonus is not None:
        total_single_hit *= (1 + support_bonus)
    
    return floor(total_single_hit)

def calculate_actual_damage(sequence, current_team_buffs, support_bonus=None):
    """Calculates total damage of a sequence."""
    # Use config support_bonus if not provided
    if support_bonus is None:
        support_bonus = config.support_bonus
    if not sequence:
        return 0, 0
    
    # Start with base team buffs (no domain)
    running_buffs = current_team_buffs.copy()
    
    # Vectorized per-character calculations
    char_data = []
    for char in sequence:
        # Apply this character's domain buffs to running buffs
        if char.domain:
            for buff_type, value in char.domain.items():
                if buff_type == "chain_count" or buff_type == "overall":
                    running_buffs[buff_type] += value
                elif running_buffs.get(buff_type, None) is None:
                    continue
                else:
                    running_buffs[buff_type] += value / 2
        
        # Calculate damage with updated running buffs
        single_hit = calculate_single_hit(char, running_buffs, support_bonus)
        chain_mult = calculate_chain_multiplier(running_buffs, char.temp_buffs)
        char_data.append((char.hits, single_hit, chain_mult))
    
    # Vectorized batch processing
    hits, single_hits, chain_mults = zip(*char_data)
    hits = np.array(hits)
    single_hits = np.array(single_hits)
    chain_mults = np.array(chain_mults)

    # Use shared chain bonus calculation
    total_damage = 0
    current_chain = 0
    
    for i, char in enumerate(sequence):
        char_hits = hits[i]
        if char_hits > 0:
            chain_bonuses = _compute_chain_bonuses(current_chain, char_hits, chain_mults[i])
            char_damage = (single_hits[i] * chain_bonuses).sum()
            total_damage += char_damage
            current_chain += char_hits * chain_mults[i]
    
    return total_damage, current_chain

def evaluate_team_with_gear(team, gear_assignments, support_bonus=None):
    """Assigns gear to characters and calculates the total damage."""
    # Use config support_bonus if not provided
    if support_bonus is None:
        support_bonus = config.support_bonus
    # Check cache first
    assignment_hash = get_assignment_hash(gear_assignments)
    cache_key = f"{assignment_hash}_{support_bonus}"
    
    if cache_key in _damage_cache:
        return _damage_cache[cache_key]
    
    # Apply gear assignments to team
    team_with_gear = []
    for char in team:
        char_copy = Character(
            name=char.name,
            damage_type=char.damage_type,
            atk=char.base_atk,  # Use base stats to recalculate
            crit_dmg=char.base_crit_dmg,
            ratio_per_hit=char.ratio_per_hit,
            hits=char.hits,
            buffs=char.buffs.copy(),
            temp_buffs=char.temp_buffs.copy(),
            domain=char.domain.copy(),
            base_flat_atk=char.base_flat_atk,
            base_atk_percent=char.base_atk_percent,
            base_hp=char.base_hp,
            base_flat_hp=char.base_flat_hp,
            base_hp_percent=char.base_hp_percent,
        )
        
        # Equip gear
        base_name = char.get_base_character()
        if base_name in gear_assignments:
            for slot, gear_piece in gear_assignments[base_name].items():
                if gear_piece is not None:
                    char_copy.equip_gear(gear_piece)
        else:
            # No gear assigned for this character, use base stats
            char_copy._recalculate_stats()
        team_with_gear.append(char_copy)
    
    # Calculate damage
    team_buffs = calculate_team_buffs(team_with_gear)
    buffers, attackers = get_attackers_and_buffers(team_with_gear)
    
    sequence = rotation_optimizer(team_buffs, attackers)
    
    full_sequence = buffers + sequence
    damage, chain = calculate_actual_damage(full_sequence, team_buffs, support_bonus)

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
    # Get unique base characters
    base_characters = get_unique_base_characters(team)
    unique_bases = list(base_characters.values())

    # Use shared gear preparation, but handle initial assignment logic separately
    used_gear_in_initial = set()  # Initialize upfront
    
    if initial_assignment is not None:
        # Start with a copy of the initial assignment
        start_assignment = shallow_copy_assignment(initial_assignment)
        
        # Get exclusive assignment to merge with initial assignment
        exclusive_assignment, _ = apply_exclusive_gear(team, gear_pool)
        
        # Ensure exclusive gear is still assigned (Stage 1 might have missed some)
        for base_name, slots in exclusive_assignment.items():
            for slot, gear in slots.items():
                if gear is not None and start_assignment.get(base_name, {}).get(slot) is None:
                    start_assignment[base_name][slot] = gear
        
        # Calculate which gear is already used in the initial assignment
        for base_name, slots in start_assignment.items():
            for slot, gear in slots.items():
                if gear is not None:
                    used_gear_in_initial.add(gear)
        
        # Remaining gear is everything in the pool not already used
        remaining_gear = [g for g in gear_pool if g not in used_gear_in_initial and g.exclusive_for is None]
        
        # Use shared preparation for the remaining gear
        _, _, eligibility, filtered_remaining, gear_by_slot = _prepare_gear_search(
            team, remaining_gear, prefilter_top_k, base_characters, start_assignment
        )
        
        initial_damage, _, _ = evaluate_team_with_gear(team, start_assignment)
        print(f"  Using Stage 1 assignment as starting point (damage: {initial_damage:,.0f})")
    else:
        # Use shared preparation for the standard case
        start_assignment, remaining_gear, eligibility, filtered_remaining, gear_by_slot = _prepare_gear_search(
            team, gear_pool, prefilter_top_k, base_characters, None
        )
        initial_damage, _, _ = evaluate_team_with_gear(team, start_assignment)
        # used_gear_in_initial remains empty set for standard case
    
    slots = list(gear_by_slot.keys()) if gear_by_slot else []
    
    # Priority queue: (negative_damage, counter, assignment, used_gear_set)
    counter = 0
    beam = [(-initial_damage, counter, start_assignment, frozenset(used_gear_in_initial))]
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

def _beam_search_core(team, initial_assignment, slots_to_consider, eligibility, gear_by_slot,
                      beam_width, max_iterations):
    """
    Core beam search loop. slots_to_consider is a list of (base_name, slot) pairs
    to attempt filling. Pass all (base_name × slot) combos for full search,
    or just empty ones for fill phase.
    """
    initial_damage, _, _ = evaluate_team_with_gear(team, initial_assignment)
    counter = 0
    beam = [(-initial_damage, counter, initial_assignment, frozenset())]
    best_ever = (-initial_damage, initial_assignment)

    for iteration in range(max_iterations):
        next_beam = []
        for neg_damage, _, assignment, used_gear in beam:
            current_damage = -neg_damage
            if current_damage > -best_ever[0]:
                best_ever = (neg_damage, shallow_copy_assignment(assignment))

            for base_name, slot in slots_to_consider:
                if assignment[base_name][slot] is not None:
                    continue
                if slot not in gear_by_slot:
                    continue
                for gear in gear_by_slot[slot]:
                    if gear in used_gear:
                        continue
                    if base_name not in eligibility.get(gear.name, set()):
                        continue
                    new_assignment = shallow_copy_assignment(assignment)
                    new_assignment[base_name][slot] = gear
                    new_damage, _, _ = evaluate_team_with_gear(team, new_assignment)
                    counter += 1
                    heapq.heappush(next_beam, (-new_damage, counter, new_assignment, used_gear | {gear}))

        beam = heapq.nsmallest(beam_width, next_beam)
        if not beam:
            break

    return -best_ever[0], best_ever[1]

def _prepare_gear_search(team, gear_pool, prefilter_top_k, base_characters=None, initial_assignment=None):
    """Returns (assignment, remaining_gear, eligibility, filtered_gear, gear_by_slot)."""
    if base_characters is None:
        base_characters = get_unique_base_characters(team)
    
    assignment, remaining_gear = apply_exclusive_gear(team, gear_pool)
    eligibility = precompute_gear_eligibility(remaining_gear, base_characters)
    if prefilter_top_k > 0:
        filtered = prefilter_gear_for_team(
            team, remaining_gear, eligibility,
            top_k_per_slot=prefilter_top_k,
            baseline_assignment=initial_assignment or assignment,
            base_characters=base_characters
        )
    else:
        filtered = remaining_gear
    gear_by_slot = organize_gear_by_slot(filtered)
    return assignment, remaining_gear, eligibility, filtered, gear_by_slot

def prefilter_gear_for_team(team, remaining_gear, eligibility, top_k_per_slot,
                                     baseline_assignment=None, base_characters=None):
    """
    Uses stat_value_for_character to give top candidates for gear for each slot.
    """
    if base_characters is None:
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
            
            # Track currently used gear to avoid duplication
            currently_used_gear = set()
            for char_name, slots in perturbed_assignment.items():
                for slot, gear in slots.items():
                    if gear is not None:
                        currently_used_gear.add(gear)
            
            # Find alternative gear for this slot
            base_character = next(c for c in team if c.get_base_character() == base_name)
            eligible_gear = [g for g in gear_pool 
                           if g.slot == slot_to_perturb and 
                              g != current_gear and
                              g not in currently_used_gear and
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


def greedy_gear_assignment(team, gear_pool, prefilter_top_k=5):
    """
    Assigns gear to a team using a greedy algorithm based on the
    stat_value_for_character method.
    """
    base_characters = get_unique_base_characters(team)
    assignment, remaining_gear, eligibility, filtered_remaining, gear_by_slot = _prepare_gear_search(
        team, gear_pool, prefilter_top_k, base_characters, None
    )
    
    slots = list(gear_by_slot.keys())
    
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
    - gear_method: Gear optimization method ("greedy", "adaptive_sa", "sa")
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
        
        for _ in range(iterations_per_temp):
            iteration += 1
            
            # Generate neighbor by swapping one character
            neighbor_team = current_team.copy()
            
            if fixed_core:
                # Find a non-core character to replace
                non_core_indices = [i for i, c in enumerate(neighbor_team) if c not in fixed_core]
                
                if non_core_indices:
                    replace_idx = random.choice(non_core_indices)
                    
                    # Find a character not in current team
                    available_for_swap = [c for c in available_roster if c not in neighbor_team]
                    if available_for_swap:
                        new_char = random.choice(available_for_swap)
                        neighbor_team[replace_idx] = new_char
            else:
                # Random swap
                replace_idx = random.randint(0, len(neighbor_team) - 1)
                
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
        "adaptive_sa": {"max_iterations": 10, "temperature": 50}
    },
    "balanced": {  # For general use
        "adaptive_sa": {"max_iterations": 50, "temperature": 100}
    },
    "thorough": {  # For final optimization
        "adaptive_sa": {"max_iterations": 100, "temperature": 200}
    }
}

def optimize_gear_for_team(team, gear_pool, method="adaptive_sa", preset="balanced", 
                          prefilter_top_k=5, **kwargs):
    """
    Unified gear optimization interface.
    
    Parameters:
    - method: "adaptive_sa" (only supported method)
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
    if method == "adaptive_sa":
        result = adaptive_gear_assignment(team, gear_pool, prefilter_top_k, **params)
        return result
    else:
        raise ValueError(f"Unknown gear optimization method: {method}. Only 'adaptive_sa' is supported.")

def optimize_team_with_beam_search(roster, gear_pool, team_size=20, 
                                            beam_width=200,
                                            fixed_core=None, use_simulated_annealing=True,
                                            sa_initial_temp=2500, sa_cooling_rate=0.97, sa_min_temp=1000,
                                            bs_iteration_multiplier=5.0,
                                            gear_method="adaptive_sa", gear_preset="fast"):
    """
    Two-step optimization process:
    1. Find the best promising team using either simulated annealing (recommended) or random sampling
    2. Assign gear using beam search for that single best team

    beam_width: Number of gear assignments to keep in beam search
    fixed_core: List of characters that are auto-includes (usually OM Liberta, Bride Refi, Shrine Granadair)
    use_simulated_annealing: 
        - True (recommended): Use simulated annealing for better team exploration
        - False: Use random sampling (faster for very large search spaces, good for testing/benchmarking)
    sa_initial_temp: Starting temperature for simulated annealing
    sa_cooling_rate: Temperature decay rate for simulated annealing
    sa_min_temp: Minimum temperature for simulated annealing
    bs_iteration_multiplier: Multiplier for beam search iterations (higher = more thorough search)
    gear_method: Gear optimization method ("adaptive_sa" only)
    gear_preset: Parameter preset for gear method ("fast", "balanced", "thorough")
    
    Note: Random sampling (use_simulated_annealing=False) is primarily used for:
    - Testing and benchmarking against simulated annealing
    - Very large search spaces where SA might be too slow
    - Quick approximate results when speed is prioritized over quality
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
    
    fill_damage = 0  # Initialize to avoid undefined variable
    if empty_count > 0:
        print(f"  Found {empty_count} empty slots, filling with beam search...")
        best_assignment, filled_count, fill_damage = beam_search_fill_empty_slots(
            best_team, gear_pool, best_assignment, 
            beam_width=max(20, beam_width//4),  # Smaller beam for fill
            prefilter_top_k=0,  # No filtering for fill phase - guarantee coverage
        )
        print(f"  Filled {filled_count} slots, damage: {fill_damage:,.0f}")
        # Note: fill_damage might use different rotation optimization, so we recalculate in next step
    
    # Get final sequence with BEST rotation
    print(f"  Optimizing final rotation...")
    damage, chain, sequence = evaluate_team_with_gear(best_team, best_assignment)
    
    # Check for inconsistency between fill_damage and final damage
    if empty_count > 0 and abs(fill_damage - damage) > 1000:  # Allow small rounding differences
        print(f"  ⚠️  Warning: Fill damage ({fill_damage:,.0f}) differs from final damage ({damage:,.0f})")
        print(f"  Difference: {damage - fill_damage:,.0f}")
    
    final_results = [{
        'team': best_team,
        'sequence': sequence,
        'gear_assignment': best_assignment,
        'damage': damage,
        'chain': chain
    }]
    
    print(f"  Final damage: {damage:,.0f}\n")
    
    return final_results

def _compute_chain_bonuses(current_chain, num_hits, chain_mult):
    """Calculate chain bonuses for a given number of hits.
    
    This centralizes the chain bonus calculation logic.
    """
    hit_chains = current_chain + np.arange(num_hits) * chain_mult
    return hit_chains * 0.1 + 1

def _hits_data(sequence, team_buffs, support_bonus=None):
    """Helper function to get (char_name, crit_damage, non_crit_damage, crit_rate) for each hit"""
    # Use config support_bonus if not provided
    if support_bonus is None:
        support_bonus = config.support_bonus
    if not sequence:
        return []
    
    # Pre-allocate arrays for all hits
    total_hits = sum(char.hits for char in sequence)
    char_name_arr = np.empty(total_hits, dtype=object)
    crit_damage_arr = np.zeros(total_hits, dtype=np.float64)
    non_crit_damage_arr = np.zeros(total_hits, dtype=np.float64)
    crit_rate_arr = np.zeros(total_hits, dtype=np.float64)
    
    # Extract character data into arrays - using same method as calculate_actual_damage
    char_data = []
    hit_indices = []
    current_idx = 0
    
    # Start with base team buffs (no domain) - same as calculate_actual_damage
    running_buffs = team_buffs.copy()
    
    team_crit_rate = min(team_buffs.get("crit_rate", 0) + 0.1, 1.0)
    
    for char in sequence:
        # Apply this character's domain buffs to running buffs - same as calculate_actual_damage
        if char.domain:
            for buff_type, value in char.domain.items():
                if buff_type == "chain_count" or buff_type == "overall":
                    running_buffs[buff_type] += value
                elif running_buffs.get(buff_type, None) is None:
                    continue
                else:
                    running_buffs[buff_type] += value / 2
        
        # Per-character effective rate: team base + personal temp buff (halved)
        # Small bug: If domain buffs crit_rate, need to change this to use running total
        char_crit_rate = min(
            team_crit_rate + char.temp_buffs.get("crit_rate", 0) / 2,
            1.0
        )
        
        # Use same calculations as calculate_actual_damage with running_buffs
        single_hit = calculate_single_hit(char, running_buffs, support_bonus)
        chain_mult = calculate_chain_multiplier(running_buffs, char.temp_buffs)
        crit_mult = char.crit_dmg + running_buffs.get('crit_dmg', 0) + char.temp_buffs.get('crit_dmg', 0) / 2
        
        # Store character data for vectorized processing
        char_data.append({
            'name': char.name,
            'single_hit': single_hit,
            'chain_mult': chain_mult,
            'crit_mult': crit_mult,
            'crit_rate': char_crit_rate,
            'hits': char.hits
        })
        
        hit_indices.append((current_idx, current_idx + char.hits))
        current_idx += char.hits
    
    # Vectorized calculation for all hits - using same logic as calculate_actual_damage
    current_chain = 0
    for i, (start_idx, end_idx) in enumerate(hit_indices):
        data = char_data[i]
        num_hits = end_idx - start_idx
        
        if num_hits > 0:
            # Use shared chain bonus calculation
            chain_bonuses = _compute_chain_bonuses(current_chain, num_hits, data['chain_mult'])
            
            # Calculate damage using same method as calculate_actual_damage
            # Non-crit damage: single_hit_without_crit * chain_bonuses
            # We need to remove crit_mult from single_hit to get base damage
            base_single_hit = data['single_hit'] / data['crit_mult']
            non_crit_damage = base_single_hit * chain_bonuses
            
            # Crit damage: single_hit * chain_bonuses (single_hit already includes crit_mult)
            crit_damage = data['single_hit'] * chain_bonuses
            
            # Assign to result arrays
            char_name_arr[start_idx:end_idx] = data['name']
            crit_damage_arr[start_idx:end_idx] = crit_damage
            non_crit_damage_arr[start_idx:end_idx] = non_crit_damage
            crit_rate_arr[start_idx:end_idx] = data['crit_rate']
            
            # Update chain count - same as calculate_actual_damage
            current_chain += num_hits * data['chain_mult']
    
    # Convert back to list of tuples for compatibility
    return list(zip(char_name_arr, crit_damage_arr, non_crit_damage_arr, crit_rate_arr))

def simulate_crit_distribution(sequence, team_buffs, n_simulations=100000, support_bonus=None):
    # Use config support_bonus if not provided
    if support_bonus is None:
        support_bonus = config.support_bonus
    hdata = _hits_data(sequence, team_buffs, support_bonus)
    if not hdata:
        return np.array([]), 0, min(team_buffs.get("crit_rate", 0), 1.0)

    crit_arr     = np.array([h[1] for h in hdata], dtype=np.float64)
    non_crit_arr = np.array([h[2] for h in hdata], dtype=np.float64)
    rate_arr     = np.array([h[3] for h in hdata], dtype=np.float64)
    full_damage  = calculate_actual_damage(sequence, team_buffs, support_bonus)[0]

    rolls = np.random.random((n_simulations, len(hdata)))
    crits = rolls < rate_arr
    totals = (crits * crit_arr + ~crits * non_crit_arr).sum(axis=1)
    fractions = totals / full_damage

    team_crit_rate = min(team_buffs.get("crit_rate", 0) + 0.1, 1.0)
    return fractions, full_damage, team_crit_rate

def rotation_optimizer(current_buffs, team):
    """
    Optimized rotation algorithm based on key insight:
    
    HIGH DAMAGE-PER-HIT characters should go LATE to benefit from chain.
    LOW DAMAGE-PER-HIT characters should go EARLY to build chain.
    
    This is because total damage = sum of (damage_per_hit × chain_multiplier).
    The character with highest damage_per_hit benefits most from high chain.
    
    Strategy:
    1. Calculate damage per hit for each character using calculate_single_hit
    2. Sort by damage per hit (ascending)
    3. Low damage/hit first (chain builders), high damage/hit last (chain users)
    """
    if not team:
        return []
    
    # Calculate damage per hit for each character
    damage_data = []
    for char in team:
        per_hit = calculate_single_hit(char, current_buffs)
        damage_data.append((per_hit, per_hit * char.hits, char))
    
    # Sort by damage per hit (ascending): low damage/hit first, high damage/hit last
    # Tiebreaker: if same damage/hit, prefer higher total damage potential last
    damage_data.sort(key=lambda x: (x[0], x[1]))
    
    # Return sorted sequence
    return [char for _, _, char in damage_data]

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
    focused_assignment = shallow_copy_assignment(assignment)
    
    # Run beam search on remaining gear only
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
        # Recalculate damage after greedy fallback to ensure consistency
        beam_damage, _, _ = evaluate_team_with_gear(team, assignment)
    
    return assignment, slots_filled, beam_damage


def _beam_search_empty_slots(team, remaining_gear, assignment, empty_slots, beam_width=50, prefilter_top_k=3):
    """
    Internal beam search that only operates on specified empty slots.
    Optimizes assignment of remaining gear to empty slots using beam search.
    """
    # Get unique base characters
    base_characters = get_unique_base_characters(team)
    
    # Precompute gear eligibility for remaining gear
    eligibility = precompute_gear_eligibility(remaining_gear, base_characters)
    
    # Prefilter remaining gear for efficiency
    if prefilter_top_k > 0:
        filtered_remaining = prefilter_gear_for_team(
            team, remaining_gear, eligibility,
            top_k_per_slot=prefilter_top_k,
            baseline_assignment=assignment,
            base_characters=base_characters
        )
    else:
        filtered_remaining = remaining_gear
    
    gear_by_slot = organize_gear_by_slot(filtered_remaining)
    
    # Use shared core function with empty_slots as slots_to_consider
    max_iterations = len(set(slot for _, slot in empty_slots))  # One iteration per slot type
    best_damage, best_assignment = _beam_search_core(
        team, assignment, empty_slots, eligibility, gear_by_slot,
        beam_width, max_iterations
    )
    
    return best_assignment, best_damage
