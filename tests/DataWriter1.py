import subprocess
import sys
from pathlib import Path

CRASH_WRITER = Path("crash_writer.py")
data_dir = Path("./data_manual_test")
data_dir.mkdir(exist_ok=True)

target_line = "WRITE_DONE 500"

proc = subprocess.Popen(
    [sys.executable, "-u", str(CRASH_WRITER), str(data_dir), "1000", "500", "64"],
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
    bufsize=1,
)

for line in proc.stdout:
    print(line.strip())
    if line.strip() == target_line:
        proc.kill()
        print(f">>> KILLED right after {target_line}")
        break

proc.wait(timeout=5)
print(">>> confirmed dead")