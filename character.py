class Character:
    def __init__(self, name, damage_type, atk, crit_dmg, ratio_per_hit, hits, buffs=None, temp_buffs=None):
        self.name = name
        self.damage_type = damage_type
        self.base_atk = atk  # Store base stats separately
        self.base_crit_dmg = crit_dmg  # Store raw base crit_dmg value
        self.atk = atk
        self.crit_dmg = crit_dmg  # Will be recalculated properly in _recalculate_stats
        self.buffs = buffs if buffs is not None else []       # list of (buff_type, value) tuples
        self.temp_buffs = temp_buffs if temp_buffs is not None else {}  # dict; per-character, no duplicates
        self.ratio_per_hit = ratio_per_hit
        self.hits = hits
        self.equipped_gear = {
            "weapon": None,
            "head": None,
            "armor": None,
            "accessory": None,
            "glove": None
        }
        
        # Initialize stats properly
        self._recalculate_stats()
    
    def __repr__(self):
        return self.name
    
    def __hash__(self):
        return hash(self.name)
    
    def get_base_character(self):
        """
        Extract base character name from costume name.
        E.g., "WPQ Wilhelmina" -> "Wilhelmina"
              "Bride Eclipse" -> "Eclipse"
        """
        # Split by space and take the last word as base name
        parts = self.name.split()
        return parts[-1]
    
    def equip_gear(self, gear_piece):
        """Equip a gear piece in its appropriate slot."""
        if self.equipped_gear[gear_piece.slot] is not None:
            raise ValueError(f"{self.name} already has {gear_piece.slot} equipped!")
        self.equipped_gear[gear_piece.slot] = gear_piece
        self._recalculate_stats()
    
    def unequip_slot(self, slot):
        """Remove gear from a specific slot."""
        self.equipped_gear[slot] = None
        self._recalculate_stats()
    
    def unequip_all_gear(self):
        """Remove all gear and reset to base stats."""
        for slot in self.equipped_gear:
            self.equipped_gear[slot] = None
        self._recalculate_stats()
    
    def _recalculate_stats(self):
        """Recalculate stats based on base stats + all equipped gear."""
        # Start with base stats
        total_flat_atk = self.base_atk if self.damage_type == "ATK" else 0
        total_flat_matk = self.base_atk if self.damage_type == "MATK" else 0
        total_atk_percent = 0
        total_matk_percent = 0
        total_crit_dmg = self.base_crit_dmg
        
        # Apply all gear bonuses
        for slot, gear in self.equipped_gear.items():
            if gear is not None:
                total_flat_atk += gear.flat_atk
                total_flat_matk += gear.flat_matk
                total_atk_percent += gear.atk_percent
                total_matk_percent += gear.matk_percent
                total_crit_dmg += gear.crit_dmg
        
        # Calculate final stats
        if self.damage_type == "MATK":
            self.atk = total_flat_matk * (1 + total_matk_percent)
        elif self.damage_type == "ATK":
            self.atk = total_flat_atk * (1 + total_atk_percent)
        else:  # Max HP
            self.atk = self.base_atk
        
        self.crit_dmg = total_crit_dmg + 1
    
    def copy(self):
        """Create a deep copy of this character."""
        new_char = Character(
            self.name, self.damage_type, self.base_atk, self.base_crit_dmg,
            self.ratio_per_hit, self.hits, list(self.buffs), dict(self.temp_buffs)
        )
        # Note: Gear objects are immutable, so we can safely reference them
        for slot, gear in self.equipped_gear.items():
            new_char.equipped_gear[slot] = gear
        new_char._recalculate_stats()
        return new_char