import os
import re
from pathlib import Path

# Paths to scan
base_dir = Path(r"C:\Users\dguil\Documents\repo\Sports-Betting-Analyzer")
projects = ["frontend", "mobile", "shared"]

# 1. Find all defined routes
routes = set()
for p in projects:
    for root, _, files in os.walk(base_dir / p):
        for f in files:
            if f.endswith('.razor'):
                content = Path(root) / f
                try:
                    text = content.read_text(encoding='utf-8')
                    # Find @page "..."
                    for match in re.finditer(r'@page\s+"([^"]+)"', text):
                        route = match.group(1)
                        # strip query params or route params like {Sport} for loose matching
                        base_route = route.split('{')[0].strip('/')
                        routes.add(base_route.lower() if base_route else '/')
                except Exception:
                    pass

routes.add('') # root path /
routes.add('account/login') # likely identity routes
routes.add('account/register') # likely identity routes

# 2. Find all internal links
broken_links = []
href_regex = re.compile(r'href="([^"]+)"')

for p in projects:
    for root, _, files in os.walk(base_dir / p):
        for f in files:
            if f.endswith('.razor') or f.endswith('.cs'):
                content = Path(root) / f
                try:
                    text = content.read_text(encoding='utf-8')
                    for match in href_regex.finditer(text):
                        link = match.group(1)
                        if link.startswith('http') or link.startswith('#') or link.startswith('mailto:'):
                            continue
                            
                        # Extract base path
                        base_link = link.split('?')[0].split('#')[0].strip('/')
                        base_link = base_link.lower()
                        
                        # Handle potential route params
                        # If a link is /players/NBA, we want to match a route /players or /players/{Sport}
                        # We will just check if any route is a prefix of the link
                        found = False
                        
                        # Exact match
                        if base_link in routes:
                            found = True
                        elif not found:
                            # prefix match for params
                            for r in routes:
                                if r != '' and base_link.startswith(r):
                                    # ensure it's a full segment match (e.g. /players/NBA matches /players)
                                    if len(base_link) > len(r) and base_link[len(r)] == '/':
                                        found = True
                                        break
                                        
                        if not found:
                            broken_links.append((f"{p}/{Path(root).relative_to(base_dir / p)}/{f}", link))
                except Exception:
                    pass

print(f"Found {len(routes)} valid route bases.")
if not broken_links:
    print("All internal links appear to resolve to a valid page route!")
else:
    print("Potential broken links found:")
    for file, link in set(broken_links):
        print(f"File: {file} -> Link: {link}")
