# ?? Python Service Still Not Available - Troubleshooting

## Quick Diagnosis

The Blazor app still shows "Python Service not available" because **the service is not running**.

The Blazor app is correctly configured and trying to connect, but it's unable to reach the Python service on `http://localhost:8000`.

---

## Step-by-Step Fix

### Step 1: Verify Service is NOT Running

Open PowerShell and check if port 8000 is in use:

```powershell
netstat -ano | findstr :8000
```

**Expected Output**: (empty - port is free)  
**Problem**: If you see a process, the previous service is still running or crashed

### Step 2: Clean Start the Python Service

Open **New PowerShell Window** (important - new window):

```powershell
cd C:\Users\dguil\source\repos\PythonMLService
```

Check that you're in the right directory:
```powershell
dir api/app.py    # Should show the file
```

Now start the service:
```powershell
env\Scripts\python.exe -m uvicorn api.app:app --reload --host 0.0.0.0 --port 8000
```

### Step 3: Wait for Service to Start

You should see output like:
```
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
INFO:     Started reloader process [12345]
INFO:     Started server process [12346]
INFO:     Application startup complete
```

**DO NOT close this PowerShell window** - service must keep running

### Step 4: Verify Service is Running

**Open a NEW PowerShell window** and test:

```powershell
curl http://localhost:8000/health
```

Expected response:
```json
{"ok":true,"sports":["nascar","nfl"]}
```

### Step 5: Refresh Blazor App

Go back to your browser with the Blazor app and refresh (F5 or Ctrl+R).

**Now it should show**: "Python ML Service connected" ?

---

## Common Issues & Fixes

### Issue 1: "Port 8000 already in use"

Error:
```
ERROR: Address already in use. Trying to bind to 0.0.0.0:8000
```

**Fix**: Kill the process using port 8000:
```powershell
netstat -ano | findstr :8000
taskkill /PID {pid_number} /F
```

Then try starting again.

### Issue 2: "ModuleNotFoundError: No module named 'fastapi'"

Error:
```
ModuleNotFoundError: No module named 'fastapi'
```

**Fix**: Reinstall all dependencies:
```powershell
cd C:\Users\dguil\source\repos\PythonMLService
env\Scripts\python.exe -m pip install -r requirements.txt
```

### Issue 3: "No such file or directory: api/app.py"

Error:
```
cannot import name 'app' from 'api.app'
```

**Fix**: Verify you're in the correct directory:
```powershell
pwd  # Should show: C:\Users\dguil\source\repos\PythonMLService
ls api/app.py  # Should show the file
```

### Issue 4: Python Not Found

Error:
```
'python' is not recognized
```

**Fix**: Use the full path to Python in the venv:
```powershell
cd C:\Users\dguil\source\repos\PythonMLService
.\env\Scripts\python.exe -m uvicorn api.app:app --reload --host 0.0.0.0 --port 8000
```

### Issue 5: Blazor App Still Says "Not Available" After Service Started

**Solution**: 
1. Verify service is running: `curl http://localhost:8000/health`
2. Hard refresh Blazor (Ctrl+Shift+R) to clear cache
3. Check browser console (F12) for errors
4. Wait 5 seconds for health checks to update

---

## Correct Setup Diagram

```
PowerShell Window 1 (KEEP OPEN):
???????????????????????????????????????????????????
? cd C:\Users\dguil\source\repos\PythonMLService ?
? env\Scripts\python.exe -m uvicorn api.app:app \?
?   --reload --host 0.0.0.0 --port 8000          ?
?       ?
? [Service Running on http://localhost:8000]     ?
? [DO NOT CLOSE THIS WINDOW]      ?
???????????????????????????????????????????????????

PowerShell Window 2 (Test):
???????????????????????????????????????????????????
? curl http://localhost:8000/health   ?
? {"ok":true,"sports":["nascar","nfl"]}          ?
???????????????????????????????????????????????????

PowerShell Window 3 (Blazor):
???????????????????????????????????????????????????
? cd C:\Users\dguil\source\repos\...Analyzer     ?
? dotnet run       ?
? https://localhost:5001/ml-training      ?
? [Should show "Service connected" ?]      ?
???????????????????????????????????????????????????
```

---

## Checklist - Service Ready?

- [ ] New PowerShell window opened
- [ ] Navigated to: `C:\Users\dguil\source\repos\PythonMLService`
- [ ] Ran: `env\Scripts\python.exe -m uvicorn api.app:app --reload --host 0.0.0.0 --port 8000`
- [ ] Saw: "Application startup complete"
- [ ] PowerShell window still open (service running)
- [ ] Health check works: `curl http://localhost:8000/health`
- [ ] Blazor app refreshed
- [ ] Shows: "Python ML Service connected" ?

---

## What's Actually Happening

1. **Blazor App** runs on `https://localhost:5001`
2. **Blazor checks** if Python service on `http://localhost:8000` is healthy
3. **PythonMLServiceClient** calls `GET /health` endpoint
4. **Python service** must be running to respond
5. **Blazor displays** connection status based on response

**If service is not running** ? Blazor shows error ?

---

## Startup Script Alternative

You can also use the startup script we created:

```powershell
cd C:\Users\dguil\source\repos\PythonMLService
.\start_service.ps1
```

This does the same thing as the manual command above.

---

## Still Not Working?

If you've followed all steps and it still doesn't work:

1. **Check Python version**:
   ```powershell
   python --version
   ```

2. **Check installed packages**:
   ```powershell
   env\Scripts\python.exe -m pip list | findstr fastapi
   ```
   Should show `fastapi 0.121.1`

3. **Check if app loads**:
   ```powershell
   env\Scripts\python.exe -c "from api.app import app; print('? App loads')"
   ```

4. **Check port availability**:
   ```powershell
   netstat -ano | findstr :8000
 ```
   Should be empty

---

## Key Points to Remember

1. **Service must keep running** - Don't close the PowerShell window
2. **New window for each task** - One for service, one for Blazor
3. **Port 8000 must be free** - Kill any conflicting processes
4. **Refresh browser** - After starting service
5. **Give it 5 seconds** - Health checks are cached for 30 seconds

---

**Status**: Service not running (likely cause)  
**Fix Time**: < 1 minute  
**Effort**: Run one command and keep window open

---

**Next Action**: Open new PowerShell and run the startup command above
