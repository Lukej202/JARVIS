"""Read-only Windows PC telemetry for JARVIS running inside Ubuntu WSL.

Uses *Windows* PowerShell rather than /proc or psutil inside WSL: those would
report the WSL virtual machine, not the host Windows CPU and memory.

Data is sampled on request, cached briefly, and never sent to an external API.
NVIDIA statistics use the Windows nvidia-smi utility when available. No
administrator privileges or third-party Python dependencies are required.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
import shutil
import subprocess
import threading
import time

CACHE_SECONDS = 6.0
COMMAND_TIMEOUT_SECONDS = 9
_cache_lock = threading.Lock()
_cache_expires_at = 0.0
_cached_data = None

# Run as a single PowerShell process to avoid frequent startup overhead.
# PowerShell handles failures per group so NVIDIA not being present does not
# prevent otherwise valid CPU/RAM data from being displayed.
WINDOWS_METRICS_SCRIPT = r'''
$ErrorActionPreference = 'Stop'
$results = @{
  cpu_utilization_percent = $null
  memory_total_gib = $null
  memory_used_gib = $null
  gpu_name = $null
  gpu_utilization_percent = $null
  gpu_temperature_c = $null
  gpu_memory_used_gib = $null
  gpu_memory_total_gib = $null
}
try {
  $processors = @(Get-CimInstance -ClassName Win32_Processor -ErrorAction Stop)
  if ($processors.Count -gt 0) {
    $avg = ($processors | Measure-Object -Property LoadPercentage -Average).Average
    if ($null -ne $avg) {
      $results.cpu_utilization_percent = [math]::Round([double]$avg, 0)
    }
  }
} catch { }
try {
  $os = Get-CimInstance -ClassName Win32_OperatingSystem -ErrorAction Stop
  if ($null -ne $os -and [double]$os.TotalVisibleMemorySize -gt 0) {
    $total = [double]$os.TotalVisibleMemorySize / 1048576
    $free = [double]$os.FreePhysicalMemory / 1048576
    $results.memory_total_gib = [math]::Round($total, 2)
    $results.memory_used_gib = [math]::Round([math]::Max(0, ($total - $free)), 2)
  }
} catch { }
try {
  $nvidiaCmd = Get-Command 'nvidia-smi.exe' -ErrorAction SilentlyContinue
  $nvidiaExe = if ($nvidiaCmd) { $nvidiaCmd.Source } else { $null }
  if (-not $nvidiaExe) {
    $choices = @(
      (Join-Path $env:WINDIR 'System32\nvidia-smi.exe'),
      (Join-Path $env:ProgramFiles 'NVIDIA Corporation\NVSMI\nvidia-smi.exe')
    )
    foreach ($choice in $choices) {
      if (Test-Path -LiteralPath $choice -PathType Leaf) {
        $nvidiaExe = $choice
        break
      }
    }
  }
  if ($nvidiaExe) {
    $line = & $nvidiaExe '--query-gpu=name,utilization.gpu,temperature.gpu,memory.used,memory.total' '--format=csv,noheader,nounits' 2>$null | Select-Object -First 1
    if ($line) {
      $cols = @(([string]$line).Split(','))
      if ($cols.Count -ge 5) {
        $results.gpu_name = $cols[0].Trim()
        $num = 0.0
        if ([double]::TryParse($cols[1].Trim(), [ref]$num)) { $results.gpu_utilization_percent = $num }
        if ([double]::TryParse($cols[2].Trim(), [ref]$num)) { $results.gpu_temperature_c = $num }
        if ([double]::TryParse($cols[3].Trim(), [ref]$num)) { $results.gpu_memory_used_gib = [math]::Round($num / 1024, 2) }
        if ([double]::TryParse($cols[4].Trim(), [ref]$num)) { $results.gpu_memory_total_gib = [math]::Round($num / 1024, 2) }
      }
    }
  }
} catch { }
$results | ConvertTo-Json -Compress -Depth 3
'''


def _powershell_exe() -> str | None:
    """Find the host Windows PowerShell executable from WSL."""
    detected = shutil.which("powershell.exe")
    if detected:
        return detected
    standard = Path("/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe")
    if standard.is_file():
        return str(standard)
    return None


def _number(value, low: float = 0.0, high: float = float("inf")) -> float | None:
    try:
        number = float(value)
        if math.isfinite(number) and low <= number <= high:
            return round(number, 2)
    except (TypeError, ValueError):
        pass
    return None


def _take_sample() -> dict:
    sampled_at = int(time.time())
    base = {
        "sampled_at": sampled_at,
        "source": "Windows host",
        "status": "unavailable",
        "cpu": {"percent": None},
        "memory": {"percent": None, "used_gib": None, "total_gib": None},
        "gpu": {
            "name": None, "percent": None, "temperature_c": None,
            "memory_used_gib": None, "memory_total_gib": None,
        },
        "message": "Windows metrics are unavailable from this WSL session.",
    }
    ps = _powershell_exe()
    if not ps:
        base["message"] = "Windows PowerShell is not accessible from WSL."
        return base
    try:
        completed = subprocess.run(
            [ps, "-NoProfile", "-NonInteractive", "-Command", WINDOWS_METRICS_SCRIPT],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=COMMAND_TIMEOUT_SECONDS,
            check=True,
        )
        # Some Windows installations prepend a BOM to JSON output.
        raw = json.loads(completed.stdout.strip().lstrip("\ufeff"))
        if not isinstance(raw, dict):
            raise ValueError("Unexpected PowerShell output")
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError, OSError,
            ValueError, json.JSONDecodeError):
        base["message"] = "Could not retrieve Windows metrics; check WSL interop."
        return base

    cpu = _number(raw.get("cpu_utilization_percent"), high=100)
    mem_total = _number(raw.get("memory_total_gib"))
    mem_used = _number(raw.get("memory_used_gib"))
    if mem_total is not None and mem_total <= 0:
        mem_total = None
    if mem_total is not None and mem_used is not None:
        mem_used = min(mem_used, mem_total)
        base["memory"] = {
            "percent": round(100 * mem_used / mem_total, 1),
            "used_gib": mem_used,
            "total_gib": mem_total,
        }
    base["cpu"]["percent"] = cpu

    gpu_name = raw.get("gpu_name")
    if not isinstance(gpu_name, str) or not gpu_name.strip():
        gpu_name = None
    gpu = base["gpu"]
    gpu["name"] = gpu_name
    gpu["percent"] = _number(raw.get("gpu_utilization_percent"), high=100)
    gpu["temperature_c"] = _number(raw.get("gpu_temperature_c"), high=150)
    gpu["memory_used_gib"] = _number(raw.get("gpu_memory_used_gib"))
    gpu["memory_total_gib"] = _number(raw.get("gpu_memory_total_gib"))

    if cpu is not None or base["memory"]["percent"] is not None:
        base["status"] = "ready" if gpu["percent"] is not None else "partial"
        base["message"] = (
            "Windows host CPU, memory, and NVIDIA GPU readings."
            if base["status"] == "ready" else
            "Windows CPU/RAM available; NVIDIA GPU readings are unavailable."
        )
    elif gpu["percent"] is not None:
        base["status"] = "partial"
        base["message"] = "GPU available; Windows CPU/RAM readings are unavailable."
    return base


def get_system_metrics() -> dict:
    """Return one cached, read-only Windows host telemetry snapshot."""
    global _cache_expires_at, _cached_data
    with _cache_lock:
        now = time.monotonic()
        if _cached_data is None or now >= _cache_expires_at:
            _cached_data = _take_sample()
            _cache_expires_at = time.monotonic() + CACHE_SECONDS
        return dict(_cached_data)


if __name__ == "__main__":
    print(json.dumps(get_system_metrics(), indent=2))
