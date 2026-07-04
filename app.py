"""
Dispensary E-Commerce Report Card — public web app
===================================================

Thin FastAPI wrapper around report_card.scan().

Endpoints
---------
GET  /              landing page with URL input form
GET  /scan?url=...  runs a scan, stores it, redirects to /r/<token>
GET  /r/<token>     stored report: teaser (grade + category scores) until the
                    visitor unlocks with an email, then the full report
POST /unlock        email-gate submission -> saves lead, sets unlock cookie
GET  /admin?key=..  private: leads + scans tables (ADMIN_KEY env var)
GET  /admin.csv     private: leads CSV export for your ESP
GET  /health        for the host's healthcheck

Safety
------
- SSRF protection: refuses private/loopback/link-local IPs, plus localhost.
- Rate limit: 5 scans per IP per hour (in-memory; resets on cold start).
- Hard scan timeout: 35s total (Render free tier has ~30s safe window;
  individual fetches are capped at 8s).
- URL length: max 500 chars.
- Only http(s) schemes accepted.
"""

from __future__ import annotations

import ipaddress
import logging
import os
import re
import secrets
import socket
import time
from collections import defaultdict
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import (HTMLResponse, JSONResponse, PlainTextResponse,
                               RedirectResponse)

import db
import report_card

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("report-card-web")

app = FastAPI(title="Dispensary Report Card", docs_url=None, redoc_url=None)

db.init()

# Secret for the /admin page. If unset, the admin page is disabled (404).
ADMIN_KEY = os.environ.get("ADMIN_KEY", "")

# Cookie that marks a browser as having already given an email once —
# returning visitors aren't gated twice.
UNLOCK_COOKIE = "dsr_unlocked"

# ---------------------------------------------------------------------------
# Tighten the fetcher used by the scanner: shorter timeout for public use
# ---------------------------------------------------------------------------

PUBLIC_FETCH_TIMEOUT = 8.0  # seconds per HTTP request


def _public_fetch(url, timeout=PUBLIC_FETCH_TIMEOUT):
    try:
        return requests.get(
            url,
            headers={
                "User-Agent": (
                    "DispensaryStack/1.0 (+https://dispensarystack.com)"
                ),
                "Accept-Language": "en-US,en;q=0.9",
            },
            cookies=report_card.AGE_GATE_COOKIES,
            timeout=PUBLIC_FETCH_TIMEOUT,
            allow_redirects=True,
        )
    except requests.RequestException:
        return None


# Monkey-patch the scanner's fetch to use the shorter public timeout.
report_card.fetch = _public_fetch


# ---------------------------------------------------------------------------
# Rate limiting (per-IP, in-memory)
# ---------------------------------------------------------------------------

RATE_LIMIT = int(os.environ.get("RATE_LIMIT", 5))
RATE_WINDOW_SECONDS = int(os.environ.get("RATE_WINDOW", 3600))
_visits = defaultdict(list)


def _check_rate(ip):
    now = time.time()
    _visits[ip] = [t for t in _visits[ip] if now - t < RATE_WINDOW_SECONDS]
    if len(_visits[ip]) >= RATE_LIMIT:
        retry = int(RATE_WINDOW_SECONDS - (now - _visits[ip][0]))
        raise HTTPException(
            status_code=429,
            detail=(
                "Rate limit reached (" + str(RATE_LIMIT) + " scans per "
                + str(RATE_WINDOW_SECONDS // 60) + " minutes). "
                "Try again in about " + str(max(1, retry // 60)) + " minutes."
            ),
        )
    _visits[ip].append(now)


# ---------------------------------------------------------------------------
# URL validation — SSRF protection
# ---------------------------------------------------------------------------

BLOCKED_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}


def _validate_url(raw):
    if not raw:
        raise HTTPException(400, "Please provide a URL.")
    raw = raw.strip()
    if len(raw) > 500:
        raise HTTPException(400, "URL is too long.")
    # Reject any non-http(s) scheme up front. urlparse handles things like
    # "javascript:..." (no "//") as well as "ftp://..."
    first_parse = urlparse(raw)
    if first_parse.scheme and first_parse.scheme.lower() not in ("http", "https"):
        raise HTTPException(400, "Only http and https URLs are allowed.")
    if not first_parse.scheme:
        # Bare hostname like "example.com/path" — prepend https://
        raw = "https://" + raw

    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(400, "Only http and https URLs are allowed.")
    if not parsed.netloc:
        raise HTTPException(400, "That URL is missing a hostname.")

    host = (parsed.hostname or "").lower()
    if host in BLOCKED_HOSTS:
        raise HTTPException(400, "Cannot scan localhost.")

    # Resolve and refuse private/internal IPs
    try:
        ip_str = socket.gethostbyname(host)
    except socket.gaierror:
        raise HTTPException(400, "Could not resolve hostname: " + host)

    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        raise HTTPException(400, "Invalid IP address: " + ip_str)

    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    ):
        raise HTTPException(
            400,
            "Cannot scan internal/private addresses. Only public websites are supported.",
        )

    return raw


# ---------------------------------------------------------------------------
# Client IP — Render and most reverse proxies pass X-Forwarded-For
# ---------------------------------------------------------------------------

def _client_ip(request):
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# ---------------------------------------------------------------------------
# Landing page
# ---------------------------------------------------------------------------

INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>Dispensary E-Commerce Report Card</title>
<meta name="viewport" content="width=device-width,initial-scale=1" />
<meta name="description" content="Free scoring tool for cannabis dispensary websites. Grades SEO, email marketing, loyalty, analytics, and retention in under a minute." />
<style>
  :root {
    --bg: #0f1419;
    --panel: #1a1f26;
    --line: #2a313b;
    --text: #e6e8eb;
    --muted: #8a93a0;
    --accent: #5cd6ff;
    --accent-hover: #7adfff;
  }
  * { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; background: var(--bg); color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
    Helvetica, Arial, sans-serif; line-height: 1.55; min-height: 100%; }
  body { display: flex; flex-direction: column; min-height: 100vh; }
  main { flex: 1; }
  .wrap { max-width: 720px; margin: 0 auto; padding: 56px 24px 32px; }
  h1 { margin: 0 0 8px; font-size: 32px; font-weight: 700; letter-spacing: -0.01em; }
  .tagline { color: var(--muted); font-size: 16px; margin-bottom: 36px; }
  .card { background: var(--panel); border: 1px solid var(--line);
    border-radius: 14px; padding: 28px; }
  label { display: block; font-weight: 600; margin-bottom: 10px; font-size: 14px; }
  .row { display: flex; gap: 10px; }
  input[type=url] { flex: 1; padding: 14px 16px; font-size: 16px;
    background: #0a0e12; color: var(--text); border: 1px solid var(--line);
    border-radius: 8px; outline: none; transition: border-color 0.15s; }
  input[type=url]:focus { border-color: var(--accent); }
  button { padding: 14px 24px; font-size: 16px; font-weight: 600;
    background: var(--accent); color: #0a0e12; border: none;
    border-radius: 8px; cursor: pointer; transition: background 0.15s; }
  button:hover { background: var(--accent-hover); }
  button:disabled { opacity: 0.5; cursor: not-allowed; }
  .hint { color: var(--muted); font-size: 13px; margin-top: 10px; }
  h2 { margin: 40px 0 16px; font-size: 20px; font-weight: 600; }
  .features { display: grid; grid-template-columns: repeat(2, 1fr);
    gap: 12px; margin-top: 16px; }
  @media (max-width: 540px) { .features { grid-template-columns: 1fr; } }
  .feature { background: var(--panel); border: 1px solid var(--line);
    border-radius: 10px; padding: 14px 16px; }
  .feature-name { font-weight: 600; font-size: 14px; }
  .feature-detail { color: var(--muted); font-size: 13px; margin-top: 4px; }
  footer { color: var(--muted); font-size: 12px; padding: 24px;
    text-align: center; border-top: 1px solid var(--line); }
  footer a { color: var(--muted); }
  .spinner { display: none; margin-top: 16px; color: var(--muted); font-size: 13px; }
  .spinner.visible { display: block; }
  .dots::after { content: ""; animation: dots 1.4s steps(4, end) infinite; }
  @keyframes dots {
    0%   { content: ""; }
    25%  { content: "."; }
    50%  { content: ".."; }
    75%  { content: "..."; }
    100% { content: ""; }
  }
</style>
</head>
<body>
<main><div class="wrap">
  <h1>Dispensary E-Commerce Report Card</h1>
  <div class="tagline">
    Free scoring tool for cannabis dispensary websites.
    Grades SEO, email marketing, loyalty, analytics, and retention
    in under a minute.
  </div>

  <form class="card" id="scan-form" action="/scan" method="get">
    <label for="url">Enter a dispensary website URL</label>
    <div class="row">
      <input type="url" id="url" name="url"
             placeholder="https://example-dispensary.com"
             required autofocus />
      <button type="submit" id="submit-btn">Get Report</button>
    </div>
    <div class="hint">
      We only scan public pages. Most scans complete in 10&ndash;30 seconds.
    </div>
    <div class="spinner" id="spinner">
      Scanning the site<span class="dots"></span>
      <br />This can take 10&ndash;30 seconds.
    </div>
  </form>

  <h2>What we check</h2>
  <div class="features">
    <div class="feature">
      <div class="feature-name">SEO Fundamentals (20%)</div>
      <div class="feature-detail">Title, meta description, Open Graph, structured data, sitemap.</div>
    </div>
    <div class="feature">
      <div class="feature-name">Email Marketing (25%)</div>
      <div class="feature-detail">Newsletter capture + ESP detection (Klaviyo &gt; Mailchimp &gt; others).</div>
    </div>
    <div class="feature">
      <div class="feature-name">Loyalty Program (15%)</div>
      <div class="feature-detail">AlpineIQ, Springbig, Sticky Cards, or custom.</div>
    </div>
    <div class="feature">
      <div class="feature-name">Retention &amp; Reviews (15%)</div>
      <div class="feature-detail">Abandoned cart, review platforms, post-purchase flows.</div>
    </div>
    <div class="feature">
      <div class="feature-name">Analytics &amp; Tracking (15%)</div>
      <div class="feature-detail">GA4, GTM, Search Console. Ad pixels reported as info.</div>
    </div>
    <div class="feature">
      <div class="feature-name">E-commerce Structure (10%)</div>
      <div class="feature-detail">Product pages, clean URLs, HTTPS.</div>
    </div>
  </div>
</div></main>

<footer>
  Built by <a href="https://poof.ca">poof.ca</a>.
  Scans use only public data. Reports are saved so you can share a
  permanent link.
</footer>

<script>
document.getElementById("scan-form").addEventListener("submit", function() {
  document.getElementById("submit-btn").disabled = true;
  document.getElementById("submit-btn").textContent = "Scanning...";
  document.getElementById("spinner").classList.add("visible");
});
</script>
</body>
</html>
"""


ERROR_HTML_TEMPLATE = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8" />
<title>Error - Dispensary Report Card</title>
<meta name="viewport" content="width=device-width,initial-scale=1" />
<style>
  body { margin: 0; background: #0f1419; color: #e6e8eb;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
    sans-serif; line-height: 1.55; }
  .wrap { max-width: 600px; margin: 0 auto; padding: 80px 24px; }
  h1 { font-size: 22px; }
  p { color: #8a93a0; }
  a { color: #5cd6ff; }
  .card { background: #1a1f26; border: 1px solid #2a313b; border-radius: 12px;
    padding: 24px; margin-top: 24px; }
</style></head>
<body><div class="wrap">
  <h1>We couldn't run that scan.</h1>
  <div class="card"><p>__MESSAGE__</p></div>
  <p style="margin-top: 24px;"><a href="/">&larr; Try another URL</a></p>
</div></body></html>"""


def _error_page(message, status=400):
    # Escape any HTML-special characters in the message
    safe = (
        str(message)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    body = ERROR_HTML_TEMPLATE.replace("__MESSAGE__", safe)
    return HTMLResponse(body, status_code=status)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

# The designed landing page (landing.html, built in Shuffle) is served when
# present; the original inline page below stays as a fallback so the app
# never 500s if the file goes missing.
LANDING_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "landing.html")
_landing_cache: str | None = None


def _landing() -> str:
    global _landing_cache
    if _landing_cache is None:
        try:
            with open(LANDING_PATH, encoding="utf-8") as f:
                _landing_cache = f.read()
        except OSError:
            _landing_cache = INDEX_HTML
    return _landing_cache


@app.get("/", response_class=HTMLResponse)
async def index():
    return HTMLResponse(_landing())


@app.get("/health")
async def health():
    return JSONResponse({"status": "ok"})


REPORT_HEADER_TEMPLATE = (
    '<div class="no-print" style="background: #0f1419; padding: 16px 24px; '
    'border-bottom: 1px solid #2a313b; '
    'font-family: -apple-system, BlinkMacSystemFont, sans-serif; '
    'color: #8a93a0; font-size: 13px;">'
    '<a href="/" style="color: #5cd6ff; text-decoration: none;">&larr; New scan</a>'
    '<span style="margin: 0 12px;">|</span>'
    'Shareable link: '
    '<code style="color: #e6e8eb; font-size: 12px; user-select: all;">__SHARE__</code>'
    '</div>'
)


@app.get("/scan", response_class=HTMLResponse)
async def scan(request: Request, url: str = Query(...)):
    ip = _client_ip(request)
    try:
        _check_rate(ip)
        safe_url = _validate_url(url)
    except HTTPException as e:
        return _error_page(str(e.detail), status=e.status_code)

    log.info("scan start ip=%s url=%s", ip, safe_url)
    t0 = time.time()
    api_key = os.environ.get("GOOGLE_PLACES_API_KEY") or None
    try:
        result = report_card.scan(safe_url, gbp_api_key=api_key)
    except report_card.ScanError as e:
        log.warning("scan failed url=%s err=%s", safe_url, e)
        return _error_page(
            "We couldn't fetch this site. The server returned an error or timed out. "
            "Details: " + str(e),
            status=502,
        )
    except Exception:
        log.exception("unexpected scan error")
        return _error_page(
            "Something went wrong during the scan. Try again in a moment.",
            status=500,
        )
    elapsed = time.time() - t0
    log.info("scan done url=%s elapsed=%.1fs grade=%s pct=%.1f",
             safe_url, elapsed, result.overall_letter, result.overall_percent)

    html = report_card.render_html(result)
    token = db.save_scan(
        safe_url,
        urlparse(safe_url).hostname or "",
        round(result.overall_percent, 1),
        result.overall_letter,
        html,
    )
    return RedirectResponse("/r/" + token, status_code=303)


# ---------------------------------------------------------------------------
# Stored reports: teaser -> email gate -> full report
# ---------------------------------------------------------------------------

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")

GATE_HTML = """
<div style="max-width:860px;margin:8px auto 32px;padding:28px;
  background:#1a1f26;border:1px solid #5cd6ff;border-radius:14px;
  font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
  color:#e6e8eb;">
  <h3 style="margin:0 0 8px;font-size:20px;">Unlock the full report — free</h3>
  <p style="color:#8a93a0;margin:0 0 18px;font-size:14px;">
    You're seeing the summary. The full report shows every check we ran on
    this site — what's passing, what's failing, and what to fix first.
  </p>
  <form method="post" action="/unlock" style="margin:0;">
    <input type="hidden" name="token" value="__TOKEN__" />
    <div style="display:flex;gap:10px;flex-wrap:wrap;">
      <input type="email" name="email" required
             placeholder="you@yourdispensary.com"
             style="flex:1;min-width:220px;padding:13px 15px;font-size:15px;
             background:#0a0e12;color:#e6e8eb;border:1px solid #2a313b;
             border-radius:8px;outline:none;" />
      <button type="submit"
              style="padding:13px 22px;font-size:15px;font-weight:600;
              background:#5cd6ff;color:#0a0e12;border:none;border-radius:8px;
              cursor:pointer;">Unlock full report</button>
    </div>
    <label style="display:block;margin-top:14px;font-size:13px;color:#8a93a0;
                  cursor:pointer;">
      <input type="checkbox" name="consent" value="1"
             style="margin-right:6px;vertical-align:middle;" />
      Also send me practical e-commerce tips for cannabis retailers (optional)
    </label>
    <div style="margin-top:10px;font-size:12px;color:#8a93a0;">
      We use your email to unlock this report. No spam, no sharing your data.
    </div>
  </form>
</div>
"""


def _teaser_html(full_html: str, token: str) -> str:
    """Strip check-level detail, notes, and the detected stack out of a stored
    report, leaving the grade hero + per-category scores, and insert the
    email gate. Detail is removed server-side (not hidden with CSS), so
    view-source reveals nothing."""
    soup = BeautifulSoup(full_html, "lxml")
    # .priority ("Where to start" fix list) is the core gated value —
    # strip it along with check details, notes, and the stack.
    for el in soup.select(".check, .notes, .stack, .priority"):
        el.decompose()
    gate = BeautifulSoup(GATE_HTML.replace("__TOKEN__", token), "lxml")
    footer = soup.select_one(".footer")
    gate_el = gate.find("div")
    if footer is not None and gate_el is not None:
        footer.insert_before(gate_el)
    elif gate_el is not None and soup.body is not None:
        soup.body.append(gate_el)
    return str(soup)


def _report_nav(request: Request, token: str) -> str:
    host = request.headers.get("host", "dispensarystack.com")
    share_url = "https://" + host + "/r/" + token
    return REPORT_HEADER_TEMPLATE.replace("__SHARE__", escape_html(share_url))


@app.get("/r/{token}", response_class=HTMLResponse)
async def stored_report(request: Request, token: str):
    row = db.get_scan(token)
    if row is None:
        return _error_page("That report link doesn't exist (or was mistyped).",
                           status=404)
    unlocked = request.cookies.get(UNLOCK_COOKIE) == "1"
    html = row["report_html"] if unlocked else _teaser_html(
        row["report_html"], token)
    html = html.replace("<body>", "<body>" + _report_nav(request, token), 1)
    return HTMLResponse(html)


@app.post("/unlock")
async def unlock(token: str = Form(...), email: str = Form(...),
                 consent: str = Form("")):
    email = (email or "").strip()
    if len(email) > 254 or not EMAIL_RE.match(email):
        return _error_page("That email address doesn't look valid — "
                           "please go back and try again.")
    if db.get_scan(token) is None:
        return _error_page("That report link doesn't exist.", status=404)
    db.save_lead(email, token, consent == "1")
    log.info("lead captured token=%s consent=%s", token, consent == "1")
    resp = RedirectResponse("/r/" + token, status_code=303)
    resp.set_cookie(UNLOCK_COOKIE, "1", max_age=60 * 60 * 24 * 365,
                    httponly=True, samesite="lax")
    return resp


# ---------------------------------------------------------------------------
# Admin: leads + scans (secret key), CSV export
# ---------------------------------------------------------------------------

def _admin_ok(key: str) -> bool:
    return bool(ADMIN_KEY) and secrets.compare_digest(key or "", ADMIN_KEY)


@app.get("/admin", response_class=HTMLResponse)
async def admin(key: str = Query("")):
    if not _admin_ok(key):
        raise HTTPException(404)
    n_scans, n_leads = db.counts()
    lead_rows = "".join(
        "<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td>"
        "<td><a href='/r/{}'>{}</a></td></tr>".format(
            escape_html(r["email"]),
            "yes" if r["marketing_consent"] else "no",
            escape_html(r["created_at"] or ""),
            escape_html(r["hostname"] or "?"),
            escape_html(r["scan_token"] or ""),
            (str(r["score"]) + " (" + (r["grade"] or "?") + ")")
            if r["score"] is not None else "?")
        for r in db.list_leads())
    scan_rows = "".join(
        "<tr><td>{}</td><td>{}</td><td>{}</td>"
        "<td><a href='/r/{}'>open</a></td></tr>".format(
            escape_html(r["hostname"] or r["url"]),
            (str(r["score"]) + " (" + (r["grade"] or "?") + ")")
            if r["score"] is not None else "?",
            escape_html(r["created_at"] or ""),
            escape_html(r["token"]))
        for r in db.list_scans())
    page = """<!doctype html><html><head><meta charset="utf-8" />
    <title>Admin — Dispensary Report Card</title>
    <style>body{{margin:0;background:#0f1419;color:#e6e8eb;
    font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;}}
    .wrap{{max-width:1000px;margin:0 auto;padding:40px 24px;}}
    h1{{font-size:24px;}} h2{{font-size:18px;margin-top:36px;}}
    table{{width:100%;border-collapse:collapse;font-size:13px;}}
    th,td{{text-align:left;padding:8px 10px;border-bottom:1px solid #2a313b;}}
    th{{color:#8a93a0;font-weight:600;}}
    a{{color:#5cd6ff;text-decoration:none;}}
    .pill{{background:#1a1f26;border:1px solid #2a313b;border-radius:8px;
    padding:10px 16px;display:inline-block;margin-right:10px;}}</style>
    </head><body><div class="wrap">
    <h1>Dispensary Report Card — Admin</h1>
    <div><span class="pill">Scans: {n_scans}</span>
    <span class="pill">Leads: {n_leads}</span>
    <span class="pill"><a href="/admin.csv?key={key}">Download leads CSV</a></span></div>
    <h2>Leads (newest first)</h2>
    <table><tr><th>Email</th><th>Marketing consent</th><th>Captured (UTC)</th>
    <th>Site scanned</th><th>Score</th></tr>{lead_rows}</table>
    <h2>Scans (newest first)</h2>
    <table><tr><th>Site</th><th>Score</th><th>When (UTC)</th><th>Report</th></tr>
    {scan_rows}</table>
    </div></body></html>""".format(
        n_scans=n_scans, n_leads=n_leads, key=escape_html(key),
        lead_rows=lead_rows or "<tr><td colspan='5'>none yet</td></tr>",
        scan_rows=scan_rows or "<tr><td colspan='4'>none yet</td></tr>")
    return HTMLResponse(page)


@app.get("/admin.csv")
async def admin_csv(key: str = Query("")):
    if not _admin_ok(key):
        raise HTTPException(404)
    return PlainTextResponse(
        db.leads_csv(),
        headers={"Content-Disposition": "attachment; filename=leads.csv"},
        media_type="text/csv",
    )


def escape_html(s):
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


if __name__ == "__main__":
    # Local development: python3 app.py  →  http://localhost:8000
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", 8000)))