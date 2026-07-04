"""
Dispensary E-Commerce Report Card — public web app
===================================================

Thin FastAPI wrapper around report_card.scan().

Endpoints
---------
GET  /              landing page with URL input form
GET  /scan?url=...  runs a scan and renders the HTML report (shareable link)
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
import socket
import time
from collections import defaultdict
from urllib.parse import urlparse, quote_plus

import requests
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse

import report_card

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("report-card-web")

app = FastAPI(title="Dispensary Report Card", docs_url=None, redoc_url=None)

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
      <div class="feature-detail">GA4, GTM, GSC, Meta Pixel, TikTok Pixel.</div>
    </div>
    <div class="feature">
      <div class="feature-name">E-commerce Structure (10%)</div>
      <div class="feature-detail">Product pages, clean URLs, HTTPS.</div>
    </div>
  </div>
</div></main>

<footer>
  Built by <a href="https://budmafia.com">BudMafia.com</a>.
  Scans use only public data and are not stored.
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

@app.get("/", response_class=HTMLResponse)
async def index():
    return HTMLResponse(INDEX_HTML)


@app.get("/health")
async def health():
    return JSONResponse({"status": "ok"})


REPORT_HEADER_TEMPLATE = (
    '<div style="background: #0f1419; padding: 16px 24px; '
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
    host = request.headers.get("host", "dispensarystack.com")
    share_url = "https://" + host + "/scan?url=" + quote_plus(safe_url)
    header_html = REPORT_HEADER_TEMPLATE.replace("__SHARE__", escape_html(share_url))
    # Inject the nav header right after <body> so the report keeps its own styling.
    html = html.replace("<body>", "<body>" + header_html, 1)
    return HTMLResponse(html)


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
