from dataclasses import dataclass
from poke_env.battle import AbstractBattle, Pokemon, Move, MoveCategory, Weather, Effect, Status
from poke_env.player import Player
from poke_env.data import GenData
from logging import Logger
from enum import Enum, auto
import os
import csv

logger = Logger(__name__)

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

###########
#  Types  #
###########

class ActionType(Enum):
    ATTACK = auto()
    STATUS = auto()
    HEAL = auto()
    SWITCH = auto()

@dataclass
class Action:
    type: ActionType
    move: Move | None = None
    target: Pokemon | None = None
    score: float = 0.0

###############
#  Constants  #
###############

TYPE_CHART = GenData.from_gen(9).type_chart

GUARANTEED_CRITICAL_MOVES = {"Storm Throw","Frost Breath","Zippy Zap","Surging Strikes","Wicked Blow","Flower Trick"}

HEALING_MOVES = {"Recover","Roost","Slack Off","Soft-Boiled","Milk Drink","Synthesis","Morning Sun","Moonlight","Shore Up"}

SWITCH_MOVES = {"U-turn","Volt Switch","Parting Shot","Flip Turn"}

FIRST_ACTING_WEIGHTS = {
    "switch": 1.0,
    "attack": 0.9,
    "heal": 0.7,
    "status": 1.0,
}

LAST_ACTING_WEIGHTS = {
    "switch": 1.0,
    "attack": 0.7,
    "heal": 0.9,
    "status": 1.0,
}

#############
#  Utility  #
#############

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
    
    logger.warning(f"Move {move} has no type, defaulting to 'Normal'")
    return "Normal"

# Fetch the move's name as a string
def fetch_move_name(move: Move) -> str:
    if move.id:
        return move.id
    
    logger.warning(f"Move {move} has no id, defaulting to 'Unknown Move'")
    return "Unknown Move"

# Fetch healing moves from a pokemon
def fetch_healing_moves(pokemon: Pokemon) -> list[Move]:
    healing_moves = []
    for move in pokemon.moves.values():
        if move.category == MoveCategory.STATUS and fetch_move_name(move) in HEALING_MOVES:
            healing_moves.append(move)
    return healing_moves

# Fetch switching moves from a pokemon
def fetch_switch_moves(pokemon: Pokemon) -> list[Move]:
    switch_moves = []
    for move in pokemon.moves.values():
        if move.id in SWITCH_MOVES:
            switch_moves.append(move)
    return switch_moves

# Fetch status moves from a pokemon excluding healing moves
def fetch_status_moves(pokemon: Pokemon) -> list[Move]:
    status_moves = []
    for move in pokemon.moves.values():
        if move.category == MoveCategory.STATUS:
            status_moves.append(move)

    # remove healing status moves to simplify logic
    healing_moves = fetch_healing_moves(pokemon)
    for move in healing_moves:
        if move in status_moves:
            status_moves.remove(move)

    return status_moves

# Fetch if acting first
def fetch_acting_first(attacker: Pokemon, defender: Pokemon) -> bool:
    if not (attacker and attacker.moves) or not (defender and defender.moves):
        return True
    attacker_priority = max((m.priority for m in attacker.moves.values()), default=0)
    defender_priority = max((m.priority for m in defender.moves.values()), default=0)
    if attacker_priority != defender_priority:
        return attacker_priority > defender_priority
    return (attacker.stats["spe"] or attacker.base_stats["spe"]) >= (defender.stats["spe"] or defender.base_stats["spe"])


#######################
#  Base Calculations  #
#######################

# Calculate the anticipated damage for a given move in the battle conditions
# Roughly follows Bulbapedia equation for Gen V + (https://bulbapedia.bulbagarden.net/wiki/Damage) in relation to Gen 9 Ubers
def calculate_expected_damage(attacker: Pokemon, defender: Pokemon, move: Move, weather: Weather):
    if not attacker or not defender or not move:
        return 0.0
    
    # Calculate level factor impacting base damage
    def calculate_level_ratio(attacker: Pokemon) -> float:
        return ((2*attacker.level)/5) + 2
    
    # Calculate attack/defense ratio impacting base damage
    def calculate_attack_defense_ratio(attacker: Pokemon, defender: Pokemon, move: Move) -> float:
        if move.category == MoveCategory.PHYSICAL:
            return (attacker.stats["atk"] or attacker.base_stats["atk"]) / (defender.stats["def"] or defender.base_stats["def"])
        elif move.category == MoveCategory.SPECIAL:
            return (attacker.stats["spa"] or attacker.base_stats["spa"]) / (defender.stats["spd"] or defender.base_stats["spd"])
        return 1.0
    
    # Calculate base damage
    def calculate_base(attacker: Pokemon, defender: Pokemon, move: Move) -> float:
        return (calculate_level_ratio(attacker) * move.base_power * 
                calculate_attack_defense_ratio(attacker, defender, move) / 50) + 2

    # Calculate current weather effect on damage
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
    
    # Calculate Glaive Rush effect on damage
    def calculate_glaive_bonus(defender: Pokemon) -> float:
        if not defender.effects:
            return 1.0
        
        if Effect.GLAIVE_RUSH in defender.effects:
            return 2.0
        else:
            return 1.0
    
    # Calculate whether any move is guaranteed to (or never to) critically hit
    def calculate_determined_critical_hit(attacker: Pokemon, defender: Pokemon, move: Move) -> float:
        if not defender.ability:
            return 1.0

        if defender.ability == "Battle Armor" or defender.ability == "Shell Armor":
            return 1.0
        if fetch_move_name(move) in GUARANTEED_CRITICAL_MOVES:
            return 1.5
        
        
        if not defender.status:
            return 1.0
        
        if defender.status == Status.PSN and attacker.ability == "Merciless":
            return 1.5
        
        if Effect.LASER_FOCUS in attacker.effects:
            return 1.5
        return 1.0
    
    # Calculate burn status on damage
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

    # Calculate type effectiveness on damage excluding STAB
    def calculate_type_effectiveness(attacker: Pokemon, defender: Pokemon, move: Move, weather: Weather) -> float:
        multi = 1.0
        move_type = fetch_move_type(move)
        move_name = fetch_move_name(move)

        for defending_type in fetch_pokemon_types(defender):
            if move_name == "Flying Press":
                multi *= TYPE_CHART.get("Fighting").get(defending_type) * TYPE_CHART.get("Flying").get(defending_type)
                continue
            if move_name == "Freeze-Dry" and defending_type == "Water":
                multi *= 2.0
                continue

            effectiveness = TYPE_CHART.get(move_type).get(defending_type)
            
            if attacker.ability == "Scrappy" and defending_type == "Ghost" and move_type in {"Normal", "Fighting"} and effectiveness == 0.0:
                effectiveness = 1.0
            if move_name == "Thousand Arrows" and defending_type == "Flying":
                effectiveness = 1.0
            if defender.item and defender.item == "Ring Target" and effectiveness == 0.0:
                effectiveness = 1.0
            
            if defender.effects and (Effect.FORESIGHT in defender.effects) and defending_type == "Ghost" and move_type in {"Normal", "Fighting"} and effectiveness == 0.0:
                effectiveness = 1.0
            if defender.effects and Effect.MIRACLE_EYE in defender.effects and defending_type == "Dark" and move_type == "Psychic" and effectiveness == 0.0:
                effectiveness = 1.0

            multi *= effectiveness

        return multi

    # Calculate stab multiplier on damage
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
            return 2.0
        if orig_match:
            return 1.5
        return 1.0

    # Early exit for 0 damage moves
    if not move or move.category not in (MoveCategory.PHYSICAL, MoveCategory.SPECIAL) or move.base_power == 0:
        return 0.0

    # Calculate approximate damage
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

# Calculate the expected healing of a given status move. Very over-simplified.
def calculate_expected_healing(healer, move):
    name = fetch_move_name(move)
    if name == "Rest":
        return healer.max_hp - healer.current_hp
    return min(healer.max_hp - healer.current_hp, healer.max_hp * 0.5)

# Calculates the pokemons expected next move
def calculate_anticipated_move(attacker: Pokemon, defender: Pokemon, weather: Weather) -> Move:
    if not attacker.moves:
        return None

    best_move = max(
        attacker.moves.values(),
        key=lambda m: calculate_expected_damage(
            attacker,
            defender,
            m,
            weather,
        ),
    )
    return best_move

# Calculates the pokemons expected next status move
def calculate_anticipated_status_move(attacker: Pokemon, defender: Pokemon, weather: Weather) -> Move:
    status_moves = fetch_status_moves(attacker)
    if not status_moves:
        return None
    
    best_move = max(
        status_moves,
        key=lambda m: calculate_expected_damage(
            attacker,
            defender,
            m,
            weather,
        ),
    )
    return best_move

# Calculates the pokemons expected next healing move
def calculate_anticipated_healing_move(healer: Pokemon) -> Move:
    healing_moves = fetch_healing_moves(healer)
    if not healing_moves:
        return None
    
    best_move = max(
        healing_moves,
        key=lambda m: calculate_expected_healing(
            healer,
            m,
        ),
    )
    return best_move

# Calculates the approximate best pokemon to switch into
def calculate_best_switch(battle: AbstractBattle) -> Pokemon:
    if not battle.available_switches:
        return None
    best_switch = min(
        battle.available_switches,
        key=lambda p: calculate_threat_value(battle.opponent_active_pokemon, p, battle.weather),
    )
    return best_switch

########################
#  Value Calculations  #
########################

# Calculate the threat value of the attacker based on their best move
def calculate_threat_value(attacker: Pokemon, defender: Pokemon, weather: Weather) -> float:
    if not attacker or not defender:
        return 0.0
    
    best_move = calculate_anticipated_move(attacker, defender, weather)
    expected_damage = calculate_expected_damage(attacker, defender, best_move, weather)
    return expected_damage / defender.max_hp

# Calculates the value of switching out the current pokemon
def calculate_switch_value(battle: AbstractBattle) -> float:
    current_threat = calculate_threat_value(
        battle.opponent_active_pokemon,
        battle.active_pokemon,
        battle.weather,
    )
    best_switch = calculate_best_switch(battle)
    best_switch_threat = calculate_threat_value(
        battle.opponent_active_pokemon,
        best_switch,
        battle.weather,
    )
    return max(0.0, current_threat - best_switch_threat)

# Calculate the value of attacking a pokemon with the best move
def calculate_attack_value(attacker: Pokemon, defender: Pokemon, weather: Weather) -> float:
    if not attacker or not defender:
        return 0.0
    
    best_move = calculate_anticipated_move(attacker, defender, weather)
    expected_damage = calculate_expected_damage(attacker, defender, best_move, weather)
    attack_value = expected_damage / defender.max_hp
    return attack_value

# Calculate the value of using status move
def calculate_status_value(attacker: Pokemon, defender: Pokemon, weather: Weather) -> float:
    if not attacker or not defender:
        return 0.0

    anticipated_status_move = calculate_anticipated_status_move(attacker, defender, weather)
    return attacker.current_hp / defender.current_hp if anticipated_status_move else 0.0

# Calculates the value of using the pokemons best healing move
def calculate_heal_value(healer: Pokemon):
    if not healer:
        return 0.0
    
    best_move = calculate_anticipated_healing_move(healer)
    if not best_move:
        return 0.0
    expected_healing = calculate_expected_healing(healer, best_move)
    return expected_healing / healer.max_hp

# Calculate most effective move
def calculate_most_effective_move(battle: AbstractBattle, player: Pokemon, opponent: Pokemon, weather: Weather) -> Move:
    if not player or not opponent:
        return None
    
    switch_value = calculate_switch_value(battle) # If high, should consider switching
    status_value = calculate_status_value(player, opponent, weather) # If low, could use status move
    attack_value = calculate_attack_value(player, opponent, weather) # If high, should attack
    heal_value = calculate_heal_value(player) # If high, should heal

    weights = FIRST_ACTING_WEIGHTS if fetch_acting_first(player, opponent) else LAST_ACTING_WEIGHTS

    actions: list[Action] = [
        Action(type=ActionType.SWITCH, score=switch_value * weights["switch"]),
        Action(type=ActionType.ATTACK, score=attack_value * weights["attack"]),
        Action(type=ActionType.STATUS, score=status_value * weights["status"]),
        Action(type=ActionType.HEAL, score=heal_value * weights["heal"]),
    ]

    best_action = max(actions, key=lambda a: a.score)

    if best_action.type == ActionType.SWITCH:
        return calculate_best_switch(battle)
    elif best_action.type == ActionType.ATTACK:
        return calculate_anticipated_move(player, opponent, weather)
    elif best_action.type == ActionType.STATUS:
        return calculate_anticipated_status_move(player, opponent, weather)
    elif best_action.type == ActionType.HEAL:
        return calculate_anticipated_healing_move(player)
    else:
        return None

class CustomAgent(Player):
    def __init__(self, *args, **kwargs):
        super().__init__(team=team, *args, **kwargs)

    # Log results as CSV for review
    def _battle_finished_callback(self, battle: AbstractBattle):
        result = "Win" if battle.won else "Loss"
        my_remaining = sum(p.current_hp > 0 for p in battle.team.values())
        opp_remaining = sum(p.current_hp > 0 for p in battle.opponent_team.values())
        log_path = "battle_results.csv"
        file_exists = os.path.isfile(log_path)
        with open(log_path, "a", newline="") as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(["battle_tag", "result", "my_remaining", "opp_remaining"])
            writer.writerow([battle.battle_tag, result, my_remaining, opp_remaining])

    def choose_move(self, battle: AbstractBattle):
        if not battle.available_moves:
            return self.choose_random_move(battle)
        else:
            best_move = calculate_most_effective_move(
                battle,
                battle.active_pokemon,
                battle.opponent_active_pokemon,
                battle.weather,
            )
            if best_move:
                return self.create_order(best_move)
            else:
                return self.choose_random_move(battle)
            
