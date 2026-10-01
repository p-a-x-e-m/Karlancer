# Security Policy

## Reporting a vulnerability

Please **do not open a public issue** for security problems.

Report privately through GitHub's
[Report a vulnerability](https://github.com/p-a-x-e-m/KarlancerBot/security/advisories/new)
form (Security → Advisories → Report a vulnerability). This keeps the report
confidential until a fix is available.

Please include:

- what the issue is and where (`file:line`),
- how to reproduce it,
- what an attacker could do with it,
- any suggested fix.

You can expect an acknowledgement within a few days. This is a small
volunteer-maintained project, so there is no formal SLA.

## Scope

In scope:

- `main.py` and any other code in this repository.
- Credential handling: the `karlancer.db` token store, anything written to
  logs or screenshots.

Out of scope:

- **Vulnerabilities in karlancer.com itself.** Report those to the site
  operator, not here.
- The fact that this tool automates a third-party website. That is the
  tool's stated purpose and is covered by the disclaimer in the README,
  not a vulnerability.
- Issues that require an attacker to already control the machine the bot
  runs on (e.g. a local process reading `karlancer.db`).

## Handling of credentials

This tool authenticates to karlancer.com and stores the resulting token in a
local SQLite file, `karlancer.db`.

- `karlancer.db` holds a **live session token** and is git-ignored. Treat it
  as a secret: anyone with the file can act as the logged-in account until
  the token expires (30 days).
- If you believe your `karlancer.db` leaked, sign out of karlancer.com to
  invalidate the token, then delete the file.
- The bot never reads environment variables, so there is no `.env` file to
  manage. `.env` and key/certificate patterns are still git-ignored as a
  safeguard against future changes.

## Supported versions

This project does not publish versioned releases. Fixes land on `main`.
