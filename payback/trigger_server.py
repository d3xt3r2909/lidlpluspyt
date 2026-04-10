#!/usr/bin/env python3
"""
Payback trigger server — runs as a systemd service on the Pi host.

Endpoints:
  GET  /           HTML dashboard (embed in HA as iframe panel)
  POST /login      Attempt headless auto-login; save cookies on success
  POST /activate   Start headless coupon activation in background
  GET  /coupons    Return coupon list as JSON (cached 1 h)
  GET  /status     Return last activation result as JSON
"""
import json
import logging
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

PORT = 7654
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.join(BASE_DIR, "..")
VENV_PYTHON = os.path.join(PARENT_DIR, "venv", "bin", "python3")
ACTIVATE_SCRIPT = os.path.join(BASE_DIR, "activate.py")
COOKIES_FILE = os.path.join(BASE_DIR, "cookies.json")
STATUS_FILE = os.path.join(BASE_DIR, "last_result.json")
ENV_FILE = os.path.join(PARENT_DIR, ".env")

_lock = threading.Lock()
_running = False
_coupon_cache: dict = {"data": None, "ts": 0}
COUPON_CACHE_TTL = 3600  # seconds

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _load_env() -> dict:
    env = dict(os.environ)
    if os.path.exists(ENV_FILE):
        with open(ENV_FILE) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env.setdefault(k.strip(), v.strip())
    return env


def _init_browser(headless: bool):
    """Return a Firefox webdriver with selenium-wire."""
    sys.path.insert(0, PARENT_DIR)
    from seleniumwire import webdriver
    from selenium.webdriver.firefox.options import Options

    for _noisy in ("seleniumwire", "urllib3", "hpack"):
        logging.getLogger(_noisy).setLevel(logging.WARNING)

    options = Options()
    options.accept_insecure_certs = True
    options.set_preference("dom.webdriver.enabled", False)
    if headless:
        options.add_argument("--headless")
    browser = webdriver.Firefox(options=options, seleniumwire_options={"verify_ssl": False})
    browser.set_page_load_timeout(60)
    return browser


def _load_cookies(browser) -> bool:
    if not os.path.exists(COOKIES_FILE):
        return False
    from selenium.webdriver.support.ui import WebDriverWait
    browser.get("https://www.payback.de")
    time.sleep(2)
    with open(COOKIES_FILE) as f:
        cookies = json.load(f)
    for cookie in cookies:
        cookie.pop("sameSite", None)
        try:
            browser.add_cookie(cookie)
        except Exception:
            pass
    return True


def _is_logged_in(browser) -> bool:
    cur = browser.current_url
    title = browser.title.lower()
    return "/login" not in cur and "payback.de" in cur and "404" not in title


# ---------------------------------------------------------------------------
# Background tasks
# ---------------------------------------------------------------------------

def _run_activation():
    global _running
    python = VENV_PYTHON if os.path.exists(VENV_PYTHON) else "python3"
    env = _load_env()
    result = subprocess.run(
        [python, ACTIVATE_SCRIPT],
        capture_output=True, text=True,
        cwd=PARENT_DIR, env=env,
    )
    status = {
        "exit_code": result.returncode,
        "success": result.returncode == 0,
        "stdout": result.stdout[-2000:],
        "stderr": result.stderr[-500:] if result.returncode != 0 else "",
        "timestamp": __import__("datetime").datetime.now().isoformat(),
    }
    with open(STATUS_FILE, "w") as f:
        json.dump(status, f, indent=2)
    with _lock:
        _running = False
    log.info(f"Activation finished — exit {result.returncode}")


SCRAPE_JS = """
return (function() {
    var stack = document.querySelector('[data-testid="coupons-list-stack"]');
    if (!stack) return null;
    return Array.from(stack.children).map(function(card) {
        var img = card.querySelector('img');
        var btns = Array.from(card.querySelectorAll('button'))
                        .map(function(b) { return b.textContent.trim(); });
        var isActivated = !btns.includes('Jetzt aktivieren');
        var leaves = Array.from(card.querySelectorAll('p,span,div,h1,h2,h3,h4,h5,h6'))
            .filter(function(el) {
                return el.children.length === 0 && el.textContent.trim().length > 1;
            })
            .map(function(el) { return el.textContent.trim(); })
            .filter(function(t) { return t.length < 200; });
        return {
            title: leaves[0] || '',
            description: leaves[1] || '',
            points: leaves.find(function(t) { return /\\d+.*[Pp]unkt/.test(t); }) || '',
            validUntil: leaves.find(function(t) { return /bis\\s|gültig|valid/i.test(t); }) || '',
            image: img ? img.src : '',
            isActivated: isActivated,
        };
    }).filter(function(c) { return c.title.length > 0; });
})();
"""

LOGIN_JS_CHECK = """
return (function() {
    var loginEl = document.querySelector('pbc-login');
    if (!loginEl) return {found: false};
    return {found: true, hasShadow: !!loginEl.shadowRoot};
})();
"""


def _scrape_coupons() -> list:
    browser = _init_browser(headless=True)
    try:
        if not _load_cookies(browser):
            return []
        browser.refresh()
        time.sleep(3)
        if not _is_logged_in(browser):
            return []
        browser.get("https://www.payback.de/coupons")
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.common.by import By
        try:
            WebDriverWait(browser, 20).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, '[data-testid="coupons-list-stack"]'))
            )
        except Exception:
            pass
        time.sleep(2)
        data = browser.execute_script(SCRAPE_JS)
        return data or []
    finally:
        browser.quit()


def _do_login(email: str, password: str) -> dict:
    """Attempt headless login via Shadow DOM. Returns {success, message}."""
    browser = _init_browser(headless=True)
    try:
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.common.by import By

        browser.get("https://www.payback.de/login")
        time.sleep(3)

        # Dismiss cookie banner
        try:
            btn = WebDriverWait(browser, 5).until(
                EC.presence_of_element_located((By.ID, "onetrust-accept-btn-handler"))
            )
            browser.execute_script("arguments[0].click();", btn)
            time.sleep(1)
        except Exception:
            pass

        # Check login form structure
        check = browser.execute_script(LOGIN_JS_CHECK)
        if not check.get("found"):
            return {"success": False, "message": "Login form not found on page"}

        shadow_host = WebDriverWait(browser, 10).until(
            EC.presence_of_element_located((By.TAG_NAME, "pbc-login"))
        )
        time.sleep(1)
        shadow_root = shadow_host.shadow_root

        email_field = shadow_root.find_element(
            By.CSS_SELECTOR, "input[type='email'], input[autocomplete='email'], input[name='email']"
        )
        email_field.clear()
        email_field.send_keys(email)
        time.sleep(0.5)

        pwd_field = shadow_root.find_element(By.CSS_SELECTOR, "input[type='password']")
        pwd_field.clear()
        pwd_field.send_keys(password)
        time.sleep(0.5)

        submit = shadow_root.find_element(By.CSS_SELECTOR, "button[type='submit']")
        submit.click()

        # Wait for redirect
        start = time.time()
        while time.time() - start < 30:
            if _is_logged_in(browser):
                # Save cookies
                cookies = browser.get_cookies()
                with open(COOKIES_FILE, "w") as f:
                    json.dump(cookies, f, indent=2)
                # Invalidate coupon cache
                _coupon_cache["ts"] = 0
                return {"success": True, "message": f"Logged in. {len(cookies)} cookies saved."}
            time.sleep(2)

        title = browser.title
        cur = browser.current_url
        return {
            "success": False,
            "message": f"Login timed out. URL: {cur} | Title: {title}",
        }
    except Exception as e:
        return {"success": False, "message": f"Login error: {str(e)[:200]}"}
    finally:
        browser.quit()


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Payback</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: #111827; color: #f3f4f6; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; min-height: 100vh; padding: 16px; }
  header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; flex-wrap: wrap; gap: 8px; }
  h1 { font-size: 18px; font-weight: 700; display: flex; align-items: center; gap: 8px; }
  .actions { display: flex; gap: 8px; }
  button { padding: 8px 16px; border: none; border-radius: 8px; cursor: pointer; font-size: 13px; font-weight: 600; transition: opacity .15s; }
  button:hover { opacity: .85; }
  button:disabled { opacity: .5; cursor: not-allowed; }
  .btn-login { background: #6366f1; color: #fff; }
  .btn-activate { background: #10b981; color: #fff; }
  #status { background: #1f2937; border-radius: 8px; padding: 10px 14px; margin-bottom: 16px; font-size: 13px; color: #9ca3af; min-height: 38px; }
  #status.ok { color: #10b981; }
  #status.err { color: #ef4444; }
  #status.info { color: #60a5fa; }
  .meta { font-size: 12px; color: #6b7280; margin-bottom: 16px; }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 12px; }
  .card { background: #1f2937; border-radius: 10px; overflow: hidden; display: flex; flex-direction: column; }
  .card img { width: 100%; height: 110px; object-fit: contain; background: #374151; }
  .card-body { padding: 8px; flex: 1; display: flex; flex-direction: column; gap: 4px; }
  .card-title { font-size: 12px; font-weight: 600; line-height: 1.3; }
  .card-points { font-size: 11px; color: #60a5fa; }
  .card-valid { font-size: 10px; color: #6b7280; }
  .badge { display: inline-block; font-size: 10px; padding: 2px 7px; border-radius: 999px; font-weight: 600; margin-top: auto; }
  .badge-on { background: #065f46; color: #34d399; }
  .badge-off { background: #374151; color: #9ca3af; }
  .empty { text-align: center; color: #6b7280; padding: 40px; grid-column: 1/-1; }
  .spinner { display: inline-block; width: 14px; height: 14px; border: 2px solid #374151; border-top-color: #60a5fa; border-radius: 50%; animation: spin .7s linear infinite; vertical-align: middle; margin-right: 6px; }
  @keyframes spin { to { transform: rotate(360deg); } }
</style>
</head>
<body>
<header>
  <h1>🏷️ Payback Coupons</h1>
  <div class="actions">
    <button class="btn-login" onclick="doLogin()" id="btnLogin">🔑 Login</button>
    <button class="btn-activate" onclick="doActivate()" id="btnActivate">✅ Activate All</button>
  </div>
</header>
<div id="status">Loading...</div>
<div id="meta" class="meta"></div>
<div id="grid" class="grid"></div>

<script>
async function load() {
  try {
    const [coupons, status] = await Promise.all([
      fetch('/coupons').then(r => r.json()),
      fetch('/status').then(r => r.json()),
    ]);
    renderStatus(status);
    renderCoupons(coupons);
  } catch(e) {
    setStatus('err', 'Connection error: ' + e.message);
  }
}

function setStatus(cls, msg) {
  const el = document.getElementById('status');
  el.className = cls;
  el.innerHTML = msg;
}

function renderStatus(s) {
  if (s.running) { setStatus('info', '<span class="spinner"></span>Running activation…'); return; }
  if (!s.timestamp) { setStatus('', 'No activation run yet.'); return; }
  const icon = s.success ? '✅' : '❌';
  const match = (s.stdout || '').match(/Activated\\s*:\\s*(\\d+)/);
  const n = match ? match[1] : '?';
  setStatus(s.success ? 'ok' : 'err', `${icon} Last run: ${new Date(s.timestamp).toLocaleString('de-DE')} — ${n} coupons activated`);
}

function renderCoupons(data) {
  const grid = document.getElementById('grid');
  const meta = document.getElementById('meta');
  if (!Array.isArray(data) || data.length === 0) {
    grid.innerHTML = '<div class="empty">No coupons found. Make sure you are logged in.</div>';
    meta.textContent = '';
    return;
  }
  const active = data.filter(c => c.isActivated).length;
  meta.textContent = `${data.length} coupons · ${active} activated · ${data.length - active} pending`;
  grid.innerHTML = data.map(c => `
    <div class="card">
      ${c.image ? `<img src="${c.image}" loading="lazy" onerror="this.style.display='none'">` : ''}
      <div class="card-body">
        <div class="card-title">${escHtml(c.title)}</div>
        ${c.points ? `<div class="card-points">${escHtml(c.points)}</div>` : ''}
        ${c.validUntil ? `<div class="card-valid">${escHtml(c.validUntil)}</div>` : ''}
        <span class="badge ${c.isActivated ? 'badge-on' : 'badge-off'}">${c.isActivated ? 'Activated' : 'Not yet'}</span>
      </div>
    </div>
  `).join('');
}

function escHtml(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

async function doActivate() {
  document.getElementById('btnActivate').disabled = true;
  setStatus('info', '<span class="spinner"></span>Starting activation…');
  await fetch('/activate', {method:'POST'});
  pollStatus();
}

async function doLogin() {
  document.getElementById('btnLogin').disabled = true;
  setStatus('info', '<span class="spinner"></span>Attempting login…');
  try {
    const resp = await fetch('/login', {method:'POST'});
    const data = await resp.json();
    setStatus(data.success ? 'ok' : 'err', (data.success ? '✅ ' : '❌ ') + data.message);
    if (data.success) setTimeout(load, 2000);
  } catch(e) {
    setStatus('err', 'Login request failed: ' + e.message);
  }
  document.getElementById('btnLogin').disabled = false;
}

function pollStatus() {
  fetch('/status').then(r => r.json()).then(s => {
    renderStatus(s);
    if (s.running) setTimeout(pollStatus, 3000);
    else { document.getElementById('btnActivate').disabled = false; load(); }
  });
}

load();
</script>
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/", "/dashboard"):
            self._html(200, DASHBOARD_HTML)
        elif self.path == "/status":
            data = {}
            if os.path.exists(STATUS_FILE):
                with open(STATUS_FILE) as f:
                    data = json.load(f)
            with _lock:
                data["running"] = _running
            self._json(200, data)
        elif self.path == "/coupons":
            self._serve_coupons()
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        global _running
        if self.path == "/activate":
            with _lock:
                if _running:
                    self._json(409, {"status": "already_running"})
                    return
                _running = True
            threading.Thread(target=_run_activation, daemon=True).start()
            self._json(202, {"status": "started"})
        elif self.path == "/login":
            env = _load_env()
            email = env.get("PAYBACK_EMAIL", "")
            password = env.get("PAYBACK_PASSWORD", "")
            if not email or not password:
                self._json(400, {"success": False, "message": "PAYBACK_EMAIL / PAYBACK_PASSWORD not set in .env"})
                return
            # Run in current thread (blocking) so client gets result
            result = _do_login(email, password)
            self._json(200 if result["success"] else 502, result)
        else:
            self._json(404, {"error": "not found"})

    def _serve_coupons(self):
        now = time.time()
        if _coupon_cache["data"] is not None and now - _coupon_cache["ts"] < COUPON_CACHE_TTL:
            self._json(200, _coupon_cache["data"])
            return

        def _refresh():
            try:
                data = _scrape_coupons()
                _coupon_cache["data"] = data
                _coupon_cache["ts"] = time.time()
            except Exception as e:
                log.error(f"Coupon scrape error: {e}")
                _coupon_cache["data"] = []
                _coupon_cache["ts"] = time.time()

        # Serve stale data immediately, refresh in background
        if _coupon_cache["data"] is not None:
            self._json(200, _coupon_cache["data"])
            threading.Thread(target=_refresh, daemon=True).start()
        else:
            # First request — must wait
            _refresh()
            self._json(200, _coupon_cache["data"] or [])

    def _json(self, code: int, data):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _html(self, code: int, html: str):
        body = html.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    log.info(f"Payback server listening on :{PORT}")
    log.info(f"Dashboard: http://0.0.0.0:{PORT}/")
    HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
