support_bonus: float = 1.0
NH_NEBRIS_RATIO_MULTIPLIER: float = 0.2

def set_support_bonus(value: float):
    global support_bonus
    support_bonus = value

def set_nh_nebris_ratio_multiplier(value: float):
    global NH_NEBRIS_RATIO_MULTIPLIER
    NH_NEBRIS_RATIO_MULTIPLIER = value
