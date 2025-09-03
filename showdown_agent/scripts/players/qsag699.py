from poke_env.battle import AbstractBattle, Pokemon, Move, MoveCategory, Weather, Effect, Status
from poke_env.player import Player
from poke_env.data import GenData

team = """
Arceus-Electric @ Zap Plate
Ability: Multitype
Tera Type: Flying
EVs: 252 hp / 4 spa / 252 spe 
Timid Nature
IVs: 0 atk 
- Judgment
- Ice Beam
- Calm Mind
- Recover

Palafin @ Leftovers
Ability: Zero to Hero
Tera Type: Fairy
EVs: 248 hp / 8 atk / 252 spd 
Careful Nature
- Jet Punch
- Bulk Up
- Drain Punch
- Taunt

Baxcalibur @ Loaded Dice
Ability: Thermal Exchange
Tera Type: Fairy
EVs: 252 atk / 4 spd / 252 spe 
Adamant Nature
- Icicle Spear
- Glaive Rush
- Earthquake
- Dragon Dance

Giratina @ Heavy-Duty Boots
Ability: Pressure
Tera Type: Fairy
EVs: 252 hp / 252 def / 4 spd 
Impish Nature
- Dragon Tail
- Will-O-Wisp
- Defog
- Rest

Zacian-Crowned @ Rusted Sword
Ability: Intrepid Sword
Tera Type: Fighting
EVs: 252 atk / 4 spd / 252 spe 
Jolly Nature
- Swords Dance
- Behemoth Blade
- Close Combat
- Wild Charge

Zamazenta-Crowned @ Rusted Shield
Ability: Dauntless Shield
EVs: 252 hp / 4 def / 252 spe 
Jolly Nature
- Body Press
- Iron Defense
- Rest
- Substitute
"""

###############
#  Constants  #
###############

TYPE_CHART = GenData.from_gen(9).type_chart

GUARANTEED_CRITICAL_MOVES = {"Storm Throw","Frost Breath","Zippy Zap","Surging Strikes","Wicked Blow","Flower Trick"}

#############
#  Utility  #
#############

# Calculate damage multiplier of an attack relative to the defending pokemon's type
def fetch_attack_multiplier(attack_type: str, attacking_types: list[str], attacking_ability: str, defending_types: list[str]) -> float:
    m = 1.0
    for defending_type in defending_types:
        m *= TYPE_CHART.get(attack_type, {}).get(defending_type, 1.0)
    
    if attack_type in attacking_types:
        if attacking_ability == "Adaptability":
            m *= 2.0
        else:
            m *= 1.5
            
    return m

# Fetch the pokemon's types and format into list
def fetch_pokemon_types(pokemon: Pokemon) -> list[str]:
    pokemon_types = []
    if pokemon.type_1:
        pokemon_types.append(pokemon.type_1.name)
    if pokemon.type_2:
        pokemon_types.append(pokemon.type_2.name)
    return pokemon_types

# Fetch the move's type as a string
def fetch_move_type(move: Move) -> str:
    if move.type and move.type.name:
        return move.type.name
    return "Normal"

# Fetch the move's name as a string
def fetch_move_name(move: Move) -> str:
    if move.name:
        return move.name
    return "Unknown Move"

##################
#  Calculations  #
##################

# Calculate the anticipated damage for a given move in the battle conditions
# Follows Bulbapedia equation for Gen V + (https://bulbapedia.bulbagarden.net/wiki/Damage)
def calculate_expected_damage(attacker: Pokemon, defender: Pokemon, move: Move, weather: Weather):
    def calculate_level_ratio(attacker: Pokemon) -> float:
        return ((2*attacker.level)/5) + 2
    
    def calculate_attack_defense_ratio(attacker: Pokemon, defender: Pokemon, move: Move) -> float:
        if move.category == MoveCategory.PHYSICAL:
            return attacker.stats["atk"] / defender.stats["def"]
        elif move.category == MoveCategory.SPECIAL:
            return attacker.stats["spa"] / defender.stats["spd"]
        return 1.0
    
    def calculate_base(attacker: Pokemon, defender: Pokemon, move: Move) -> float:
        return (calculate_level_ratio(attacker) * move.base_power * 
                calculate_attack_defense_ratio(attacker, defender, move) / 50) + 2

    def calculate_weather_bonus(move: Move, weather: Weather) -> float:
        move_name = fetch_move_name(move)
        move_type = fetch_move_type(move)
        if weather == Weather.PRIMORDIALSEA:
            if move_type == "Fire":  return 0.0
            if move_type == "Water": return 1.5
            return 1.0
        if weather == Weather.DESOLATELAND: 
            if move_type == "Water": return 0.0
            if move_type == "Fire":  return 1.5
            return 1.0
        if weather == Weather.RAINDANCE:
            if move_type == "Water": return 1.5
            if move_type == "Fire":  return 0.5
            return 1.0
        if weather == Weather.SUNNYDAY:
            if move_name == "Hydro Steam": return 1.5
            if move_type == "Fire":  return 1.5
            if move_type == "Water": return 0.5
            return 1.0
        return 1.0
    
    def calculate_glaive_bonus(defender: Pokemon) -> float:
        if Effect.GLAIVE_RUSH in defender.effects:
            return 2.0
        else:
            return 1.0
        
    def calculate_determined_critical_hit(attacker: Pokemon, defender: Pokemon, move: Move) -> float:
        if defender.ability == "Battle Armor" or defender.ability == "Shell Armor":
            return 1.0
        # TODO: Cant seem to find lucky chant effect
        if fetch_move_name(move) in GUARANTEED_CRITICAL_MOVES:
            return 1.5
        if defender.status == Status.PSN and attacker.ability == "Merciless":
            return 1.5
        if Effect.LASER_FOCUS in attacker.effects:
            return 1.5
        return 1.0
        
    def calculate_burn_factor(attacker: Pokemon, move: Move) -> float:
        if move.category != MoveCategory.PHYSICAL:
            return 1.0
        if attacker.status != Status.BRN:
            return 1.0
        if attacker.ability == "Guts":
            return 1.0
        if fetch_move_name(move) == "Facade":
            return 1.0
        return 0.5

    def calculate_type_effectiveness(attacker: Pokemon, defender: Pokemon, move: Move, weather: Weather) -> float:
        multi = 1.0
        move_type = fetch_move_type(move)
        move_name = fetch_move_name(move)

        for defending_type in fetch_pokemon_types(defender):
            if move_name == "Flying Press":
                multi *= TYPE_CHART.get("Fighting", {}).get(defending_type, 1.0) * TYPE_CHART.get("Flying", {}).get(defending_type, 1.0)
                continue
            if move_name == "Freeze-Dry" and defending_type == "Water":
                multi *= 2.0
                continue

            effectiveness = TYPE_CHART.get(move_type, {}).get(defending_type, 1.0)

            if attacker.ability == "Scrappy" and defending_type == "Ghost" and move_type in {"Normal", "Fighting"} and effectiveness == 0.0:
                effectiveness = 1.0
            if move_name == "Thousand Arrows" and defending_type == "Flying":
                effectiveness = 1.0
            if defender.item == "Ring Target" and effectiveness == 0.0:
                effectiveness = 1.0
            
            if (Effect.FORESIGHT in defender.effects) and defending_type == "Ghost" and move_type in {"Normal", "Fighting"} and effectiveness == 0.0:
                effectiveness = 1.0
            if Effect.MIRACLE_EYE in defender.effects and defending_type == "Dark" and move_type == "Psychic" and effectiveness == 0.0:
                effectiveness = 1.0

            multi *= effectiveness

        return multi

    def calculate_stab(attacker: Pokemon, move: Move) -> float:
        move_type = fetch_move_type(move)
        if move_type == "Typeless":
            return 1.0

        adapt = attacker.ability == "Adaptability"
        
        orig_match = move_type in fetch_pokemon_types(attacker)
        tera_match = attacker.is_terastallized and attacker.tera_type == move_type
        tera_same_as_orig = attacker.is_terastallized and attacker.tera_type in fetch_pokemon_types(attacker)
        if not attacker.is_terastallized:
            return 2.0 if adapt and orig_match else (1.5 if orig_match else 1.0)
        if tera_match and tera_same_as_orig:
            return 2.25 if adapt else 2.0
        if tera_match and not tera_same_as_orig:
            return 2.0 if adapt else 1.5
        if orig_match:
            return 1.5
        return 1.0

    if move.category not in (MoveCategory.PHYSICAL, MoveCategory.SPECIAL) or move.base_power == 0:
        return 0.0

    base = calculate_base(attacker, defender, move)

    modifiers = []
    modifiers.append(calculate_weather_bonus(move, weather))
    modifiers.append(calculate_glaive_bonus(defender))
    modifiers.append(calculate_determined_critical_hit(attacker, defender, move))
    modifiers.append(0.925) # Random distribution factor
    modifiers.append(calculate_stab(attacker, move))
    modifiers.append(calculate_type_effectiveness(attacker, defender, move, weather))
    modifiers.append(calculate_burn_factor(attacker, move))

    total_modifier = 1.0
    for modifier in modifiers:
        total_modifier *= modifier

    return base * total_modifier

class CustomAgent(Player):
    def __init__(self, *args, **kwargs):
        super().__init__(team=team, *args, **kwargs)

    def choose_move(self, battle: AbstractBattle):
        if battle.available_moves:
            best_move = max(battle.available_moves, key=lambda move: calculate_expected_damage(battle.active_pokemon, battle.opponent_active_pokemon, move, battle.weather))
            return self.create_order(best_move)
        else:
            return self.choose_random_move(battle)
