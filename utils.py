"""
Utility functions to reduce code duplication across the codebase.
"""

from typing import Dict, List, Set, Tuple
from copy import deepcopy


def get_unique_base_characters(team):
    """
    Extract unique base characters from a team.
    
    Args:
        team: List of Character objects
        
    Returns:
        Dict mapping base character name to representative Character object
    """
    attackers = [c for c in team if c.hits > 0]
    base_characters = {}
    for char in attackers:
        base_name = char.get_base_character()
        if base_name not in base_characters:
            base_characters[base_name] = char
    return base_characters


def organize_gear_by_slot(gear_list):
    """
    Organize gear pieces by their slot.
    
    Args:
        gear_list: List of Gear objects
        
    Returns:
        Dict mapping slot name to list of Gear objects
    """
    gear_by_slot = {}
    for gear in gear_list:
        if gear.slot not in gear_by_slot:
            gear_by_slot[gear.slot] = []
        gear_by_slot[gear.slot].append(gear)
    return gear_by_slot

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

def calculate_damage_stats(char, team_buffs):
    """
    Calculate damage statistics for a character.
    
    Args:
        char: Character object
        team_buffs: Dict of team buffs
        
    Returns:
        Tuple of (attack, damage_type_buff, ratio_per_hit)
    """
    if char.damage_type == "Max HP":
        atk = 50000
        damage_type_buff = 1
    elif char.damage_type == "MATK":
        atk = char.atk
        damage_type_buff = team_buffs.get('MATK%', 1) * (char.temp_buffs.get('MATK%', 2) / 2)
    else:  # ATK
        atk = char.atk
        damage_type_buff = team_buffs.get('ATK%', 1) * (char.temp_buffs.get('ATK%', 2) / 2)
    
    # Handle special character cases
    ratio = char.ratio_per_hit
    if char.name == "NH Nebris":
        ratio = 0.2 * team_buffs.get('buff_count', 0)
    
    return atk, damage_type_buff, ratio


def get_eligible_gear_for_character(gear_list, base_character_name):
    """
    Get gear that can be equipped to a specific character.
    
    Args:
        gear_list: List of Gear objects
        base_character_name: Base character name
        
    Returns:
        List of Gear objects that can be equipped
    """
    return [g for g in gear_list if g.can_equip_to(base_character_name)]


def determine_prefilter_k(gear_pool_size):
    """
    Determine prefilter_k value based on gear pool size.
    
    Args:
        gear_pool_size: Number of gear pieces in pool
        
    Returns:
        Integer prefilter_k value
    """
    if gear_pool_size < 30:
        return 13
    elif gear_pool_size < 60:
        return 8
    else:
        return 5


def initialize_gear_assignment(base_characters, slots):
    """
    Initialize empty gear assignment dictionary.
    
    Args:
        base_characters: Dict of base character names to Character objects
        slots: List of slot names
        
    Returns:
        Dict mapping base character name to dict of slot: None
    """
    return {base_name: {slot: None for slot in slots} 
            for base_name in base_characters.keys()}


def calculate_crit_multiplier(char, team_buffs):
    """
    Calculate critical damage multiplier for a character.
    
    Args:
        char: Character object
        team_buffs: Dict of team buffs
        
    Returns:
        Critical damage multiplier value
    """
    return (char.crit_dmg + team_buffs.get('crit_dmg', 0) + 
            char.temp_buffs.get('crit_dmg', 0) / 2)


def calculate_chain_multiplier(team_buffs, char_temp_buffs):
    """
    Calculate chain multiplier for damage calculations.
    
    Args:
        team_buffs: Dict of team buffs
        char_temp_buffs: Dict of character temporary buffs
        
    Returns:
        Chain multiplier value
    """
    if team_buffs.get("chain_count") or char_temp_buffs.get("chain_count") is not None:
        return 1 + team_buffs.get("chain_count", 0) + char_temp_buffs.get("chain_count", 0)
    return 1


def get_attackers_and_buffers(team):
    """
    Separate team into attackers and buffers.
    
    Args:
        team: List of Character objects
        
    Returns:
        Tuple of (buffers_list, attackers_list)
    """
    buffers = []
    attackers = []
    
    for char in team:
        if char.buffs:
            buffers.append(char)
        else:
            attackers.append(char)
    
    return buffers, attackers
