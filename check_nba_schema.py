#!/usr/bin/env python3

import asyncpg
import asyncio

async def check_nba_schema():
    conn = await asyncpg.connect('postgresql://sports_user:sportsbetting2024@postgres:5432/sports_betting')
    
    try:
        # Check NBA data specifically
        nba_games = await conn.fetchval("""
            SELECT COUNT(*) FROM results r 
            JOIN sports s ON r.sport_id = s.id 
            WHERE s.name = 'nba'
        """)
        print(f'NBA games in database: {nba_games}')
        
        # Sample NBA data
        sample = await conn.fetch("""
            SELECT r.* FROM results r 
            JOIN sports s ON r.sport_id = s.id 
            WHERE s.name = 'nba' 
            LIMIT 1
        """)
        
        if sample:
            print('Sample NBA game columns:')
            for key in sample[0].keys():
                print(f'  {key}')
        else:
            print('No NBA data found')
            
        # Check available seasons for NBA
        seasons = await conn.fetch("""
            SELECT season, COUNT(*) as games
            FROM results r
            JOIN sports s ON r.sport_id = s.id
            WHERE s.name = 'nba' AND season IS NOT NULL
            GROUP BY season
            ORDER BY season DESC
            LIMIT 10
        """)
        
        # Check what's in entities table
        all_entities = await conn.fetch("""
            SELECT type, COUNT(*) as count
            FROM entities
            GROUP BY type
            ORDER BY count DESC
        """)
        
        print('\nEntity types in database:')
        for entity in all_entities:
            print(f'  {entity["type"]}: {entity["count"]} entries')
            
        # Check NBA games with scores
        games_with_scores = await conn.fetchval("""
            SELECT COUNT(*) FROM results r
            JOIN sports s ON r.sport_id = s.id
            WHERE s.name = 'nba' AND r.season = 2025
            AND r.home_score IS NOT NULL AND r.away_score IS NOT NULL
        """)
        
        print(f'NBA 2025 games with scores: {games_with_scores}')
        
        # Check total games
        total_games = await conn.fetchval("""
            SELECT COUNT(*) FROM results r
            JOIN sports s ON r.sport_id = s.id
            WHERE s.name = 'nba' AND r.season = 2025
        """)
        
        print(f'Total NBA 2025 games: {total_games}')

        # Check team name resolution
        team_test = await conn.fetch("""
            SELECT r.home_score, r.away_score, r.game_date,
                   he.name as home_team, ae.name as away_team,
                   r.home_entity_id, r.away_entity_id
            FROM results r
            JOIN sports s ON r.sport_id = s.id
            LEFT JOIN entities he ON r.home_entity_id = he.id
            LEFT JOIN entities ae ON r.away_entity_id = ae.id
            WHERE s.name = 'nba' AND r.season = 2025
            AND r.home_score IS NOT NULL AND r.away_score IS NOT NULL
            LIMIT 5
        """)
        
        print('\nSample NBA games with team names:')
        for game in team_test:
            print(f'  {game["home_team"]} vs {game["away_team"]}: {game["home_score"]}-{game["away_score"]}')
            print(f'    IDs: {game["home_entity_id"]} -> {game["away_entity_id"]}')
            
    except Exception as e:
        print(f'Error: {e}')
    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(check_nba_schema())
