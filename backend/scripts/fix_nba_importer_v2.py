import os

file_path = r'c:\Users\dguil\source\repos\PythonMLService\backend\scripts\nba_importer.py'

with open(file_path, 'r') as f:
    lines = f.readlines()

new_lines = []
found_end = False

for i, line in enumerate(lines):
    new_lines.append(line)
    # The last known good point in the game logs function
    if 'return {"imported": imported}' in line and i > 1100:
        # Check if next lines are the standard exception handler
        new_lines.append('\n')
        new_lines.append('    except Exception as e:\n')
        new_lines.append('        logger.error(f"Error importing NBA game logs: {e}")\n')
        new_lines.append('        return {"imported": 0, "error": str(e)}\n\n')
        found_end = True
        break

if found_end:
    # Add the main block back
    new_lines.append('\n')
    new_lines.append('if __name__ == "__main__":\n')
    new_lines.append('    async def test_import():\n')
    new_lines.append('        def log_progress(msg):\n')
    new_lines.append('            print(f"[PROGRESS] {msg}")\n')
    new_lines.append('        \n')
    new_lines.append('        result = await import_all_nba(clear_existing=True, progress_callback=log_progress)\n')
    new_lines.append('        print(f"Result: {result}")\n')
    new_lines.append('    \n')
    new_lines.append('    asyncio.run(test_import())\n')

    with open(file_path, 'w') as f:
        f.writelines(new_lines)
    print("Cleaned up nba_importer.py perfectly.")
else:
    print("Could not find the target end point.")
