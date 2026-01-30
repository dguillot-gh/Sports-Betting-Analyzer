import sys
import os

target_file = r'd:\repo\backend\api\bet_tracker_endpoints.py'
with open(target_file, 'r', encoding='utf-8') as f:
    content = f.read()

new_code = r"""
@router.post("/import-csv")
async def import_bets_csv(file: UploadFile = File(...)):
    """Import bets from Juice Reel CSV."""
    import asyncpg
    from collections import defaultdict
    import io
    import csv
    
    content = await file.read()
    string_content = content.decode('utf-8')
    f = io.StringIO(string_content)
    reader = csv.DictReader(f)
    
    # Group by juice_bet_id
    bets_map = defaultdict(list)
    for row in reader:
        bets_map[row['juice_bet_id']].append(row)
    
    await ensure_tables()
    conn = await asyncpg.connect(DATABASE_URL)
    
    imported_count = 0
    errors = []
    
    try:
        async with conn.transaction():
            for bet_id, legs in bets_map.items():
                try:
                    first_leg = legs[0]
                    num_legs = int(first_leg['number_of_legs'])
                    stake = float(first_leg['risk_amount'])
                    odds = int(first_leg['odds_american'])
                    profit = float(first_leg['amount_won_or_lost'])
                    outcome_raw = first_leg['bet_result'].lower()
                    
                    # Normalize outcome
                    if outcome_raw == "cashedout":
                        outcome = "cashout"
                    elif outcome_raw in ["won", "loss", "pending"]:
                        outcome = outcome_raw
                    else:
                        outcome = "pending"
                        
                    # Payout calculation
                    potential_payout = calculate_potential_payout(stake, odds)
                    
                    # Sport/Description logic (Simplified)
                    if num_legs == 1:
                        sport_raw = first_leg['leg_sport'].lower()
                        league_raw = first_leg['leg_league'].lower()
                        if "nba" in league_raw: sport = "nba"
                        elif "nfl" in league_raw: sport = "nfl"
                        elif "mlb" in league_raw: sport = "mlb"
                        elif "basketball" in sport_raw: sport = "nba"
                        elif "football" in sport_raw: sport = "nfl"
                        elif "racing" in sport_raw: sport = "nascar"
                        else: sport = sport_raw[:20]
                        
                        game_name = first_leg['event_name']
                        description = first_leg['leg_description']
                    else:
                        sport = "parlay"
                        game_name = f"{num_legs}-leg parlay"
                        description = ", ".join([l['event_name'] for l in legs])[:200]
                    
                    # Insert Bet
                    bet_row = await conn.fetchrow("""
                        INSERT INTO bets (sport, bet_type, sportsbook, stake, odds, potential_payout, 
                                         outcome, profit, game_name, description, source, 
                                         game_date, clv_percent)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
                        RETURNING id
                    """, sport, "single" if num_legs == 1 else "parlay", first_leg['sportsbook'],
                        stake, odds, potential_payout, outcome, profit, game_name, description, 
                        "import", datetime.fromisoformat(first_leg['date_placed'].replace("+00", "+00:00")),
                        float(first_leg['clv_percent']) if first_leg['clv_percent'] else None)
                    
                    bet_db_id = bet_row['id']
                    
                    # Insert Legs
                    for leg in legs:
                        await conn.execute("""
                            INSERT INTO bet_legs (bet_id, description, odds, outcome)
                            VALUES ($1, $2, $3, $4)
                        """, bet_db_id, leg['leg_description'], int(leg['leg_vig']), 
                            "pending") 
                    
                    imported_count += 1
                except Exception as e:
                    errors.append(f"Bet {bet_id}: {str(e)}")
        
        return {
            "status": "success",
            "imported_count": imported_count,
            "error_count": len(errors),
            "errors": errors[:10]
        }
    finally:
        await conn.close()
"""

if "@router.post(\"/import-csv\")" not in content:
    with open(target_file, 'w', encoding='utf-8') as f:
        f.write(content + new_code)
    print("Code successfully appended.")
else:
    print("Code already exists.")
