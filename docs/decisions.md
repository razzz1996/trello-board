# Decisions

## 2026-09-29
- Canonical architecture follows the supplied Version 2 runbook: React + TypeScript, Django + DRF, PostgreSQL, Python scheduler/worker, Waitress, Caddy.
- Django remains on the 5.2 LTS series rather than moving to Django 6.x.
- Python 3.14 is accepted because current Django 5.2 supports it; exact packages are locked locally.
- Node 24 LTS is retained; no Node upgrade is required.
- PostgreSQL 18.6 is selected as the supported current PostgreSQL 18 minor release, but installation is BLOCKED pending owner-entered credential.
- Slack mode remains off. No real Slack recipient or token will be used before S21 approval.
- No public tunnel, cloud database, hosted repository, analytics SDK, CDN, external font, paid model, or paid service is introduced.
- Local Git metadata uses a clearly local-only implementation identity and is not presented as the user's email identity.
