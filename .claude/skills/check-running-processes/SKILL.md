---
name: check-running-processes
description: Check the local machine for stray processes that waste resources or contribute to token usage outside the current conversation — leftover dev servers for this project, orphaned child processes, and other Claude Code CLI sessions. Use daily, or whenever asked "is anything running", "check for running servers", "check token usage", or before starting a fresh dev session.
---

# Check for Stray Running Processes

Personal finance app dev servers (`uvicorn --reload` on :8000, Vite on :5173) get left running across sessions, and multiple Claude Code CLI sessions can be open on the same machine without either one being aware of the other. This skill is the repeatable version of the manual check performed on 2026-07-27.

## 1. Check this project's dev server ports

```
netstat -ano | findstr LISTENING | findstr -E ":5173|:8000"
```

For any hit, resolve the owning process before touching it:

```
wmic process where "ProcessId=<pid>" get CommandLine
```

Confirm it's actually this project's `uvicorn app.main:app --reload --port 8000` or the frontend's `vite` before killing — don't kill a PID just because it's on a common port. Kill with `taskkill //PID <pid> //F`.

`--reload` uvicorn processes spawn a multiprocessing child (`multiprocessing.spawn`) that can survive `taskkill` on the parent. After killing the port owner, re-check for a lingering child via `wmic process where "ProcessId=<pid>" get CommandLine` — the child's command line contains `parent_pid=<the pid you just killed>`. Kill it too if found.

## 2. Check for other Claude Code CLI sessions

```
tasklist //FI "IMAGENAME eq claude.exe"
```

This lists **two different products** with the same executable name — tell them apart before doing anything:
- `...\AppData\Roaming\npm\node_modules\@anthropic-ai\claude-code\bin\claude.exe` — the actual Claude Code **CLI**. Other instances of this are other coding sessions that can run background bash tasks and burn tokens independent of the current chat.
- `...\Program Files\WindowsApps\Claude_...\app\claude.exe` — the separate Claude **desktop app** (chat windows), unrelated to Claude Code sessions.

Get the command line per PID to sort them:
```
wmic process where "ProcessId=<pid>" get CommandLine
```

**Before closing any CLI instance, identify which PID is the current session** so it doesn't kill itself — walk the process ancestry from inside the running session (PowerShell, single command, since shell PIDs are transient per tool call):

```powershell
$proc = Get-CimInstance Win32_Process -Filter "ProcessId=$PID"
$chain = @()
while ($proc) {
    $chain += "$($proc.ProcessId) $($proc.Name)"
    $parentId = $proc.ParentProcessId
    $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$parentId" -ErrorAction SilentlyContinue
}
$chain -join " <- "
```

The `claude.exe` PID in that chain is the current session — exclude it. Any other CLI `claude.exe` PID is fair game to close directly (`taskkill //PID <pid> //F`) since it's the same product as this session.

## 3. Desktop app instances — ask first

The desktop app is a different product with its own windows/conversations that may be actively in use. Don't close these without asking — confirm with the user first, since it's a bigger blast radius than cleaning up this project's own dev servers or a stray CLI session. Note: killing one desktop app instance can cascade and close sibling windows (shared process tree), so a "close all" confirmation only needs one or two `taskkill` calls, not one per PID.

## 4. Report findings plainly

State what was found and what was done (or, for the desktop app, what's pending confirmation) — PID, process, and action — rather than just "all clear". If nothing was found, say so explicitly rather than silently doing nothing.

## 5. Unattended / scheduled runs — report-only, always

When this skill runs from a scheduled/headless invocation (no interactive user present, e.g. the daily Task Scheduler job — see `.claude/scripts/daily-process-check.ps1`), **never kill anything**, regardless of §1-3 above — those kill steps are for interactive sessions where a human can see and correct a wrong guess. Unattended, a wrong guess about which process is "safe" can't be caught before it's acted on. Instead:

1. Run the checks in §1-3 read-only (skip every `taskkill`).
2. Append a timestamped entry to `.claude/logs/process-check.log` (create the file/directory if missing) summarizing what's running — or "all clear" if nothing was found.
3. Send exactly one `PushNotification` with a one-line summary (e.g. "Process check: personalfinanceapp dev servers still running" or "Process check: all clear").

This was chosen deliberately (2026-07-27) over auto-closing anything unattended, specifically so a scheduled run can't destroy in-progress work in another session or the desktop app without a human able to weigh in.
