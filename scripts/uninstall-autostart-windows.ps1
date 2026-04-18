# Removes the "Mneme MCP (HTTP)" scheduled task created by
# scripts/install-autostart-windows.ps1.
#
# Usage:
#   pwsh -File scripts/uninstall-autostart-windows.ps1
#   pwsh -File scripts/uninstall-autostart-windows.ps1 -TaskName "Custom Name"

[CmdletBinding()]
param(
    [string] $TaskName = "Mneme MCP (HTTP)"
)

$ErrorActionPreference = "Stop"

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if (-not $task) {
    Write-Host "Task '$TaskName' not found. Nothing to uninstall."
    exit 0
}

# Stop the task if it's currently running — otherwise Unregister can race.
try {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
} catch {
    # Task may not be running; ignore.
}

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
Write-Host "Uninstalled scheduled task: $TaskName"
