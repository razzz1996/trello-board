# Operator environment inputs

These values are intentionally not committed as secrets.

Required before database runtime:
- PRODUCTIVITY_DB_USER
- PRODUCTIVITY_DB_PASSWORD_FILE
- optional PRODUCTIVITY_DB_HOST / PRODUCTIVITY_DB_PORT / PRODUCTIVITY_DB_NAME

Required for restore drills:
- PRODUCTIVITY_MAINTENANCE_DB_USER
- PRODUCTIVITY_MAINTENANCE_DB_PASSWORD_FILE
- config restore_mode=true
- config slack_mode=off

Required only for Slack dry-run/live:
- PRODUCTIVITY_SLACK_TOKEN_FILE

Pilot reverse proxy:
- PRODUCTIVITY_PRIVATE_HOST
- PRODUCTIVITY_ALLOWED_CIDRS
- config private_base_url must be the matching https URL

Do not place secret values in this file, config JSON, Git, PowerShell history, or service command arguments.
