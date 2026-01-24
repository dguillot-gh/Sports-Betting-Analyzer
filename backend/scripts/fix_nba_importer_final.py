import os

file_path = r'c:\Users\dguil\source\repos\PythonMLService\backend\scripts\nba_importer.py'

with open(file_path, 'r') as f:
    lines = f.readlines()

new_lines = []
target_func = 'async def import_game_logs_via_nba_api'
stop_line = -1

for i, line in enumerate(lines):
    if target_func in line:
        # We found the function. Now find its return statement.
        for j in range(i, len(lines)):
            if 'return {"imported": imported}' in lines[j] and 'import_game_logs' not in lines[j]:
                # Found the return. Go a bit further for the except block.
                for k in range(j, len(lines)):
                    if 'except Exception as e:' in lines[k]:
                         # The standard handler is usually 3-4 lines
                         stop_line = k + 3
                         break
                if stop_line != -1: break
        if stop_line != -1: break

if stop_line != -1:
    content = lines[:stop_line + 1]
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
    print("SUCCESS: File restored by signature.")
else:
    print("CRITICAL: Failed to find signature.")
