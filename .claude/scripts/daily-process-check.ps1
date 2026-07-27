$ErrorActionPreference = "Stop"
Set-Location "C:\Projects\personalfinanceapp"

$prompt = @'
Run the check-running-processes skill. This is an unattended scheduled run — follow its "Unattended / scheduled runs" section: report-only, never kill/close anything, append a timestamped entry to .claude/logs/process-check.log summarizing findings (or "all clear"), then send exactly one PushNotification with a one-line summary.
'@

& "C:\Users\lizzi\AppData\Roaming\npm\claude.cmd" -p $prompt --allowedTools "Bash,Read,Write,ToolSearch,PushNotification"
