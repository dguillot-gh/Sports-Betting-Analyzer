import sys
from pathlib import Path
sys.path.append(str(Path.cwd() / 'src'))
from sports.nascar import NASCARSport

def check_teams():
    config = {
        'name': 'nascar',
        'data': {'results_file': 'cup_enhanced.csv'},
        'features': {},
        'targets': {}
    }
    sport = NASCARSport(config)
    teams = sport.get_teams()
    
    major_teams = [
        "Hendrick Motorsports",
        "Joe Gibbs Racing",
        "Team Penske",
        "Stewart-Haas Racing",
        "Trackhouse Racing",
        "23XI Racing",
        "RFK Racing",
        "Richard Childress Racing"
    ]
    
    print(f"Total teams found: {len(teams)}")
    print("-" * 20)
    
    found_count = 0
    for target in major_teams:
        found = False
        for team in teams:
            if target.lower() in team.lower():
                print(f"FOUND: {team}")
                found = True
        if not found:
            print(f"MISSING: {target}")
        else:
            found_count += 1
            
    print("-" * 20)
    print(f"Found {found_count} out of {len(major_teams)} major teams.")

if __name__ == "__main__":
    check_teams()
