**This python package is unofficial and is not related in any way to Lidl or Payback. It was developed by reversed engineered requests and can stop working at anytime!**

> [!IMPORTANT]
> Auth and ticket download are working as of April 2026. This fork fixes errors after Lidl's API changes.

---

# Lidl Plus + Payback — Home Automation

This repo contains two tools:

1. **Lidl Plus** — Python API + Home Assistant custom component (coupons, receipts, token refresh)
2. **Payback** — Browser automation to activate all coupons headlessly

---

## Lidl Plus

### Home Assistant Integration

A custom HA component is included in `custom_components/lidl_plus/`. Install via HACS or copy the folder directly into your HA `custom_components/` directory.

> [!IMPORTANT]
> **HACS 2.x:** If you see *“The version … can not be used with HACS”* when installing from the default branch, HACS is comparing your commit hash to `manifest.json`’s semver — they never match. **Install a numbered release instead** (e.g. **1.2.0**): in HACS open the integration → **⋮** → pick a version from the list, or add the repo and select the latest **Release** (not “main”). This repo publishes GitHub Releases tagged `v1.x.x` matching `manifest.json`.

Features:
- Coupon sensors (count, list, images)
- Receipt sensors
- Refresh token renewal from the HA UI
- Service call to activate all coupons

**If reauth says “Invalid or expired token” but the token is new:** paste only the long hex line (no dashed separators, no line breaks). **Country + language in HA must match** the auth CLI (`lidl-auth.sh` uses `DE` + `de` by default). Easiest fix: run `./lidl-ha-sync.sh` from your Mac — it validates the token and calls **`lidl_plus.set_refresh_token`**, which now works even when the integration is stuck in reauth (the service registers before validation).

### Quick Auth (`lidl-auth.sh`)

One-command authentication that obtains a refresh token and optionally pushes it to Home Assistant.

**Setup** — copy `.env.example` to `.env` and fill in:
```env
LIDL_EMAIL=your@email.com
LIDL_PASSWORD=yourpassword
LIDL_REFRESH_TOKEN=          # filled automatically after first login

HA_URL=http://192.168.1.x:8123
HA_TOKEN=your_long_lived_ha_token
```

**Usage:**
```bash
# Browser login (recommended first time or when token expires)
./lidl-auth.sh --debug

# Headless login using saved token
./lidl-auth.sh

# Override credentials
./lidl-auth.sh -u other@email.com -p password --debug
```

| Option | Description |
|---|---|
| `--debug` | Opens Firefox for manual login |
| `-u`, `--user` | Override email from `.env` |
| `-p`, `--password` | Override password from `.env` |

> [!TIP]
> When using `--debug`, Firefox opens and shows the Lidl login form. Fill in your credentials and click **Anmelden**. If a rate-limit page appears ("Die Kapazität wurde überschritten"), re-enter your password and click Anmelden again. The refresh token is captured automatically and saved to `.env`.

### Python API

```bash
pip install lidl-plus
```

> [!IMPORTANT]
> The PyPi version may be outdated. Clone this repo and install with `pip install -r requirements.txt` for the latest fixes.

**Receipts:**
```python
from lidlplus import LidlPlusApi

lidl = LidlPlusApi("de", "DE", refresh_token="YOUR_TOKEN")
for receipt in lidl.tickets():
    pprint(lidl.ticket(receipt["id"]))
```

**Coupons:**
```python
lidl = LidlPlusApi("de", "DE", refresh_token="YOUR_TOKEN")
for section in lidl.coupons()["sections"]:
    for coupon in section["coupons"]:
        print(coupon["title"], coupon["id"])
```

**CLI:**
```bash
# Activate all coupons
lidl-plus --language=de --country=DE --refresh-token=XXXXX coupon --all

# Download receipts
lidl-plus --language=de --country=DE --refresh-token=XXXXX receipt
```

---

## Payback

Browser automation (Selenium + Firefox) to activate all Payback.de coupons with a single command.

> No official API exists. This uses cookie-based session persistence to avoid reCAPTCHA.

### Setup

```bash
# Install dependencies (requires venv already set up for Lidl)
pip install selenium-wire

# Add credentials to .env
PAYBACK_EMAIL=your@email.com
PAYBACK_PASSWORD=yourpassword
```

### Usage

**First time (or when session expires):**
```bash
./payback/payback.sh --login
```
Firefox opens visibly. Log in manually. Cookies are saved to `payback/cookies.json` and reused for all future headless runs.

**Activate all coupons (headless):**
```bash
./payback/payback.sh
```

Example output:
```
==================================================
PAYBACK COUPON ACTIVATION RESULTS
==================================================
  Activated : 257
  Skipped   : 0  (already active)
  Failed    : 0
==================================================
```

**When cookies expire** (every few weeks), just run `--login` again.

### Cookie file

`payback/cookies.json` is git-ignored and never committed.

---

## Repository Structure

```
lidl-plus/
├── custom_components/lidl_plus/   HA custom component
├── payback/
│   ├── activate.py                headless coupon activation
│   ├── trigger_server.py          HTTP trigger server (optional Pi setup)
│   ├── payback.sh                 shell wrapper
│   └── cookies.json               saved session (git-ignored)
├── lidl-auth.sh                   Lidl auth wrapper
├── .env                           credentials (git-ignored)
└── .env.example                   template
```
