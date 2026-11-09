$PSScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $PSScriptRoot
python "scripts\tracker.py" --html
Start-Process "dashboard.html"
