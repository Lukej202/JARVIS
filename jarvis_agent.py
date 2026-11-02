"""JARVIS: desktop tools, workspace files, memory, and on-demand screen vision."""
from windows_input_test import paste_into_notepad
import subprocess
import platform
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI
from agents import Agent, Runner, SQLiteSession, function_tool
from vision_test import capture_screen

load_dotenv()
vision_client = OpenAI()

# For now these file tools work only inside this WSL directory.
WORKSPACE = (Path.home() / "JARVIS" / "workspace").resolve()
WORKSPACE.mkdir(parents=True, exist_ok=True)


def safe_path(name: str, *, allow_root: bool = False) -> Path:
    """Resolve a relative path and reject access outside WORKSPACE."""
    if not name or "\\" in name:
        raise ValueError("Use a relative path inside the workspace.")
    path = (WORKSPACE / name).resolve()
    if not path.is_relative_to(WORKSPACE):
        raise ValueError("Access outside the workspace is denied.")
    if path == WORKSPACE and not allow_root:
        raise ValueError("Please specify a file or subfolder.")
    return path


@function_tool
def open_notepad() -> str:
    """Open Windows Notepad."""
    subprocess.Popen(["notepad.exe"])
    return "Notepad launch requested."

@function_tool
def open_VSCode() -> str:
    """Open Visual Studio Code."""
    subprocess.Popen(["code.exe"])
    return "Visual Studio Code launch requested."

@function_tool
def open_calculator() -> str:
    """Open Windows Calculator."""
    subprocess.Popen(["calc.exe"])
    return "Calculator launch requested."


@function_tool
def create_file(filename: str, content: str) -> str:
    """Create a new UTF-8 text file in the workspace without overwriting files."""
    try:
        path = safe_path(filename)
        with path.open("x", encoding="utf-8") as file:
            file.write(content)
        return f"Created {path.relative_to(WORKSPACE)} in the workspace."
    except (ValueError, OSError) as exc:
        return f"Could not create file: {exc}"


@function_tool
def read_file(filename: str) -> str:
    """Read a small UTF-8 text file from the workspace."""
    try:
        path = safe_path(filename)
        if path.stat().st_size > 100_000:
            return "File too large for this tool (limit: 100 KB)."
        return path.read_text(encoding="utf-8")
    except (ValueError, OSError, UnicodeError) as exc:
        return f"Could not read file: {exc}"


@function_tool
def write_file(filename: str, content: str) -> str:
    """Write a workspace text file; get terminal approval before replacing an existing file."""
    try:
        path = safe_path(filename)
        if path.exists():
            answer = input(
                f"JARVIS: Overwrite '{path.relative_to(WORKSPACE)}'? (y/N): "
            ).strip().lower()
            if answer != "y":
                return "File change cancelled."
        path.write_text(content, encoding="utf-8")
        return f"Saved {path.relative_to(WORKSPACE)}."
    except (ValueError, OSError) as exc:
        return f"Could not write file: {exc}"


@function_tool
def list_directory(directory: str = ".") -> str:
    """List items in a workspace folder. Use '.' for the workspace root."""
    try:
        path = safe_path(directory, allow_root=True)
        if not path.is_dir():
            return "That is not a directory."
        names = sorted(p.name for p in path.iterdir())
        return "\n".join(names[:100]) or "Directory is empty."
    except (ValueError, OSError) as exc:
        return f"Could not list directory: {exc}"


@function_tool
def search_files(query: str) -> str:
    """Find files with a matching name inside the workspace."""
    if not query.strip():
        return "Please supply a filename search term."
    results = [
        str(path.relative_to(WORKSPACE))
        for path in WORKSPACE.rglob("*")
        if path.is_file() and query.lower() in path.name.lower()
    ]
    return "\n".join(results[:50]) or "No matching files."


@function_tool
def get_system_info() -> str:
    """Get basic information about the WSL Linux environment."""
    return f"OS: {platform.system()} | Release: {platform.release()}"


@function_tool
def inspect_screen(question: str) -> str:
    """Look at the Windows screen only when the user explicitly requests it.

    Ask permission before capturing and sending the screenshot to the AI API.
    """
    approval = input(
        "JARVIS: Capture and send the primary monitor to the AI? (y/N): "
    ).strip().lower()
    if approval != "y":
        return "Screen inspection cancelled."

    try:
        image = capture_screen()
        response = vision_client.responses.create(
            model="gpt-6-luna",
            input=[
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": question},
                        {
                            "type": "input_image",
                            "image_url": f"data:image/jpeg;base64,{image}",
                            "detail": "high",
                        },
                    ],
                }
            ],
        )
        return response.output_text or "No visual description was returned."
    except Exception as exc:
        return f"Screen inspection failed: {type(exc).__name__}: {exc}"



@function_tool
def type_in_notepad(text: str) -> str:
    """Open Notepad and paste user-requested text."""

    print("\nJARVIS wants to type:")
    print("--------------------")
    print(text)
    print("--------------------")

    approval = input(
        "Allow JARVIS to type this into Notepad? (y/N): "
    ).strip().lower()

    if approval != "y":
        return "Keyboard action cancelled."

    try:
        result = paste_into_notepad(text)
        return f"Paste command executed. {result}"
    except Exception as error:
        return f"Keyboard automation failed: {error}"

jarvis = Agent(
    name="JARVIS",
    model="gpt-6-luna",
    instructions=(
        "You are JARVIS, a helpful personal desktop assistant. "
        "Respond conversationally and remember context. "
        "Use tools to perform requested actions, and do not claim success without evidence. "
        "File tools only access the JARVIS workspace in WSL. "
        "When using file tools, give paths relative to the workspace, not prefixed with 'workspace/'. "
        "Only call inspect_screen when the user explicitly asks to see or inspect the screen. "
        "Never delete files or run arbitrary shell commands."
    ),
    tools=[
        open_notepad,
        open_calculator,
        create_file,
        read_file,
        write_file,
        list_directory,
        search_files,
        get_system_info,
        inspect_screen,
        type_in_notepad,
    ],
)


def main() -> None:
    session = SQLiteSession(
        "jarvis_main", str(Path.home() / "JARVIS" / "jarvis_memory.db")
    )
    print("JARVIS: Online. Awaiting instructions.")
    print(f"JARVIS: Workspace is {WORKSPACE}")
    while True:
        try:
            command = input("You: ").strip()
            if command.lower() in {"exit", "quit"}:
                print("JARVIS: Shutting down.")
                break
            if not command:
                continue
            result = Runner.run_sync(jarvis, command, session=session)
            print("JARVIS:", result.final_output)
        except (KeyboardInterrupt, EOFError):
            print("\nJARVIS: Shutting down.")
            break
        except Exception as exc:
            print(f"JARVIS: Error: {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    main()
