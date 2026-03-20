import os
import glob

shared_dir = r"C:\Users\dguil\Documents\repo\Sports-Betting-Analyzer\shared\Components"
mobile_home = r"C:\Users\dguil\Documents\repo\Sports-Betting-Analyzer\mobile\Components\Pages\Home.razor"
mobile_nav = r"C:\Users\dguil\Documents\repo\Sports-Betting-Analyzer\mobile\Components\Layout\NavMenu.razor"

# 1. Update all @page directives in shared/Components
for filepath in glob.glob(os.path.join(shared_dir, "*.razor")):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    if '@page "/' in content and '@page "/mobile-' not in content:
        # Don't prefix simple root route if any existed
        if '@page "/"' in content:
            continue
            
        content = content.replace('@page "/', '@page "/mobile-')
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
            print(f"Patched shared @page: {os.path.basename(filepath)}")

# 2. Update all href links in mobile NavMenu.razor and Home.razor
for fp in [mobile_home, mobile_nav]:
    with open(fp, 'r', encoding='utf-8') as f:
        content = f.read()
        
    lines = content.split('\n')
    new_lines = []
    for line in lines:
        if 'href="/' in line and 'href="/mobile-' not in line:
            if 'href="/"' in line:
                pass # Home doesn't get prefix
            else:
                line = line.replace('href="/', 'href="/mobile-')
        new_lines.append(line)
    
    with open(fp, 'w', encoding='utf-8') as f:
        f.write('\n'.join(new_lines))
        print(f"Patched mobile href: {os.path.basename(fp)}")

print("Done padding routes.")
