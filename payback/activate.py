#!/usr/bin/env python3
"""
Payback.de — activate all coupons via browser automation.

Usage:
    python3 payback/activate.py --debug   (visible Firefox, manual login)
    python3 payback/activate.py           (headless, auto-login from .env)
"""
import argparse
import logging
import os
import sys
import time

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# Suppress selenium-wire and urllib3 noise
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

BASE_URL = "https://www.payback.de"
LOGIN_URL = f"{BASE_URL}/login"
COUPONS_URL = f"{BASE_URL}/coupons"

# Payback uses React/MUI. Unactivated coupons show a "Jetzt aktivieren" button.
# Already-activated coupons show "Online einlösen" / "Vor Ort einlösen" instead.
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
            try {
                btn.click();
                results.activated++;
            } catch(e) {
                results.failed++;
                results.errors.push(e.toString().substring(0, 100));
            }
        });
    } catch(e) {
        results.errors.push(e.toString());
    }

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
            btn = browser.find_element(By.XPATH,
                "//*[contains(@id,'accept') or contains(text(),'Alle akzeptieren')]"
            )
            browser.execute_script("arguments[0].click();", btn)
            log.info("Cookie banner dismissed")
            time.sleep(1)
        except Exception:
            pass


def _login(browser, wait, email: str, password: str, debug: bool):
    log.info("Opening login page...")
    browser.get(LOGIN_URL)
    time.sleep(2)
    _accept_cookies(browser)

    if debug:
        log.info("Browser ready — please fill in email and password if not auto-filled, then submit.")
        log.info("Waiting up to 120 seconds for login to complete...")
    else:
        log.info("Filling in credentials...")
        try:
            email_field = wait.until(EC.presence_of_element_located(
                (By.XPATH, "//input[@type='email' or @name='email' or @id='email' or @autocomplete='email']")
            ))
            browser.execute_script("arguments[0].value = arguments[1];", email_field, email)
            browser.execute_script(
                "arguments[0].dispatchEvent(new Event('input', {bubbles:true}));", email_field
            )
            time.sleep(0.5)
            try:
                next_btn = browser.find_element(By.XPATH,
                    "//button[@type='submit' or contains(@class,'next') or contains(@class,'weiter')]"
                )
                next_btn.click()
                time.sleep(1.5)
            except Exception:
                pass

            pwd_field = wait.until(EC.presence_of_element_located(
                (By.XPATH, "//input[@type='password']")
            ))
            browser.execute_script("arguments[0].value = arguments[1];", pwd_field, password)
            browser.execute_script(
                "arguments[0].dispatchEvent(new Event('input', {bubbles:true}));", pwd_field
            )
            time.sleep(0.5)
            submit = browser.find_element(By.XPATH,
                "//button[@type='submit' or contains(@class,'login') or contains(@class,'anmelden')]"
            )
            submit.click()
        except Exception as e:
            raise RuntimeError(f"Could not auto-fill login form: {e}. Try --debug for manual login.") from e

    timeout = 120 if debug else 30
    start = time.time()
    while time.time() - start < timeout:
        cur = browser.current_url
        title = browser.title.lower()
        if "/login" not in cur and "payback.de" in cur and "404" not in title and "not found" not in title:
            log.info(f"Logged in. Current URL: {cur}")
            return
        time.sleep(2)

    raise RuntimeError("Login timed out — check credentials or try --debug")


def _activate_coupons(browser, wait) -> dict:
    log.info(f"Navigating to coupons page: {COUPONS_URL}")
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
        raise RuntimeError("Coupon list not found — check if you are logged in or if Payback changed their structure")

    count = info.get("activatable", 0)
    log.info(f"Found {count} coupon(s). Scrolling to trigger lazy loading...")

    browser.execute_script("window.scrollTo(0, document.body.scrollHeight);")
    time.sleep(1)
    browser.execute_script("window.scrollTo(0, 0);")
    time.sleep(0.5)

    info2 = browser.execute_script(INSPECT_JS)
    final_count = info2.get("activatable", count)
    log.info(f"Activating {final_count} coupon(s)... (do not close the browser)")

    return browser.execute_script(ACTIVATE_JS)


def main():
    parser = argparse.ArgumentParser(description="Activate all Payback.de coupons")
    parser.add_argument("--debug", action="store_true", help="Open visible browser for manual login")
    parser.add_argument("-u", "--user", help="Payback email (or set PAYBACK_EMAIL in .env)")
    parser.add_argument("-p", "--password", help="Payback password (or set PAYBACK_PASSWORD in .env)")
    args = parser.parse_args()

    env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())

    email = args.user or os.environ.get("PAYBACK_EMAIL", "")
    password = args.password or os.environ.get("PAYBACK_PASSWORD", "")

    if not email or not password:
        sys.exit(
            "ERROR: Payback credentials required.\n"
            "Add PAYBACK_EMAIL and PAYBACK_PASSWORD to .env\n"
            "or pass -u email -p password"
        )

    browser = _init_browser(headless=not args.debug)
    wait = WebDriverWait(browser, 20)

    try:
        _login(browser, wait, email, password, args.debug)
        results = _activate_coupons(browser, wait)

        print("\n" + "="*50)
        print("PAYBACK COUPON ACTIVATION RESULTS")
        print("="*50)
        print(f"  Activated : {results.get('activated', 0)}")
        print(f"  Skipped   : {results.get('skipped', 0)}  (already active)")
        print(f"  Failed    : {results.get('failed', 0)}")
        if results.get("errors"):
            print(f"  Errors    : {results['errors'][:3]}")
        print("="*50)

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
