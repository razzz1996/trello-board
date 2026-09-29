# eMEGA Productivity - Local Development Handoff

## Current local access

- Standard local website: `http://127.0.0.1:8080/`
- Vite development host (when running): `http://127.0.0.1:5173/`
- Initial administrator username: `raz`
- Administrator password: known only to the operator; it is not stored in project documentation.
- Environment: `development`
- Slack mode: `off`

The development website is intentionally loopback-only. It is not exposed to the LAN or public internet.

## One-click start and stop

Two desktop launchers are available:

- `Start eMEGA Productivity.cmd`
- `Stop eMEGA Productivity.cmd`

The Start launcher checks PostgreSQL, starts Waitress, scheduler, worker, and Caddy when needed, waits for readiness, and opens the local website.

The Stop launcher stops the local web, scheduler, worker, and proxy processes. PostgreSQL remains running as the Windows service `postgresql-x64-18`.

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

- `evidence/verify_all_20260929T074944Z.json`
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
- full automated test suite: 76 passing tests
- live API route matrix and end-to-end task workflow
- live admin state changes with audit persistence
- database integrity audit with no issues
- local stop -> cold start -> readiness cycle

The runtime readiness endpoint currently reports healthy database, scheduler, and worker components.

## Implemented functional areas

- local username/password authentication and forced-password-change workflow
- administrator account management with last-admin protection
- administrator-only board creation
- every active user automatically receives access to every board
- every active user can add, edit, assign, comment on, and drag cards on every board
- active administrators are board managers; other active users receive member access automatically
- new users are automatically synchronized to all existing boards
- five-list Trello-style workflow: Inbox, To Do, In Progress, Later, Done
- quick Inbox capture with title-first card creation
- free drag/reorder between the five everyday lists
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
- PostgreSQL is not listening on the LAN.
- The development reverse proxy is not listening on the LAN.
- Slack live sending is disabled.
- No paid service has been enabled or purchased.
- Release checks fail closed while the pilot/infrastructure gates remain unresolved.
