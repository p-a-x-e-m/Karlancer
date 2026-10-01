# karbot

> 🌐 **Language / زبان:** &nbsp; **English** &nbsp;·&nbsp; [فارسی](README.md)

An auto-bidding bot for **karlancer.com** — built with Selenium, it watches for fresh projects matching a keyword and automatically submits a proposal (price + duration + description).

> **Important:** this tool automates proposal submission on a third-party site. Please read the [Disclaimer](#disclaimer) section.

## Features

- **Login once** — the `auth-token` is stored in an SQLite database and stays valid for 30 days, so you don't sign in on every run.
- **Keyword filter** — searches the `/search/` page for your chosen phrase.
- **Fresh projects only** — only projects published within the last **7 minutes** are considered (`max_age` in `main.py`).
- **No duplicates** — each project is bid on once per run; seen projects are tracked in `previous_projects`.
- **Bid form filled automatically:**
  - Price ← **midpoint of the budget range** (`(min + max) // 2`)
  - Duration ← **half the client's suggested days** (minimum 1 day)
  - Proposal text ← contents of `descriptions.txt`
- **Dismisses interrupting modals** — "don't show this again", the "no related portfolio" warning, and the paid "upgrade" offer are all handled automatically.
- **Headless mode** for servers and VPS.
- **Error handling** — screenshots and page source are saved on failure; the bot attempts to reconnect if the session drops.

## How it works

Every cycle follows this path (`start_monitoring()` in `main.py`):

1. Clean up previous browser sessions (`pkill chrome/chromedriver` on Linux).
2. Restore the token from the database, or fall back to manual login if missing/expired.
3. Open `https://www.karlancer.com/search/`.
4. Apply the keyword search filter.
5. Read the project cards (title, link, age, budget, suggested duration).
6. Drop duplicates and anything older than 7 minutes.
7. For each new project: open its page, extract the budget range, click "submit a proposal".
8. Fill in price, duration and text, submit, then confirm the "your proposal was submitted successfully" message.
9. Sleep for `interval` seconds and start the next cycle.

Persian time strings (seconds/minutes/hours/days) are converted to real durations by `parse_persian_time()`.

## Requirements

- Python 3.x
- **Google Chrome** or **Chromium** (the driver is downloaded automatically; no manual chromedriver install needed)
- **Linux** for full operation — the `pkill` cleanup command is Linux-only. On Windows and macOS those commands fail silently and cleaning `/tmp` logs a `Cleanup error` warning; execution continues, but leftover processes and directories are not reaped.

## Installation

```bash
pip install -r requirements.txt
```

## Usage

```bash
python main.py --search-term "طراحی سایت" --interval 300 --headless
```

| Argument | Default | Description |
|---|---|---|
| `-s`, `--search-term` | `طراحی سایت` | Keyword used to filter projects |
| `-i`, `--interval` | `300` | Seconds to wait before the next check |
| `--headless` | off | Run Chrome without a window (for servers) |
| `-h`, `--help` | — | Show help |

With no arguments at all, the bot runs with the defaults above and opens a visible browser window.

## First run (manual login)

There is no token on the first run, so:

1. A browser opens at `/login`.
2. **You** sign in yourself, then press `Enter` in the terminal.
3. The bot reads `auth-token` and `user.data` from `localStorage` and stores them in `karlancer.db` (valid for 30 days).

Later runs restore the token automatically. If it has expired you'll see `Tokens expired or not found` in the log and will need to sign in again.

## The proposal text (`descriptions.txt`)

This file is **a single UTF-8 text block**; it is read in full and sent as the text of every proposal.

- Editing it affects subsequent proposals; no restart required.
- An empty file raises an error (`Description file is empty`).
- A leading BOM is ignored (`utf-8-sig`).

## Generated files

The bot writes these into the working directory while running (all covered by `.gitignore`):

| File | Description |
|---|---|
| `karlancer.db` | SQLite database storing the auth token |
| `karlancer_monitor.log` | Log file (UTF-8) |
| `chromedriver.log` | Chrome driver log |
| `error_*.png` | Screenshot from the main loop on error |
| `proposal_error.png` | Screenshot on proposal submission failure |
| `project_error.png` | Screenshot on project processing failure |
| `search_error.png` | Screenshot on search filter failure |
| `page_source.html` | Page source on search failure (for debugging selectors) |

## Troubleshooting

- **`Tokens expired or not found`** — the 30-day token has expired; run again and sign in once more.
- **`Failed to initialize WebDriver`** — Chrome is missing or the driver doesn't match your Chrome version. Update Chrome; the bot already retries up to 3 times.
- **`Could not load descriptions`** — `descriptions.txt` is empty or not in the current directory.
- **Proposal not submitted** — check `proposal_error.png` and the log first. Site messages (e.g. the portfolio warning) may have changed.
- **Selectors not matching** — every XPath depends on the site's current DOM structure and will break if karlancer.com changes its markup. `page_source.html` exists precisely for this.
- **Success not confirmed** — the log warns `Could not verify proposal submission`; the submission may have succeeded but the message text changed. Always verify on the site yourself.

## Disclaimer

- Automating proposal submission likely violates karlancer.com's terms of use and can lead to account suspension or a ban.
- The bot applies **no quality filtering**: it bids on every fresh project matching the keyword, so it may send irrelevant proposals.
- Price and duration are computed naively (budget midpoint and half the suggested duration) and deserve manual review.
- Use of this tool is at your own risk.

## Detection evasion

karlancer.com blocks obvious automation, so the bot hides WebDriver's
fingerprints: it suppresses the `enable-automation` switch and replaces
`navigator.webdriver` on every page load. This is intentional — without it
the bot does not function — but it is worth being explicit about, both
because it is the kind of technique that is easy to miss when reading the
code, and because it is a further reason the site's operators may object to
this tool (see [Disclaimer](#disclaimer)).

## Security

See [SECURITY.md](SECURITY.md) for how to report a vulnerability privately.
Note that `karlancer.db` holds a live session token and should be treated as
a secret.

## License

[MIT](LICENSE) © 2026 p-a-x-e-m
