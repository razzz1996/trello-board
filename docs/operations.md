# Operations Guide

## Current local runtime

- Application root: C:\Users\PC 19\Desktop\PRODUCTIVITY WEBSITE
- Web application server: Waitress on 127.0.0.1:8000
- Development reverse proxy: Caddy on 127.0.0.1:8080
- Team LAN frontend: Vite on 172.16.0.222:5173
- Windows Firewall scope: TCP 5173 from 172.16.0.0/23 only
- PostgreSQL 18.6: loopback only on 127.0.0.1 and ::1 port 5432
- Scheduler and worker: Python management commands with database-backed heartbeats
- Slack mode: off
- AI/model execution: disabled by configuration and startup guard
- Development health:
  - /api/v1/health/live
  - /api/v1/health/ready
  - administrator-only /api/v1/health/detail

## Health thresholds

Initial thresholds follow the runbook:
- worker or scheduler heartbeat older than 90 seconds: warning
- oldest eligible READY/RETRY_WAIT job older than 5 minutes: warning
- independent backup older than 26 hours: warning
- free disk below 10 percent: warning
- failed and UNKNOWN jobs are always displayed to administrators

The host cannot notify anyone when it is powered off. No independent external monitor is currently configured. Until one exists, the daily operator must perform a manual availability check.

## Daily operator checklist

Operator: UNASSIGNED - owner input required.
Backup operator: UNASSIGNED - owner input required.

1. Open the private application and confirm liveness/readiness.
2. Open Administration > Operational health.
3. Confirm worker and scheduler heartbeats are fresh.
4. Check failed and UNKNOWN jobs.
5. Confirm the oldest ready job is under five minutes.
6. Confirm disk free space is at least ten percent.
7. Confirm the independent backup is no older than 26 hours.
8. Confirm Slack mode is appropriate for the current gate. It must remain off before the approved pilot.
9. Record any outage, recovery action, or manual reconciliation.

## Startup

Host-only development/manual:
1. ops\windows\run-web.ps1
2. ops\windows\run-scheduler.ps1
3. ops\windows\run-worker.ps1
4. ops\windows\run-caddy-dev.ps1

Office LAN access:
1. Double-click `Start eMEGA Team Access.cmd` on the desktop.
2. Share `http://172.16.0.222:5173/` with users on the same office subnet.
3. Use `Stop eMEGA Team Access.cmd` before maintenance or when LAN access is no longer needed.
4. If the host's Ethernet address changes, update `PRODUCTIVITY_LAN_HOST`, the Vite launcher, and the scoped firewall rule before restarting.

Pilot supervision is not yet configured. S18 requires a restricted service identity plus reboot, logoff and forced-failure recovery verification.

## Shutdown / maintenance

1. Stop new user writes at the front door or announce maintenance.
2. Allow active mutations to finish.
3. Stop scheduler and worker before a consistent backup/restore operation.
4. Keep Slack off during restore drills.
5. Restart database-dependent services only after database readiness is confirmed.
6. Verify /health/ready and job heartbeats before reopening writes.

## Backup and restore

The implementation supports:
- PostgreSQL custom-format dump
- local staging copy
- SHA-256 integrity verification
- independent destination copy
- 7 daily plus 4 weekly retention after a newly verified backup succeeds
- restore into a separate temporary database
- restore_mode=true and slack_mode=off guards
- smoke queries and cleanup

Current blocker: this PC has one physical disk and no mapped independent share. A same-disk folder is not accepted as an independent backup. S17/T18 cannot be verified until an existing encrypted external drive or vetted independent network destination is provided.

## Credential and token rotation

Database credentials live only in protected runtime secret files and are excluded from Git. Slack tokens, if later approved, must use the same file-only pattern. A leaked credential must be rotated immediately; evidence must record the incident without repeating the secret.

Admin password reset increments session generation and revokes active sessions. Disabled users are also rejected by session middleware.

## Network outage

Local work must continue while the internet is unavailable. Slack delivery requires internet and must not block database/task operations. Retryable Slack pre-connection failures remain queued; ambiguous post-send failures become UNKNOWN and require reconciliation.

## Host failure

1. Record the outage start if known.
2. Do not claim the host can self-alert while powered off.
3. Recover power/host first.
4. Verify PostgreSQL, Caddy, web, scheduler and worker.
5. Check delayed reports/jobs and UNKNOWN sends.
6. Restore only from an independently verified backup if database recovery is required.
7. Keep Slack off during restore/reconciliation.

## Escalation

Escalate immediately for:
- database readiness failure
- repeated worker heartbeat failure
- growing ready queue over five minutes
- any UNKNOWN outbound delivery requiring business reconciliation
- backup missing/stale or integrity mismatch
- free disk below ten percent
- private TLS/trust failure on an authorised client
- any suspected credential/token exposure


## Board, card, and recurrence operations

- Only active administrators may create or permanently delete boards.
- Board deletion requires typing the exact board name. It removes the board, cards, schedules, occurrences, task notifications, and task activity stored under that board. Report snapshots remain immutable historical records.
- Any active user may permanently delete a card from Card details. Card deletion uses task and board version checks so a stale browser cannot silently remove a newer card state.
- A card may repeat daily, weekly, or monthly. The user must choose the next action date and time.
- When the scheduler observes that date, it enqueues a generation-scoped recurrence job. The worker moves the same card back to Inbox, clears the old commitment/current submission state, resets checked checklist items, and advances the next action date.
- Monthly repetition preserves the selected day where possible and uses the final valid day in shorter months.
- If the host was offline at the action time, the next scheduler pass processes the overdue occurrence and advances the schedule to the next future date.
