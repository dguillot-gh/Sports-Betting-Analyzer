import sys
from pathlib import Path
sys.path.append(str(Path.cwd() / 'src'))
from sports.nascar import NASCARSport

def verify_sorting():
    config = {
        'name': 'nascar',
        'data': {'results_file': 'cup_enhanced.csv'},
        'features': {},
        'targets': {}
    }
    sport = NASCARSport(config)
    teams = sport.get_teams()
    
    print(f"Total teams: {len(teams)}")
    print("Top 20 teams (should be active in 2024/2025):")
    for i, team in enumerate(teams[:20]):
        print(f"{i+1}. {team}")
        
    # Check if major teams are in the top 100
    major_teams = [
        "Hendrick Motorsports",
        "Joe Gibbs Racing",
        "Team Penske",
        "23XI Racing"
    ]
    
    print("-" * 20)
    for target in major_teams:
        try:
            index = teams.index(target)
            print(f"{target} is at index {index}")
        except ValueError:
            # Try partial match
            found = False
            for i, team in enumerate(teams):
                if target.lower() in team.lower():
                    print(f"{target} (partial: {team}) is at index {i}")
                    found = True
                    break
            if not found:
                print(f"MISSING: {target}")

if __name__ == "__main__":
    verify_sorting()
