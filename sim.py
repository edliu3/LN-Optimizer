from math import floor, comb
import heapq
import numpy as np
from functools import lru_cache
import hashlib
from utils import determine_prefilter_k, get_unique_base_characters, organize_gear_by_slot, calculate_damage_stats, calculate_crit_multiplier, initialize_gear_assignment, get_eligible_gear_for_character, get_attackers_and_buffers, calculate_chain_multiplier, calculate_team_buffs
from character.character import Character
import random
import config

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
def cached_calculate_damage_stats(char_name, char_atk, char_damage_type, char_ratio, team_buffs_tuple, temp_atk_buff, temp_matk_buff, buff_count):
    """Cached version of calculate_damage_stats with proper temp_buffs handling."""
    # Convert tuple back to dict for calculation
    team_buffs = dict(team_buffs_tuple)
    
    if char_damage_type == "Max HP":
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

def calculate_single_hit(char, team_buffs, support_bonus=None):
    """Calculates damage of a single hit including all buffs and chain count."""
    # Use config support_bonus if not provided
    if support_bonus is None:
        support_bonus = config.support_bonus
    
    # Use cached calculations
    char_key = (char.name, char.atk, char.damage_type, char.ratio_per_hit)
    buffs_key = tuple(sorted(team_buffs.items()))
    
    # Extract temp_buffs for caching
    temp_atk_buff = char.temp_buffs.get('ATK%', 2)
    temp_matk_buff = char.temp_buffs.get('MATK%', 2)
    buff_count = team_buffs.get('buff_count', 0)
    
    atk, damage_type_buff, ratio = cached_calculate_damage_stats(
        char.name, char.atk, char.damage_type, char.ratio_per_hit, buffs_key,
        temp_atk_buff, temp_matk_buff, buff_count
    )
    
    crit_key = (team_buffs.get('crit_dmg', 0),)  # Just pass crit_dmg value
    crit_mult = cached_calculate_crit_multiplier(char.crit_dmg, crit_key)
    
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

def evaluate_team_with_gear(team, gear_assignments, support_bonus=None,
                            objective="max_damage", threshold=None, n_bins=300):
    """
    Assigns gear to characters and returns a scalar score for optimisation.

    Parameters
    ----------
    objective : str
        "max_damage"        — existing behaviour, returns full-crit damage
        "exceed_threshold"  — returns P(D > threshold) via FFT convolution
    threshold : float or None
        Required when objective="exceed_threshold".
    n_bins : int
        Convolution resolution. Only used when objective="exceed_threshold".
        300 for SA inner loop, 1000+ for final beam search eval.

    Returns
    -------
    (score, chain, sequence)
        score is damage when objective="max_damage",
              is float in [0,1] when objective="exceed_threshold"
    """
    if support_bonus is None:
        support_bonus = config.support_bonus

    # Cache key includes objective and threshold so different modes don't
    # share entries. Threshold-mode entries are also reused across SA steps.
    assignment_hash = get_assignment_hash(gear_assignments)
    if objective == "exceed_threshold":
        cache_key = f"{assignment_hash}_{support_bonus}_t{threshold}_b{n_bins}"
    else:
        cache_key = f"{assignment_hash}_{support_bonus}"

    if cache_key in _damage_cache:
        return _damage_cache[cache_key]

    # ── Apply gear to a fresh copy of each character ──────────────────────────
    team_with_gear = []
    for char in team:
        char_copy = Character(
            name=char.name,
            damage_type=char.damage_type,
            atk=char.base_atk,
            crit_dmg=char.base_crit_dmg,
            ratio_per_hit=char.ratio_per_hit,
            hits=char.hits,
            buffs=char.buffs.copy(),
            temp_buffs=char.temp_buffs.copy(),
            domain=char.domain.copy(),
            base_flat_atk=getattr(char, 'base_flat_atk', 0),
            base_atk_percent=getattr(char, 'base_atk_percent', 0)
        )
        base_name = char.get_base_character()
        if base_name in gear_assignments:
            for slot, gear_piece in gear_assignments[base_name].items():
                if gear_piece is not None:
                    char_copy.equip_gear(gear_piece)
        else:
            char_copy._recalculate_stats()
        team_with_gear.append(char_copy)

    # ── Compute rotation and base damage ─────────────────────────────────────
    team_buffs = calculate_team_buffs(team_with_gear)
    buffers, attackers = get_attackers_and_buffers(team_with_gear)
    sequence = rotation_optimizer(team_buffs, attackers)
    full_sequence = buffers + sequence

    damage, chain = calculate_actual_damage(full_sequence, team_buffs, support_bonus)

    # ── Score ─────────────────────────────────────────────────────────────────
    if objective == "exceed_threshold":
        if threshold is None:
            raise ValueError("threshold must be provided when objective='exceed_threshold'")
        
        fft_score = probability_exceed_threshold_fft(
            full_sequence, team_buffs, threshold,
            support_bonus=support_bonus, n_bins=n_bins
        )
        
        score = fft_score
    else:
        score = damage

    result = (score, chain, full_sequence)
    _damage_cache[cache_key] = result
    return result

GEAR_METHOD_PRESETS = {
    "fast": {
        "adaptive_sa": {"max_iterations": 10, "temperature": 50},
        "n_bins_sa":   200,    # bins used during SA inner loop
        "n_bins_beam": 500,    # bins used during final beam search eval
    },
    "balanced": {
        "adaptive_sa": {"max_iterations": 50, "temperature": 100},
        "n_bins_sa":   500,
        "n_bins_beam": 1000,
    },
    "thorough": {
        "adaptive_sa": {"max_iterations": 100, "temperature": 200},
        "n_bins_sa":   500,
        "n_bins_beam": 1000,
    }
}

def beam_search_gear_optimization(team, gear_pool, beam_width=100,
                                  depth_limit=None, prefilter_top_k=5,
                                  initial_assignment=None,
                                  iteration_multiplier=1.0,
                                  objective="max_damage",
                                  threshold=None,
                                  n_bins=1000):
    """
    Beam search over gear assignments.

    objective/threshold/n_bins are forwarded to evaluate_team_with_gear.
    For threshold mode, n_bins should be higher than during SA (1000+) since
    this step produces the final assignment shown in the report.
    """

    def _eval(assignment):
        score, chain, seq = evaluate_team_with_gear(
            team, assignment,
            objective=objective, threshold=threshold, n_bins=n_bins
        )
        return score, chain, seq

    attackers       = [c for c in team if c.hits > 0]
    base_characters = get_unique_base_characters(team)
    unique_bases    = list(base_characters.values())

    used_gear_in_initial = set()

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

        remaining_gear = [
            g for g in gear_pool
            if g not in used_gear_in_initial and g.exclusive_for is None
        ]
        _, _, eligibility, filtered_remaining, gear_by_slot = _prepare_gear_search(
            team, remaining_gear, prefilter_top_k, base_characters, start_assignment
        )
        initial_score, _, _ = _eval(start_assignment)
        print(f"  Using Stage 1 assignment as starting point "
              f"({_fmt(initial_score, objective)})")
    else:
        start_assignment, remaining_gear, eligibility, filtered_remaining, gear_by_slot = \
            _prepare_gear_search(team, gear_pool, prefilter_top_k, base_characters, None)
        initial_score, _, _ = _eval(start_assignment)

    slots   = list(gear_by_slot.keys()) if gear_by_slot else []
    counter = 0
    beam    = [(-initial_score, counter, start_assignment,
                frozenset(used_gear_in_initial))]
    counter += 1

    # Ensure assignment includes all base characters from the team
    for base_char in unique_bases:
        base_name = base_char.get_base_character()
        if base_name not in start_assignment:
            # Add missing base character to assignment with empty slots
            start_assignment[base_name] = {slot: None for slot in slots}
    print(f"  Starting beam search with {len(unique_bases)} unique base characters...")
    print(f"  Remaining gear pool: {len(remaining_gear)} pieces")
    if not remaining_gear:
        print("  All gear is exclusive — no optimisation needed!")
        return start_assignment, initial_score

    # Check for early termination if we already have perfect threshold probability
    if objective == "exceed_threshold" and initial_score >= 0.999999:
        print(f"Starting assignment already has perfect threshold probability! Skipping beam search.")
        return start_assignment, initial_score
    
    iteration    = 0
    max_iterations = depth_limit if depth_limit else int(
        len(remaining_gear) * iteration_multiplier
    )
    best_ever = (-initial_score, start_assignment)

    while beam and iteration < max_iterations:
        iteration += 1
        next_beam = []

        for neg_score, _, assignment, used_gear in beam:
            current_score = -neg_score
            if current_score > -best_ever[0]:
                best_ever = (neg_score, shallow_copy_assignment(assignment))

            for slot in slots:
                if slot not in gear_by_slot:
                    continue
                for gear in gear_by_slot[slot]:
                    if gear in used_gear:
                        continue
                    eligible_chars = eligibility.get(gear.name, set())
                    for base_char in unique_bases:
                        base_name = base_char.get_base_character()
                        if base_name not in eligible_chars:
                            continue
                        if assignment[base_name][slot] is not None:
                            continue

                        new_assignment = shallow_copy_assignment(assignment)
                        new_assignment[base_name][slot] = gear
                        new_used_gear  = used_gear | {gear}

                        new_score, _, _ = _eval(new_assignment)
                        heapq.heappush(
                            next_beam,
                            (-new_score, counter, new_assignment, new_used_gear)
                        )
                        counter += 1

        beam = heapq.nsmallest(beam_width, next_beam)

        if iteration % 5 == 0 and beam:
            best_in_beam = -beam[0][0]
            print(f"  Iteration {iteration}/{max_iterations}: "
                  f"Best = {_fmt(best_in_beam, objective)}")

    best_score      = -best_ever[0]
    best_assignment = best_ever[1]
    return best_assignment, best_score

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

def adaptive_gear_assignment(team, gear_pool, prefilter_top_k=5,
                             max_iterations=50, temperature=100,
                             cooling_rate=0.975,
                             objective="max_damage", threshold=None, n_bins=300):
    """
    Simulated annealing gear assignment.

    Now accepts objective/threshold/n_bins and passes them down to
    evaluate_team_with_gear so the SA landscape matches the real objective.
    """

    def _eval(assignment):
        score, chain, seq = evaluate_team_with_gear(
            team, assignment,
            objective=objective, threshold=threshold, n_bins=n_bins
        )
        return score, chain, seq

    # Start with greedy assignment (greedy always uses max_damage heuristic —
    # stat_value_for_character is damage-based and remains a valid initialiser
    # even for threshold mode since it still selects high-stat gear).
    best_assignment, _ = greedy_gear_assignment(team, gear_pool, prefilter_top_k)
    best_score, _, _ = _eval(best_assignment)

    if len(team) <= 5 or len(gear_pool) <= len(team) * 3:
        return best_assignment, best_score

    current_assignment = shallow_copy_assignment(best_assignment)
    current_score = best_score

    temp = temperature
    stagnation_counter = 0

    for iteration in range(max_iterations):
        perturbed_assignment = shallow_copy_assignment(current_assignment)

        # More aggressive perturbations when stuck
        if stagnation_counter > 5:
            num_perturbations = min(5, max(2, int(temp / 25)))
        else:
            num_perturbations = min(3, max(1, int(temp / 50)))

        for _ in range(num_perturbations):
            base_names = [
                name for name in perturbed_assignment
                if any(g is not None for g in perturbed_assignment[name].values())
            ]
            if not base_names:
                break

            base_name = random.choice(base_names)
            char_slots = [
                slot for slot, gear in perturbed_assignment[base_name].items()
                if gear is not None
            ]
            if not char_slots:
                continue

            slot_to_perturb = random.choice(char_slots)
            current_gear    = perturbed_assignment[base_name][slot_to_perturb]

            currently_used = {
                g for slots in perturbed_assignment.values()
                for g in slots.values() if g is not None
            }

            base_character = next(
                c for c in team if c.get_base_character() == base_name
            )
            eligible_gear = [
                g for g in gear_pool
                if g.slot == slot_to_perturb
                and g != current_gear
                and g not in currently_used
                and g.can_equip_to(base_name)
            ]

            if eligible_gear:
                if stagnation_counter > 5:
                    new_gear = (
                        random.choice(eligible_gear) if random.random() < 0.7
                        else max(eligible_gear,
                                 key=lambda g: g.stat_value_for_character(base_character))
                    )
                else:
                    new_gear = (
                        random.choice(eligible_gear) if random.random() < temp / temperature
                        else max(eligible_gear,
                                 key=lambda g: g.stat_value_for_character(base_character))
                    )
                perturbed_assignment[base_name][slot_to_perturb] = new_gear

        perturbed_score, _, _ = _eval(perturbed_assignment)
        score_diff = perturbed_score - current_score

        if score_diff > 0:
            current_assignment = perturbed_assignment
            current_score      = perturbed_score
            stagnation_counter = 0
            if perturbed_score > best_score:
                best_assignment = perturbed_assignment
                best_score      = perturbed_score
        else:
            stagnation_counter += 1
            if temp > 0 and random.random() < np.exp(score_diff / (temp + 1e-9)):
                current_assignment = perturbed_assignment
                current_score      = perturbed_score
                stagnation_counter = 0

        temp *= cooling_rate
        if stagnation_counter > 15:
            break

    return best_assignment, best_score


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
                                    initial_temp=2500, cooling_rate=0.97,
                                    min_temp=1000, iterations_per_temp=400,
                                    fixed_core=None,
                                    gear_method="adaptive_sa",
                                    gear_preset="fast",
                                    objective="max_damage",
                                    threshold=None):
    """
    Simulated annealing for team composition.

    objective/threshold are threaded down to optimize_gear_for_team so that
    every team evaluation uses the correct scoring function.
    """
    print(f"  Simulated annealing "
          f"(temp={initial_temp}->{min_temp}, rate={cooling_rate}, "
          f"gear={gear_method}, objective={objective})...")

    preset_cfg  = GEAR_METHOD_PRESETS.get(gear_preset, {})
    n_bins_sa   = preset_cfg.get("n_bins_sa",   300)

    prefilter_k = determine_prefilter_k(len(gear_pool))

    if fixed_core:
        available_roster = [c for c in roster if c not in fixed_core]
        slots_to_fill    = team_size - len(fixed_core)
    else:
        available_roster = roster
        slots_to_fill    = team_size

    def _eval_team(team):
        return optimize_gear_for_team(
            team, gear_pool,
            method=gear_method,
            preset=gear_preset,
            prefilter_top_k=prefilter_k,
            objective=objective,
            threshold=threshold,
            n_bins=n_bins_sa,
        )

    def create_random_team():
        remaining = random.sample(available_roster, slots_to_fill)
        return (fixed_core + remaining) if fixed_core else remaining

    current_team                    = create_random_team()
    current_assignment, current_score = _eval_team(current_team)

    best_team       = current_team.copy()
    best_score      = current_score
    best_assignment = shallow_copy_assignment(current_assignment)

    temperature                      = initial_temp
    iteration                        = 0
    stagnation_counter               = 0
    last_best_score                  = 0
    total_iter_without_improvement   = 0
    perfect_solution_found           = False
    results = [(current_score, current_team.copy())]

    while temperature > min_temp and not perfect_solution_found:
        print(f"    Temperature {temperature:.1f}: Best = {_fmt(best_score, objective)}")

        if best_score == last_best_score:
            stagnation_counter             += 1
            total_iter_without_improvement += 1
        else:
            stagnation_counter             = 0
            last_best_score                = best_score
            total_iter_without_improvement = 0

        if total_iter_without_improvement > 12:
            print(f"    Early termination: no improvement for "
                  f"{total_iter_without_improvement} temperature levels")
            break

        for _ in range(iterations_per_temp):
            iteration += 1
            neighbor_team = current_team.copy()

            if fixed_core:
                non_core_indices = [
                    i for i, c in enumerate(neighbor_team)
                    if c not in fixed_core
                ]
                if non_core_indices:
                    replace_idx = random.choice(non_core_indices)
                    available_for_swap = [
                        c for c in available_roster if c not in neighbor_team
                    ]
                    if available_for_swap:
                        neighbor_team[replace_idx] = random.choice(available_for_swap)
            else:
                replace_idx = random.randint(0, len(neighbor_team) - 1)
                available_for_swap = [
                    c for c in available_roster if c not in neighbor_team
                ]
                if available_for_swap:
                    neighbor_team[replace_idx] = random.choice(available_for_swap)

            neighbor_assignment, neighbor_score = _eval_team(neighbor_team)
            score_diff = neighbor_score - current_score

            # Early termination check - check best_score, not just neighbor_score
            # Use slightly less than 1.0 to account for floating-point precision
            if objective == "exceed_threshold" and best_score >= 0.999999:
                print(f"    🎯 Perfect threshold probability achieved! Early termination.")
                # Ensure the perfect team is added to results before terminating
                results.append((
                    best_score,
                    best_team.copy(),
                    shallow_copy_assignment(best_assignment)
                ))
                perfect_solution_found = True
                break

            if score_diff > 0:
                current_team       = neighbor_team
                current_score      = neighbor_score
                current_assignment = neighbor_assignment
                if neighbor_score > best_score:
                    best_team       = neighbor_team.copy()
                    best_score      = neighbor_score
                    best_assignment = shallow_copy_assignment(neighbor_assignment)
            else:
                # Accept worse solutions with probability based on temperature
                if temperature > 0:
                    accept_prob = np.exp(score_diff / (temperature + 1e-9))
                    if random.random() < accept_prob:
                        current_team       = neighbor_team
                        current_score      = neighbor_score
                        current_assignment = neighbor_assignment

            if iteration % 50 == 0:
                results.append((
                    current_score,
                    current_team.copy(),
                    shallow_copy_assignment(current_assignment)
                ))

        temperature *= cooling_rate

    print(f"    Final best: {_fmt(best_score, objective)}")
    results.sort(reverse=True, key=lambda x: x[0])
    return results, best_assignment


def _fmt(score, objective):
    """Format a score value for console output."""
    if objective == "exceed_threshold":
        return f"{score*100:.2f}% threshold probability"
    return f"{score:,.0f} damage"

def optimize_gear_for_team(team, gear_pool, method="adaptive_sa", preset="balanced",
                           prefilter_top_k=5, objective="max_damage",
                           threshold=None, n_bins=300, **kwargs):
    """
    Unified gear optimisation interface.

    New parameters
    --------------
    objective : "max_damage" | "exceed_threshold"
    threshold : float — required when objective="exceed_threshold"
    n_bins    : int   — convolution resolution for threshold mode
    """
    params = GEAR_METHOD_PRESETS.get(preset, {}).get(method, {})
    params.update(kwargs)

    if method == "adaptive_sa":
        return adaptive_gear_assignment(
            team, gear_pool, prefilter_top_k,
            objective=objective, threshold=threshold, n_bins=n_bins,
            **params
        )
    else:
        raise ValueError(f"Unknown gear optimisation method: {method}")

def optimize_team_with_beam_search(roster, gear_pool, team_size=20,
                                   beam_width=200, fixed_core=None,
                                   use_simulated_annealing=True,
                                   sa_initial_temp=2500, sa_cooling_rate=0.97,
                                   sa_min_temp=1000,
                                   bs_iteration_multiplier=5.0,
                                   gear_method="adaptive_sa",
                                   gear_preset="fast",
                                   objective="max_damage",
                                   threshold=None):
    """
    Two-stage optimisation: SA team search → beam search gear assignment.

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
    objective  : "max_damage" | "exceed_threshold"
    threshold  : float — required when objective="exceed_threshold"

    When objective="exceed_threshold":
    - SA inner loop uses n_bins_sa   (low resolution, fast)
    - Beam search uses   n_bins_beam (higher resolution, accurate final ranking)
    Both values come from GEAR_METHOD_PRESETS[gear_preset].
    """
    from math import comb

    if objective == "exceed_threshold" and threshold is None:
        raise ValueError("threshold is required when objective='exceed_threshold'")

    preset_cfg  = GEAR_METHOD_PRESETS.get(gear_preset, {})
    n_bins_sa   = preset_cfg.get("n_bins_sa",   300)
    n_bins_beam = preset_cfg.get("n_bins_beam", 1000)
    
    # For threshold optimization, use higher resolution in SA to avoid false positives
    if objective == "exceed_threshold":
        n_bins_sa = n_bins_beam  # Use same resolution for consistency

    if fixed_core:
        available_count    = len(roster) - len(fixed_core)
        slots_to_fill      = team_size - len(fixed_core)
        total_combinations = comb(available_count, slots_to_fill)
    else:
        total_combinations = comb(len(roster), team_size)

    print(f"  Total possible teams: {total_combinations:,}")

    prefilter_k = determine_prefilter_k(len(gear_pool))

    print(" Stage 1: Finding promising teams...")
    if use_simulated_annealing:
        quick_results, stage1_best_assignment = simulated_annealing_team_search(
            roster, gear_pool, team_size,
            sa_initial_temp, sa_cooling_rate, sa_min_temp,
            fixed_core=fixed_core,
            gear_method=gear_method,
            gear_preset=gear_preset,
            objective=objective,
            threshold=threshold,
        )
    else:
        # Random sampling fallback (unchanged from original)
        if fixed_core:
            available_roster = [c for c in roster if c not in fixed_core]
            slots_to_fill = team_size - len(fixed_core)
            print(f"  Fixed core: {', '.join(c.name for c in fixed_core)}")
            print(f"  Filling {slots_to_fill} remaining slots from {len(available_roster)} characters")
        else:
            available_roster = roster
            slots_to_fill    = team_size

        sample_size = max(100, min(int(total_combinations * 0.2), 100000))
        quick_results            = []
        stage1_best_assignment   = None
        best_stage1_score        = 0

        for i in range(sample_size):
            remaining_chars = random.sample(available_roster, slots_to_fill)
            team = (fixed_core + remaining_chars) if fixed_core else remaining_chars

            assignment, score = optimize_gear_for_team(
                team, gear_pool,
                method=gear_method, preset=gear_preset,
                prefilter_top_k=prefilter_k,
                objective=objective, threshold=threshold, n_bins=n_bins_sa,
            )
            quick_results.append((score, team, assignment))
            if score > best_stage1_score:
                best_stage1_score      = score
                stage1_best_assignment = shallow_copy_assignment(assignment)

            if (i + 1) % 500 == 0:
                print(f"  Sampled {i + 1}/{sample_size} teams...")

    quick_results.sort(reverse=True, key=lambda x: x[0])
    best_team = quick_results[0][1] if quick_results else []
    
    # Extract best assignment - handle both SA and random sampling paths
    if use_simulated_annealing and stage1_best_assignment is not None:
        # SA path: assignment is passed separately
        best_assignment_from_stage1 = stage1_best_assignment
    elif quick_results and len(quick_results[0]) > 2:
        # Random sampling path: assignment is in the tuple
        best_assignment_from_stage1 = quick_results[0][2]
    else:
        best_assignment_from_stage1 = None

    print(f"\n  Stage 2: Beam search gear optimisation for the best team...\n")
    if not best_team:
        print("  No teams found in Stage 1!")
        return []
    
    # Stage 2 uses higher resolution bins for final scoring
    best_assignment, best_score = beam_search_gear_optimization(
        best_team, gear_pool,
        beam_width=beam_width,
        prefilter_top_k=prefilter_k,
        initial_assignment=best_assignment_from_stage1,
        iteration_multiplier=bs_iteration_multiplier,
        objective=objective,
        threshold=threshold,
        n_bins=n_bins_beam,
    )

    # Fill empty slots (always uses damage internally — structural, not scoring)
    empty_count = sum(
        1 for slots in best_assignment.values()
        for g in slots.values() if g is None
    )
    if empty_count > 0:
        print(f"  Found {empty_count} empty slots, filling...")
        best_assignment, filled_count, _ = beam_search_fill_empty_slots(
            best_team, gear_pool, best_assignment,
            beam_width=max(20, beam_width // 4),
            prefilter_top_k=0,
        )
        print(f"  Filled {filled_count} slots")

    # Final evaluation — always use high-res bins and also compute damage for report
    print("  Computing final stats...")
    
    # Primary evaluation for threshold mode
    final_prob, chain, sequence = evaluate_team_with_gear(
        best_team, best_assignment,
        objective=objective, threshold=threshold, n_bins=n_bins_beam
    )
    
    # Also compute raw damage for reporting (reuse sequence from above)
    damage, _, _ = evaluate_team_with_gear(
        best_team, best_assignment, objective="max_damage"
    )

    final_results = [{
        'team':                best_team,
        'sequence':            sequence,
        'gear_assignment':     best_assignment,
        'damage':              damage,
        'chain':               chain,
        'threshold_probability': final_prob if objective == "exceed_threshold" else None,
        'threshold':           threshold,
    }]

    if objective == "exceed_threshold":
        print(f"  Final: P(D > {threshold:,.0f}) = {final_prob*100:.2f}%  "
              f"| Full-crit damage = {damage:,.0f}\n")
    else:
        print(f"  Final damage: {damage:,.0f}\n")

    return final_results

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
    
    for char in sequence:
        # Per-character effective rate: character's base crit_rate + team buffs + personal temp buff (halved)
        char_crit_rate = min(
            char.crit_rate + team_buffs.get("crit_rate", 0) + char.temp_buffs.get("crit_rate", 0) / 2,
            1.0
        )
        
        # Use same calculations as calculate_actual_damage
        single_hit = calculate_single_hit(char, team_buffs, support_bonus)
        chain_mult = calculate_chain_multiplier(team_buffs, char.temp_buffs)
        crit_mult = calculate_crit_multiplier(char, team_buffs)
        
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
            # Create chain bonus array for this character's hits - same as calculate_actual_damage
            hit_chains = current_chain + np.arange(num_hits) * data['chain_mult']
            chain_bonuses = hit_chains * 0.1 + 1
            
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

def simulate_crit_distribution(sequence, team_buffs, n_simulations=60_000, support_bonus=None):
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

    # Calculate average base crit rate from characters for team display
    if sequence:
        avg_base_crit_rate = sum(char.crit_rate for char in sequence) / len(sequence)
        team_crit_rate = min(avg_base_crit_rate + team_buffs.get("crit_rate", 0), 1.0)
    else:
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
        temp_atk_buff = char.temp_buffs.get('ATK%', 2)
        temp_matk_buff = char.temp_buffs.get('MATK%', 2)
        buff_count = current_buffs.get('buff_count', 0)
        
        atk, damage_type_buff, ratio = cached_calculate_damage_stats(
            char.name, char_atk, char_damage_type, char_ratio, buffs_key,
            temp_atk_buff, temp_matk_buff, buff_count
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
        # Recalculate damage after greedy fallback to ensure consistency
        from sim import evaluate_team_with_gear
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


def probability_exceed_threshold_fft(sequence, team_buffs, threshold, 
                                      support_bonus=None, n_bins=2000):
    """
    Exact P(D > threshold) via FFT convolution of per-hit distributions.
    Handles heterogeneous crit rates and damage values correctly.
    ~100-500x faster than MC, exact up to discretization error.
    """
    import config
    if support_bonus is None:
        support_bonus = config.support_bonus

    # Collect all (p_i, d_crit_i, d_non_crit_i) per hit
    hits = []
    current_chain = 0

    for char in sequence:
        # Use character's actual crit_rate + team buffs + temp buffs
        p_i = min(char.crit_rate + team_buffs.get("crit_rate", 0) + char.temp_buffs.get("crit_rate", 0) / 2, 1.0)
        crit_mult  = calculate_crit_multiplier(char, team_buffs)
        chain_mult = calculate_chain_multiplier(team_buffs, char.temp_buffs)
        single_hit = calculate_single_hit(char, team_buffs, support_bonus)
        base_hit   = single_hit / crit_mult

        for h in range(char.hits):
            chain_bonus = current_chain * 0.1 + 1
            hits.append((p_i, single_hit * chain_bonus, base_hit * chain_bonus))
            current_chain += chain_mult

    if not hits:
        return 0.0

    # Discretize damage range
    max_possible = sum(d_crit for _, d_crit, _ in hits)
    if max_possible <= 0:
        return 0.0
    
    bin_size = max_possible / n_bins
    
    # Start with a point mass at 0
    pmf = np.zeros(n_bins + 1)
    pmf[0] = 1.0

    # Convolve each hit's two-point distribution into the running PMF
    for p_i, d_crit, d_non in hits:
        # Replace int() with round() — unbiased rounding
        bin_crit = min(round(d_crit / bin_size), n_bins)
        bin_non  = min(round(d_non  / bin_size), n_bins)

        new_pmf = np.zeros(n_bins + 1)
        # Non-crit branch - shift right by bin_non with probability (1-p_i)
        if bin_non < n_bins + 1:
            new_pmf[bin_non:] += (1 - p_i) * pmf[:n_bins + 1 - bin_non]
        # Crit branch - shift right by bin_crit with probability p_i  
        if bin_crit < n_bins + 1:
            new_pmf[bin_crit:] += p_i * pmf[:n_bins + 1 - bin_crit]

        pmf = new_pmf

    # P(D > threshold)
    threshold_bin = round(threshold / bin_size)
    if threshold_bin >= n_bins:
        return 0.0
    
    probability = float(pmf[threshold_bin + 1:].sum())
    
    # Ensure probability is within valid bounds [0, 1]
    probability = max(0.0, min(1.0, probability))
    
    return probability


def optimize_for_threshold(roster, gear_pool, threshold, team_size=20,
                           beam_width=200, fixed_core=None,
                           gear_preset="balanced"):
    """
    Optimise team composition and gear to maximise P(D > threshold).

    This is a thin wrapper around optimize_team_with_beam_search that sets
    objective="exceed_threshold" from the very first SA step, ensuring the
    entire search landscape — including which buffers and crit-rate providers
    are favoured — reflects the true goal rather than full-crit damage.

    Parameters
    ----------
    threshold : float
        Target damage value. Typically set to 70–90% of a reference
        full-crit score, e.g. from a prior max_damage run.

    Returns
    -------
    list of result dicts, each containing:
        damage                — full-crit damage (for reference)
        threshold_probability — P(D > threshold) estimated by FFT convolution
        threshold             — the threshold used
        sequence, gear_assignment, chain — as usual
    """
    print(f"\n{'='*70}")
    print(f"THRESHOLD OPTIMISATION")
    print(f"{'='*70}")
    print(f"  Target threshold : {threshold:,.0f}")
    print(f"  Preset           : {gear_preset}")
    print(f"  Objective        : P(D > threshold) via FFT convolution")
    print()

    return optimize_team_with_beam_search(
        roster, gear_pool,
        team_size=team_size,
        beam_width=beam_width,
        fixed_core=fixed_core,
        gear_method="adaptive_sa",
        gear_preset=gear_preset,
        objective="exceed_threshold",
        threshold=threshold,
    )
