import os

path = r'c:\Users\dguil\source\repos\SportsBettingAnalyzer\Services\PythonMLServiceClient.cs'

try:
    with open(path, 'r', encoding='utf-8-sig') as f:
        lines = f.readlines()

    # Find the second occurrence of "using System;"
    # The first one is at line 0 (index 0)
    # The second one is at line 119 (index 119)
    # We want to keep from index 119 onwards.

    start_index = -1
    count = 0
    for i, line in enumerate(lines):
        if line.strip() == 'using System;':
            count += 1
            if count == 2:
                start_index = i
                break

    if start_index != -1:
        new_content = lines[start_index:]
        with open(path, 'w', encoding='utf-8-sig') as f:
            f.writelines(new_content)
        print(f"Fixed file. Kept {len(new_content)} lines starting from line {start_index + 1}.")
    else:
        print("Could not find second 'using System;'")
        # Fallback: check if file is already fixed (only 1 using System;)
        if count == 1:
             print("File appears to be already fixed (only 1 'using System;').")

except Exception as e:
    print(f"Error: {e}")
