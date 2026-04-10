#!/usr/bin/env python3
"""
Payback.de — activate all coupons via browser automation.

Usage:
    python3 payback/activate.py --login    Open visible Firefox, log in manually,
                                           save session cookies, then quit.
    python3 payback/activate.py            Headless run using saved cookies.
    python3 payback/activate.py --debug    Headless run but keep browser open on error.

First-time setup (or when cookies expire):
    ./payback/payback.sh --login
"""
import argparse
import json
import logging
import os
import sys
import time


logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

for _noisy in ("seleniumwire", "urllib3", "hpack", "selenium.webdriver.remote"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

try:
    from seleniumwire import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.firefox.options import Options
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait
except ImportError:
    sys.exit("Missing dependency: pip install selenium-wire")

def _notify_ha(activated: int, failed: int):
    """Post activation result to Home Assistant as a persistent notification."""
    import urllib.request
    ha_url = os.environ.get("HA_URL", "").rstrip("/")
    ha_token = os.environ.get("HA_TOKEN", "")
    if not ha_url or not ha_token:
        return
    icon = "mdi:check-circle" if failed == 0 else "mdi:alert-circle"
    msg = f"✅ {activated} coupons activated" if failed == 0 else f"⚠️ {activated} activated, {failed} failed"
    payload = json.dumps({
        "message": msg,
        "title": "Payback Coupons",
        "notification_id": "payback_activation",
    }).encode()
    req = urllib.request.Request(
        f"{ha_url}/api/services/persistent_notification/create",
        data=payload,
        headers={"Authorization": f"Bearer {ha_token}", "Content-Type": "application/json"},
    )
    try:
        urllib.request.urlopen(req, timeout=10)
        log.info("Notified Home Assistant")
    except Exception as e:
        log.warning(f"Could not notify Home Assistant: {e}")


BASE_URL = "https://www.payback.de"
LOGIN_URL = f"{BASE_URL}/login"
COUPONS_URL = f"{BASE_URL}/coupons"
COOKIES_FILE = os.path.join(os.path.dirname(__file__), "cookies.json")

ACTIVATE_JS = """
return (function() {
    var results = {activated: 0, skipped: 0, failed: 0, errors: []};
    try {
        var activateBtns = Array.from(document.querySelectorAll('button')).filter(function(b) {
            return b.textContent.trim() === 'Jetzt aktivieren' && !b.disabled;
        });
        if (activateBtns.length === 0) {
            results.errors.push("No 'Jetzt aktivieren' buttons found");
            return results;
        }
        activateBtns.forEach(function(btn) {
            try { btn.click(); results.activated++; }
            catch(e) { results.failed++; results.errors.push(e.toString().substring(0, 100)); }
        });
    } catch(e) { results.errors.push(e.toString()); }
    return results;
})();
"""

INSPECT_JS = """
return (function() {
    var info = {found: false, activatable: 0};
    var stack = document.querySelector('[data-testid="coupons-list-stack"]');
    if (stack) {
        info.found = true;
        info.activatable = Array.from(document.querySelectorAll('button')).filter(function(b) {
            return b.textContent.trim() === 'Jetzt aktivieren';
        }).length;
    }
    return info;
})();
"""


def _init_browser(headless: bool) -> webdriver.Firefox:
    options = Options()
    options.accept_insecure_certs = True
    if headless:
        options.add_argument("--headless")
    browser = webdriver.Firefox(
        options=options,
        seleniumwire_options={"verify_ssl": False},
    )
    browser.set_page_load_timeout(60)
    return browser


def _accept_cookies(browser):
    try:
        btn = WebDriverWait(browser, 5).until(
            EC.presence_of_element_located((By.ID, "onetrust-accept-btn-handler"))
        )
        browser.execute_script("arguments[0].click();", btn)
        log.info("Cookie banner dismissed")
        time.sleep(1)
    except Exception:
        try:
            btn = browser.find_element(
                By.XPATH, "//*[contains(@id,'accept') or contains(text(),'Alle akzeptieren')]"
            )
            browser.execute_script("arguments[0].click();", btn)
            log.info("Cookie banner dismissed")
            time.sleep(1)
        except Exception:
            pass


def _save_cookies(browser):
    cookies = browser.get_cookies()
    with open(COOKIES_FILE, "w") as f:
        json.dump(cookies, f, indent=2)
    log.info(f"Saved {len(cookies)} cookies to {COOKIES_FILE}")


def _load_cookies(browser):
    if not os.path.exists(COOKIES_FILE):
        return False
    with open(COOKIES_FILE) as f:
        cookies = json.load(f)
    # Must be on the domain before adding cookies
    browser.get(BASE_URL)
    time.sleep(2)
    for cookie in cookies:
        # Remove keys Firefox driver doesn't accept
        cookie.pop("sameSite", None)
        try:
            browser.add_cookie(cookie)
        except Exception:
            pass
    log.info(f"Loaded {len(cookies)} cookies")
    return True


def _is_logged_in(browser) -> bool:
    cur = browser.current_url
    title = browser.title.lower()
    return "/login" not in cur and "payback.de" in cur and "404" not in title


def login_flow(browser):
    """Interactive login: open login page, wait for user, save cookies."""
    log.info("Opening login page in visible browser...")
    browser.get(LOGIN_URL)
    time.sleep(2)
    _accept_cookies(browser)

    log.info("=" * 55)
    log.info("Please log in manually in the Firefox window.")
    log.info("Waiting up to 3 minutes for login to complete...")
    log.info("=" * 55)

    start = time.time()
    while time.time() - start < 180:
        if _is_logged_in(browser):
            log.info(f"Logged in! URL: {browser.current_url}")
            time.sleep(2)  # let the page settle
            _save_cookies(browser)
            return
        time.sleep(2)

    raise RuntimeError("Login timed out after 3 minutes")


def headless_flow(browser) -> bool:
    """Load saved cookies and verify we are still logged in."""
    if not os.path.exists(COOKIES_FILE):
        log.error("No saved session found.")
        log.error("Run first:  ./payback/payback.sh --login")
        return False

    _load_cookies(browser)
    browser.refresh()
    time.sleep(3)

    if _is_logged_in(browser):
        log.info(f"Session valid. URL: {browser.current_url}")
        return True

    # Might have landed on login page — cookies are expired
    log.error("Session expired or invalid.")
    log.error("Run again with:  ./payback/payback.sh --login")
    return False


def _activate_coupons(browser) -> dict:
    log.info(f"Navigating to coupons page...")
    browser.get(COUPONS_URL)

    log.info("Waiting for coupon list to render...")
    try:
        WebDriverWait(browser, 20).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, '[data-testid="coupons-list-stack"]'))
        )
        log.info("Coupon list found.")
    except Exception:
        log.warning("Coupon list element not found within 20s, trying anyway...")
    time.sleep(2)

    info = browser.execute_script(INSPECT_JS)
    if not info.get("found"):
        raise RuntimeError(
            "Coupon list not found — session may have expired. "
            "Run ./payback/payback.sh --login to renew."
        )

    count = info.get("activatable", 0)
    log.info(f"Found {count} activatable coupon(s). Scrolling to load all...")

    browser.execute_script("window.scrollTo(0, document.body.scrollHeight);")
    time.sleep(1)
    browser.execute_script("window.scrollTo(0, 0);")
    time.sleep(0.5)

    info2 = browser.execute_script(INSPECT_JS)
    final_count = info2.get("activatable", count)
    log.info(f"Activating {final_count} coupon(s)...")

    return browser.execute_script(ACTIVATE_JS)


def main():
    parser = argparse.ArgumentParser(description="Activate all Payback.de coupons")
    parser.add_argument(
        "--login",
        action="store_true",
        help="Open visible browser to log in and save session cookies",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Keep browser open on error (headless run only)",
    )
    args = parser.parse_args()

    headless = not args.login
    browser = _init_browser(headless=headless)

    try:
        if args.login:
            login_flow(browser)
            log.info("Session saved. You can now run the script without --login.")
            return

        if not headless_flow(browser):
            sys.exit(1)

        results = _activate_coupons(browser)

        activated = results.get("activated", 0)
        failed = results.get("failed", 0)

        print("\n" + "=" * 50)
        print("PAYBACK COUPON ACTIVATION RESULTS")
        print("=" * 50)
        print(f"  Activated : {activated}")
        print(f"  Skipped   : {results.get('skipped', 0)}  (already active)")
        print(f"  Failed    : {failed}")
        if results.get("errors"):
            print(f"  Errors    : {results['errors'][:3]}")
        print("=" * 50)

        _notify_ha(activated, failed)

    except Exception as e:
        log.error(f"Error: {e}")
        if args.debug:
            log.info("Browser staying open for 60s for inspection...")
            time.sleep(60)
        sys.exit(1)
    finally:
        browser.quit()


if __name__ == "__main__":
    main()
