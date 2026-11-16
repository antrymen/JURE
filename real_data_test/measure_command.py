"""Measure a subprocess using the standard library (Linux resource units)."""
import json
from pathlib import Path
import resource
import subprocess
import sys
import time

if __name__ == "__main__":
    destination, command = Path(sys.argv[1]), sys.argv[2:]
    start = time.monotonic()
    result = subprocess.run(command)
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    destination.write_text(json.dumps({
        "command": command, "exit_code": result.returncode,
        "wall_seconds": time.monotonic() - start,
        "user_cpu_seconds": usage.ru_utime, "system_cpu_seconds": usage.ru_stime,
        "largest_child_peak_rss_kib": usage.ru_maxrss,
        "memory_note": "Linux child high-water mark; not simultaneous aggregate worker memory",
    }, indent=2) + "\n")
    raise SystemExit(result.returncode)
