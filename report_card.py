#!/usr/bin/env python3
"""
Dispensary E-Commerce Report Card
=================================

Usage:
    python report_card.py https://example.com
    python report_card.py https://example.com --json > report.json
    python report_card.py https://example.com --output my_report.html

What it does:
    Fetches the site's homepage, robots.txt, sitemap.xml, and one sample
    product page. Detects SEO basics, analytics/tracking pixels, email
    platform, loyalty platform, and retention/review tools. Scores the
    site across 6 weighted categories and emits a shareable HTML report.

Dependencies:
    pip install requests beautifulsoup4 lxml

Author: Built for poof.ca — Riel
"""

from __future__ import annotations

import argparse
import json
import re
import os
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


# ---------------------------------------------------------------------------
# Detection signatures
# ---------------------------------------------------------------------------
# Each signature is a list of regex patterns checked against the raw HTML
# (including script src URLs and inline script bodies).
#
# IMPORTANT: signatures are tight on purpose. We distinguish between a
# platform being "actively in use" (its CDN scripts are loading) vs merely
# "available" (an integration plugin is installed but unconfigured). For
# example, the Breadstack e-commerce platform ships an AlpineIQ integration
# that adds CSS classes like `bs-alpineiq-reg-fname` to the DOM even when
# AIQ itself is not configured. We only credit AIQ when actual alpineiq.com
# scripts are loaded.
# ---------------------------------------------------------------------------

SIGS = {
    # ---- Email service providers ----
    "klaviyo": [
        r"static\.klaviyo\.com",
        r"static-tracking\.klaviyo\.com",
        r"a\.klaviyo\.com",
        r"/plugins/klaviyo/",
        r"_learnq\b",
    ],
    "mailchimp": [
        r"list-manage\.com",
        r"chimpstatic\.com",
        r"mailchimp\.com/(?:embed|js)",
    ],
    "omnisend": [r"omnisend\.com", r"omnisrc\.com"],
    "activecampaign": [r"activehosted\.com", r"trackcmp\.net"],
    "klaviyo_form": [
        r"klaviyo_subscribe",
        r"data-klaviyo-list",
        # Modern Klaviyo onsite forms: raw HTML holds an empty placeholder div
        # (class="klaviyo-form-XXXXXX") that Klaviyo's JS fills in at runtime.
        # Without this, JS-injected signup forms read as "no newsletter form".
        r"klaviyo-form-[A-Za-z0-9]{4,10}",
    ],

    # ---- Loyalty platforms (actively loaded) ----
    "alpineiq_active": [
        r"alpineiq\.com",
        r"lab\.alpineiq\.com",
        r"//aiq\.",
        r"window\.AIQ\b",
    ],
    "alpineiq_bundled": [
        # Breadstack's bundled integration — present but not necessarily used
        r"bs-alpineiq-",
    ],
    "springbig": [r"springbig\.com", r"sb_loyalty", r"sb-loyalty"],
    "sticky_cards": [r"stickycards\.io", r"cdn\.stickycards", r"sticky-cannabis"],
    "smile_io": [r"smile\.io", r"sweettooth\.io"],
    "yotpo_loyalty": [r"loyalty\.yotpo\.com"],
    "spark_rewards": [
        # First-party loyalty program of the FIKA family (Hifyre platform):
        # FIKA, Chrontact, Fire & Flower, etc. Branded "Spark Rewards"
        # (historically "Spark Perks" under Fire & Flower).
        r"spark\s+(rewards|perks)",
        r"href=[\"'][^\"']*/spark[\"'/#?]",
    ],

    # ---- Reviews / post-purchase ----
    "yotpo_reviews": [r"staticw2\.yotpo\.com", r"yotpo-widget"],
    "stamped": [r"stamped\.io", r"staticw2\.stamped"],
    "junip": [r"junip\.co"],
    "okendo": [r"okendo"],
    "judgeme": [r"judge\.me"],
    "automatewoo": [r"automatewoo", r"/plugins/automatewoo/"],
    "google_reviews_widget": [r"widget-google-reviews", r"google-places-reviews"],
    "google_maps_embed": [r"google\.com/maps/embed", r"maps\.google\.com/embed"],
    "google_business_link": [r"g\.page/", r"goo\.gl/maps/", r"maps\.app\.goo\.gl/"],

    # ---- Analytics & tag managers ----
    "ga4": [
        r"gtag\(\s*['\"]config['\"]\s*,\s*['\"]G-[A-Z0-9]+",
        r"googletagmanager\.com/gtag/js\?id=G-",
    ],
    "ua_legacy": [r"\bUA-\d{4,}-\d{1,}\b"],
    "gtm": [
        r"googletagmanager\.com/gtm\.js",
        r"GTM-[A-Z0-9]{4,}",
    ],
    "site_kit": [r"Site Kit by Google", r"googlesitekit"],
    "meta_pixel": [r"connect\.facebook\.net.*fbevents", r"fbq\(\s*['\"]init"],
    "tiktok_pixel": [r"analytics\.tiktok\.com"],
    "snapchat_pixel": [r"sc-static\.net/scevent"],
    "pinterest_tag": [r"s\.pinimg\.com/ct/core", r"pintrk\("],
    "hotjar": [r"static\.hotjar\.com", r"hj\("],
    "heatmap_com": [r"dashboard\.heatmap\.com"],
    "ahrefs_analytics": [r"analytics\.ahrefs\.com"],
    "cloudflare_insights": [r"static\.cloudflareinsights\.com"],

    # ---- Platform / stack ----
    "woocommerce": [r"/woocommerce/", r"wc-blocks", r"woocommerce-no-js"],
    "shopify": [r"cdn\.shopify\.com", r"\.myshopify\.com", r"Shopify\.shop"],
    "bigcommerce": [r"cdn\.bigcommerce\.com", r"bigcommerce\.com/s/"],
    "magento": [r"Magento_", r"static/version", r"mage/cookies"],
    # ---- Cannabis-specific e-commerce platforms ----
    "dutchie": [r"dutchie\.com", r"embed\.dutchie"],
    "iheartjane": [r"iheartjane\.com", r"jane-app", r"cdn\.jane\.com"],
    "buddi": [r"buddi\.io", r"cdn\.buddi", r"app\.buddi"],
    "blaze_ecom": [r"blaze\.me", r"blazeecom", r"blazenow"],
    "dispense": [r"dispense\.io", r"dispenseapp\.com", r"shop\.dispense"],
    "tymber": [r"tymber\.io"],
    "greenline": [r"getgreenline\.co", r"greenline\.shop"],
    "breadstack": [r"breadstack", r"/plugins/breadstack-connect/"],
    # Hifyre — retail platform behind the FIKA family of banners (FIKA,
    # Chrontact, Fire & Flower). Serves same-domain, server-rendered
    # /products/<slug> pages with a products sitemap.
    "hifyre": [r"hifyreretail\.com", r"cdn\.hifyre", r"\bhifyre\b"],
    # ---- POS / Inventory systems ----
    # IMPORTANT: Cova detection is tight on purpose. The Breadstack plugin
    # uses "cova" naming throughout (cova-woo-swatches-frontend.js,
    # Cova_WC_FRONT_SWATCH JS globals, cova-age-gate CSS, cova-icon-location)
    # regardless of which POS the merchant actually uses on the backend.
    # Real Cova is only credited when covasoft.com is in the HTML (its
    # actual hosted resources). If only Breadstack-bundled "cova" names
    # are present, we report the POS as undetermined.
    "cova_pos": [r"covasoft\.com", r"covasoftware\.com", r"//cova\.com/"],
    "treez": [r"treez\.io", r"treez-react"],
    "greenbits": [r"greenbits\.com"],
    "flowhub": [r"flowhub\.co", r"flowhub-"],
    "korona_pos": [r"korona\.cloud", r"koronapos"],
    "leaflogix": [r"leaflogix", r"mjfreeway"],
    # Greenline POS — has BOTH a hosted frontend menu (visible in HTML) and
    # a headless API mode (server-side only, NOT visible in public HTML).
    # We only credit when their CDN/menu domains appear.
    "greenline_pos": [r"getgreenline\.co", r"greenline\.shop", r"app\.greenline"],
    # ---- SSR / framework indicators ----
    "nextjs": [r"/_next/static/", r"__NEXT_DATA__"],
    "nuxt": [r"window\.__NUXT__", r"/_nuxt/"],
    "gatsby": [r"gatsby-", r"___gatsby"],
    "react_csr": [r'<div\s+id=["\']root["\']\s*></div>'],  # empty root div = client-rendered
    "yoast": [r"/yoast/", r"yoast-schema-graph"],
    "rankmath": [r"rank-math", r"rankmath"],
    "wordpress": [r"/wp-content/", r"/wp-includes/", r"name=[\"']generator[\"']\s+content=[\"']WordPress"],
}

# Terpene names — used to detect cannabis taxonomy richness
TERPENE_NAMES = [
    "myrcene", "limonene", "pinene", "caryophyllene", "linalool",
    "terpinolene", "humulene", "ocimene", "bisabolol", "valencene",
    "nerolidol", "geraniol", "borneol", "eucalyptol",
]

# Minor cannabinoids — beyond THC/CBD
MINOR_CANNABINOIDS = ["CBN", "CBG", "CBC", "CBDV", "THCV", "CBDA", "THCA"]


def detect_iframe_platform(html: str, soup) -> str | None:
    """Return the name of a cannabis ecom platform embedded as an iframe,
    or None. Checks both the parsed soup (homepage iframes) AND raw HTML
    via regex (catches iframes from per-store menu pages merged into the
    full_html corpus)."""
    srcs = []
    iframes = soup.find_all("iframe") if soup else []
    for f in iframes:
        srcs.append((f.get("src") or "").lower())
    # Also scan raw HTML for iframe tags merged in from subpages
    for m in re.finditer(r'<iframe[^>]+src=["\']([^"\']+)["\']',
                         html or "", re.IGNORECASE):
        srcs.append(m.group(1).lower())

    for src in srcs:
        if not src:
            continue
        if "dutchie.com" in src or "embed.dutchie" in src:
            return "dutchie"
        if "iheartjane.com" in src or "jane-app" in src:
            return "iheartjane"
        if "buddi.io" in src or "app.buddi" in src:
            return "buddi"
        if "blaze.me" in src or "blazeecom" in src:
            return "blaze_ecom"
        if "dispense.io" in src or "dispenseapp.com" in src:
            return "dispense"
    return None


def detect_terpene_taxonomy(html: str) -> tuple[bool, list[str]]:
    """Return (has_terpenes, list_of_terpenes_found). Considers it real
    'taxonomy' (vs just mentioned in passing) only if 3+ terpene names
    appear, suggesting filter facets or product attributes."""
    low = html.lower()
    found = [t for t in TERPENE_NAMES if t in low]
    return len(found) >= 3, found


def detect_minor_cannabinoids(html: str) -> tuple[bool, list[str]]:
    """Return (has_minor, list_found). Looks for cannabinoid abbreviations
    that appear as standalone tokens (not part of larger words)."""
    found = []
    for c in MINOR_CANNABINOIDS:
        # Word-boundary match, case-sensitive to avoid matching "scbn" etc.
        if re.search(r"\b" + c + r"\b", html):
            found.append(c)
    return len(found) >= 2, found


def detect_shop_subdomain(homepage_url: str, product_urls: list,
                          soup=None) -> bool:
    """Return True if the shop appears to live on a subdomain different
    from the main site (e.g. shop.example.com when homepage is example.com).

    Detects two signals:
      1. Product URLs in the sitemap point to a different host (shop.foo.com)
      2. Homepage links point to a shop/menu/store/cart subdomain
    """
    home_host = urlparse(homepage_url).netloc.lower().replace("www.", "")

    # Signal 1: sitemap product URLs on a different host
    for p in (product_urls or [])[:5]:
        p_host = urlparse(p).netloc.lower().replace("www.", "")
        if p_host and p_host != home_host:
            return True

    # Signal 2: homepage links to shop.*, menu.*, store.* subdomains
    if soup is not None:
        for a in soup.find_all("a", href=True):
            try:
                link_host = urlparse(a["href"]).netloc.lower().replace("www.", "")
            except Exception:
                continue
            if (link_host and link_host != home_host
                    and link_host.endswith("." + home_host)
                    and re.match(r"^(shop|menu|store|order|cart|buy)\.", link_host)):
                return True
    return False


# Sitemap discovery — common paths
SITEMAP_PATHS = [
    "/sitemap.xml",
    "/sitemap_index.xml",
    "/sitemap-index.xml",
    "/wp-sitemap.xml",
]

# A URL is "clean" if it has no query string and segments are slug-like
CLEAN_URL_SEGMENT = re.compile(r"^[a-z0-9][a-z0-9\-]*$")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class Check:
    """One scored check."""
    key: str
    label: str
    passed: bool
    points_earned: float
    points_possible: float
    detail: str = ""

    def __str__(self):
        mark = "PASS" if self.passed else "FAIL"
        return f"  [{mark}] {self.label} ({self.points_earned:.1f}/{self.points_possible:.0f}) — {self.detail}"


@dataclass
class Category:
    """One category in the rubric."""
    key: str
    label: str
    weight: float  # 0..1, all categories sum to 1
    checks: list[Check] = field(default_factory=list)

    @property
    def points_earned(self) -> float:
        return sum(c.points_earned for c in self.checks)

    @property
    def points_possible(self) -> float:
        return sum(c.points_possible for c in self.checks)

    @property
    def percent(self) -> float:
        if not self.points_possible:
            return 0.0
        return 100.0 * self.points_earned / self.points_possible

    @property
    def letter(self) -> str:
        return percent_to_letter(self.percent)


@dataclass
class Report:
    url: str
    scanned_at: str
    categories: list[Category]
    detected: dict[str, bool]
    notes: list[str] = field(default_factory=list)

    @property
    def overall_percent(self) -> float:
        return sum(c.percent * c.weight for c in self.categories)

    @property
    def overall_letter(self) -> str:
        return percent_to_letter(self.overall_percent)


def percent_to_letter(p: float) -> str:
    if p >= 90: return "A"
    if p >= 80: return "B"
    if p >= 70: return "C"
    if p >= 60: return "D"
    return "F"


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Safari/605.1.15"
)

# ---------------------------------------------------------------------------
# Age gate bypass — every cannabis site has one. Most use cookie-based gates
# that just check for a specific cookie name. We send a cocktail of common
# variants on every request so the server returns the actual content
# (e.g. the Dutchie iframe behind a WordPress age gate plugin) rather than
# the "Are you 19+?" interstitial.
#
# This is a public scanner doing a non-purchase audit of public content.
# Real users still see the age gate.
# ---------------------------------------------------------------------------
AGE_GATE_COOKIES = {
    # WordPress age gate plugin (Hunny Pot and many others) — verified working
    "age_gate": "19",
    "age_verified": "true",
    "age_verified_19": "yes",
    "wpAgeGate": "passed",
    "wp_age_gate": "passed",
    "wp_age_verified": "true",
    # Cova age gate (Stok'd, Lake City — these are modal-only so content is
    # already in HTML, but include for completeness)
    "cova_age_gate": "true",
    "cova-age-gate": "passed",
    # Generic patterns
    "over_19": "true",
    "over_21": "true",
    "is_of_legal_age": "true",
    "is_adult": "true",
    "adult_verified": "true",
    "ageverification": "true",
    "ageVerified": "yes",
    # Dutchie's own checkout flow (in case Dutchie embeds a second-stage gate)
    "dutchie_age_verified": "true",
}


def fetch(url: str, timeout: float = 20.0) -> requests.Response | None:
    """Fetch a URL, return None on any failure.

    Sends a comprehensive cocktail of common age-gate cookies so cannabis
    sites return the actual content (menu, iframe, etc.) instead of the
    age-verification interstitial.
    """
    try:
        r = requests.get(
            url,
            headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"},
            cookies=AGE_GATE_COOKIES,
            timeout=timeout,
            allow_redirects=True,
        )
        return r
    except requests.RequestException:
        return None


def detect(html: str, key: str) -> bool:
    """Returns True if any signature pattern for `key` matches the html."""
    patterns = SIGS.get(key, [])
    return any(re.search(p, html, re.IGNORECASE) for p in patterns)


def find_first(html: str, key: str) -> str | None:
    """Return first regex match for `key` (for excerpting in reports)."""
    for p in SIGS.get(key, []):
        m = re.search(p, html, re.IGNORECASE)
        if m:
            return m.group(0)
    return None


def extract_ids(html: str) -> dict[str, list[str]]:
    """Pull GA4, UA, GTM, and Pinterest verification IDs out of the html."""
    return {
        "ga4": sorted(set(re.findall(r"G-[A-Z0-9]{6,}", html))),
        "ua": sorted(set(re.findall(r"UA-\d{4,}-\d{1,}", html))),
        "gtm": sorted(set(re.findall(r"GTM-[A-Z0-9]+", html))),
    }


# ---------------------------------------------------------------------------
# Sitemap / product URL discovery
# ---------------------------------------------------------------------------

def find_sitemap(base: str) -> tuple[str | None, str | None]:
    """
    Try common sitemap paths plus robots.txt sitemap declaration.
    Returns (sitemap_url, sitemap_xml_text) or (None, None).
    """
    # First, check robots.txt for explicit sitemap declaration
    r = fetch(urljoin(base, "/robots.txt"))
    robots = r.text if r and r.ok else ""
    for line in robots.splitlines():
        line = line.strip()
        if line.lower().startswith("sitemap:"):
            sm_url = line.split(":", 1)[1].strip()
            r2 = fetch(sm_url)
            if r2 and r2.ok:
                return sm_url, r2.text

    # Fall back to common paths
    for path in SITEMAP_PATHS:
        url = urljoin(base, path)
        r = fetch(url)
        if r and r.ok and "<" in r.text:
            return url, r.text
    return None, None


def collect_product_urls(sitemap_xml: str, base: str, max_urls: int = 20) -> list[str]:
    """
    Walk a sitemap or sitemap index, collect URLs that look like product pages.
    Handles both flat sitemaps and sitemap-of-sitemaps.
    """
    soup = BeautifulSoup(sitemap_xml, "xml")

    # If it's a sitemap index, fetch child sitemaps that look product-related.
    # Each <sitemap> entry holds a <loc> and usually a <lastmod> — only the
    # <loc> is the URL. (Grabbing .text off the whole <sitemap> element glues
    # the lastmod timestamp onto the URL, and every real-world Yoast/Rank Math
    # index includes lastmod, so that produced zero product URLs in the wild.)
    child_sitemaps: list[str] = []
    for s in soup.find_all("sitemap"):
        loc = s.find("loc")
        if loc and loc.text.strip():
            child_sitemaps.append(loc.text.strip())
    if child_sitemaps:
        # Fetch product/shop child sitemaps first so WooCommerce's
        # product-sitemapN.xml wins over post-/page-sitemaps.
        child_sitemaps.sort(
            key=lambda u: 0 if ("product" in u.lower() or "shop" in u.lower()) else 1
        )
        urls: list[str] = []
        for sm in child_sitemaps[:5]:  # cap to first 5 child sitemaps
            r = fetch(sm)
            if r and r.ok:
                urls.extend(_extract_loc(r.text))
            if len(urls) >= max_urls:
                break
        return urls[:max_urls]

    return _extract_loc(sitemap_xml)[:max_urls]


def _extract_loc(xml: str) -> list[str]:
    """Pull <loc>…</loc> values from a sitemap, prioritizing product-like URLs."""
    soup = BeautifulSoup(xml, "xml")
    locs = [u.text.strip() for u in soup.find_all("loc")]
    product_like = [u for u in locs if re.search(r"/(products?|shop|p)/[^/]+/?$", u)]
    return product_like if product_like else locs


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def score_seo(soup: BeautifulSoup, html: str, robots_ok: bool,
              sitemap_ok: bool, product_html: str | None) -> Category:
    """SEO Fundamentals (weight 20%)."""
    cat = Category("seo", "SEO Fundamentals", weight=0.20)

    # Title
    title = (soup.title.string or "").strip() if soup.title else ""
    ok = bool(title) and 25 <= len(title) <= 70
    cat.checks.append(Check(
        "title", "Title tag (25–70 chars)", ok,
        points_earned=3 if ok else (1.5 if title else 0),
        points_possible=3,
        detail=f'"{title}" ({len(title)} chars)' if title else "missing"
    ))

    # Meta description
    desc_tag = soup.find("meta", attrs={"name": "description"})
    desc = (desc_tag.get("content") or "").strip() if desc_tag else ""
    ok = bool(desc) and 70 <= len(desc) <= 165
    cat.checks.append(Check(
        "meta_description", "Meta description (70–165 chars)", ok,
        points_earned=3 if ok else (1.5 if desc else 0),
        points_possible=3,
        detail=f"{len(desc)} chars" if desc else "missing"
    ))

    # Canonical
    canon = soup.find("link", rel="canonical")
    ok = bool(canon and canon.get("href"))
    cat.checks.append(Check(
        "canonical", "Canonical URL", ok,
        2 if ok else 0, 2,
        canon.get("href", "") if ok else "missing"
    ))

    # Open Graph
    og_required = ["og:title", "og:description", "og:image"]
    og_found = [p for p in og_required
                if soup.find("meta", attrs={"property": p}) is not None]
    cat.checks.append(Check(
        "open_graph", "Open Graph (title/description/image)",
        len(og_found) == 3,
        len(og_found),  # 1 point per tag
        3,
        f"{len(og_found)}/3 tags found: {', '.join(og_found) or 'none'}"
    ))

    # Twitter Card
    tw = soup.find("meta", attrs={"name": "twitter:card"})
    cat.checks.append(Check(
        "twitter_card", "Twitter Card", bool(tw),
        1 if tw else 0, 1,
        tw.get("content", "") if tw else "missing"
    ))

    # Structured data (look on product page if available, else homepage)
    target_html = product_html or html
    has_product_schema = bool(
        re.search(r'"@type"\s*:\s*"Product"', target_html)
    )
    cat.checks.append(Check(
        "product_schema", "Product structured data (Schema.org)",
        has_product_schema,
        6 if has_product_schema else 0, 6,
        "found" if has_product_schema else "no Product schema on sampled page"
    ))

    # robots.txt
    cat.checks.append(Check(
        "robots_txt", "robots.txt accessible", robots_ok,
        2 if robots_ok else 0, 2,
        "found" if robots_ok else "not found or 404"
    ))

    # sitemap.xml
    cat.checks.append(Check(
        "sitemap_xml", "sitemap.xml accessible", sitemap_ok,
        3 if sitemap_ok else 0, 3,
        "found" if sitemap_ok else "not found"
    ))

    # Viewport (mobile-friendly indicator)
    vp = soup.find("meta", attrs={"name": "viewport"})
    cat.checks.append(Check(
        "viewport", "Viewport meta (mobile)", bool(vp),
        2 if vp else 0, 2,
        "set" if vp else "missing"
    ))

    return cat


def classify_ecom_platform(html: str, soup, product_urls: list) -> tuple:
    """Classify the e-commerce surface into a tier with explanation.
    Returns (tier, base_points, platform_label, detail).
    Tiers: S=top, A=custom-but-good, B=proxy-redirect, C=iframe/SPA, F=none.
    Base points out of 25."""
    # First check: iframe-embedded cannabis platform — lowest tier
    iframe_platform = detect_iframe_platform(html, soup)
    if iframe_platform:
        label_map = {
            "dutchie": "Dutchie (iframe)",
            "iheartjane": "Jane (iframe)",
            "buddi": "Buddi (iframe)",
            "blaze_ecom": "Blaze Ecom (iframe)",
            "dispense": "Dispense (iframe)",
        }
        return ("C", 5, label_map[iframe_platform],
                "Iframe-embedded ecom is largely invisible to crawlers. "
                "Product pages don't get indexed; you can't rank for "
                "specific products or strains on Google.")

    # Second: known proxy / redirect cannabis platforms (script-detected, not iframed)
    if detect(html, "cova_pos"):
        # Real Cova-hosted shop (covasoftware.com / covasoft.com). This is
        # a client-rendered SPA hosted by Cova. Better than an iframe (the
        # shop is on its own URL, not embedded inside another page) but
        # still client-rendered and usually on a subdomain.
        return ("B", 14, "Cova-hosted shop",
                "Cova-hosted e-commerce. The shop is a Cova-rendered SPA "
                "(often on a shop.* subdomain). Better than an iframe but "
                "client-rendered, so product pages are less indexable than "
                "a true on-domain WooCommerce/Shopify setup.")
    if detect(html, "blaze_ecom"):
        return ("B", 15, "Blaze Ecom",
                "Proxy/redirect cannabis ecom. Some indexability but "
                "product URLs and structure are usually compromised.")
    if detect(html, "dispense"):
        return ("B", 15, "Dispense (AIQ)",
                "Proxy/redirect cannabis ecom. Better than iframe but "
                "not 'true' on-domain ecommerce.")
    if detect(html, "tymber"):
        return ("B", 14, "Tymber",
                "Cannabis ecom platform. Indexability varies by setup.")
    if detect(html, "greenline_pos"):
        return ("B", 14, "Greenline ecom",
                "Cannabis ecom platform.")

    # Third: top-tier — on-domain, indexable, dedicated product pages
    if detect(html, "woocommerce"):
        return ("S", 25, "WooCommerce",
                "Top-tier: same-domain product pages, full SEO benefit.")
    if detect(html, "shopify"):
        return ("S", 25, "Shopify",
                "Top-tier: same-domain product pages, full SEO benefit.")
    if detect(html, "bigcommerce"):
        return ("S", 24, "BigCommerce", "Top-tier on-domain ecom.")
    if detect(html, "magento"):
        return ("S", 23, "Magento / Adobe Commerce", "Top-tier on-domain ecom.")

    # Hifyre (FIKA family): custom cannabis platform with same-domain,
    # server-rendered /products/<slug> pages + products sitemap (verified
    # on chrontact.ca: SSR product titles, 3,400+ URL product sitemap).
    if detect(html, "hifyre"):
        if product_urls:
            return ("A", 22, "Hifyre (FIKA)",
                    "Hifyre retail platform: same-domain, server-rendered "
                    "product pages with a products sitemap. Near top-tier "
                    "indexability for a custom platform.")
        return ("B", 14, "Hifyre (FIKA) — no product sitemap found",
                "Hifyre retail platform detected, but no product URLs were "
                "discovered via the sitemap. Manual review recommended.")

    # Fourth: custom built — Next.js / Nuxt / Gatsby. SSR is key.
    has_nextjs = detect(html, "nextjs")
    has_nuxt = detect(html, "nuxt")
    has_gatsby = detect(html, "gatsby")
    has_react_csr = detect(html, "react_csr")

    if has_nextjs or has_nuxt or has_gatsby:
        # Has SSR framework. Verify it's actually rendering content
        # server-side by checking for product URLs in the sitemap.
        ssr_works = bool(product_urls)
        if ssr_works:
            framework = ("Next.js" if has_nextjs
                         else "Nuxt" if has_nuxt else "Gatsby")
            return ("A", 22, f"Custom ({framework} SSR)",
                    "Custom-built ecom with SSR framework. Indexable if "
                    "the SEO basics are flushed out.")
        else:
            framework = ("Next.js" if has_nextjs
                         else "Nuxt" if has_nuxt else "Gatsby")
            return ("C", 8, f"Custom ({framework} — no sitemap)",
                    "Custom framework detected but no product pages found "
                    "in sitemap. Likely client-rendered without SEO setup.")

    # Pure client-side React (empty root div, no SSR signals)
    if has_react_csr and not product_urls:
        return ("C", 5, "Custom (client-rendered React)",
                "Pure client-rendered React with no SSR or sitemap. "
                "Effectively invisible to crawlers.")

    # Couldn't identify a platform but products exist in sitemap → mid-tier
    if product_urls:
        return ("B", 16, "Unknown platform (products indexable)",
                f"{len(product_urls)} product URLs in sitemap but couldn't "
                "identify the platform. Manual review recommended.")

    return ("F", 0, "No e-commerce detected",
            "No e-commerce platform identified and no product URLs in sitemap.")


def score_ecommerce(homepage_url: str, html: str, soup,
                    product_urls: list, product_html: str | None) -> Category:
    """E-commerce & Platform (weight 17%). Combines structural checks with
    platform-tier classification and cannabis-specific bonuses."""
    cat = Category("ecommerce", "E-commerce & Platform", weight=0.17)

    # ---- Platform tier (max 25 pts) ----
    tier, tier_pts, platform_label, tier_detail = classify_ecom_platform(
        html, soup, product_urls)

    # Subdomain penalty (also checks homepage links for shop.* subdomains)
    sub_shop = detect_shop_subdomain(homepage_url, product_urls, soup)
    if sub_shop and tier in ("S", "A", "B"):
        tier_pts = max(0, tier_pts - 5)
        tier_detail += (" SUBDOMAIN PENALTY: shop is on a different "
                        "host than the main site (e.g. shop.example.com), "
                        "which splits SEO authority. −5 points.")

    cat.checks.append(Check(
        "platform_tier", f"E-commerce platform tier ({tier}): {platform_label}",
        tier in ("S", "A"),
        tier_pts, 25, tier_detail
    ))

    # ---- Terpene taxonomy bonus (max 3 pts) ----
    combined = html + ("\n" + product_html if product_html else "")
    has_terp, terps = detect_terpene_taxonomy(combined)
    cat.checks.append(Check(
        "terpene_taxonomy", "Searchable terpene taxonomy",
        has_terp, 3 if has_terp else 0, 3,
        (f"detected {len(terps)} terpenes: {', '.join(terps[:6])}"
         + (f", +{len(terps)-6} more" if len(terps) > 6 else "")
         + " — strong differentiation signal")
        if has_terp else
        "no terpene names detected — competitors with terpene filters/"
        "facets have a significant SEO + UX edge"
    ))

    # ---- Minor cannabinoid taxonomy bonus (max 2 pts) ----
    has_minor, minors = detect_minor_cannabinoids(combined)
    cat.checks.append(Check(
        "minor_cannabinoids", "Minor cannabinoid mentions/filters",
        has_minor, 2 if has_minor else 0, 2,
        f"found: {', '.join(minors)}" if has_minor
        else "no minor cannabinoid mentions (CBN, CBG, CBC, etc.)"
    ))

    # ---- Individual product pages discoverable (max 5 pts) ----
    n_products = len(product_urls)
    has_products = n_products > 0
    cat.checks.append(Check(
        "product_pages", "Individual product pages discoverable",
        has_products,
        5 if has_products else 0, 5,
        f"{n_products} product URLs found in sitemap" if has_products
        else "no product URLs discovered"
    ))

    # ---- Clean URLs (max 3 pts) ----
    if product_urls:
        clean_count = 0
        for u in product_urls:
            parsed = urlparse(u)
            if parsed.query:
                continue
            segments = [s for s in parsed.path.split("/") if s]
            if segments and all(CLEAN_URL_SEGMENT.match(s) for s in segments):
                clean_count += 1
        clean_pct = clean_count / len(product_urls)
        ok = clean_pct >= 0.8
        cat.checks.append(Check(
            "clean_urls", "Clean URLs on product pages", ok,
            3 if ok else (1.5 if clean_pct >= 0.5 else 0), 3,
            f"{clean_count}/{len(product_urls)} URLs ({clean_pct:.0%}) are clean"
        ))
    else:
        cat.checks.append(Check(
            "clean_urls", "Clean URLs on product pages", False,
            0, 3, "no product URLs to evaluate"
        ))

    # ---- HTTPS (max 2 pts) ----
    https = homepage_url.startswith("https://")
    cat.checks.append(Check(
        "https", "Served over HTTPS", https,
        2 if https else 0, 2,
        "yes" if https else "no — major security/SEO issue"
    ))

    return cat


def score_analytics(html: str, ids: dict[str, list[str]]) -> Category:
    """Analytics & Tracking (weight 15%)."""
    cat = Category("analytics", "Analytics & Tracking", weight=0.15)

    # GA4
    has_ga4 = detect(html, "ga4")
    cat.checks.append(Check(
        "ga4", "Google Analytics 4", has_ga4,
        5 if has_ga4 else 0, 5,
        f"GA4 properties: {', '.join(ids['ga4'])}" if ids["ga4"]
        else "not detected"
    ))

    # GTM
    has_gtm = detect(html, "gtm")
    cat.checks.append(Check(
        "gtm", "Google Tag Manager", has_gtm,
        3 if has_gtm else 0, 3,
        f"GTM containers: {', '.join(ids['gtm'])}" if ids["gtm"]
        else "not detected"
    ))

    # GSC verification — site-verification meta tag OR Site Kit by Google
    has_gsc_meta = bool(re.search(
        r'meta\s+[^>]*name=["\']google-site-verification["\']',
        html, re.IGNORECASE))
    has_site_kit = detect(html, "site_kit")
    has_gsc = has_gsc_meta or has_site_kit
    detail = []
    if has_gsc_meta:
        detail.append("google-site-verification meta tag present")
    if has_site_kit:
        detail.append("Site Kit by Google detected (implies GSC connection)")
    cat.checks.append(Check(
        "gsc", "Google Search Console connection", has_gsc,
        3 if has_gsc else 0, 3,
        "; ".join(detail) if detail
        else "no GSC meta tag or Site Kit (could still be verified via DNS/file)"
    ))

    # Meta Pixel
    has_meta = detect(html, "meta_pixel")
    cat.checks.append(Check(
        "meta_pixel", "Meta (Facebook) Pixel", has_meta,
        2 if has_meta else 0, 2,
        "loaded" if has_meta else "not detected"
    ))

    # TikTok Pixel
    has_tt = detect(html, "tiktok_pixel")
    cat.checks.append(Check(
        "tiktok_pixel", "TikTok Pixel", has_tt,
        2 if has_tt else 0, 2,
        "loaded" if has_tt else "not detected"
    ))

    return cat


def score_email(html: str, soup: BeautifulSoup) -> Category:
    """Email Marketing (weight 25% — heaviest, per CMO priorities)."""
    cat = Category("email", "Email Marketing", weight=0.25)

    # Newsletter form present?
    has_form = bool(soup.find("form", action=re.compile(
        r"(newsletter|subscribe|mailchimp|list-manage|klaviyo|/forms)",
        re.IGNORECASE))) or detect(html, "klaviyo_form")

    cat.checks.append(Check(
        "newsletter_form", "Newsletter capture form present", has_form,
        5 if has_form else 0, 5,
        "form found" if has_form else "no obvious signup form on homepage"
    ))

    # ESP detection — pick best one detected
    klaviyo = detect(html, "klaviyo")
    omnisend = detect(html, "omnisend")
    activecampaign = detect(html, "activecampaign")
    mailchimp = detect(html, "mailchimp")

    # Tiered scoring: 20 max for Klaviyo, decreasing for others
    if klaviyo:
        esp_pts = 20
        esp_label = "Klaviyo (best-in-class)"
    elif omnisend:
        esp_pts = 15
        esp_label = "Omnisend"
    elif activecampaign:
        esp_pts = 12
        esp_label = "ActiveCampaign"
    elif mailchimp:
        esp_pts = 10
        esp_label = "Mailchimp"
    else:
        esp_pts = 0
        esp_label = "none detected — likely missing major retention revenue"

    cat.checks.append(Check(
        "esp", "Email service provider quality",
        esp_pts > 0,
        esp_pts, 20,
        esp_label
    ))

    # Flag conflicts (e.g. both Klaviyo AND Mailchimp loaded — common indicator
    # of a half-migrated stack)
    if klaviyo and mailchimp:
        cat.checks.append(Check(
            "esp_conflict", "ESP stack hygiene", False,
            0, 0,  # informational only, no points
            "Klaviyo AND Mailchimp both detected — consolidate to avoid duplicate sends/leaks"
        ))

    return cat


def score_loyalty(html: str, soup: BeautifulSoup) -> Category:
    """Loyalty Program (weight 15%)."""
    cat = Category("loyalty", "Loyalty Program", weight=0.15)

    aiq_active = detect(html, "alpineiq_active")
    aiq_bundled = detect(html, "alpineiq_bundled")
    springbig = detect(html, "springbig")
    spark = detect(html, "spark_rewards")
    sticky = detect(html, "sticky_cards")
    smile = detect(html, "smile_io")
    yotpo_loy = detect(html, "yotpo_loyalty")

    # Branded loyalty page link (catches custom programs)
    branded_loyalty = bool(soup.find("a", href=re.compile(
        r"(loyalty|rewards|membership|points)", re.IGNORECASE)))

    if aiq_active:
        pts, label = 15, "AlpineIQ actively loaded"
    elif springbig:
        pts, label = 12, "Springbig"
    elif spark:
        pts, label = 12, "Spark Rewards (FIKA/Hifyre first-party loyalty)"
    elif sticky:
        pts, label = 10, "Sticky Cards"
    elif smile:
        pts, label = 9, "Smile.io"
    elif yotpo_loy:
        pts, label = 9, "Yotpo Loyalty"
    elif aiq_bundled:
        pts, label = 3, "AlpineIQ integration available (Breadstack) but not actively configured"
    elif branded_loyalty:
        pts, label = 5, "Custom/branded loyalty page found — platform unknown"
    else:
        pts, label = 0, "no loyalty platform detected"

    cat.checks.append(Check(
        "loyalty_platform", "Loyalty platform", pts > 0,
        pts, 15, label
    ))

    return cat


def score_retention(html: str) -> Category:
    """Retention & Reviews (weight 15%)."""
    cat = Category("retention", "Retention & Reviews", weight=0.15)

    # Abandoned cart / post-purchase capability
    has_automatewoo = detect(html, "automatewoo")
    has_klaviyo = detect(html, "klaviyo")

    if has_automatewoo and has_klaviyo:
        cap_pts = 5
        cap_label = "AutomateWoo + Klaviyo — strong abandoned cart / post-purchase capability"
    elif has_automatewoo:
        cap_pts = 4
        cap_label = "AutomateWoo detected — abandoned cart + follow-ups possible"
    elif has_klaviyo:
        cap_pts = 3
        cap_label = "Klaviyo detected — flows available (verify they're enabled)"
    else:
        cap_pts = 0
        cap_label = "no automation platform detected for abandoned cart / post-purchase"

    cat.checks.append(Check(
        "automation_capability", "Abandoned cart / post-purchase capability",
        cap_pts > 0, cap_pts, 5, cap_label
    ))

    # Review collection platforms
    yotpo = detect(html, "yotpo_reviews")
    stamped = detect(html, "stamped")
    junip = detect(html, "junip")
    okendo = detect(html, "okendo")
    judgeme = detect(html, "judgeme")
    review_platform = next(
        (n for n, v in [("Yotpo", yotpo), ("Stamped", stamped),
                        ("Junip", junip), ("Okendo", okendo),
                        ("Judge.me", judgeme)] if v), None)

    cat.checks.append(Check(
        "review_platform", "Dedicated review platform",
        bool(review_platform),
        5 if review_platform else 0, 5,
        f"{review_platform} detected" if review_platform
        else "no dedicated review platform — likely missing post-purchase review requests"
    ))

    # Google Reviews widget (proxy: at least pulling in social proof)
    gr = detect(html, "google_reviews_widget")
    cat.checks.append(Check(
        "google_reviews", "Google Reviews social proof on site", gr,
        2 if gr else 0, 2,
        "Google Reviews widget embedded" if gr else "no Google Reviews widget"
    ))

    # WooCommerce native reviews (basic, lower-value)
    has_woo_reviews = "wc-reviews" in html or "comment_form" in html
    if not review_platform and has_woo_reviews:
        cat.checks.append(Check(
            "woo_reviews", "WooCommerce native reviews fallback",
            True, 1.5, 3,
            "native WC reviews present (low engagement vs Yotpo/Stamped/etc.)"
        ))
    else:
        cat.checks.append(Check(
            "woo_reviews", "WooCommerce native reviews fallback",
            has_woo_reviews,
            0 if review_platform else (1.5 if has_woo_reviews else 0),
            3,
            "covered by dedicated platform" if review_platform
            else ("present" if has_woo_reviews else "absent")
        ))

    return cat


def score_gbp(gbp: GBPData, html: str, soup, homepage_url: str,
              api_key_present: bool) -> Category:
    """Local Search & Google Business Profile (weight 20%).

    Without an API key we score only what's visible on the website itself
    (embedded GBP widget, Maps embed, location count). With the key, we
    score the full GBP completeness signals.
    """
    cat = Category("gbp", "Local Search & Google Business Profile", weight=0.20)

    # Always-on checks (work without API key)
    has_maps_embed = detect(html, "google_maps_embed")
    has_reviews_widget = detect(html, "google_reviews_widget")
    has_gbp_link = detect(html, "google_business_link")

    cat.checks.append(Check(
        "social_proof_on_site", "Google reviews / Maps embedded on website",
        has_reviews_widget or has_maps_embed or has_gbp_link,
        5 if (has_reviews_widget or has_maps_embed) else (3 if has_gbp_link else 0),
        5,
        "Google Reviews widget" if has_reviews_widget
        else ("Maps embed" if has_maps_embed
              else ("g.page / maps.app.goo.gl link" if has_gbp_link
                    else "no Google content embedded — missing easy social proof"))
    ))

    # Multi-store presence: count location links on the homepage.
    # Patterns we look for: standard (/locations/, /stores/, /find-us/)
    # plus city-slug-based variants (/burlington-cannabis-menu/,
    # /toronto-dispensary/, etc.) which dispensary multisite networks often use.
    locations = []
    multi_store_re = re.compile(
        r"/(locations?|stores?|find-us|find-a-store)/"
        r"|/[a-z][a-z0-9\-]+-(cannabis-menu|cannabis-store|dispensary)/?$",
        re.IGNORECASE
    )
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if multi_store_re.search(href):
            locations.append(href.lower())
    location_count = len(set(locations))  # unique
    has_multi_store = location_count >= 2

    if has_multi_store:
        cat.checks.append(Check(
            "multi_store_pages", "Per-store landing pages present on site",
            True, 5, 5,
            f"{location_count} unique location links found on homepage"
        ))
    else:
        cat.checks.append(Check(
            "multi_store_pages", "Per-store landing pages present on site",
            False, 0, 5,
            "single-location site, or no per-store landing pages detected"
        ))

    # ---- GBP-dependent checks (need API key) ----

    if not api_key_present:
        cat.checks.append(Check(
            "gbp_api_status", "Google Business Profile data",
            False, 0, 0,
            "Skipped — no GOOGLE_PLACES_API_KEY configured. Add one to "
            "enable photo count, rating, review activity, and website-link "
            "attribution checks."
        ))
        return cat

    if not gbp.found:
        cat.checks.append(Check(
            "gbp_found", "Business found on Google Maps", False, 0, 15,
            "Places API returned no match — business may not be on Google "
            "Maps, or the business name on the site doesn't match"
        ))
        return cat

    cat.checks.append(Check(
        "gbp_found", "Business found on Google Maps", True, 15, 15,
        f"{gbp.display_name} — {gbp.address}"
    ))

    # Completeness
    completeness_pts = 0
    have = []
    miss = []
    if gbp.phone:
        completeness_pts += 10; have.append("phone")
    else:
        miss.append("phone")
    if gbp.address:
        completeness_pts += 10; have.append("address")
    else:
        miss.append("address")
    if gbp.website_uri:
        completeness_pts += 10; have.append("website")
    else:
        miss.append("website")
    if gbp.has_opening_hours:
        completeness_pts += 5; have.append("hours")
    else:
        miss.append("hours")

    cat.checks.append(Check(
        "gbp_completeness", "GBP profile completeness (phone/address/website/hours)",
        completeness_pts == 35,
        completeness_pts, 35,
        ("complete" if not miss else
         f"present: {', '.join(have) or 'none'}; missing: {', '.join(miss)}")
    ))

    # Photos
    enough_photos = gbp.photo_count >= 10
    some_photos = gbp.photo_count >= 1
    cat.checks.append(Check(
        "gbp_photos", "GBP has photos (≥10)",
        enough_photos,
        10 if enough_photos else (5 if some_photos else 0),
        10,
        f"{gbp.photo_count} photos returned"
        + (" (Places API caps at 10 — actual count may be higher)"
           if gbp.photo_count == 10 else "")
    ))

    # Rating and volume
    good_rating = bool(gbp.rating and gbp.rating >= 4.0
                       and gbp.user_rating_count and gbp.user_rating_count >= 25)
    has_any_rating = bool(gbp.rating and gbp.user_rating_count
                          and gbp.user_rating_count >= 1)
    cat.checks.append(Check(
        "gbp_rating", "Rating ≥4.0 with ≥25 reviews",
        good_rating,
        10 if good_rating else (5 if has_any_rating else 0),
        10,
        (f"{gbp.rating}/5 over {gbp.user_rating_count} reviews"
         if has_any_rating else "no reviews returned by Places API")
    ))

    # Recent review activity
    cat.checks.append(Check(
        "gbp_recent_review", "Recent review activity (within ~90 days)",
        gbp.has_recent_review,
        5 if gbp.has_recent_review else 0, 5,
        "active review stream" if gbp.has_recent_review
        else "no review in the last quarter — may indicate quiet/stagnant listing"
    ))

    # Owner reply rate — Places API New does NOT reliably expose owner
    # replies. Note this in the report rather than score it.
    cat.checks.append(Check(
        "gbp_owner_replies", "Owner replies to reviews",
        False, 0, 0,
        "Cannot detect reliably via Places API. "
        "Check manually: log into your GBP and aim for ≥50% reply rate "
        "on recent reviews."
    ))

    # Website link matches scanned domain
    scan_host = urlparse(homepage_url).netloc.lower().replace("www.", "")
    gbp_host = ""
    if gbp.website_uri:
        gbp_host = urlparse(gbp.website_uri).netloc.lower().replace("www.", "")
    domain_match = gbp_host == scan_host
    is_https = bool(gbp.website_uri and gbp.website_uri.startswith("https://"))
    cat.checks.append(Check(
        "gbp_website_match", "GBP website link is HTTPS + matches scanned domain",
        domain_match and is_https,
        5 if (domain_match and is_https) else (3 if domain_match else 0),
        5,
        (f"matches ({gbp.website_uri})" if domain_match and is_https
         else f"present: {gbp.website_uri or 'no website link'}")
    ))

    # UTM parameters on GBP website link
    has_utm = bool(gbp.website_uri and
                   ("utm_source=" in gbp.website_uri.lower()
                    or "utm_medium=" in gbp.website_uri.lower()))
    cat.checks.append(Check(
        "gbp_website_utm", "UTM parameters on GBP website link",
        has_utm,
        5 if has_utm else 0, 5,
        "UTM tracking present (attribution traceable)" if has_utm
        else "no UTM params — GBP traffic shows as 'direct' or 'organic' in GA. "
             "Suggest tagging the GBP website link with "
             "?utm_source=google&utm_medium=organic&utm_campaign=gbp"
    ))

    # Multi-store deep link check: if site is multi-store but GBP website
    # points to homepage rather than a specific store page, flag it
    if has_multi_store and gbp.website_uri:
        path = urlparse(gbp.website_uri).path.strip("/")
        points_to_homepage = path in ("", "index.html", "home")
        if points_to_homepage:
            cat.checks.append(Check(
                "gbp_deep_link", "Multi-store GBP deep links to specific store",
                False, 0, 5,
                "GBP website link points to homepage. For multi-store brands, "
                "each store's GBP should link to its own store page."
            ))
        else:
            cat.checks.append(Check(
                "gbp_deep_link", "Multi-store GBP deep links to specific store",
                True, 5, 5,
                f"GBP links to /{path} — appears to be a store-specific page"
            ))

    # Business status
    if gbp.business_status and gbp.business_status != "OPERATIONAL":
        cat.checks.append(Check(
            "gbp_status", "GBP business status", False, 0, 0,
            f"Status is {gbp.business_status} — fix in GBP immediately"
        ))

    return cat


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------

class ScanError(Exception):
    """Raised when a scan cannot complete (network failure, blocked, etc.)."""
    pass


# ---------------------------------------------------------------------------
# Google Business Profile lookup via Places API New
# ---------------------------------------------------------------------------

@dataclass
class GBPData:
    """Parsed Google Business Profile data. None fields = not available."""
    found: bool = False
    place_id: str | None = None
    display_name: str | None = None
    address: str | None = None
    phone: str | None = None
    website_uri: str | None = None
    google_maps_uri: str | None = None
    rating: float | None = None
    user_rating_count: int | None = None
    photo_count: int = 0
    has_opening_hours: bool = False
    has_recent_review: bool = False  # any review in last 90 days
    owner_reply_rate: float | None = None  # 0..1, None if reviews not available
    review_count_sampled: int = 0  # how many reviews we sampled to compute reply rate
    business_status: str | None = None  # OPERATIONAL, CLOSED_TEMPORARILY, etc.


def _extract_business_name(soup) -> str | None:
    """Pull a probable business name from og:site_name, then page title."""
    og = soup.find("meta", attrs={"property": "og:site_name"})
    if og and og.get("content"):
        return og["content"].strip()
    if soup.title and soup.title.string:
        t = soup.title.string.strip()
        # Heuristic: "Page | Brand Name" → take the part after | or –
        for sep in [" | ", " - ", " – "]:
            if sep in t:
                return t.split(sep)[-1].strip()
        return t
    return None


PLACES_API_ENDPOINT = "https://places.googleapis.com/v1/places:searchText"
PLACES_FIELD_MASK = (
    "places.id,places.displayName,places.formattedAddress,"
    "places.nationalPhoneNumber,places.internationalPhoneNumber,"
    "places.websiteUri,places.googleMapsUri,places.rating,"
    "places.userRatingCount,places.businessStatus,"
    "places.regularOpeningHours,places.photos,places.reviews"
)


def fetch_gbp(homepage_url: str, business_name: str | None,
              api_key: str | None) -> GBPData:
    """
    Look up the dispensary's Google Business Profile via Places API New.

    Returns GBPData with found=False if:
    - No API key provided
    - API call fails
    - No matching place found
    - The result's website doesn't match the scanned domain (filter out
      same-name businesses elsewhere)
    """
    if not api_key:
        return GBPData(found=False)
    if not business_name:
        # Fall back to bare hostname
        business_name = urlparse(homepage_url).netloc.replace("www.", "")

    host = urlparse(homepage_url).netloc.lower().replace("www.", "")
    query = f"{business_name} {host}"

    try:
        resp = requests.post(
            PLACES_API_ENDPOINT,
            headers={
                "Content-Type": "application/json",
                "X-Goog-Api-Key": api_key,
                "X-Goog-FieldMask": PLACES_FIELD_MASK,
            },
            json={"textQuery": query, "maxResultCount": 5},
            timeout=8.0,
        )
    except requests.RequestException:
        return GBPData(found=False)

    if not resp.ok:
        return GBPData(found=False)

    data = resp.json() or {}
    places = data.get("places", [])
    if not places:
        return GBPData(found=False)

    # Filter to results whose website matches our domain (if any do)
    matching = [p for p in places
                if p.get("websiteUri") and host in p["websiteUri"].lower()]
    place = matching[0] if matching else places[0]

    photos = place.get("photos", []) or []
    reviews = place.get("reviews", []) or []

    # Owner reply rate — Places API New review objects don't always expose
    # owner replies in the basic field set. When present, replies come back
    # as the review's text reflecting the owner's response. We approximate:
    # if any review has a "googleMapsUri" pointing to a reply, count it.
    # Otherwise we leave owner_reply_rate as None (informational only).
    reply_count = 0
    for r in reviews:
        # Heuristic: the field structure varies; check known indicators
        if r.get("originalText") and r.get("text"):
            # Sometimes translated reply lives in text vs originalText
            if r["originalText"].get("text") != r["text"].get("text"):
                continue  # this is just translation, not reply
        # The actual reply field may be present as "authorAttribution" with
        # a specific owner flag — this varies by API version.
        if r.get("publishTime"):
            pass  # placeholder; reply rate inference is best-effort

    # Recent review check (any review in last 90 days)
    has_recent = False
    for r in reviews:
        rel = (r.get("relativePublishTimeDescription") or "").lower()
        if any(unit in rel for unit in ["hour", "day", "week", "month"]):
            # "a year ago" and longer are excluded
            if "year" not in rel:
                has_recent = True
                break

    return GBPData(
        found=True,
        place_id=place.get("id"),
        display_name=(place.get("displayName") or {}).get("text"),
        address=place.get("formattedAddress"),
        phone=(place.get("nationalPhoneNumber")
               or place.get("internationalPhoneNumber")),
        website_uri=place.get("websiteUri"),
        google_maps_uri=place.get("googleMapsUri"),
        rating=place.get("rating"),
        user_rating_count=place.get("userRatingCount"),
        photo_count=len(photos),
        has_opening_hours=bool(place.get("regularOpeningHours")),
        has_recent_review=has_recent,
        owner_reply_rate=None,  # not reliably available via Places API New
        review_count_sampled=len(reviews),
        business_status=place.get("businessStatus"),
    )


def scan(url: str, gbp_api_key: str | None = None) -> Report:
    base = url if url.startswith("http") else f"https://{url}"
    if not base.endswith("/"):
        base += "/"

    # Fetch homepage
    r = fetch(base)
    if not r or not r.ok:
        status = r.status_code if r else "no response"
        raise ScanError(f"Could not fetch homepage: {url} (status={status})")
    homepage_html = r.text
    homepage_url = r.url

    soup = BeautifulSoup(homepage_html, "lxml")

    # Fetch robots.txt
    rb = fetch(urljoin(homepage_url, "/robots.txt"))
    robots_ok = bool(rb and rb.ok and len(rb.text) > 10)

    # Discover sitemap + sample product URLs
    sitemap_url, sitemap_xml = find_sitemap(homepage_url)
    sitemap_ok = sitemap_xml is not None
    product_urls: list[str] = []
    if sitemap_xml:
        product_urls = collect_product_urls(sitemap_xml, homepage_url)

    # Fetch one product page to look for Product schema
    product_html: str | None = None
    if product_urls:
        pr = fetch(product_urls[0])
        if pr and pr.ok:
            product_html = pr.text

    # Hunny Pot-style: marketing homepage + per-store /<city>-cannabis-menu/ pages.
    # Sacred Grass-style: content homepage + shop on a subdomain (shop.example.net).
    # In both cases, the homepage doesn't have the actual e-commerce signal, so
    # we fetch one secondary URL to enrich the detection corpus.
    menu_page_html: str | None = None
    menu_url_pattern = re.compile(
        r"/[a-z][a-z0-9\-]+-(cannabis-menu|cannabis-store|dispensary)/?$",
        re.IGNORECASE
    )
    home_host = urlparse(homepage_url).netloc.lower().replace("www.", "")
    menu_links: list[str] = []
    subdomain_shop_links: list[str] = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        # On-domain menu pattern (Hunny Pot)
        if menu_url_pattern.search(href):
            menu_links.append(href)
            continue
        # Off-domain "shop." subdomain (Sacred Grass)
        try:
            link_host = urlparse(href).netloc.lower().replace("www.", "")
        except Exception:
            continue
        if link_host and link_host != home_host and link_host.endswith("." + home_host):
            # Subdomain of the main site — flag it if it's a shop/menu host
            if re.match(r"^(shop|menu|store|order|cart|buy)\.", link_host):
                subdomain_shop_links.append(href)

    candidates = menu_links + subdomain_shop_links
    if candidates and not product_html:
        first_secondary = candidates[0]
        if first_secondary.startswith("/"):
            first_secondary = urljoin(homepage_url, first_secondary)
        mr = fetch(first_secondary)
        if mr and mr.ok:
            menu_page_html = mr.text

    # Combine all html for detection (homepage + product page + menu page)
    full_html = homepage_html
    if product_html:
        full_html += "\n" + product_html
    if menu_page_html:
        full_html += "\n" + menu_page_html

    # Pull tracking IDs
    ids = extract_ids(full_html)

    # Look up Google Business Profile via Places API (no-op if no key)
    business_name = _extract_business_name(soup)
    gbp = fetch_gbp(homepage_url, business_name, gbp_api_key)

    # Score each category (weights sum to 100%)
    seo_cat = score_seo(soup, full_html, robots_ok, sitemap_ok, product_html)
    seo_cat.weight = 0.18
    ecom_cat = score_ecommerce(homepage_url, full_html, soup,
                               product_urls, product_html)
    ecom_cat.weight = 0.17
    analytics_cat = score_analytics(full_html, ids)
    analytics_cat.weight = 0.10
    email_cat = score_email(full_html, soup)
    email_cat.weight = 0.17
    loyalty_cat = score_loyalty(full_html, soup)
    loyalty_cat.weight = 0.08
    retention_cat = score_retention(full_html)
    retention_cat.weight = 0.10
    gbp_cat = score_gbp(gbp, full_html, soup, homepage_url, bool(gbp_api_key))
    gbp_cat.weight = 0.20

    categories = [seo_cat, ecom_cat, analytics_cat, email_cat,
                  loyalty_cat, retention_cat, gbp_cat]

    # Collect detected platforms for the report summary
    detected = {
        "klaviyo": detect(full_html, "klaviyo"),
        "mailchimp": detect(full_html, "mailchimp"),
        "omnisend": detect(full_html, "omnisend"),
        "alpineiq_active": detect(full_html, "alpineiq_active"),
        "alpineiq_bundled_only": detect(full_html, "alpineiq_bundled") and not detect(full_html, "alpineiq_active"),
        "springbig": detect(full_html, "springbig"),
        "sticky_cards": detect(full_html, "sticky_cards"),
        "yotpo": detect(full_html, "yotpo_reviews"),
        "stamped": detect(full_html, "stamped"),
        "junip": detect(full_html, "junip"),
        "okendo": detect(full_html, "okendo"),
        "automatewoo": detect(full_html, "automatewoo"),
        "ga4": detect(full_html, "ga4"),
        "gtm": detect(full_html, "gtm"),
        "site_kit": detect(full_html, "site_kit"),
        "meta_pixel": detect(full_html, "meta_pixel"),
        "tiktok_pixel": detect(full_html, "tiktok_pixel"),
        "woocommerce": detect(full_html, "woocommerce"),
        "shopify": detect(full_html, "shopify"),
        "dutchie": detect(full_html, "dutchie"),
        "iheartjane": detect(full_html, "iheartjane"),
        "breadstack": detect(full_html, "breadstack"),
        "cova_pos": detect(full_html, "cova_pos"),
        # Greenline POS in headless mode runs server-side; only credits
        # when their frontend menu / CDN domains appear in HTML.
        "greenline_pos": detect(full_html, "greenline_pos"),
        # If Breadstack is in use AND no specific POS frontend is detected,
        # the backend POS choice (Cova / Greenline-headless / Tymber / etc.)
        # is not visible from public HTML.
        "pos_undetermined_breadstack": (
            detect(full_html, "breadstack")
            and not detect(full_html, "cova_pos")
            and not detect(full_html, "greenline_pos")
            and not detect(full_html, "treez")
            and not detect(full_html, "flowhub")
            and not detect(full_html, "korona_pos")
            and not detect(full_html, "leaflogix")
        ),
        "wordpress": detect(full_html, "wordpress"),
        "yoast": detect(full_html, "yoast"),
        "rankmath": detect(full_html, "rankmath"),
        "hotjar": detect(full_html, "hotjar"),
        "heatmap_com": detect(full_html, "heatmap_com"),
        "ahrefs_analytics": detect(full_html, "ahrefs_analytics"),
        "google_reviews_widget": detect(full_html, "google_reviews_widget"),
        "google_maps_embed": detect(full_html, "google_maps_embed"),
        "google_business_link": detect(full_html, "google_business_link"),
        "gbp_lookup_succeeded": gbp.found,
        # New cannabis-specific platforms
        "bigcommerce": detect(full_html, "bigcommerce"),
        "magento": detect(full_html, "magento"),
        "buddi": detect(full_html, "buddi"),
        "blaze_ecom": detect(full_html, "blaze_ecom"),
        "dispense": detect(full_html, "dispense"),
        "tymber": detect(full_html, "tymber"),
        "greenline": detect(full_html, "greenline"),
        "treez_pos": detect(full_html, "treez"),
        "greenbits_pos": detect(full_html, "greenbits"),
        "flowhub_pos": detect(full_html, "flowhub"),
        "korona_pos": detect(full_html, "korona_pos"),
        "leaflogix_pos": detect(full_html, "leaflogix"),
        "nextjs": detect(full_html, "nextjs"),
        "nuxt": detect(full_html, "nuxt"),
        "gatsby": detect(full_html, "gatsby"),
    }

    notes: list[str] = []
    if detected["klaviyo"] and detected["mailchimp"]:
        notes.append(
            "Both Klaviyo and Mailchimp signatures present. This is usually "
            "a half-migrated stack; consolidate to avoid duplicate sends "
            "and split audience attribution."
        )
    if detected["alpineiq_bundled_only"]:
        notes.append(
            "Breadstack ships an AlpineIQ integration that's wired into the "
            "page CSS even when AIQ itself isn't configured. We only credit "
            "AIQ when its CDN scripts are actually loading."
        )
    # Age gate detection — if the scanned page has an age gate, the
    # scanner may not see the actual shop (which loads after the user
    # confirms age). Common dispensary pattern.
    has_age_gate = bool(re.search(
        r"age[-_ ]?gate|over[-_ ]?(?:18|19|21)|age[-_ ]?verif|"
        r"are you over (?:18|19|21)|please confirm you are",
        full_html, re.IGNORECASE))
    if has_age_gate and not (detected.get("woocommerce") or detected.get("shopify")):
        notes.append(
            "An age verification gate was detected on this page. If the "
            "actual e-commerce (Dutchie/Jane/Buddi iframe or similar) only "
            "loads after the user clicks 'Yes' on the age gate, our scanner "
            "won't see it. Platform tier may be underestimated. Run the scan "
            "on a per-store menu subpage if the homepage is marketing-only."
        )
    if detected.get("pos_undetermined_breadstack"):
        notes.append(
            "POS system: not determinable from public HTML. This site uses "
            "Breadstack, whose WordPress plugin uses 'cova'-prefixed file "
            "names and JS globals (cova_wc_params, Cova_WC_FRONT_SWATCH, "
            "cova-woo-swatches-frontend.js, etc.) regardless of which POS "
            "the merchant actually runs. The actual POS (Cova, Greenline "
            "headless, Tymber, etc.) is configured server-side and is not "
            "visible to a public crawl."
        )
    if not detected["automatewoo"] and not detected["klaviyo"]:
        notes.append(
            "No abandoned-cart engine detected (no AutomateWoo, no Klaviyo). "
            "This is typically the single highest-ROI fix for dispensary "
            "e-commerce — abandoned-cart recovery alone often pays back "
            "platform costs in the first month."
        )

    return Report(
        url=homepage_url,
        scanned_at=datetime.utcnow().isoformat() + "Z",
        categories=categories,
        detected=detected,
        notes=notes,
    )




# ---------------------------------------------------------------------------
# Tech stack grouping for the report
# ---------------------------------------------------------------------------

STACK_GROUPS = [
    ("E-commerce platform", [
        ("woocommerce", "WooCommerce"),
        ("shopify", "Shopify"),
        ("bigcommerce", "BigCommerce"),
        ("magento", "Magento"),
        ("dutchie", "Dutchie"),
        ("iheartjane", "Jane"),
        ("buddi", "Buddi"),
        ("blaze_ecom", "Blaze Ecom"),
        ("dispense", "Dispense (AIQ)"),
        ("tymber", "Tymber"),
        ("greenline", "Greenline"),
        ("breadstack", "Breadstack"),
    ]),
    ("POS / Inventory", [
        ("cova_pos", "Cova"),
        ("greenline_pos", "Greenline (frontend menu)"),
        ("treez_pos", "Treez"),
        ("greenbits_pos", "GreenBits"),
        ("flowhub_pos", "Flowhub"),
        ("korona_pos", "Korona"),
        ("leaflogix_pos", "LeafLogix / MJ Freeway"),
        ("pos_undetermined_breadstack", "POS not determinable (Breadstack frontend; backend POS hidden)"),
    ]),
    ("Email / SMS", [
        ("klaviyo", "Klaviyo"),
        ("mailchimp", "Mailchimp"),
        ("omnisend", "Omnisend"),
        ("activecampaign", "ActiveCampaign"),
    ]),
    ("Loyalty", [
        ("alpineiq_active", "AlpineIQ (active)"),
        ("alpineiq_bundled_only", "AlpineIQ (bundled but inactive)"),
        ("springbig", "Springbig"),
        ("sticky_cards", "Sticky Cards"),
    ]),
    ("Reviews", [
        ("yotpo", "Yotpo"),
        ("stamped", "Stamped"),
        ("junip", "Junip"),
        ("okendo", "Okendo"),
        ("google_reviews_widget", "Google Reviews widget"),
    ]),
    ("Retention", [
        ("automatewoo", "AutomateWoo"),
    ]),
    ("Analytics", [
        ("ga4", "GA4"),
        ("gtm", "GTM"),
        ("site_kit", "Site Kit by Google"),
        ("meta_pixel", "Meta Pixel"),
        ("tiktok_pixel", "TikTok Pixel"),
    ]),
    ("Other tracking", [
        ("hotjar", "Hotjar"),
        ("heatmap_com", "Heatmap.com"),
        ("ahrefs_analytics", "Ahrefs Analytics"),
    ]),
    ("CMS / framework", [
        ("wordpress", "WordPress"),
        ("yoast", "Yoast SEO"),
        ("rankmath", "Rank Math"),
        ("nextjs", "Next.js"),
        ("nuxt", "Nuxt"),
        ("gatsby", "Gatsby"),
    ]),
]


def group_stack(detected):
    """Return [(group_name, [labels])] for the categorized stack widget."""
    out = []
    for group, items in STACK_GROUPS:
        present = [label for key, label in items if detected.get(key)]
        if present:
            out.append((group, present))
    return out


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>Report Card &mdash; URL_PLACEHOLDER</title>
<meta name="viewport" content="width=device-width,initial-scale=1" />
<style>
  :root{--bg:#0f1419;--panel:#1a1f26;--line:#2a313b;--text:#e6e8eb;--muted:#8a93a0;--pass:#2ec27e;--fail:#e5484d;--warn:#f5a524;--accent:#5cd6ff}
  *{box-sizing:border-box}
  html,body{margin:0;padding:0;background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;line-height:1.5}
  .wrap{max-width:880px;margin:0 auto;padding:32px 24px 64px}
  h1{margin:0 0 4px;font-size:24px;font-weight:600}
  .url{color:var(--muted);font-size:14px;word-break:break-all}
  .scanned{color:var(--muted);font-size:12px;margin-top:4px}
  .hero{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:28px;margin-top:24px;display:flex;align-items:center;gap:28px}
  .grade{font-size:72px;font-weight:700;line-height:1;width:110px;text-align:center;padding:8px;border-radius:12px}
  .grade.A{color:var(--pass);background:rgba(46,194,126,.08)}
  .grade.B{color:#7bd88f;background:rgba(123,216,143,.08)}
  .grade.C{color:var(--warn);background:rgba(245,165,36,.08)}
  .grade.D{color:#ff8a3d;background:rgba(255,138,61,.08)}
  .grade.F{color:var(--fail);background:rgba(229,72,77,.08)}
  .score-num{font-size:40px;font-weight:600}
  .score-sub{color:var(--muted);font-size:13px}
  .category{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:20px 24px;margin-top:16px}
  .cat-header{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:12px}
  .cat-name{font-size:17px;font-weight:600}
  .cat-meta{color:var(--muted);font-size:13px}
  .bar{height:6px;background:rgba(255,255,255,.05);border-radius:3px;overflow:hidden;margin:8px 0 16px}
  .bar>div{height:100%;transition:width .4s}
  .bar.A>div{background:var(--pass)}.bar.B>div{background:#7bd88f}.bar.C>div{background:var(--warn)}.bar.D>div{background:#ff8a3d}.bar.F>div{background:var(--fail)}
  .check{display:flex;gap:12px;padding:8px 0;border-bottom:1px solid var(--line);font-size:14px}
  .check:last-child{border-bottom:none}
  .mark{font-size:16px;min-width:20px}
  .mark.pass{color:var(--pass)}.mark.fail{color:var(--fail)}.mark.partial{color:var(--warn)}
  .check-body{flex:1}
  .check-label{font-weight:500}
  .check-detail{color:var(--muted);font-size:13px;margin-top:2px}
  .check-pts{color:var(--muted);font-size:12px;min-width:56px;text-align:right}
  .notes,.stack{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:20px 24px;margin-top:16px}
  .notes h3,.stack h3{margin:0 0 12px;font-size:16px}
  .notes h3{color:var(--accent)}
  .notes ul{margin:0;padding-left:20px}
  .notes li{margin:6px 0;font-size:14px}
  .stack-group{display:flex;gap:12px;padding:6px 0;border-bottom:1px solid var(--line);font-size:13px}
  .stack-group:last-child{border-bottom:none}
  .stack-label{color:var(--muted);min-width:170px;font-weight:500}
  .stack-vals{color:var(--text);flex:1}
  .footer{color:var(--muted);font-size:12px;margin-top:32px;text-align:center}
  .footer a{color:var(--accent);text-decoration:none}
  .footer a:hover{text-decoration:underline}
</style>
</head>
<body>
<div class="wrap">
  <h1>Dispensary E-Commerce Report Card</h1>
  <div class="url">URL_PLACEHOLDER</div>
  <div class="scanned">Scanned SCANNED_PLACEHOLDER</div>
  <div class="hero">
    <div class="grade LETTER_PLACEHOLDER">LETTER_PLACEHOLDER</div>
    <div>
      <div class="score-num">PERCENT_PLACEHOLDER / 100</div>
      <div class="score-sub">Weighted across 7 categories</div>
    </div>
  </div>
  CATEGORIES_PLACEHOLDER
  NOTES_PLACEHOLDER
  <div class="stack"><h3>Detected stack</h3>STACK_PLACEHOLDER</div>
  <div class="footer">Run your own report at <a href="https://dispensarystack.com">dispensarystack.com</a></div>
</div>
</body>
</html>
"""


def escape(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def render_html(report):
    def cat_block(cat):
        rows = []
        for c in cat.checks:
            if c.points_possible == 0:
                mark = '<span class="mark partial">i</span>'
            elif c.points_earned == c.points_possible:
                mark = '<span class="mark pass">&#9679;</span>'
            elif c.points_earned == 0:
                mark = '<span class="mark fail">&#9675;</span>'
            else:
                mark = '<span class="mark partial">&#9680;</span>'
            pts = (f"{c.points_earned:.1f}/{c.points_possible:.0f}"
                   if c.points_possible else "info")
            rows.append(
                '<div class="check">' + mark
                + '<div class="check-body">'
                + '<div class="check-label">' + escape(c.label) + '</div>'
                + '<div class="check-detail">' + escape(c.detail) + '</div>'
                + '</div><div class="check-pts">' + pts + '</div></div>')
        bar = min(100, max(0, cat.percent))
        return ('<div class="category"><div class="cat-header">'
                + '<div class="cat-name">' + escape(cat.label) + '</div>'
                + '<div class="cat-meta">' + f"{cat.percent:.0f}/100 &middot; grade {cat.letter} &middot; weight {cat.weight:.0%}" + '</div>'
                + f'</div><div class="bar {cat.letter}"><div style="width:{bar:.1f}%"></div></div>'
                + ''.join(rows) + '</div>')

    cats = "\n".join(cat_block(c) for c in report.categories)
    notes = ''
    if report.notes:
        notes = ('<div class="notes"><h3>Notes &amp; recommendations</h3><ul>'
                 + ''.join('<li>' + escape(n) + '</li>' for n in report.notes)
                 + '</ul></div>')
    # Categorized stack
    groups = group_stack(report.detected)
    if groups:
        stack = ''.join(
            '<div class="stack-group">'
            '<div class="stack-vals">' + escape(', '.join(items)) + '</div>'
            '</div>'
            for g, items in groups)
    else:
        stack = '<span class="check-detail">Nothing detected.</span>'
    return (HTML_TEMPLATE
            .replace("URL_PLACEHOLDER", escape(report.url))
            .replace("SCANNED_PLACEHOLDER", escape(report.scanned_at))
            .replace("LETTER_PLACEHOLDER", report.overall_letter)
            .replace("PERCENT_PLACEHOLDER", f"{report.overall_percent:.1f}")
            .replace("CATEGORIES_PLACEHOLDER", cats)
            .replace("NOTES_PLACEHOLDER", notes)
            .replace("STACK_PLACEHOLDER", stack))


def render_text(report):
    out = ["=" * 70, "DISPENSARY E-COMMERCE REPORT CARD",
           f"Site:        {report.url}",
           f"Scanned:     {report.scanned_at}", "=" * 70, "",
           f"OVERALL SCORE: {report.overall_percent:.1f} / 100   GRADE: {report.overall_letter}", ""]
    for cat in report.categories:
        out.append(f"--- {cat.label}  ({cat.percent:.0f}/100  grade {cat.letter}  weight {cat.weight:.0%}) ---")
        for c in cat.checks:
            if c.points_possible == 0:
                mark = "INFO"
            elif c.points_earned == c.points_possible and c.points_possible > 0:
                mark = "PASS"
            elif c.points_earned == 0:
                mark = "FAIL"
            else:
                mark = "PART"
            out.append(f"  [{mark}] {c.label} ({c.points_earned:.1f}/{c.points_possible:.0f}) -- {c.detail}")
        out.append("")
    if report.notes:
        out.append("NOTES & RECOMMENDATIONS")
        out.append("-" * 70)
        for n in report.notes:
            out.append(f"  * {n}")
        out.append("")
    out.append("DETECTED STACK")
    out.append("-" * 70)
    for group, items in group_stack(report.detected):
        out.append(f"  {group:25s} {', '.join(items)}")
    return "\n".join(out)


def main(argv=None):
    p = argparse.ArgumentParser(description="Dispensary e-commerce report card scanner.")
    p.add_argument("url", help="Site URL")
    p.add_argument("--output", "-o", help="Write HTML report to this path")
    p.add_argument("--json", action="store_true", help="Print JSON instead of text")
    p.add_argument("--no-html", action="store_true", help="Skip writing HTML report")
    args = p.parse_args(argv)
    t0 = time.time()
    api_key = os.environ.get("GOOGLE_PLACES_API_KEY")
    try:
        report = scan(args.url, gbp_api_key=api_key)
    except ScanError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    elapsed = time.time() - t0
    if args.json:
        out = {"url": report.url, "scanned_at": report.scanned_at,
               "overall_percent": round(report.overall_percent, 2),
               "overall_letter": report.overall_letter,
               "categories": [{"key": c.key, "label": c.label, "weight": c.weight,
                               "percent": round(c.percent, 2), "letter": c.letter,
                               "checks": [asdict(ch) for ch in c.checks]}
                              for c in report.categories],
               "detected": report.detected,
               "stack_grouped": [{"group": g, "items": items}
                                 for g, items in group_stack(report.detected)],
               "notes": report.notes}
        print(json.dumps(out, indent=2))
    else:
        print(render_text(report))
        print(f"\n(scan took {elapsed:.1f}s)\n")
    if not args.no_html:
        host = urlparse(report.url).netloc.replace(".", "_")
        html_path = args.output or f"report_{host}.html"
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(render_html(report))
        print(f"HTML report written to: {html_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
