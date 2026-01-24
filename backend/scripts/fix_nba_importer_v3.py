import os

file_path = r'c:\Users\dguil\source\repos\PythonMLService\backend\scripts\nba_importer.py'

with open(file_path, 'r') as f:
    lines = f.readlines()

new_lines = []
for line in lines:
    new_lines.append(line)
    # Stop exactly at the end of the last valid function
    if 'return {"imported": imported}' in line and 'import_game_logs' not in line:
        # Search for the start of the next function or the main block
        # We'll check the count of lines to avoid stopping too early
        pass

# Actually, I'll just find the line number of the LAST 'return {"imported": imported}'
last_return_idx = -1
for i, line in enumerate(lines):
    if 'return {"imported": imported}' in line:
        last_return_idx = i

if last_return_idx != -1:
    content = lines[:last_return_idx + 1]
    content.append('\n')
    content.append('    except Exception as e:\n')
    content.append('        logger.error(f"Error importing NBA game logs: {e}")\n')
    content.append('        return {"imported": 0, "error": str(e)}\n')
    content.append('\n\n')
    content.append('if __name__ == "__main__":\n')
    content.append('    async def test_import():\n')
    content.append('        def log_progress(msg):\n')
    content.append('            print(f"[PROGRESS] {msg}")\n')
    content.append('        \n')
    content.append('        result = await import_all_nba(clear_existing=True, progress_callback=log_progress)\n')
    content.append('        print(f"Result: {result}")\n')
    content.append('    \n')
    content.append('    asyncio.run(test_import())\n')

    with open(file_path, 'w') as f:
        f.writelines(content)
    print("RESTORED AND CLEANED!")
else:
    print("FALLBACK: OVERWRITING END")
