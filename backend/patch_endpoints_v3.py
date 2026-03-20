import re
import glob
import os

files_to_patch = glob.glob('api/*_endpoints.py')
if 'api/db_endpoints.py' not in files_to_patch:
    files_to_patch.append('api/db_endpoints.py')

for file_path in files_to_patch:
    if not os.path.exists(file_path):
        continue
        
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 1. Add Request import if missing
    if 'from fastapi import APIRouter' in content and ' Request' not in content and ',Request' not in content:
        content = content.replace(
            'from fastapi import APIRouter',
            'from fastapi import APIRouter, Request'
        )
        
    # 2. Add get_db_connection import if not db_endpoints
    if not file_path.endswith('db_endpoints.py'):
        if 'from api.db_endpoints import DATABASE_URL' in content and 'get_db_connection' not in content:
            content = content.replace(
                'from api.db_endpoints import DATABASE_URL',
                'from api.db_endpoints import DATABASE_URL, get_db_connection'
            )
        elif 'from api.db_endpoints import' in content and 'get_db_connection' not in content:
            # We must be careful not to greedily match across newlines here either!
            # It's better to just regex exclusively on the line containing this import
            content = re.sub(
                r'(from api\.db_endpoints import [^\n]+)',
                r'\1, get_db_connection',
                content
            )
            
    # 3. Handle try/except asyncpg block wrapper used in many places
    content = re.sub(
        r'(?s)[ \t]*try:[ \t\n]*import asyncpg[ \t\n]*conn = await asyncpg\.connect\(DATABASE_URL\)[ \t\n]*except Exception as e:[ \t\n]*logger\.error\(f"Database connection failed:[^\n]*\)[ \t\n]*raise HTTPException\(status_code=500, detail="Database connection string not configured properly\."\)',
        '\n    conn = await get_db_connection(request)',
        content
    )
    
    # Handle direct connect calls inside init functions and others
    content = re.sub(
        r'[ \t]*conn\s*=\s*await\s*asyncpg\.connect\([^)]*\)',
        '\n    conn = await get_db_connection(request)',
        content
    )
    
    content = re.sub(
        r'[ \t]*conn\s*=\s*await\s*asyncpg\.connect\(DATABASE_URL\)',
        '\n    conn = await get_db_connection(request)',
        content
    )

    # 4. Insert request: Request into router signatures
    content = re.sub(
        r'@router\.(get|post|put|delete|patch)\((.*?)\)\s*async def (.*?)\((.*?)\):',
        lambda m: f'@router.{m.group(1)}({m.group(2)})\nasync def {m.group(3)}(request: Request' + (f', {m.group(4)}):' if m.group(4) and not m.group(4).startswith('request') else '):'),
        content
    )
    
    # 5. Fix await conn.close() using precise indentation matching!
    content = re.sub(
        r'([ \t]*)await conn\.close\(\)',
        r"\1if hasattr(request.app.state, 'pool') and request.app.state.pool:\n\1    await request.app.state.pool.release(conn)\n\1else:\n\1    await conn.close()",
        content
    )
    
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"Patched {file_path}")

print("Successfully patched endpoints.")
