# Lidl Plus (HACS)

**Install a release version** (e.g. **1.2.2**), not the default branch — HACS 2 compares the git commit to `manifest.json` and rejects branch installs.

1. Open the **⋮** menu (top right on this page).
2. Choose **Redownload** or **Change version** / version list.
3. Select **1.2.2** (or latest **1.2.x**).
4. **Restart Home Assistant** after install.

Token issues: use **`lidl_plus.set_refresh_token`** in Developer tools → Services, or **`./lidl-ha-sync.sh`** on your Mac. Country + language in HA must match your CLI (default: **DE** + **de**).
