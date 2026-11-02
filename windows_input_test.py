
import subprocess
import base64


POWERSHELL_SCRIPT = r"""
$ErrorActionPreference = "Stop"

# Windows keyboard API
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;

public class Keyboard {
    [DllImport("user32.dll")]
    public static extern void keybd_event(
        byte key, byte scan, uint flags, UIntPtr extra
    );
}
'@

# Open Notepad
Start-Process notepad.exe
Start-Sleep -Seconds 2

# Locate the Notepad window
$shell = New-Object -ComObject WScript.Shell

$notepad = Get-Process notepad |
    Where-Object { $_.MainWindowHandle -ne 0 } |
    Sort-Object StartTime -Descending |
    Select-Object -First 1

if (-not $notepad) {
    throw "Notepad window not found."
}

# Focus Notepad
if (-not $shell.AppActivate($notepad.Id)) {
    throw "Could not activate Notepad."
}

Start-Sleep -Milliseconds 500

# Press Ctrl + V using Windows API
[Keyboard]::keybd_event(0x11, 0, 0, [UIntPtr]::Zero)
[Keyboard]::keybd_event(0x56, 0, 0, [UIntPtr]::Zero)

Start-Sleep -Milliseconds 100

# Release V and Ctrl
[Keyboard]::keybd_event(0x56, 0, 2, [UIntPtr]::Zero)
[Keyboard]::keybd_event(0x11, 0, 2, [UIntPtr]::Zero)

Write-Output "Paste shortcut sent."
"""




def paste_into_notepad(text: str):
    if not text:
        raise ValueError("Cannot paste empty text.")

    # Copy the text into the Windows clipboard
    subprocess.run(
        ["clip.exe"],
        input=text,
        text=True,
        check=True
    )

    # Run the Windows automation script
    encoded_script = base64.b64encode(
        POWERSHELL_SCRIPT.encode("utf-16le")
    ).decode("ascii")

    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-STA",
            "-EncodedCommand",
            encoded_script,
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )

    return result.stdout.strip()



if __name__ == "__main__":
    message = "print('Hello from JARVIS')\nprint(2 + 2)"

    print("Text to paste:\n", message)

    approval = input(
        "\nAllow JARVIS to paste into Notepad? (y/N): "
    ).strip().lower()

    if approval == "y":
        print(paste_into_notepad(message))
    else:
        print("JARVIS: Cancelled.")
