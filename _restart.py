"""Force-kill ALL python.exe except hermes, then start one clean tattoo_bot."""
import subprocess, os, time, json

# 1. Kill all cmd windows titled "Tattoo Bot"
ps_cmd = r"Get-Process cmd -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowTitle -like '*Tattoo*' } | Select-Object Id,MainWindowTitle"
r = subprocess.run(["powershell", "-NoProfile", "-Command", ps_cmd], capture_output=True, text=True)
print("CMD Tattoo windows:\n", r.stdout)

# kill by window title via taskkill
subprocess.run(["taskkill", "/F", "/FI", "WINDOWTITLE eq Tattoo Bot*"], capture_output=True)
subprocess.run(["taskkill", "/F", "/T", "/FI", "WINDOWTITLE eq Tattoo Bot*"], capture_output=True)
time.sleep(1)

# 2. Find python.exe processes and keep only hermes ones
ps2 = r"Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Select-Object ProcessId,CommandLine | ConvertTo-Json"
r2 = subprocess.run(["powershell", "-NoProfile", "-Command", ps2], capture_output=True, text=True)
procs = []
out2 = r2.stdout.strip()
if out2:
    try:
        data = json.loads(out2)
        if isinstance(data, dict):
            data = [data]
        for d in data:
            pid = int(d["ProcessId"])
            cl = d.get("CommandLine", "") or ""
            if "hermes" in cl.lower():
                print(f"  KEEP  {pid}  (hermes)")
            elif "tattoo_bot" in cl.lower() or "main.py" in cl.lower():
                print(f"  KILL  {pid}  ({cl[:80]})")
                procs.append(pid)
    except Exception as e:
        print("parse error:", e)

for pid in procs:
    try:
        os.kill(pid, 9)
        print(f"  killed {pid}")
    except Exception as e:
        print(f"  failed {pid}: {e}")

time.sleep(3)
print(f"\nKilled {len(procs)} tattoo_bot processes.")

# 3. Start fresh
subprocess.Popen(["cmd", "/c", r"C:\Projects\tattoo_bot\start_bot.bat"], creationflags=subprocess.CREATE_NEW_CONSOLE)
print("Started fresh bot.")
time.sleep(6)

# 4. Show last log
with open(r"C:\Projects\tattoo_bot\bot.log", "r", encoding="utf-8") as f:
    print("\n--- last 8 log lines ---")
    print("".join(f.readlines()[-8:]), end="")
