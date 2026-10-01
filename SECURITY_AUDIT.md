# Security Audit — KarlancerBot

Date: 2026-10-01
Branch: `security/hardening`
Scope: entire repository (`main.py`, `descriptions.txt`, `requirements.txt`,
`README*.md`, `.gitignore`) and its full git history.

## Summary

This is a small, single-file Selenium bot. Several sections of the review
checklist (Docker/k8s, CI/CD, IaC, npm/Java/Rust dependencies) **do not apply**
— those files do not exist in this repository. Rather than pad the report,
each is listed as N/A with the reason.

- **Secrets:** none found. Verified by dumping and scanning the content of
  every file in every commit, not just the working tree.
- **Dependencies:** 2 pinned packages, **no known vulnerabilities**.
- **Real code findings:** 1 injection vulnerability (fixed), 1 credential
  exposure surface (fixed), plus hardening and privacy items.
- **Requires your action:** the commit author email is public and needs a
  history rewrite; several GitHub settings can only be changed by you.

## Findings

| Severity | File:Line | Issue | Fix |
|---|---|---|---|
| **Medium** | `main.py:424` (pre-fix) | **JS injection (CWE-94).** The `--search-term` CLI value was interpolated straight into a JavaScript string: `input.value = '{self.search_term}'`. A term containing a quote broke out and executed arbitrary JS in the page context — the authenticated karlancer.com session. Insufficient escaping risk; reachable by anyone who runs the tool with a crafted argument. | Fixed: the term is now passed as a `execute_script(..., self.search_term)` argument and read via `arguments[0]`, so it never enters the script source. |
| **Medium** | git history (all commits) | **Public PII.** The author and committer email was the maintainer's personal Gmail address on every commit, served publicly by the GitHub API. Redacted here deliberately — reproducing it would defeat the fix. | Resolved: history rewritten to the GitHub noreply address, then reduced to a single clean commit. See **Manual tasks**. |
| **Medium** | `main.py:50` (pre-fix) | **Hardcoded temp dir** (bandit B108). Cleanup wiped `chrome_*` from a fixed `/tmp`; wrong on Windows/macOS and could delete another user's directories in a shared `/tmp`. | Fixed: uses `tempfile.gettempdir()` and additionally checks `os.path.isdir` before removing. |
| **Medium** | `main.py:134` (pre-fix) | **Unnecessary open debug port.** `--remote-debugging-port=9222` exposed the browser on a fixed local port. Nothing in the code ever connects to it, and any local process could have driven the authenticated session. | Fixed: flag removed, with an explanatory comment. |
| **Low** | `main.py:47-48` (pre-fix) | **Shell invocation** (bandit B605/B607). `os.system('pkill -f chrome')` spawned a shell via a partial path. No user input reached it, so not exploitable, but `os.system` is a bad pattern to keep. | Fixed: replaced with `subprocess.run(["pkill","-f",pattern], check=False)`, argument array, no shell; `FileNotFoundError` handled for non-POSIX platforms. |
| **Low** | `main.py` (11 clauses; bandit flags 7 as B110/B112) | **Bare `except:`** (bandit B110/B112). Silently swallows everything including `KeyboardInterrupt` and `SystemExit`, hiding real failures and preventing clean shutdown. | **Not changed** — see "Accepted risks". |
| **Low** | `main.py:123-152` | **`--no-sandbox`** disables Chrome's sandbox. Standard on VPS images where the sandbox cannot initialise, but it means a browser exploit is not contained. | Documented, left as-is (required for the tool to run on its target host). |
| **Low** | `main.py:142-144`, `166-168` | **Detection evasion.** Suppresses `enable-automation` and rewrites `navigator.webdriver` to hide that this is a bot. Not a vulnerability in itself; a governance/honesty concern on a public repo. | Kept (without it the tool does not work) but now explicitly commented in code and documented in a new README section, per your decision. |
| **Low** | `.gitignore` | **Missing secret patterns.** Only runtime artifacts were ignored; no `.env`, key, cert, or DB-dump patterns. | Fixed: added `.env*`, `*.pem`, `*.key`, `*.p12`, `*.pfx`, `*.jks`, `service-account*.json`, dumps/backups. |
| **Low** | `README*.md` | **Stale statement.** Both READMEs still claimed no license was declared, after `LICENSE` (MIT) had been added. | Fixed: license section updated in both, plus links to `SECURITY.md`. |

## Category results

### 1. Secrets and sensitive data

Scanned the working tree **and the full history** by dumping the content of
every blob in every commit (2,731 lines) and pattern-matching for API keys,
tokens, passwords, private keys, connection strings, JWTs, `SECRET_KEY`, and
certificates.

**No secrets found.** Every match was either the literal word "token" in
prose/variable names (`auth-token`, `save_tokens`) or a SQL column name. There
are no `.env` files, no key material, and no binary blobs in history.

Confirmed absent: `verify=False` / TLS verification disabled, hardcoded
credentials, JWT config, connection strings.

Note: `main.py` writes no credential *values* to logs — only status messages.
The token itself lives in `karlancer.db` (git-ignored) and is a live session
token, now documented as a secret in `SECURITY.md`.

**`.env.example`: deliberately not created.** The codebase reads zero
environment variables, so the file would document nothing. The `.env`/key
patterns were still added to `.gitignore` as future-proofing. This is a
deviation from the checklist, recorded here rather than silently skipped.

### 2. Dependencies

`pip-audit -r requirements.txt`: **no known vulnerabilities**. Both packages
are pinned (`selenium==4.32.0`, `webdriver-manager==4.0.2`).

- No lock file exists. For a 2-package application with exact pins, the
  pinned `requirements.txt` provides the same reproducibility a lock file
  would; adding `pip-tools`/`uv.lock` machinery would be overhead for no gain.
- No unused, abandoned, or typosquatted packages: both are the canonical
  packages for their purpose.
- No npm/cargo/Go components exist, so those audits are N/A.

**Deliberately not done:** upgrading `selenium` to the version installed here
(4.49.0). That is a functional change requiring re-verification of every
selector and the WebDriver init path, which I cannot test without a live
karlancer.com account, and it was not requested. Pins stay as they are.

### 3. Code-level review (SAST)

`bandit -r .` reported 12 issues before the fixes (0 High, 1 Medium, 11 Low)
and **10 after (0 High, 0 Medium, 10 Low)**. Every remaining finding is
triaged above; all Medium-severity findings are cleared.

Checked and **not present**: SQL/NoSQL injection (parameterised queries used
throughout), command injection, XSS sinks, CSRF, SSRF, open redirect, path
traversal, unsafe file upload, insecure deserialization (no `pickle`,
`yaml.load`, `eval`, or `exec`), weak password hashing, weak crypto,
insecure randomness, and missing input validation of the kind that applies
here.

Authentication/authorization: this is a client-side automation tool with no
server component — IDOR, permission checks, sessions, JWT config, CORS,
security headers, and cookie flags have no surface here. The only
authentication is against karlancer.com itself, handled by their site.

`set_localstorage()` was reviewed specifically and is **safe**: the token
values are embedded with `json.dumps()`, which escapes quotes and newlines,
so no injection is possible there (unlike the search-term path, which is now
fixed).

### 4. Config and infrastructure — **N/A**

No `Dockerfile`, `.dockerignore`, `docker-compose.yml`, Kubernetes manifests,
nginx config, or infrastructure-as-code exists in this repository. There is
nothing to harden. If any are added later, re-run this section.

### 5. Repository hardening

Created: `SECURITY.md` (private reporting via GitHub advisories, scope,
credential handling).

Requires your action in GitHub settings — see **Manual tasks**.

### 6. Privacy / OSINT

Checked the working tree and all history.

| Check | Result |
|---|---|
| Emails | ❌ **Was exposed** — commit author/committer email; now rewritten to noreply |
| IP addresses | ✅ None |
| Internal/local paths | ✅ None (no `C:\...`, `/home/...`, `/Users/...`) |
| Hostnames / internal domains | ✅ Only `www.karlancer.com` (the target) and `github.com` |
| Server names, usernames in code | ✅ None |
| Screenshots / metadata | ✅ No images, PDFs, or `docx` files in the repository, so no EXIF/metadata exposure |
| Secrets in history | ✅ None (see §1) |

The only PII is the commit email above.

## Accepted risks (not fixed, deliberately)

1. **Bare `except:` blocks (11 sites).** Wrapping them in specific exception
   types is the correct fix, but it changes error handling on nearly every
   code path in a tool that interacts with a live third-party site. Without an
   account to test against, a wrong narrowing silently breaks the bot. Left
   alone rather than making an untestable behavioural change to your working
   tool. Worth doing as separate, tested work.
2. **`--no-sandbox`.** Required for this tool to run in its target VPS
   environment.
3. **Detection evasion.** Kept as functional requirement; disclosed in code
   and README per your decision.
4. **`selenium` pin not updated.** See §2.

## Manual tasks (cannot be done from the repository)

These are yours to action; nothing in git can do them.

1. **Purge the old history from GitHub.** The commit email was PII exposure,
   not a leaked secret — no credential is compromised, so there is nothing to
   rotate. The local history has already been rewritten to a noreply address
   and reduced to a single clean commit. What remains is server-side: old
   commits may stay reachable in GitHub's cache by SHA until support runs a
   garbage collection. See the checklist handed over at the end of the task.
2. **Enable GitHub security features** (Settings → Code security):
   - Dependabot alerts + security updates
   - Secret scanning + **push protection**
   - CodeQL code scanning
3. **Branch protection on `main`:** require pull-request reviews, disallow
   force pushes, disallow deletions.
4. **Account security:** enable 2FA; consider signing commits.
5. **Private email setting:** enable "Keep my email addresses private" so
   future commits don't re-expose the address, and use the `noreply` address
   going forward.
6. **Choose a license holder identity** — see the note I raise separately.

## Tests

No test suite exists in this repository. Verification performed:

- `python -c "import ast; ast.parse(...)"` — syntax OK after all edits.
- `python main.py --help` — runs, exit 0, flags render.
- `bandit` re-run — see below.
- Startup smoke test (`--headless`, closed stdin) — reaches authentication,
  then fails at login because no account is configured, as expected.

Full end-to-end behaviour (login → bid submission) **cannot be verified
without a live karlancer.com account**, and I will not submit real proposals
to test. The injection fix is verified by inspection and by confirming the
term is no longer part of the script source; it changes only how the value is
passed, not the browser flow.
