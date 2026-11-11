"""Approval-only workspace execution. NOT a security sandbox.

Call execute_approved_program only from JARVIS's approved action dispatcher.
"""
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import secrets

MAX_SOURCE_BYTES = 100_000
MAX_OUTPUT_CHARS = 12_000
TIMEOUT_SECONDS = 20
TOP_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")


def _source(root: Path, relative: str, allowed: tuple[str, ...]) -> Path:
    if not isinstance(relative, str) or not relative or "\\" in relative or "\x00" in relative:
        raise ValueError("Provide a relative workspace filename.")
    name = Path(relative)
    if name.is_absolute() or ".." in name.parts:
        raise ValueError("Filename must stay within workspace.")
    path = (root / name).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("File resolves outside workspace.")
    if not path.is_file() or path.suffix.lower() not in allowed:
        raise ValueError(f"Expected an existing {', '.join(allowed)} file in workspace.")
    if path.stat().st_size > MAX_SOURCE_BYTES:
        raise ValueError("Source exceeds 100 KB limit.")
    return path


def validate_request(root: Path, filename: str, testbench: str = "", top_module: str = "") -> dict:
    root = root.resolve()
    if not isinstance(filename, str):
        raise ValueError("Filename is required.")
    suffix = Path(filename).suffix.lower()
    if suffix == ".py":
        source = _source(root, filename, (".py",))
        if testbench or top_module:
            raise ValueError("Testbench and top_module apply only to Verilog.")
        return {"language": "python", "filename": str(source.relative_to(root)), "testbench": "", "top_module": ""}
    if suffix not in (".v", ".sv"):
        raise ValueError("Only .py, .v and .sv are supported.")
    source = _source(root, filename, (".v", ".sv"))
    tb = _source(root, testbench, (".v", ".sv")) if testbench else None
    if top_module and not TOP_RE.fullmatch(top_module):
        raise ValueError("Invalid top-level module name.")
    if tb and not top_module:
        raise ValueError("Specify the testbench top_module, e.g. counter_tb.")
    if not tb and top_module:
        raise ValueError("Provide testbench when specifying top_module.")
    if tb and tb == source:
        raise ValueError("Design source and testbench must be different files.")
    return {"language": "verilog", "filename": str(source.relative_to(root)),
            "testbench": str(tb.relative_to(root)) if tb else "", "top_module": top_module}


def _run(argv: list[str], *, cwd: Path) -> tuple[int, str]:
    try:
        proc = subprocess.run(argv, cwd=cwd, capture_output=True, text=True,
                              errors="replace", timeout=TIMEOUT_SECONDS, stdin=subprocess.DEVNULL,
                              check=False)
    except FileNotFoundError as exc:
        return 127, f"Required tool not installed: {exc.filename}"
    except subprocess.TimeoutExpired:
        return 124, f"Execution timed out after {TIMEOUT_SECONDS} seconds."
    output = (proc.stdout or "") + ("\n" if proc.stdout and proc.stderr else "") + (proc.stderr or "")
    if len(output) > MAX_OUTPUT_CHARS:
        output = output[:MAX_OUTPUT_CHARS] + "\n...[output truncated]"
    return proc.returncode, output.strip() or "(no output)"


def execute_approved_program(root: Path, filename: str, testbench: str = "", top_module: str = "") -> str:
    """Execute only AFTER explicit user approval. Code runs with WSL user privileges."""
    data = validate_request(root, filename, testbench, top_module)
    root = root.resolve()
    src = root / data["filename"]
    if data["language"] == "python":
        # Isolated Python mode avoids user-site and environment injection;
        # it does NOT restrict filesystem/network/process permissions.
        rc, out = _run([sys.executable, "-I", "-B", str(src)], cwd=root)
        return f"Python: {data['filename']}\nExit code: {rc}\nOutput:\n{out}"
    iverilog = shutil.which("iverilog")
    if not iverilog:
        return "Icarus Verilog isn't installed. Install with: sudo apt install iverilog"
    with tempfile.TemporaryDirectory(prefix="jarvis_sim_") as temp:
        work = Path(temp)
        if not data["testbench"]:
            rc, out = _run([iverilog, "-g2012", "-t", "null", str(src)], cwd=work)
            return f"Verilog syntax check: {data['filename']}\nExit code: {rc}\nOutput:\n{out}\nNo simulation run (no testbench provided)."
        vvp = shutil.which("vvp")
        if not vvp:
            return "Icarus simulator vvp isn't installed. Install with: sudo apt install iverilog"
        binary = work / "simulation.vvp"
        tb = root / data["testbench"]
        compile_args = [iverilog, "-g2012", "-s", data["top_module"], "-o", str(binary), str(src), str(tb)]
        rc, compile_output = _run(compile_args, cwd=work)
        if rc:
            return f"Verilog compile FAILED (exit {rc}):\n{compile_output}"
        sim_rc, sim_output = _run([vvp, "-n", str(binary)], cwd=work)
        saved = []
        for vcd in work.glob("*.vcd"):
            if not vcd.is_file() or vcd.is_symlink() or vcd.stat().st_size > 10_000_000:
                continue
            output_dir = root / "simulations"
            output_dir.mkdir(exist_ok=True)
            dest = output_dir / (f"{data['top_module']}_{secrets.token_hex(4)}.vcd")
            with vcd.open("rb") as stream, dest.open("xb") as out_file:
                shutil.copyfileobj(stream, out_file)
            saved.append(str(dest.relative_to(root)))
        waveform = ("\nWaveform(s): " + ", ".join(saved)) if saved else "\nNo .vcd waveform generated; add $dumpfile/$dumpvars to testbench."
        return (f"Verilog compiled successfully: {data['filename']} + {data['testbench']}\n"
                f"Simulation top: {data['top_module']}\nSimulation exit code: {sim_rc}\n"
                f"Simulation output:\n{sim_output}" + waveform)
