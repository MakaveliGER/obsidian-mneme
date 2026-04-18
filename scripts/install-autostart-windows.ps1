# Install a Windows Task Scheduler entry that launches the Mneme MCP server
# in HTTP transport mode at user login.
#
# Usage (from an elevated PowerShell or regular prompt — a scheduled task
# running as the current user does NOT need admin):
#
#   pwsh -File scripts/install-autostart-windows.ps1
#   pwsh -File scripts/install-autostart-windows.ps1 -Port 9000
#   pwsh -File scripts/install-autostart-windows.ps1 -PythonExe "C:\path\to\.venv\Scripts\pythonw.exe"
#
# What it does:
#   - Registers a task named "Mneme MCP (HTTP)".
#   - Trigger: at user logon.
#   - Action: runs `pythonw.exe -m mneme.cli serve --transport streamable-http`
#     so no console window pops up.
#   - Runs as the current user (no admin needed).
#
# Uninstall with `scripts/uninstall-autostart-windows.ps1`.

[CmdletBinding()]
param(
    [string] $TaskName = "Mneme MCP (HTTP)",
    [string] $PythonExe = "",
    [int]    $Port = 8765,
    [string] $HostAddr = "127.0.0.1"
)

$ErrorActionPreference = "Stop"

# Resolve pythonw.exe: prefer the one the user passed, then fall back to the
# active venv, then PATH. pythonw = no console window.
if (-not $PythonExe) {
    if ($env:VIRTUAL_ENV) {
        $candidate = Join-Path $env:VIRTUAL_ENV "Scripts\pythonw.exe"
        if (Test-Path $candidate) { $PythonExe = $candidate }
    }
    if (-not $PythonExe) {
        $found = Get-Command pythonw.exe -ErrorAction SilentlyContinue
        if ($found) { $PythonExe = $found.Path }
    }
}
if (-not $PythonExe -or -not (Test-Path $PythonExe)) {
    Write-Error "pythonw.exe not found. Pass -PythonExe '<full path to pythonw.exe>'."
    exit 1
}

$Arguments = "-m mneme.cli serve --transport streamable-http --host $HostAddr --port $Port"

Write-Host "Installing scheduled task: $TaskName"
Write-Host "  Python  : $PythonExe"
Write-Host "  Args    : $Arguments"
Write-Host "  Endpoint: http://$HostAddr`:$Port/mcp"

$action    = New-ScheduledTaskAction -Execute $PythonExe -Argument $Arguments
$trigger   = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive
$settings  = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 0) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1)

$task = New-ScheduledTask -Action $action -Trigger $trigger -Principal $principal -Settings $settings `
    -Description "Mneme MCP server (streamable-http transport). Auto-starts at user logon."

Register-ScheduledTask -TaskName $TaskName -InputObject $task -Force | Out-Null

Write-Host "Installed. Start now with:  Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "Uninstall with:              scripts/uninstall-autostart-windows.ps1"
