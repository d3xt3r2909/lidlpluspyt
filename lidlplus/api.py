"""
Lidl Plus api
"""

import base64
import html
import logging
import re
from datetime import datetime, timedelta

import requests

from lidlplus.exceptions import (
    WebBrowserException,
    LoginError,
    LegalTermsException,
    MissingLogin,
)

try:
    from getuseragent import UserAgent
    from oic.oic import Client
    from oic.utils.authn.client import CLIENT_AUTHN_METHOD
    from selenium.common.exceptions import InvalidSessionIdException, TimeoutException
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions
    from selenium.webdriver.support.ui import WebDriverWait
    from seleniumwire import webdriver
    import seleniumwire.undetected_chromedriver as sw_uc
    from seleniumwire.utils import decode
    from webdriver_manager.chrome import ChromeDriverManager
    from webdriver_manager.firefox import GeckoDriverManager
    from webdriver_manager.core.os_manager import ChromeType
except ImportError as e:
    if e.__traceback__ is not None:
        line_no = e.__traceback__.tb_lineno
    else:
        line_no = "unknown"
    logging.error(f"ImportError: {type(e).__name__} at line {line_no}: {e}")



class LidlPlusApi:
    """Lidl Plus api connector"""

    _CLIENT_ID = "LidlPlusNativeClient"
    _AUTH_API = "https://accounts.lidl.com"
    _TICKET_API = "https://tickets.lidlplus.com/api/v2"
    _COUPONS_API = "https://coupons.lidlplus.com/app/api"
    _COUPONS_V1_API = "https://coupons.lidlplus.com/app/api/"
    _PROFILE_API = "https://profile.lidlplus.com/profile/api"
    _APP = "com.lidlplus.app"
    _OS = "iOs"
    _TIMEOUT = 10

    def __init__(self, language, country, refresh_token=""):
        self._login_url = ""
        self._code_verifier = ""
        self._refresh_token = refresh_token
        self._expires = None
        self._token = ""
        self._country = country.upper()
        self._language = language.lower()

    @property
    def refresh_token(self):
        """Lidl Plus api refresh token"""
        return self._refresh_token

    @property
    def token(self):
        """Current token to query api"""
        return self._token

    def _register_oauth_client(self):
        if self._login_url:
            return self._login_url
        client = Client(client_authn_method=CLIENT_AUTHN_METHOD, client_id=self._CLIENT_ID)
        client.provider_config(self._AUTH_API)
        code_challenge, self._code_verifier = client.add_code_challenge()
        args = {
            "client_id": client.client_id,
            "response_type": "code",
            "scope": ["openid profile offline_access lpprofile lpapis"],
            "redirect_uri": f"{self._APP}://callback",
            **code_challenge,
        }
        auth_req = client.construct_AuthorizationRequest(request_args=args)
        self._login_url = auth_req.request(client.authorization_endpoint)
        return self._login_url

    def _init_chrome(self, headless=True):
        import ssl
        ssl._create_default_https_context = ssl._create_unverified_context  # needed for uc driver download
        user_agent = UserAgent(self._OS.lower()).Random()
        logging.getLogger("WDM").setLevel(logging.NOTSET)
        options = sw_uc.ChromeOptions()
        if headless:
            options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--ignore-certificate-errors")  # trust seleniumwire proxy cert
        options.add_experimental_option("mobileEmulation", {"userAgent": user_agent})
        wire_options = {"verify_ssl": False}
        try:
            return sw_uc.Chrome(options=options, use_subprocess=True, seleniumwire_options=wire_options)
        except Exception:
            pass
        raise WebBrowserException("Unable to find a suitable Chrome driver")

    def _init_firefox(self, headless=True):
        logging.getLogger("WDM").setLevel(logging.NOTSET)
        options = webdriver.FirefoxOptions()
        if headless:
            options.add_argument("--headless")
        options.accept_insecure_certs = True  # trust seleniumwire MITM proxy cert
        wire_options = {"verify_ssl": False}
        return webdriver.Firefox(options=options, seleniumwire_options=wire_options)

    def _get_browser(self, headless=True):
        try:
            return self._init_chrome(headless=headless)
        # pylint: disable=broad-except
        except Exception as exc1:
            try:
                return self._init_firefox(headless=headless)
            except Exception as exc2:
                raise WebBrowserException from exc1 and exc2

    def _auth(self, payload):
        default_secret = base64.b64encode(f"{self._CLIENT_ID}:secret".encode()).decode()
        headers = {
            "Authorization": f"Basic {default_secret}",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        kwargs = {"headers": headers, "data": payload, "timeout": self._TIMEOUT}
        response = requests.post(f"{self._AUTH_API}/connect/token", **kwargs).json()
        self._expires = datetime.utcnow() + timedelta(seconds=response["expires_in"])
        self._token = response["access_token"]
        self._refresh_token = response["refresh_token"]

    def _renew_token(self):
        payload = {"refresh_token": self._refresh_token, "grant_type": "refresh_token"}
        return self._auth(payload)

    def _authorization_code(self, code):
        payload = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": f"{self._APP}://callback",
            "code_verifier": self._code_verifier,
        }
        return self._auth(payload)

    @property
    def _register_link(self):
        args = {
            "Country": self._country,
            "language": f"{self._language}-{self._country}",
        }
        params = "&".join([f"{key}={value}" for key, value in args.items()])
        return f"{self._register_oauth_client()}&{params}"

    @staticmethod
    def _accept_legal_terms(browser, wait, accept=True):
        wait.until(expected_conditions.visibility_of_element_located((By.ID, "checkbox_Accepted"))).click()
        if not accept:
            title = browser.find_element(By.TAG_NAME, "h2").text
            raise LegalTermsException(title)
        browser.find_element(By.TAG_NAME, "button").click()

    def _parse_code(self, browser, wait, accept_legal_terms=True):
        # First try intercepted seleniumwire requests
        for request in reversed(browser.requests):
            if "/connect/authorize/callback" not in request.url:
                continue
            resp = request.response
            location = resp.headers.get("Location", "") if resp else ""
            logging.debug("callback req: %s status=%s location=%s", request.url[:80], resp.status_code if resp else "?", location[:120])
            if "legalTerms" in location:
                self._accept_legal_terms(browser, wait, accept=accept_legal_terms)
                return self._parse_code(browser, wait, False)
            if code := re.findall("code=([0-9A-Za-z_-]+)", location):
                return code[0]
            # Code may also be a query param on the callback URL itself
            if code := re.findall("code=([0-9A-Za-z_-]+)", request.url):
                return code[0]
        # Fallback: check browser's current URL (SPA may have navigated there)
        try:
            current_url = browser.current_url
            if code := re.findall("code=([0-9A-Za-z_-]+)", current_url):
                return code[0]
        except Exception:
            pass
        return ""

    def _wait_for_auth_callback(self, browser, timeout=60, debug=False):
        """Poll seleniumwire requests AND the live browser URL until auth callback appears."""
        import time
        deadline = time.time() + timeout
        last_url = None
        while time.time() < deadline:
            # Check intercepted network requests
            for req in reversed(list(browser.requests)):
                if "/connect/authorize/callback" not in req.url:
                    continue
                # Code in the request URL itself
                if "code=" in req.url:
                    return
                if not req.response:
                    continue
                # Code in the redirect Location header
                location = req.response.headers.get("Location", "")
                if "code=" in location or "legalTerms" in location:
                    return
            # Fallback: code may appear in browser URL (SPA redirect or custom scheme)
            try:
                current_url = browser.current_url
                if current_url != last_url:
                    if debug and last_url is not None:
                        # Show the end of the URL (hash fragment) which is the meaningful part
                        suffix = current_url[-100:] if len(current_url) > 100 else current_url
                        print(f"[DEBUG] URL changed (tail): ...{suffix}")
                    last_url = current_url
                if "code=" in current_url and (
                    "/connect/authorize/callback" in current_url
                    or "com.lidlplus.app" in current_url
                ):
                    return
            except Exception:
                pass
            time.sleep(0.5)
        # On timeout dump captured requests to help diagnose
        if debug:
            print("[DEBUG] Timeout! All captured lidl.com requests:")
            for req in browser.requests:
                if "lidl" in req.url or "code=" in req.url:
                    resp = req.response
                    loc = resp.headers.get("Location", "") if resp else ""
                    print(f"[DEBUG]   {req.method} {req.url[:120]} → {resp.status_code if resp else '?'} {loc[:80]}")
        raise TimeoutException(f"Timed out after {timeout}s waiting for auth callback")

    def _click(self, browser, button, request=""):
        del browser.requests
        browser.backend.storage.clear_requests()
        browser.find_element(*button).click()
        self._check_input_error(browser)
        if request and browser.wait_for_request(request, 10):
            self._check_input_error(browser)

    @staticmethod
    def _check_input_error(browser):
        if errors := browser.find_elements(By.CLASS_NAME, "input-error-message"):
            for error in errors:
                if error.text:
                    raise LoginError(error.text)

    def _check_login_error(self, browser):
        response = browser.wait_for_request(f"{self._AUTH_API}/Account/Login.*", 10).response
        body = html.unescape(decode(response.body, response.headers.get("Content-Encoding", "identity")).decode())
        if error := re.findall('app-errors="\\{[^:]*?:.(.*?).}', body):
            raise LoginError(error[0])

    def _check_2fa_auth(self, browser, wait, verify_mode="phone", verify_token_func=None):
        if verify_mode not in ["phone", "email"]:
            raise ValueError(f'Unknown 2fa-mode "{verify_mode}" - Only "phone" or "email" supported')
        response = browser.wait_for_request(f"{self._AUTH_API}/Account/Login.*", 10).response
        if "/connect/authorize/callback" not in (response.headers.get("Location") or ""):
            try:
                element = wait.until(expected_conditions.visibility_of_element_located((By.CLASS_NAME, verify_mode)))
                element.find_element(By.TAG_NAME, "button").click()
                verify_code = verify_token_func() # type: ignore
                browser.find_element(By.NAME, "VerificationCode").send_keys(verify_code)
                self._click(browser, (By.CLASS_NAME, "role_next"))
            except TimeoutException:
                pass  # No 2FA prompt appeared, login proceeded without it
            except InvalidSessionIdException:
                raise WebBrowserException("Browser session lost — Chrome may have crashed or been closed.")

    @staticmethod
    def _check_rate_limit(browser):
        """Raise LoginError if Lidl is rate-limiting the login page."""
        body = browser.page_source
        rate_limit_phrases = [
            "Kapazität wurde überschritten",
            "capacity has been exceeded",
            "versuche es erneut",
            "try again later",
        ]
        if any(phrase.lower() in body.lower() for phrase in rate_limit_phrases):
            raise LoginError("Rate limited by Lidl — please wait a few minutes and try again.")

    def login(self, login, password, method, **kwargs):
        """Simulate app auth"""
        debug = not kwargs.get("headless", True)
        def dbg(msg):
            if debug:
                print(f"[DEBUG] {msg}")

        browser = self._get_browser(headless=kwargs.get("headless", True))
        try:
            dbg("Opening register link...")
            browser.get(self._register_link)
            wait = WebDriverWait(browser, 15)
            dbg(f"Page loaded: {browser.current_url}")
            self._check_rate_limit(browser)
            dbg("Clicking Anmelden button...")
            wait.until(expected_conditions.visibility_of_element_located((By.XPATH, '//*[@id="duple-button-block"]/button[1]/span'))).click()
            dbg(f"After Anmelden click: {browser.current_url}")
            self._check_rate_limit(browser)
            if debug:
                print("")
                print("  Browser is ready — fill in your email and password and click Anmelden.")
                print("  If a rate-limit page appears, re-enter your password and click Anmelden again.")
                print("  Waiting up to 120 seconds...")
                print("")
            else:
                if method == "p": # Login with phone number
                    wait.until(expected_conditions.element_to_be_clickable((By.CSS_SELECTOR, 'button.btn-secondary'))).click()
                    wait.until(expected_conditions.element_to_be_clickable((By.NAME, "input-phone"))).send_keys(login)
                else: # Login with email
                    wait.until(expected_conditions.element_to_be_clickable((By.NAME, "input-email"))).send_keys(login)
                browser.execute_script("""
                    ['Email','EmailPhone'].forEach(function(n){
                        var f = document.querySelector('input[name="'+n+'"]');
                        if(f) f.value = arguments[0];
                    });
                """, login)
                visible_pw = wait.until(expected_conditions.element_to_be_clickable((By.CSS_SELECTOR, 'input[type="password"]')))
                visible_pw.send_keys(password)
                browser.execute_script("""
                    document.querySelectorAll('input[name="Password"]').forEach(function(f){
                        f.value = arguments[0];
                    });
                """, password)
                wait.until(expected_conditions.element_to_be_clickable((By.CSS_SELECTOR, 'button.btn-primary'))).click()

            if not debug:
                self._check_login_error(browser)
                self._check_2fa_auth(
                    browser,
                    wait,
                    kwargs.get("verify_mode", "phone"),
                    kwargs.get("verify_token_func"),
                )

            dbg("Waiting for auth callback...")
            self._wait_for_auth_callback(browser, timeout=120 if debug else 60, debug=debug)
            dbg("Parsing code...")
            code = self._parse_code(browser, wait, accept_legal_terms=kwargs.get("accept_legal_terms", True))
            dbg(f"Got code: {bool(code)}")
            self._authorization_code(code)
            dbg("Authorization complete!")
        except InvalidSessionIdException:
            raise WebBrowserException("Browser session lost — Chrome may have crashed or been closed.")
        finally:
            try:
                browser.close()
            except Exception:
                pass

    def _default_headers(self):
        if (not self._token and self._refresh_token):
            self._renew_token()
        if not self._token:
            raise MissingLogin("You need to login!")
        return {
            "Authorization": f"Bearer {self._token}",
            "App-Version": "999.99.9",
            "Operating-System": self._OS,
            "App": "com.lidl.eci.lidl.plus",
            "Accept-Language": self._language,
        }

    def tickets(self, only_favorite=False):
        """
        Get a list of all tickets.

        :param onlyFavorite: A boolean value indicating whether to only retrieve favorite tickets.
            If set to True, only favorite tickets will be returned.
            If set to False (the default), all tickets will be retrieved.
        :type onlyFavorite: bool
        """
        url = f"{self._TICKET_API}/{self._country}/tickets"
        kwargs = {"headers": self._default_headers(), "timeout": self._TIMEOUT}
        ticket = requests.get(f"{url}?pageNumber=1&onlyFavorite={only_favorite}", **kwargs).json()
        tickets = ticket["tickets"]
        for i in range(2, int(ticket["totalCount"] / ticket["size"] + 2)):
            tickets += requests.get(f"{url}?pageNumber={i}", **kwargs).json()["tickets"]
        return tickets

    def ticket(self, ticket_id):
        """Get full data of single ticket by id"""
        kwargs = {"headers": self._default_headers(), "timeout": self._TIMEOUT}
        url = f"https://tickets.lidlplus.com/api/v3/{self._country}/tickets"
        return requests.get(f"{url}/{ticket_id}", **kwargs).json()

    def coupon_promotions_v1(self):
        """Get list of all coupons API V1"""
        url = f"{self._COUPONS_V1_API}/v1/promotionslist"
        kwargs = {"headers": {**self._default_headers(), "Country": self._country}, "timeout": self._TIMEOUT}
        return requests.get(url, **kwargs).json()

    def activate_coupon_promotion_v1(self, promotion_id):
        """Activate single coupon by id API V1"""
        url = f"{self._COUPONS_API}/v1/promotions/{promotion_id}/activation"
        kwargs = {"headers": {**self._default_headers(), "Country": self._country}, "timeout": self._TIMEOUT}
        return requests.post(url, **kwargs).text

    def coupons(self):
        """Get list of all coupons"""
        url = f"{self._COUPONS_API}/v2/promotionsList"
        headers = {**self._default_headers(), "Country": self._country}
        kwargs = {"headers": headers, "timeout": self._TIMEOUT}
        return requests.get(url, **kwargs).json()

    def activate_coupon(self, coupon_id):
        """Activate single coupon by id"""
        url = f"{self._COUPONS_API}/v1/promotions/{coupon_id}/activation"
        kwargs = {"headers": {**self._default_headers(), "Country": self._country}, "timeout": self._TIMEOUT}
        return requests.post(url, **kwargs).text

    def deactivate_coupon(self, coupon_id):
        """Deactivate single coupon by id"""
        url = f"{self._COUPONS_API}/v1/{self._country}/{coupon_id}/activation"
        kwargs = {"headers": self._default_headers(), "timeout": self._TIMEOUT}
        return requests.delete(url, **kwargs).json()

    def loyalty_id(self):
        """Get your loyalty ID"""
        url = f"{self._PROFILE_API}/v1/{self._country}/loyalty"
        kwargs = {"headers": self._default_headers(), "timeout": self._TIMEOUT}
        response = requests.get(url, **kwargs)
        response.raise_for_status()
        return response.text
