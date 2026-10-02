# eMEGA Productivity - Local Development Handoff

## Current local access

- Team LAN website: `http://172.16.0.178:5173/`
- Standard host-only website: `http://127.0.0.1:8080/`
- Initial administrator username: `raz`
- Administrator password: known only to the operator; it is not stored in project documentation.
- Environment: `development`
- Slack mode: `off`

The Team Access launcher now detects the host's current Ethernet address automatically. The current address is `172.16.0.178`. The Windows Firewall rule permits TCP 5173 only from the local `172.16.0.0/23` subnet. Waitress, Caddy, and PostgreSQL remain loopback-only and are reached through Vite's same-origin API proxy.

## One-click start and stop

Four desktop launchers are available:

- `Start eMEGA Productivity.cmd` â€” host-only mode
- `Stop eMEGA Productivity.cmd`
- `Start eMEGA Team Access.cmd` â€” office LAN mode
- `Stop eMEGA Team Access.cmd`

The Team Access launcher checks PostgreSQL, starts Waitress, scheduler, worker, and Caddy, then runs `npm run dev -- --host 172.16.0.178 --port 5173 --strictPort`. It waits for API readiness and opens the LAN URL.

The stop launchers stop the relevant web, scheduler, worker, proxy, and Vite processes. PostgreSQL remains running as the Windows service `postgresql-x64-18`.

## Runtime components

- PostgreSQL 18.6
  - database listener restricted to `127.0.0.1` / `::1`
  - SCRAM authentication enabled
  - application and maintenance credentials stored only in ignored, ACL-protected runtime secret files
- Django 5.2.17 + Django REST Framework 3.18.1
- Waitress 3.0.2 on `127.0.0.1:8000`
- Caddy 2.11.4 on `127.0.0.1:8080`
- React 19.3.0 + TypeScript + Vite
- Scheduler and worker loops with database heartbeats

## Verified behavior

Latest full verifier evidence:

- `evidence/verify_all_20261002T074348Z.json`
- `evidence/lan_access_20261002T051351Z.json`
- `evidence/lan_login_throttle_20260930T021959Z.json`
- `evidence/local_restart_cycle_20260929T054104Z.json`

The latest full verifier passed:

- Python compilation
- Django system checks
- migration drift check
- Ruff
- mypy
- frontend typecheck
- production frontend build
- npm audit: 0 vulnerabilities
- calendar fixtures
- PostgreSQL connectivity
- full automated test suite: 90 passing tests
- frontend UUID compatibility tests: 3 passing tests
- live LAN login, persistent-session, card-create, card-move, and card-delete workflow
- live API route matrix and end-to-end task workflow
- live admin board deletion, member card deletion, and recurrence execution
- live admin state changes with audit persistence
- LAN login throttling isolates five-attempt account locks without blocking other office users
- database integrity audit with no issues
- local stop -> cold start -> readiness cycle

The runtime readiness endpoint currently reports healthy database, scheduler, and worker components.

## Implemented functional areas

- local username/password authentication and forced-password-change workflow
- sliding 10-year persistent sessions; explicit logout, password reset, disable, and generation revocation still invalidate access
- LAN-safe idempotency-key generation for browsers where `crypto.randomUUID` is unavailable
- administrator account management with last-admin protection
- administrator-only board creation
- every active user automatically receives access to every board
- every active user can add, edit, assign, comment on, and drag cards on every board
- active administrators are board managers; other active users receive member access automatically
- new users are automatically synchronized to all existing boards
- five-list Trello-style workflow: Inbox, To Do, In Progress, Later, Done
- quick Inbox capture with title-first card creation
- free drag/reorder between the five everyday lists
- administrator-only permanent board deletion with exact-name confirmation
- permanent card deletion available to every board user, with optimistic concurrency protection
- card-level daily, weekly, and monthly repetition with a user-selected next action date
- due repeating cards automatically return to Inbox, reset checklist completion, and schedule the following occurrence
- task commitments and commitment revisions remain available as optional audited workflow
- checklist baselines
- optional submissions and independent review without blocking ordinary drag-to-Done behavior
- comments and change proposals
- idempotency receipts
- recurrence preview/publish/generation
- immutable report snapshots
- job leasing/retry/recovery
- in-app notifications
- Slack adapter with `off` / `dry_run` / `live` gates
- readiness/liveness endpoints
- operator verification CLI
- backup and restore operator commands

## Gates intentionally still blocked

The development build is verified, but the final release checker remains blocked on infrastructure/pilot requirements:

1. **Independent backup target** - this PC has one physical disk and no mapped network share. A folder on the same SSD is not accepted as an independent backup.
2. **Formal supervised pilot services** - local start/stop launchers work, but restricted service identity plus reboot/logoff/forced-failure recovery verification is still required for pilot.
3. **Restore drill** - implemented, but it requires a verified independent backup from the first gate.
4. **Private pilot network values** - an approved private hostname, HTTPS endpoint, CIDR allowlist, and external availability monitoring are not yet supplied.
5. **Slack pilot approval** - Slack remains intentionally off. No live token or verified recipient mapping has been configured.
6. **Controlled pilot and final release** - remain gated by the items above.

These blockers are recorded in `docs/implementation_status.json`.

## Security notes

- No runtime secrets are tracked by Git.
- PostgreSQL, Waitress, and Caddy are not listening on the LAN.
- Vite is listening only on `172.16.0.178:5173`; the firewall restricts access to `172.16.0.0/23`.
- Team access uses plain HTTP on the trusted office LAN and is not suitable for public or untrusted networks.
- Slack live sending is disabled.
- No paid service has been enabled or purchased.
- Release checks fail closed while the pilot/infrastructure gates remain unresolved.
