import os
import re

def swap_in_file(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    orig_content = content
    
    # Python Backend Replacements
    content = content.replace('Query("fanduel"', 'Query("draftkings"')
    content = content.replace('Field("fanduel"', 'Field("draftkings"')
    content = content.replace('sportsbook: str = "fanduel"', 'sportsbook: str = "draftkings"')
    content = content.replace('sportsbook="fanduel"', 'sportsbook="draftkings"')
    content = content.replace('sportsbook: "fanduel"', 'sportsbook: "draftkings"')
    
    # URL params
    content = content.replace('sportsbook=fanduel', 'sportsbook=draftkings')
    
    # C# Blazor Frontend Replacements
    content = content.replace('_selectedSportsbook = "fanduel"', '_selectedSportsbook = "draftkings"')
    content = content.replace('_sportsbook = "fanduel"', '_sportsbook = "draftkings"')
    content = content.replace('_editSportsbook = "fanduel"', '_editSportsbook = "draftkings"')
    content = content.replace('sportsbook = "fanduel"', 'sportsbook = "draftkings"')
    content = content.replace('Sportsbook { get; set; } = "fanduel"', 'Sportsbook { get; set; } = "draftkings"')
    content = content.replace('bookmakers = "draftkings,fanduel"', 'bookmakers = "draftkings"')
    
    if content != orig_content:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"Updated {filepath}")

def process_dir(directory):
    for root, dirs, files in os.walk(directory):
        for name in files:
            if name.endswith('.py') or name.endswith('.razor') or name.endswith('.cs'):
                # Exclude virtual environments, __pycache__, etc.
                if 'venv' in root or '__pycache__' in root or '.vs' in root or '.git' in root or 'node_modules' in root:
                    continue
                filepath = os.path.join(root, name)
                swap_in_file(filepath)

if __name__ == "__main__":
    process_dir("c:\\Users\\dguil\\Documents\\repo\\Sports-Betting-Analyzer\\backend")
    process_dir("c:\\Users\\dguil\\Documents\\repo\\Sports-Betting-Analyzer\\frontend")
    process_dir("c:\\Users\\dguil\\Documents\\repo\\Sports-Betting-Analyzer\\shared")
    print("Done")
