# Environment Inventory

Observed: 2026-09-29, Asia/Manila project timezone
Authorized project path: C:\Users\PC 19\Desktop\PRODUCTIVITY WEBSITE

## Host
- OS: Microsoft Windows 11 Pro 10.0.26200 Build 26200
- CPU: AMD Ryzen 7 5800X 8-Core Processor
- RAM: 15.93 GiB
- C: free space at inspection: 60.11 GiB
- User session is not elevated administrator
- Active power plan: Balanced
- AC sleep: disabled; AC hibernate: disabled
- Windows time source: time.windows.com; status reported not synchronized during S00 although a successful sync was recorded at 07:46 on 2026-09-29
- Local IPv4 observed by Windows listener inventory: 172.16.0.178 (current DHCP-assigned office LAN address)

## Tooling
- Python 3.14.7 installed for current user
- Node.js 24.19.0 / npm 11.17.0
- Git 2.55.0.windows.5
- Caddy 2.11.4
- PostgreSQL: NOT INSTALLED
- Existing loopback listener on 127.0.0.1:11434 is unrelated and will not be modified

## Operational inputs still unknown
- Team count and expected concurrent users
- Final board roster and reviewer mapping
- Approved office/remote private access route and CIDRs
- Independent encrypted backup target/device
- Daily operator and backup operator
- PostgreSQL superuser/service credential to be entered by the owner during installation
- Slack app/token/workspace/member mappings and pilot recipients

These unknowns are not guessed. They block the applicable deployment and pilot gates, not local source preparation.
