"""Capture the primary Windows display from Python running in WSL."""

import base64
import subprocess

SCREEN_CAPTURE = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$bounds = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
$bitmap = New-Object System.Drawing.Bitmap($bounds.Width, $bounds.Height)
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
$memory = New-Object System.IO.MemoryStream

try {
    $graphics.CopyFromScreen(
        $bounds.Left, $bounds.Top, 0, 0, $bitmap.Size
    )
    $bitmap.Save(
        $memory,
        [System.Drawing.Imaging.ImageFormat]::Jpeg
    )
    [Console]::Out.Write(
        [Convert]::ToBase64String($memory.ToArray())
    )
}
finally {
    $graphics.Dispose()
    $bitmap.Dispose()
    $memory.Dispose()
}
"""


def capture_screen() -> str:
    """Return a Base64 JPEG of the Windows primary monitor."""
    encoded_command = base64.b64encode(
        SCREEN_CAPTURE.encode("utf-16le")
    ).decode("ascii")

    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-EncodedCommand",
            encoded_command,
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=20,
    )

    screenshot = result.stdout.strip()
    if not screenshot:
        raise RuntimeError("Windows returned an empty screenshot.")

    return screenshot



