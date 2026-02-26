# Simulation functions
def calculate_single_hit(char, team_buffs):
    if char.damage_type == "Max HP":
        atk = 50000
        damage_type_buff = 1
    elif char.damage_type == "MATK":
        atk = char.atk
        damage_type_buff = team_buffs.get('MATK%', 1) * (char.temp_buffs.get('MATK%', 2) / 2)
    else:  # ATK
        atk = char.atk
        damage_type_buff = team_buffs.get('ATK%', 1) * (char.temp_buffs.get('ATK%', 2) / 2)
        
    if char.name == "NH Nebris":
        char.ratio_per_hit = 0.2 * team_buffs.get('buff_count')
    
    total_single_hit = round(damage_type_buff * atk) * (char.crit_dmg + team_buffs.get('crit_dmg', 0) +
            (char.temp_buffs.get('crit_dmg', 0)) / 2) * (team_buffs.get('overall', 1)) * char.ratio_per_hit
    
    return floor(total_single_hit)


def calculate_actual_damage(sequence, current_team_buffs):
    """Simulates the rotation to find the exact final damage number."""
    total_damage = 0
    current_chain = 0
    chain_mult = 1
    for char in sequence:
        if current_team_buffs.get("chain_count") or char.temp_buffs.get("chain_count") is not None:
            chain_mult = 1 + current_team_buffs.get("chain_count", 0) + char.temp_buffs.get('chain_count', 0)
        for _ in range(char.hits):
            total_damage += calculate_single_hit(char, current_team_buffs) * (current_chain * 0.1 + 1)
            current_chain += 1 * chain_mult
    
    return total_damage, current_chain


def rotation_optimizer(current_buffs, team):
    """
    Optimized rotation algorithm based on key insight:
    
    HIGH DAMAGE-PER-HIT characters should go LATE to benefit from chain.
    LOW DAMAGE-PER-HIT characters should go EARLY to build chain.
    
    This is because total damage = sum of (damage_per_hit × chain_multiplier).
    The character with highest damage_per_hit benefits most from high chain.
    
    Strategy:
    1. Calculate damage per hit for each character
    2. Sort by damage per hit (ascending)
    3. Low damage/hit first (chain builders), high damage/hit last (chain users)
    """
    if not team:
        return []
    
    # Calculate damage per hit for each character
    char_priorities = []
    for char in team:
        if char.hits > 0:
            damage_per_hit = calculate_single_hit(char, current_buffs)
            total_damage_potential = damage_per_hit * char.hits
            
            # Priority: characters with HIGH damage per hit go LATE
            # So we sort by damage_per_hit ascending (low first, high last)
            char_priorities.append((damage_per_hit, total_damage_potential, char))
        else:
            # Buffers (0 hits) have no damage, should go first
            char_priorities.append((0, 0, char))
    
    # Sort by damage per hit (ascending): low damage/hit first, high damage/hit last
    # Tiebreaker: if same damage/hit, prefer higher total damage potential last
    char_priorities.sort(key=lambda x: (x[0], x[1]))
    
    # Return sorted sequence
    sequence = [char for _, _, char in char_priorities]
    return sequence




def calculate_team_buffs(team):
    """Extract and calculate team buffs from a team composition."""
    team_buffs = {
        "ATK%": 1,
        "MATK%": 1,
        "overall": 1,
        "crit_dmg": 0,
        "chain_count": 1,
        "crit_rate": 0,
        "buff_count": 0
    }
    
    for char in team:
        if char.buffs:
            for buff_type, value in char.buffs:
                team_buffs["buff_count"] += 1
                if buff_type == "chain_count" or buff_type == "overall":
                    team_buffs[buff_type] += value
                elif team_buffs.get(buff_type, None) is None:
                    continue
                else:
                    team_buffs[buff_type] += value / 2
    
    return team_buffs


def separate_buffers_attackers(team):
    """Separate team into buffers and attackers."""
    buffers = []
    attackers = []
    
    for char in team:
        if char.buffs:
            buffers.append(char)
        else:
            attackers.append(char)
    
    return buffers, attackers


def apply_exclusive_gear(team, gear_pool):
    """
    Pre-assign exclusive gear to their designated characters.
    
    Returns:
        initial_assignment: Dict with exclusive gear already assigned
        remaining_gear: List of non-exclusive gear still to be assigned
    """
    # Get unique base characters in team
    attackers = [c for c in team if c.hits > 0]
    base_characters = {}
    for char in attackers:
        base_name = char.get_base_character()
        if base_name not in base_characters:
            base_characters[base_name] = char
    
    # Organize gear by slot
    gear_by_slot = {}
    for gear in gear_pool:
        if gear.slot not in gear_by_slot:
            gear_by_slot[gear.slot] = []
        gear_by_slot[gear.slot].append(gear)
    
    slots = list(gear_by_slot.keys())
    
    # Initialize empty assignment
    initial_assignment = {char.get_base_character(): {slot: None for slot in slots} 
                         for char in base_characters.values()}
    
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
    
#     if exclusive_count > 0:
#         print(f"  ✓ Pre-assigned {exclusive_count} exclusive gear pieces")
    
    return initial_assignment, remaining_gear


def prefilter_gear_for_team(team, remaining_gear, top_k_per_slot,
                             baseline_assignment=None):
    """
    baseline_assignment: the exclusive-only assignment from apply_exclusive_gear.
    When provided, uncovered (char, slot) pairs are filled by actual damage
    delta rather than the stat_value_for_character heuristic.
    """
    attackers = [c for c in team if c.hits > 0]
    base_characters = {}
    for char in attackers:
        base_name = char.get_base_character()
        if base_name not in base_characters:
            base_characters[base_name] = char
    unique_bases = list(base_characters.values())

    gear_by_slot = {}
    for gear in remaining_gear:
        gear_by_slot.setdefault(gear.slot, []).append(gear)

    gear_to_keep = set()

    # ── Main filter: top-k by heuristic ──────────────────────────────────────
    for slot, gears in gear_by_slot.items():
        for char in unique_bases:
            base_name = char.get_base_character()
            eligible = [g for g in gears if g.can_equip_to(base_name)]
            eligible.sort(key=lambda g: g.stat_value_for_character(char), reverse=True)
            for g in eligible[:top_k_per_slot]:
                gear_to_keep.add(g)

    # ── Floor guarantee: real damage delta for uncovered pairs ────────────────
    if baseline_assignment is not None:
        for char in unique_bases:
            base_name = char.get_base_character()
            for slot, gears in gear_by_slot.items():
                eligible = [g for g in gears if g.can_equip_to(base_name)]

                # Only act if this char×slot has zero survivors in the filtered set
                if not eligible or any(g in gear_to_keep for g in eligible):
                    continue

                # Evaluate baseline once (exclusive gear only, slot empty)
                baseline_dmg, _, _ = evaluate_team_with_gear(team, baseline_assignment)

                # Trial-equip each candidate and measure real damage delta
                best_gear, best_delta = None, -float("inf")
                for gear in eligible:
                    trial = deepcopy(baseline_assignment)
                    trial[base_name][slot] = gear
                    trial_dmg, _, _ = evaluate_team_with_gear(team, trial)
                    delta = trial_dmg - baseline_dmg
                    if delta > best_delta:
                        best_delta, best_gear = delta, gear

                if best_gear is not None:
                    gear_to_keep.add(best_gear)

    return list(gear_to_keep)


def evaluate_team_with_gear(team, gear_assignments, force_best_rotation=False):
    """
    Evaluate a team with specific gear assignments.
    gear_assignments: dict mapping BASE character name -> dict of {slot: Gear}
    force_best_rotation: If True, always use hill climbing regardless of team size
    
    Note: Gear is shared across all costumes of the same base character.
    E.g., "IM Wilhelmina" and "FQ Wilhelmina" both use gear assigned to "Wilhelmina"
    """
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
    buffers, attackers = separate_buffers_attackers(team_with_gear)
    
    sequence = rotation_optimizer(team_buffs, attackers)
    
    full_sequence = buffers + sequence
    damage, chain = calculate_actual_damage(full_sequence, team_buffs)
    
    return damage, chain, full_sequence


def beam_search_gear_optimization(team, gear_pool, beam_width=100, depth_limit=None, 
                                  prefilter_top_k=5):
    """
    Beam search for optimal gear assignment.
    
    Exclusive gear is automatically assigned first, then remaining gear is optimized.
    Gear is pre-filtered to keep only top candidates per character for speed.
    
    Args:
        team: List of Character objects
        gear_pool: List of Gear objects
        beam_width: Number of best candidates to keep at each step
        depth_limit: Maximum number of gear pieces to assign (None = all)
        prefilter_top_k: Keep top K gear pieces per slot per character (0 = no filtering)
    
    Returns:
        best_assignment: Dict of {base_char_name: {slot: Gear}}
        best_damage: Final damage value
    """
    # Filter out buffer characters (they don't benefit from gear)
    attackers = [c for c in team if c.hits > 0]
    
    # Get unique base characters (so we don't assign gear multiple times to same base)
    base_characters = {}
    for char in attackers:
        base_name = char.get_base_character()
        if base_name not in base_characters:
            base_characters[base_name] = char
    
    unique_bases = list(base_characters.values())

    # Pre-assign exclusive gear and get remaining gear pool
    initial_assignment, remaining_gear = apply_exclusive_gear(team, gear_pool)
    
    if prefilter_top_k > 0:
        filtered_remaining = prefilter_gear_for_team(
            team, remaining_gear,
            top_k_per_slot=prefilter_top_k,
            baseline_assignment=initial_assignment,   # ← enables real delta fallback
        )
    else:
        filtered_remaining = remaining_gear
    
    # Organize remaining gear by slot
    gear_by_slot = {}
    for gear in remaining_gear:
        if gear.slot not in gear_by_slot:
            gear_by_slot[gear.slot] = []
        gear_by_slot[gear.slot].append(gear)
    
    slots = list(gear_by_slot.keys()) if gear_by_slot else []
    
    # Evaluate initial damage with exclusive gear only
    initial_damage, _, _ = evaluate_team_with_gear(team, initial_assignment)
    
    # Priority queue: (negative_damage, counter, assignment, assigned_gear_set)
    counter = 0
    beam = [(-initial_damage, counter, initial_assignment, frozenset())]
    counter += 1
    
    print(f"  Starting beam search with {len(unique_bases)} unique base characters...")
    print(f"  (Total {len(attackers)} attacker costumes share gear)")
    print(f"  Remaining gear pool: {len(remaining_gear)} pieces (after filtering & exclusives)")
    
    # If no remaining gear to optimize, return the exclusive gear assignment
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
                best_ever = (neg_damage, deepcopy(assignment))
            
            # Try assigning each unused gear to each BASE character
            for slot in slots:
                if slot not in gear_by_slot:
                    continue
                    
                for gear in gear_by_slot[slot]:
                    # Skip if gear already used
                    if gear in used_gear:
                        continue
                    
                    # Try assigning to each unique base character
                    for base_char in unique_bases:
                        base_name = base_char.get_base_character()
                        
                        # Check if gear can be equipped to this character
                        if not gear.can_equip_to(base_name):
                            continue
                        
                        # Skip if this base character already has this slot filled
                        if assignment[base_name][slot] is not None:
                            continue
                        
                        # Create new assignment
                        new_assignment = deepcopy(assignment)
                        new_assignment[base_name][slot] = gear
                        new_used_gear = used_gear | {gear}
                        
                        # Evaluate
                        new_damage, _, _ = evaluate_team_with_gear(team, new_assignment)
                        
                        # Add to next beam with counter as tiebreaker
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



def smart_greedy_gear_assignment(team, gear_pool, prefilter_top_k=5):
    """
    Improved greedy: pre-sort gear by value, prioritize high-impact assignments.
    Gear is assigned to BASE characters and shared across costumes.
    Exclusive gear is pre-assigned automatically.
    Gear is pre-filtered for speed.
    """
    assignment, remaining_gear = apply_exclusive_gear(team, gear_pool)
    
    if prefilter_top_k > 0:
        filtered_remaining = prefilter_gear_for_team(
            team, remaining_gear,
            top_k_per_slot=prefilter_top_k,
            baseline_assignment=assignment,   # ← enables real delta fallback
        )
    else:
        filtered_remaining = remaining_gear
    
    # Organize remaining gear by slot
    gear_by_slot = {}
    for gear in remaining_gear:
        if gear.slot not in gear_by_slot:
            gear_by_slot[gear.slot] = []
        gear_by_slot[gear.slot].append(gear)
    
    slots = list(gear_by_slot.keys())
    attackers = [c for c in team if c.hits > 0]
    
    # Get unique base characters
    base_characters = {}
    for char in attackers:
        base_name = char.get_base_character()
        if base_name not in base_characters:
            base_characters[base_name] = char
    
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
                    # Only consider gear that can be equipped to this character
                    if gear.can_equip_to(base_name):
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
    Two-stage optimization:
    1. Sample random teams and quick-evaluate with greedy gear
    2. Use beam search for top teams
    
    Args:
        roster: List of all available characters
        gear_pool: List of all available gear
        team_size: Size of team to build
        beam_width: Beam width for optimization (default 200)
        num_teams_to_optimize: How many top teams to fully optimize
        fixed_core: List of characters that must be in every team
    """
    # Calculate optimal sample_size based on total combinations
    # Sample 20% of all possible team combinations
    if fixed_core:
        # Calculate combinations for remaining slots
        available_count = len(roster) - len(fixed_core)
        slots_to_fill = team_size - len(fixed_core)
        total_combinations = comb(available_count, slots_to_fill)
    else:
        total_combinations = comb(len(roster), team_size)
    
    sample_size = max(100, min(int(total_combinations * 0.2), 100000))  # Clamp between 100-5000
    
    print(f"  Total possible teams: {total_combinations:,}")
    print(f"  Sample size (20% of combinations): {sample_size:,}")
    
    # Determine pre-filtering aggressiveness based on gear pool size
    if len(gear_pool) < 30:
        prefilter_k = 8
    elif len(gear_pool) < 60:
        prefilter_k = 5
    else:
        prefilter_k = 3
    
    # If there's a fixed core, adjust roster and team_size for sampling
    if fixed_core:
        available_roster = [c for c in roster if c not in fixed_core]
        slots_to_fill = team_size - len(fixed_core)
        print(f"  Fixed core: {', '.join(c.name for c in fixed_core)}")
        print(f"  Filling {slots_to_fill} remaining slots from {len(available_roster)} characters")
    else:
        available_roster = roster
        slots_to_fill = team_size
    
    print("🔍 Stage 1: Finding promising teams...")
    
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
        
        # Quick evaluation with smart greedy (with pre-filtering)
        assignment, damage = smart_greedy_gear_assignment(team, gear_pool, prefilter_top_k=prefilter_k)
        quick_results.append((damage, team))
        
        if (i + 1) % 500 == 0:
            print(f"  Sampled {i + 1}/{sample_size} teams...")
    
    # Sort and keep top teams
    quick_results.sort(reverse=True, key=lambda x: x[0])
    top_teams = [team for _, team in quick_results[:num_teams_to_optimize]]
    
    print(f"\n⚙️  Stage 2: Beam search optimization for top {num_teams_to_optimize} teams...\n")
    
    final_results = []
    
    for idx, team in enumerate(top_teams):
        print(f"Team {idx + 1}/{num_teams_to_optimize}:")
        
        # Use beam search for this team (with pre-filtering)
        best_assignment, best_damage = beam_search_gear_optimization(
            team, gear_pool, beam_width=beam_width, prefilter_top_k=prefilter_k
        )
        
        # Get final sequence with BEST rotation (force hill climbing)
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
    hits = []
    current_chain = 0
    team_crit_rate = min(team_buffs.get("crit_rate", 0), 1.0)  # ← base team rate

    for char in sequence:
        # ↓ per-character effective rate: team base + personal temp buff (halved)
        char_crit_rate = min(
            team_crit_rate + char.temp_buffs.get("crit_rate", 0) / 2,
            1.0
        )

        chain_mult = 1
        if team_buffs.get("chain_count") or char.temp_buffs.get("chain_count") is not None:
            chain_mult = 1 + team_buffs.get("chain_count", 0) + char.temp_buffs.get("chain_count", 0)

        for _ in range(char.hits):
            chain_bonus = current_chain * 0.1 + 1

            if char.damage_type == "Max HP":
                atk = 50000
                dtb = 1.0
            elif char.damage_type == "MATK":
                atk = char.atk
                dtb = team_buffs.get("MATK%", 1) * (char.temp_buffs.get("MATK%", 2) / 2)
            else:
                atk = char.atk
                dtb = team_buffs.get("ATK%", 1) * (char.temp_buffs.get("ATK%", 2) / 2)

            # NH Nebris special case
            ratio = 0.2 * team_buffs.get("buff_count", 0) if char.name == "NH Nebris" else char.ratio_per_hit

            crit_mult = (char.crit_dmg
                         + team_buffs.get("crit_dmg", 0)
                         + char.temp_buffs.get("crit_dmg", 0) / 2)

            base_no_crit = floor(round(dtb * atk) * team_buffs.get("overall", 1) * ratio * chain_bonus)
            crit_d     = floor(round(dtb * atk) * crit_mult * team_buffs.get("overall", 1) * ratio * chain_bonus)
            non_crit_d = base_no_crit
            
            hits.append((crit_d, non_crit_d, char_crit_rate))
            current_chain += 1 * chain_mult

    return hits


def simulate_crit_distribution(sequence, team_buffs, n_simulations=60_000):
    hdata = _hits_data(sequence, team_buffs)
    if not hdata:
        return np.array([]), 0, min(team_buffs.get("crit_rate", 0), 1.0)

    crit_arr     = np.array([h[0] for h in hdata], dtype=np.float64)
    non_crit_arr = np.array([h[1] for h in hdata], dtype=np.float64)
    rate_arr     = np.array([h[2] for h in hdata], dtype=np.float64)  # ← per-hit rates
    full_damage  = int(crit_arr.sum())

    rolls = np.random.random((n_simulations, len(hdata)))
    crits = rolls < rate_arr  # ← broadcasts correctly: each column uses its own threshold
    totals = (crits * crit_arr + ~crits * non_crit_arr).sum(axis=1)
    fractions = totals / full_damage

    team_crit_rate = min(team_buffs.get("crit_rate", 0), 1.0)
    return fractions, full_damage, team_crit_rate