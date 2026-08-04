"""Windows built-in Chinese speech recognition fallback."""

from __future__ import annotations

import base64
import os
import subprocess


_PS_SCRIPT = r'''
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Speech
$info = [System.Speech.Recognition.SpeechRecognitionEngine]::InstalledRecognizers() |
  Where-Object { $_.Culture.Name -eq "zh-CN" } | Select-Object -First 1
if ($null -eq $info) { throw "No zh-CN Windows speech recognizer installed" }
$recognizer = New-Object System.Speech.Recognition.SpeechRecognitionEngine($info)
$recognizer.SetInputToWaveFile($env:GRAPHRAG_AUDIO_PATH)
$texts = New-Object System.Collections.Generic.List[string]
while ($true) {
  $result = $recognizer.Recognize()
  if ($null -eq $result) { break }
  if ($result.Text) { $texts.Add($result.Text) }
}
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::Out.Write(($texts -join ""))
'''


def transcribe_windows(audio_path: str) -> str:
    encoded = base64.b64encode(_PS_SCRIPT.encode("utf-16-le")).decode("ascii")
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-EncodedCommand",
            encoded,
        ],
        env={**os.environ, "GRAPHRAG_AUDIO_PATH": audio_path},
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        check=True,
    )
    return result.stdout.strip()
