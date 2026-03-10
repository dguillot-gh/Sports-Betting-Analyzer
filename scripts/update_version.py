#!/usr/bin/env python3
"""
Simple Version Update Script
Updates version in docker-compose.yml based on git branch and commit count
"""

import subprocess
import re
import sys
from pathlib import Path

def get_git_info():
    """Get basic git info"""
    try:
        branch = subprocess.check_output(["git", "rev-parse", "--abbrev-ref", "HEAD"], text=True).strip()
        commit_count = int(subprocess.check_output(["git", "rev-list", "--count", "HEAD"], text=True).strip())
        sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()[:8]
        return branch, commit_count, sha
    except:
        return "unknown", 0, "unknown"

def update_docker_compose(version, sha, branch):
    """Update version in docker-compose.yml"""
    compose_file = Path("docker-compose.yml")
    if not compose_file.exists():
        print("docker-compose.yml not found")
        return False
    
    content = compose_file.read_text()
    
    # Update APP_VERSION
    content = re.sub(r'APP_VERSION=.*', f'APP_VERSION={version}', content)
    # Update GIT_SHA
    content = re.sub(r'GIT_SHA=.*', f'GIT_SHA={sha}', content)
    # Update GIT_BRANCH
    content = re.sub(r'GIT_BRANCH=.*', f'GIT_BRANCH={branch}', content)
    
    compose_file.write_text(content)
    print(f"Updated docker-compose.yml with version {version}")
    return True

def main():
    branch, commit_count, sha = get_git_info()
    
    if branch == "master" or branch == "main":
        # Major release - increment major version
        major = commit_count // 100 + 1
        version = f"{major}.0.0"
    else:
        # Dev branch - patch version
        major = commit_count // 100 + 1
        patch = commit_count % 100
        version = f"{major}.0.{patch}-dev"
    
    print(f"Git info: branch={branch}, commits={commit_count}, sha={sha}")
    print(f"Calculated version: {version}")
    
    if update_docker_compose(version, sha, branch):
        print("Version updated successfully!")
    else:
        print("Failed to update version")
        sys.exit(1)

if __name__ == "__main__":
    main()
