import json
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest

from medialink.storage import ROOT


class BuildTests(unittest.TestCase):
    def test_failed_build_restores_callers_environment_and_working_directory(self):
        with TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / "scripts").mkdir()
            (folder / "src/medialink").mkdir(parents=True)
            (folder / ".venv/Scripts").mkdir(parents=True)
            (folder / "runtime").mkdir()
            (folder / "scripts/build.ps1").write_bytes((ROOT / "scripts/build.ps1").read_bytes())
            (folder / "src/medialink/__init__.py").write_text('__version__ = "0.0.1"', encoding="utf-8")
            # Invalid PE forces failure only after the script has changed its environment.
            (folder / ".venv/Scripts/python.exe").write_bytes(b"audit-invalid-executable")
            for name in ("ffmpeg.exe", "ffprobe.exe", "LICENSE"):
                (folder / "runtime" / name).touch()
            script = folder / "verify.ps1"
            script.write_text("""$ErrorActionPreference = 'Stop'
$names = @('TMP','TEMP','PYINSTALLER_CONFIG_DIR','QT_QPA_PLATFORM','PATH','PYTHONPATH')
$before = @{}
foreach ($name in $names) { $before[$name] = [Environment]::GetEnvironmentVariable($name, 'Process') }
$locationBefore = (Get-Location).Path
$failed = $false
try { & (Join-Path $PSScriptRoot 'scripts\\build.ps1') | Out-Null } catch { $failed = $true }
$same = $true
foreach ($name in $names) {
    if ($before[$name] -cne [Environment]::GetEnvironmentVariable($name, 'Process')) { $same = $false }
}
[PSCustomObject]@{ Failed=$failed; EnvironmentRestored=$same; LocationRestored=((Get-Location).Path -eq $locationBefore); StageCreated=(Test-Path (Join-Path $PSScriptRoot 'build')) } | ConvertTo-Json -Compress
""", encoding="utf-8")
            powershell = str(Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe")
            result = subprocess.run([powershell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
                                    cwd=ROOT, capture_output=True, timeout=20, check=True,
                                    creationflags=subprocess.CREATE_NO_WINDOW)
            values = json.loads(result.stdout.decode("utf-8-sig"))
            self.assertEqual(values, {"Failed": True, "EnvironmentRestored": True, "LocationRestored": True, "StageCreated": True})
