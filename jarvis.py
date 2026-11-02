
import subprocess

def open_notepad():
    subprocess.Popen(["notepad.exe"])
    print("JARVIS: Opening Notepad.")

print("JARVIS initialized. Awaiting commands.")

while True:
    command = input("You: ").strip().lower()

    if command == "open notepad":
        open_notepad()

    elif command in ("exit", "quit"):
        print("JARVIS: Shutting down.")
        break

    else:
        print("JARVIS: Unknown command.")
