#!/usr/bin/env python3
"""
Payback.de — activate all coupons via browser automation.

Usage:
    python3 payback/activate.py --debug
    python3 payback/activate.py  (headless)
"""
import argparse
import logging
import os
import sys
import time

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

try:
    from seleniumwire import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.firefox.options import Options
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait
except ImportError:
    sys.exit("Missing dependency: pip install selenium-wire")

BASE_URL = "https://www.payback.de"
LOGIN_URL = f"{BASE_URL}/pb/login"
COUPONS_URL = f"{BASE_URL}/coupons"

# JavaScript that traverses shadow DOM and clicks all unactivated coupons
# Based on https://gist.github.com/CodeBrauer/aaaa9dbeefe3a52a73c5d5cab8be4b93
# Updated to be more resilient
ACTIVATE_JS = """
return (function() {
    var results = {activated: 0, skipped: 0, failed: 0, errors: []};

    try {
        var couponCenter = document.querySelector("#coupon-center");
        if (!couponCenter) {
            results.errors.push("No #coupon-center found");
            return results;
        }

        var sr = couponCenter.shadowRoot;
        if (!sr) {
            results.errors.push("#coupon-center has no shadowRoot");
            return results;
        }

        var coupons = sr.querySelectorAll("pbc-coupon");
        if (!coupons || coupons.length === 0) {
            results.errors.push("No pbc-coupon elements found in shadowRoot");
            return results;
        }

        coupons.forEach(function(coupon) {
            try {
                var cta = coupon.shadowRoot
                    ? coupon.shadowRoot.querySelector("pbc-coupon-call-to-action")
                    : null;
                if (!cta) { results.skipped++; return; }

                var ctaSr = cta.shadowRoot;
                if (!ctaSr) { results.skipped++; return; }

                var btn = ctaSr.querySelector("button.not-activated")
                    || ctaSr.querySelector("button[class*='not-activated']")
                    || ctaSr.querySelector("button:not([class*='activated'])");

                if (btn) {
                    btn.click();
                    results.activated++;
                } else {
                    results.skipped++;
                }
            } catch(e) {
                results.failed++;
                results.errors.push(e.toString());
            }
        });
    } catch(e) {
        results.errors.push(e.toString());
    }

    return results;
})();
"""

# JS to count coupons and check page structure
INSPECT_JS = """
return (function() {
    var info = {couponCenter: false, hasShadow: false, couponCount: 0, html: ''};
    var cc = document.querySelector("#coupon-center");
    if (cc) {
        info.couponCenter = true;
        info.hasShadow = !!cc.shadowRoot;
        if (cc.shadowRoot) {
            info.couponCount = cc.shadowRoot.querySelectorAll("pbc-coupon").length;
        }
    }
    return info;
})();
"""


def _init_browser(headless: bool) -> webdriver.Firefox:
    options = Options()
    options.accept_insecure_certs = True
    if headless:
        options.add_argument("--headless")

    seleniumwire_options = {"verify_ssl": False}
    browser = webdriver.Firefox(
        options=options,
        seleniumwire_options=seleniumwire_options,
    )
    browser.set_page_load_timeout(60)
    return browser


def _accept_cookies(browser, wait):
    """Try to dismiss cookie consent banner."""
    try:
        btn = wait.until(EC.element_to_be_clickable(
            (By.XPATH, "//*[contains(@id,'accept') or contains(@class,'accept') or contains(text(),'Alle akzeptieren') or contains(text(),'Akzeptieren')]")
        ))
        btn.click()
        log.info("Cookie banner dismissed")
        time.sleep(1)
    except Exception:
        log.info("No cookie banner found (or already dismissed)")


def _login(browser, wait, email: str, password: str, debug: bool):
    log.info("Opening login page...")
    browser.get(LOGIN_URL)
    time.sleep(2)

    _accept_cookies(browser, wait)

    if debug:
        log.info("Browser ready — please fill in email and password if not auto-filled, then submit.")
        log.info("Waiting up to 120 seconds for login to complete...")
    else:
        log.info("Filling in credentials...")
        try:
            # Try to find and fill email field
            email_field = wait.until(EC.presence_of_element_located(
                (By.XPATH, "//input[@type='email' or @name='email' or @id='email' or @autocomplete='email']")
            ))
            browser.execute_script("arguments[0].value = arguments[1];", email_field, email)
            browser.execute_script(
                "arguments[0].dispatchEvent(new Event('input', {bubbles:true}));",
                email_field
            )
            time.sleep(0.5)

            # Submit email step (some sites have two steps)
            try:
                next_btn = browser.find_element(By.XPATH,
                    "//button[@type='submit' or contains(@class,'next') or contains(@class,'weiter')]"
                )
                next_btn.click()
                time.sleep(1.5)
            except Exception:
                pass

            # Password field
            pwd_field = wait.until(EC.presence_of_element_located(
                (By.XPATH, "//input[@type='password']")
            ))
            browser.execute_script("arguments[0].value = arguments[1];", pwd_field, password)
            browser.execute_script(
                "arguments[0].dispatchEvent(new Event('input', {bubbles:true}));",
                pwd_field
            )
            time.sleep(0.5)

            # Submit
            submit = browser.find_element(By.XPATH,
                "//button[@type='submit' or contains(@class,'login') or contains(@class,'anmelden')]"
            )
            submit.click()
        except Exception as e:
            if debug:
                log.warning(f"Auto-fill failed ({e}), please complete login manually in the browser.")
            else:
                raise RuntimeError(f"Could not auto-fill login form: {e}. Try --debug for manual login.") from e

    # Wait for redirect away from login page
    timeout = 120 if debug else 30
    start = time.time()
    while time.time() - start < timeout:
        if "/login" not in browser.current_url and "payback.de" in browser.current_url:
            log.info(f"Logged in. Current URL: {browser.current_url}")
            return
        time.sleep(1)

    raise RuntimeError("Login timed out — check credentials or try --debug")


def _activate_coupons(browser, wait, debug: bool) -> dict:
    log.info(f"Navigating to coupons page: {COUPONS_URL}")
    browser.get(COUPONS_URL)

    # Wait for coupon center to load
    log.info("Waiting for coupons to load...")
    time.sleep(5)

    # Inspect page structure
    info = browser.execute_script(INSPECT_JS)
    log.info(f"Page info: {info}")

    if not info.get("couponCenter"):
        if debug:
            log.warning("#coupon-center not found. Page might have changed structure.")
            log.info("Current URL: " + browser.current_url)
            log.info("Please inspect the page manually. Waiting 60s...")
            time.sleep(60)
        raise RuntimeError("#coupon-center not found — Payback may have changed their page structure")

    if info.get("couponCount", 0) == 0:
        log.warning("No coupons found in shadow DOM. Waiting longer...")
        time.sleep(5)
        info = browser.execute_script(INSPECT_JS)
        log.info(f"Page info after wait: {info}")

    log.info(f"Found {info.get('couponCount', 0)} coupon(s). Activating...")

    # Scroll down to ensure all coupons are loaded (lazy loading)
    browser.execute_script("window.scrollTo(0, document.body.scrollHeight);")
    time.sleep(2)
    browser.execute_script("window.scrollTo(0, 0);")
    time.sleep(1)

    results = browser.execute_script(ACTIVATE_JS)
    return results


def main():
    parser = argparse.ArgumentParser(description="Activate all Payback.de coupons")
    parser.add_argument("--debug", action="store_true", help="Open visible browser for manual interaction")
    parser.add_argument("-u", "--user", help="Payback email (or set PAYBACK_EMAIL in .env)")
    parser.add_argument("-p", "--password", help="Payback password (or set PAYBACK_PASSWORD in .env)")
    args = parser.parse_args()

    # Load .env from parent directory
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
        results = _activate_coupons(browser, wait, args.debug)

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
            log.info("Browser staying open for 30s for inspection...")
            time.sleep(30)
        sys.exit(1)
    finally:
        browser.quit()


if __name__ == "__main__":
    main()
