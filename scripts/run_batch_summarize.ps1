# Run batch summarize (load .env, then python -m ancilla_bot.cli.main batch summarize).
# For use from Task Scheduler etc. Example: trigger daily at 3:00, action:
#   Program: powershell.exe
#   Arguments: -ExecutionPolicy Bypass -File "C:\path\to\ancilla-bot\scripts\run_batch_summarize.ps1"
#   Start in: project root

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
Set-Location ..

if (Test-Path .env) {
    Get-Content .env -Encoding UTF8 | ForEach-Object {
        $line = $_.Trim()
        if ($line -eq "" -or $line.StartsWith("#")) { return }
        $i = $line.IndexOf("=")
        if ($i -gt 0) {
            $key = $line.Substring(0, $i).Trim()
            $val = $line.Substring($i + 1).Trim()
            if ($val.Length -ge 2 -and $val.StartsWith('"') -and $val.EndsWith('"')) {
                $val = $val.Substring(1, $val.Length - 2)
            }
            [Environment]::SetEnvironmentVariable($key, $val, "Process")
        }
    }
}

$pythonExe = $null
if (Test-Path .venv\Scripts\python.exe) {
    $pythonExe = (Resolve-Path .venv\Scripts\python.exe).Path
} else {
    $pythonExe = "python"
}

& $pythonExe -m ancilla_bot.cli.main batch summarize
exit $LASTEXITCODE
