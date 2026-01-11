
import sportsdataverse.mbb as mbb
import logging
import sys

# Force utf-8 stdout if possible, or just ignore errors
sys.stdout.reconfigure(encoding='utf-8')

try:
    df = mbb.load_mbb_team_boxscore(seasons=[2025])
    cols = df.columns
    print("COLS_START")
    for c in cols:
        print(c)
    print("COLS_END")

except Exception as e:
    print(f"Error: {e}")
