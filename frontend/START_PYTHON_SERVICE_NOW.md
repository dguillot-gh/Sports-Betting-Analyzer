# ?? Python Service Not Running - Complete Diagnosis

## The Core Problem

**Blazor Error**: "Python ML Service is not available. Please ensure the service is running at http://localhost:8000"

**Reason**: The Python FastAPI service is **not currently running** on your machine.

---

## Why This Happens

The Blazor application is configured correctly and can see the application code. However:

1. ? Code exists: `C:\Users\dguil\source\repos\PythonMLService\api\app.py`
2. ? Packages installed: FastAPI, Uvicorn are in the Python environment
3. ? Configuration ready: YAML files and configs exist
4. ? **Service NOT started**: No Python process running on port 8000

---

## The Solution (< 1 minute)

### Step 1: Open NEW PowerShell Window

**Important**: Use a NEW window, not one where you've been running other commands.

### Step 2: Navigate to Python Service

```powershell
cd C:\Users\dguil\source\repos\PythonMLService
```

Verify you're in the right place:
```powershell
dir api/app.py    # Should show: app.py exists
```

### Step 3: Start the Python Service

```powershell
env\Scripts\python.exe -m uvicorn api.app:app --reload --host 0.0.0.0 --port 8000
```

### Step 4: Wait for Startup Message

You should see:
```
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
INFO:     Started server process [12345]
INFO:     Application startup complete
```

**?? CRITICAL**: Keep this PowerShell window OPEN - service must continue running

### Step 5: Test in Another PowerShell Window

Open a **NEW** PowerShell window and test:

```powershell
curl http://localhost:8000/health
```

Expected response:
```json
{"ok":true,"sports":["nascar","nfl"]}
```

### Step 6: Refresh Blazor App

Go to your browser and refresh: `F5` or `Ctrl+R`

The Blazor page should now show:
```
? Python ML Service connected
```

---

## Troubleshooting If It Still Doesn't Work

### Problem 1: "Address already in use"

If you get an error like:
```
ERROR: Address already in use. Trying to bind to 0.0.0.0:8000
```

**Solution**: Kill the process on port 8000

```powershell
netstat -ano | findstr :8000
```

This shows something like: `TCP    0.0.0.0:8000    0.0.0.0:0    LISTENING    12345`

Kill that process:
```powershell
taskkill /PID 12345 /F
```

Then try starting the service again.

### Problem 2: "ModuleNotFoundError"

If you see:
```
ModuleNotFoundError: No module named 'fastapi'
```

**Solution**: Reinstall dependencies

```powershell
cd C:\Users\dguil\source\repos\PythonMLService
env\Scripts\python.exe -m pip install -r requirements.txt --force-reinstall
```

### Problem 3: "No module named 'api'"

If you see:
```
ModuleNotFoundError: No module named 'api'
```

**Solution**: Make sure you're in the correct directory

```powershell
pwd  # Should show: C:\Users\dguil\source\repos\PythonMLService
```

If not in the right directory, navigate there:
```powershell
cd C:\Users\dguil\source\repos\PythonMLService
```

### Problem 4: Blazor Still Shows Error After Service Starts

**Solution**:

1. **Hard refresh browser**: `Ctrl+Shift+R` (clears cache)
2. **Wait a few seconds**: Health checks are cached
3. **Check browser console** (F12): Look for any errors
4. **Verify service responding**: `curl http://localhost:8000/health`

---

## Quick Verification Checklist

- [ ] Opened NEW PowerShell window
- [ ] Navigated to: `C:\Users\dguil\source\repos\PythonMLService`
- [ ] Verified file exists: `dir api/app.py` shows the file
- [ ] Ran command: `env\Scripts\python.exe -m uvicorn api.app:app --reload --host 0.0.0.0 --port 8000`
- [ ] Saw startup message: "Application startup complete"
- [ ] PowerShell window is STILL OPEN (not closed)
- [ ] Tested in new window: `curl http://localhost:8000/health` returns JSON
- [ ] Blazor app refreshed with F5
- [ ] Shows: "Python ML Service connected" ?

---

## What's Running Where

After you complete the setup:

```
Terminal 1 (KEEP OPEN):
?? Python Service running
?? Port: http://localhost:8000
?? Status: ? Active (don't close!)

Terminal 2 (Testing):
?? Can test: curl http://localhost:8000/health
?? Shows: {"ok":true,"sports":["nascar","nfl"]}

Browser:
?? Blazor App: https://localhost:5001
?? Page: /ml-training
?? Shows: "Python ML Service connected" ?
```

---

## Using the Startup Script (Alternative)

Instead of manually running the command, you can use the startup script:

```powershell
cd C:\Users\dguil\source\repos\PythonMLService
.\start_service.ps1
```

This does the exact same thing - starts the service on port 8000.

**Keep this window open while working.**

---

## Common Questions

**Q: Do I need to keep the Python window open?**  
A: Yes! The service must continue running. If you close it, the error comes back.

**Q: Can I run it in the background?**  
A: Yes, but it's easier to keep the window open during development for debugging.

**Q: Why does Blazor keep checking?**  
A: The `PythonMLServiceClient` checks every 30 seconds if the service is healthy. This ensures it catches when the service crashes.

**Q: How do I stop the service?**  
A: Press `Ctrl+C` in the PowerShell window where it's running.

---

## Summary

| Item | Status |
|------|--------|
| **Root Cause** | Python service not running |
| **Fix Complexity** | ? Very Simple |
| **Fix Time** | < 1 minute |
| **Files Changed** | 0 (code is ready) |
| **Action Required** | Start Python service |

---

## Next Step

**Right now**: Open a new PowerShell window and run:

```powershell
cd C:\Users\dguil\source\repos\PythonMLService
env\Scripts\python.exe -m uvicorn api.app:app --reload --host 0.0.0.0 --port 8000
```

**Keep that window open** while you use the Blazor app.

---

**Everything is installed and configured correctly. You just need to start the service!** ??
