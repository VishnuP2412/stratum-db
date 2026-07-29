import os, signal, subprocess, sys, time
from stratum.engine import Engine
engine = Engine()
for i in range(1,101):
    engine.put(f"key{i}", f"value{i}")
cmd = [sys.executable, "-c", "from stratum.engine import Engine; Engine().compact()"]
proc = subprocess.Popen(cmd)
print(f"[parent] PID={proc.pid}")
time.sleep(0.5)
os.kill(proc.pid, signal.SIGKILL)
time.sleep(0.2)
engine2 = Engine()
missing = [f"key{i}" for i in range(1,101) if engine2.get(f"key{i}") != f"value{i}"]
if missing:
    print("❌ Lost:", missing); sys.exit(1)
print("✅ All recovered")
