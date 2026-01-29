import json
import re
from pathlib import Path

def clean_name(name):
    return re.sub(r'\s*\(.*?\)', '', name).strip()

def normalize(s):
    return re.sub(r'[^a-z0-9]', '', s.lower())

teams_file = Path('d:/repo/backend/data/baseball/teams_d1.json')
if teams_file.exists():
    teams = json.loads(teams_file.read_text())
    print(f"{'Original NCAA Name':<35} | {'Cleaned Name (for Matching)':<30} | {'Normalized'}")
    print("-" * 85)
    for t in teams[:100]:
        orig = t['ncaa_name']
        cleaned = clean_name(orig)
        norm = normalize(cleaned)
        print(f"{orig:<35} | {cleaned:<30} | {norm}")
else:
    print("teams_d1.json not found")
