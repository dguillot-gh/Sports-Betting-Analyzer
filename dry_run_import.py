import csv
import json
from datetime import datetime
from collections import defaultdict

def parse_juice_reel_csv(file_path):
    bets = defaultdict(list)
    with open(file_path, mode='r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            bets[row['juice_bet_id']].append(row)
    return bets

def transform_bet(bet_id, legs):
    first_leg = legs[0]
    
    # Common fields for the bet
    bet_data = {
        "juice_bet_id": bet_id,
        "sportsbook": first_leg['sportsbook'],
        "stake": float(first_leg['risk_amount']),
        "odds": int(first_leg['odds_american']),
        "outcome": first_leg['bet_result'].lower(),
        "profit": float(first_leg['amount_won_or_lost']),
        "date_placed": first_leg['date_placed'],
        "clv": float(first_leg['clv_percent']) if first_leg['clv_percent'] else None,
        "num_legs": int(first_leg['number_of_legs']),
        "legs": []
    }
    
    # Mapping outcome
    if bet_data['outcome'] == "cashedout":
        bet_data['outcome'] = "cashout"
    
    # Compile legs
    for leg in legs:
        bet_data['legs'].append({
            "leg_id": leg['bet_leg_id'],
            "sport": leg['leg_sport'],
            "league": leg['leg_league'],
            "description": leg['leg_description'],
            "event": leg['event_name'],
            "start_date": leg['event_start_date']
        })
    
    # Determine primary sport/game_name for the bet record
    if bet_data['num_legs'] == 1:
        bet_data['sport'] = first_leg['leg_sport'].lower().replace("basketball", "nba").replace("football", "nfl") # Simplification
        if "nba" in first_leg['leg_league'].lower(): bet_data['sport'] = "nba"
        elif "nfl" in first_leg['leg_league'].lower(): bet_data['sport'] = "nfl"
        elif "mlb" in first_leg['leg_league'].lower(): bet_data['sport'] = "mlb"
        
        bet_data['game_name'] = first_leg['event_name']
        bet_data['description'] = first_leg['leg_description']
    else:
        bet_data['sport'] = "parlay"
        bet_data['game_name'] = f"{bet_data['num_legs']}-leg parlay"
        bet_data['description'] = ", ".join([l['event'] for l in bet_data['legs']])[:200]
        
    return bet_data

def run_dry_run():
    files = [
        '/app/data1.csv',
        '/app/data2.csv'
    ]
    
    all_bets_raw = {}
    for file in files:
        try:
            raw = parse_juice_reel_csv(file)
            all_bets_raw.update(raw)
        except Exception as e:
            print(f"Error reading {file}: {e}")
    
    transformed_bets = []
    for bet_id, legs in all_bets_raw.items():
        try:
            transformed_bets.append(transform_bet(bet_id, legs))
        except Exception as e:
            pass # Skip errors in sample
            
    # Summary
    print(f"Total Unique Bets: {len(transformed_bets)}")
    
    summary = defaultdict(int)
    total_stake = 0
    total_profit = 0
    
    for bet in transformed_bets:
        summary[bet['sport']] += 1
        summary[bet['sportsbook']] += 1
        total_stake += bet['stake']
        total_profit += bet['profit']
        
    print("\nBreakdown:")
    for key, count in sorted(summary.items(), key=lambda x: x[1], reverse=True):
        print(f"  {key}: {count}")
        
    print(f"\nFinancials:")
    print(f"  Total Stake: ${total_stake:,.2f}")
    print(f"  Total Profit: ${total_profit:,.2f}")
    
    print("\nSample Data (First 3):")
    for bet in transformed_bets[:3]:
        print(json.dumps(bet, indent=2))

if __name__ == "__main__":
    run_dry_run()
