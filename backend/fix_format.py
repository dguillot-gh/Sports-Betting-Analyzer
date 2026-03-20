import sys

file_path = '/app/api/db_endpoints.py'
try:
    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
        
    for i in range(len(lines)):
        if "if hasattr(request.app.state, 'pool') and request.app.state.pool:" in lines[i]:
            # Look up to 5 lines backwards for the try/finally/else
            base_indent = ""
            for j in range(1, 6):
                if i-j >= 0 and "finally:" in lines[i-j]:
                    base_indent = lines[i-j][:len(lines[i-j]) - len(lines[i-j].lstrip())].replace('\n', '')
                    break
                elif i-j >= 0 and "else:" in lines[i-j] and "if hasattr" not in lines[i-j]:
                    base_indent = lines[i-j][:len(lines[i-j]) - len(lines[i-j].lstrip())].replace('\n', '') + '    '
                    break
                elif i-j >= 0 and "except" in lines[i-j]:
                    # fallback
                    base_indent = lines[i-j][:len(lines[i-j]) - len(lines[i-j].lstrip())].replace('\n', '')
                    break
            
            if base_indent == "":
                # Fallback to the leading whitespace of the current line
                base_indent = lines[i][:len(lines[i]) - len(lines[i].lstrip())].replace('\n', '')
                if len(base_indent) >= 4:
                    base_indent = base_indent[:-4]

            inner_indent = base_indent + "    "
            
            # Now rewrite this line and the next 3
            lines[i] = inner_indent + "if hasattr(request.app.state, 'pool') and request.app.state.pool:\n"
            if i+1 < len(lines): lines[i+1] = inner_indent + "    await request.app.state.pool.release(conn)\n"
            if i+2 < len(lines): lines[i+2] = inner_indent + "else:\n"
            if i+3 < len(lines): lines[i+3] = inner_indent + "    await conn.close()\n"

    with open(file_path, 'w', encoding='utf-8') as f:
        f.writelines(lines)
    print("Fixed db_endpoints format")
except Exception as e:
    print(e)
    sys.exit(1)
