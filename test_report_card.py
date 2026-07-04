"""
Unit tests for report_card.py
=============================

These test the scoring/detection logic against hand-crafted fixtures that
represent what we already confirmed lives on stokd.ca and
lakecitycannabis.ca. We can't fetch the real sites from this sandbox
(network restricted), so we verify the scorer works deterministically
against minimal-but-realistic HTML.

Run:
    python test_report_card.py
"""

import sys
from bs4 import BeautifulSoup

import report_card as rc


# ---------------------------------------------------------------------------
# Fixtures — minimal HTML that includes the actual signatures we found
# in-browser on each site.
# ---------------------------------------------------------------------------

STOKD_FIXTURE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>Cannabis Dispensaries In Scarborough &amp; Niagara Falls | Stok'd Cannabis</title>
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=5.0" />
<meta name="description" content="Shop cannabis dispensaries at 5 Stok'd locations in Scarborough & Niagara Falls. Fresh curated menus, 1-hour delivery, expert staff. Visit or order online today." />
<meta name="robots" content="follow, index, max-snippet:-1" />
<meta name="generator" content="WordPress 7.0" />
<meta property="og:title" content="Cannabis Dispensaries In Scarborough" />
<meta property="og:description" content="Shop cannabis dispensaries." />
<meta property="og:image" content="https://stokd.ca/img.png" />
<meta property="og:type" content="website" />
<meta property="og:url" content="https://stokd.ca/" />
<meta name="twitter:card" content="summary_large_image" />
<meta name="p:domain_verify" content="d01d285fa19312e23450443a4c7c1ba3" />
<link rel="canonical" href="https://stokd.ca/" />
<script src="https://www.googletagmanager.com/gtm.js?id=GTM-5ZNL9RS7"></script>
<script src="https://www.googletagmanager.com/gtag/js?id=G-30QFVHMP14"></script>
<script src="https://www.googletagmanager.com/gtag/js?id=G-WL89693VD8"></script>
<script src="https://stokd.ca/wp-content/plugins/woocommerce/assets/js/frontend/woocommerce.min.js"></script>
<script src="https://stokd.ca/wp-content/plugins/breadstack-connect/assets/hashed-files/js/cova-1a79a122.js"></script>
<script src="https://static.klaviyo.com/onsite/js/RXh3yX/klaviyo.js?ver=3.7.5"></script>
<script src="https://static-tracking.klaviyo.com/onsite/js/build-preview/static.js"></script>
<script src="https://stokd.ca/wp-content/plugins/klaviyo/inc/js/kl-identify-browser.js"></script>
<script src="https://analytics.ahrefs.com/analytics.js"></script>
<script src="https://dashboard.heatmap.com/preprocessor.min.js"></script>
<style id="bs-alpineiq-additional-css">#bs-alpineiq-reg-fname{}</style>
</head>
<body>
<form action="https://stokd.ca/?wc-ajax=newsletter_subscribe">
  <input type="email" name="email" />
</form>
<a href="https://stokd.ca/join-our-loyalty-program/">Join our loyalty program</a>
</body>
</html>
"""

# Sitemap index fixture — mirrors what Rank Math/Yoast actually serve:
# multiple child sitemaps, each with <lastmod>. The lastmod matters — a
# regression once glued it onto the URL and broke product discovery.
STOKD_SITEMAP = """<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap>
    <loc>https://stokd.ca/post-sitemap.xml</loc>
    <lastmod>2026-06-08T18:30:36+00:00</lastmod>
  </sitemap>
  <sitemap>
    <loc>https://stokd.ca/page-sitemap.xml</loc>
    <lastmod>2026-06-01T02:46:59+00:00</lastmod>
  </sitemap>
  <sitemap>
    <loc>https://stokd.ca/product-sitemap1.xml</loc>
    <lastmod>2026-06-20T03:35:47+00:00</lastmod>
  </sitemap>
</sitemapindex>
"""

STOKD_PRODUCT_SITEMAP = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://stokd.ca/product/soar-widow-pop/</loc></url>
  <url><loc>https://stokd.ca/product/simply-bare-bc-organic-plumz/</loc></url>
  <url><loc>https://stokd.ca/product/jeeter-baby-jeeter-peaches-infused-pre-roll-2/</loc></url>
  <url><loc>https://stokd.ca/product/redecan-cbd-gems/</loc></url>
</urlset>
"""

STOKD_PRODUCT_PAGE = """<!doctype html>
<html><head>
<title>Soar Widow Pop — Stok'd</title>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"Product","name":"Soar Widow Pop","sku":"abc"}
</script>
</head><body><h1>Product</h1></body></html>
"""

# ---- Lake City fixture ----

LAKECITY_FIXTURE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>Buy cannabis online | Delivery &amp; Shipping available | Lake City Cannabis</title>
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<meta name="description" content="Official Sponsor of a Better Attitude TRUE CRAFT CANNABIS SELECTION AT LOW PRICES Cannabis Delivery NOW Available in Calgary &amp; Chestermere Shop Now CALG ..." />
<meta name="generator" content="Site Kit by Google 1.164.0" />
<meta name="robots" content="max-image-preview:large" />
<meta property="og:title" content="Buy cannabis online" />
<meta property="og:description" content="Official Sponsor of a Better Attitude." />
<meta property="og:image" content="https://lakecitycannabis.ca/img.png" />
<meta property="og:type" content="website" />
<meta name="twitter:card" content="summary_large_image" />
<link rel="canonical" href="https://lakecitycannabis.ca/" />
<script src="https://www.googletagmanager.com/gtm.js?id=GTM-P3BWXL4"></script>
<script src="https://www.googletagmanager.com/gtag/js?id=G-6T1N0CBHWE"></script>
<script src="https://www.googletagmanager.com/gtag/js?id=G-SYE48003XE"></script>
<script src="https://lakecitycannabis.ca/wp-content/plugins/woocommerce/assets/js/frontend/woocommerce.min.js"></script>
<script src="https://lakecitycannabis.ca/wp-content/plugins/breadstack-connect/assets/hashed-files/js/cova-woo-swatches-frontend-639f374f.js"></script>
<script src="https://lakecitycannabis.ca/wp-content/plugins/automatewoo/assets/js/automatewoo-presubmit.min.js"></script>
<script src="https://static-tracking.klaviyo.com/onsite/js/build-preview/static.js"></script>
<script src="https://static.klaviyo.com/onsite/js/Rb8dfm/klaviyo.js"></script>
<script src="https://lakecitycannabis.ca/wp-content/plugins/klaviyo/inc/js/kl-identify-browser.js"></script>
<script src="https://lakecitycannabis.ca/wp-content/plugins/widget-google-reviews/assets/js/public-main.js"></script>
<script src="https://lakecitycannabis.ca/wp-content/plugins/wpforms-lite/assets/js/frontend/wpforms.min.js"></script>
</head>
<body>
<a href="https://lakecitycannabis.us20.list-manage.com/subscribe/post?u=30fe1f527243af6829b5ffd83&id=d9638b74fc">Newsletter</a>
<a href="https://lakecitycannabis.ca/loyalty/">Lake City Rewards Member</a>
</body>
</html>
"""

LAKECITY_SITEMAP = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://lakecitycannabis.ca/shop/topicals/rebound-by-stewart-farms-arctic-heat-extra-strength-relief-stick/</loc></url>
  <url><loc>https://lakecitycannabis.ca/shop/vaporizers/jonny-chronic-cherry-bomb-live-resin-prefilled-vape-cartridge/</loc></url>
  <url><loc>https://lakecitycannabis.ca/shop/concentrates/virtue-cannabis-watermelon-dabs/</loc></url>
</urlset>
"""


# ---------------------------------------------------------------------------
# Test helpers — patch fetch() to return our fixtures instead of hitting
# the network. Each fixture path returns a fake response.
# ---------------------------------------------------------------------------

class FakeResp:
    def __init__(self, text: str, url: str, ok: bool = True, status: int = 200):
        self.text = text
        self.url = url
        self.ok = ok
        self.status_code = status


def make_fake_fetch(routes: dict):
    """
    Given a {url_substring -> response_text} mapping, return a fetch() stub
    that returns FakeResp for matching URLs and None for everything else.
    """
    def fake_fetch(url, timeout=20.0):
        for key, text in routes.items():
            if key in url:
                return FakeResp(text, url)
        return None
    return fake_fetch


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

def run_test(name: str, fn):
    try:
        fn()
        print(f"  PASS  {name}")
        return True
    except AssertionError as e:
        print(f"  FAIL  {name}: {e}")
        return False
    except Exception as e:
        print(f"  ERROR {name}: {type(e).__name__}: {e}")
        return False


def test_signature_detection():
    assert rc.detect(STOKD_FIXTURE, "klaviyo")
    assert rc.detect(STOKD_FIXTURE, "ga4")
    assert rc.detect(STOKD_FIXTURE, "gtm")
    assert rc.detect(STOKD_FIXTURE, "woocommerce")
    assert rc.detect(STOKD_FIXTURE, "breadstack")
    assert rc.detect(STOKD_FIXTURE, "alpineiq_bundled")
    assert not rc.detect(STOKD_FIXTURE, "alpineiq_active"), (
        "Stokd has the Breadstack CSS class but NOT real AlpineIQ — must not credit"
    )
    assert not rc.detect(STOKD_FIXTURE, "automatewoo")
    assert not rc.detect(STOKD_FIXTURE, "mailchimp")


def test_lakecity_signatures():
    assert rc.detect(LAKECITY_FIXTURE, "klaviyo")
    assert rc.detect(LAKECITY_FIXTURE, "mailchimp"), "list-manage URL should match Mailchimp"
    assert rc.detect(LAKECITY_FIXTURE, "automatewoo")
    assert rc.detect(LAKECITY_FIXTURE, "site_kit")
    assert rc.detect(LAKECITY_FIXTURE, "google_reviews_widget")
    # NOTE: Lakecity does NOT actually use Cova POS — they use Greenline.
    # The Breadstack plugin's "cova"-prefixed file names are NOT proof of
    # Cova being the backend POS. We deliberately don't credit Cova here.
    assert not rc.detect(LAKECITY_FIXTURE, "cova_pos"), \
        "Breadstack-bundled cova-* names must NOT trigger Cova detection"
    assert not rc.detect(LAKECITY_FIXTURE, "alpineiq_active")


def test_extract_ids():
    ids = rc.extract_ids(STOKD_FIXTURE)
    assert "GTM-5ZNL9RS7" in ids["gtm"], ids
    assert "G-30QFVHMP14" in ids["ga4"], ids
    assert "G-WL89693VD8" in ids["ga4"], ids
    assert not ids["ua"], "stokd should not have legacy UA"

    ids2 = rc.extract_ids(LAKECITY_FIXTURE)
    assert "GTM-P3BWXL4" in ids2["gtm"]
    assert "G-6T1N0CBHWE" in ids2["ga4"]


def test_seo_scoring():
    soup = BeautifulSoup(STOKD_FIXTURE, "lxml")
    cat = rc.score_seo(soup, STOKD_FIXTURE + STOKD_PRODUCT_PAGE,
                       robots_ok=True, sitemap_ok=True,
                       product_html=STOKD_PRODUCT_PAGE)
    # Should pass most SEO checks
    passing = [c for c in cat.checks if c.points_earned == c.points_possible]
    assert len(passing) >= 6, f"only {len(passing)} SEO checks fully passed: {[c.key for c in cat.checks]}"
    # Specifically: Product schema must be detected on the sample product page
    schema = next(c for c in cat.checks if c.key == "product_schema")
    assert schema.passed, "Product schema should be detected"


def test_email_scoring_klaviyo_beats_mailchimp():
    """When both Klaviyo and Mailchimp are present, score Klaviyo's 20 (best)."""
    soup = BeautifulSoup(LAKECITY_FIXTURE, "lxml")
    cat = rc.score_email(LAKECITY_FIXTURE, soup)
    esp = next(c for c in cat.checks if c.key == "esp")
    assert esp.points_earned == 20, f"expected 20 for Klaviyo, got {esp.points_earned}"
    # Conflict check should also be present
    conflict = next((c for c in cat.checks if c.key == "esp_conflict"), None)
    assert conflict is not None, "expected ESP conflict flag for Klaviyo+Mailchimp"


def test_klaviyo_embed_placeholder_counts_as_newsletter_form():
    """REGRESSION: modern Klaviyo forms are JS-injected; the raw HTML only
    contains an empty placeholder div (class="klaviyo-form-XXXXXX"). That
    placeholder must credit the 'newsletter capture form' check — stokd.ca
    was wrongly scored 'no signup form' despite a full Klaviyo embed."""
    html = """<html><head>
    <script src="https://static.klaviyo.com/onsite/js/AbC123/klaviyo.js"></script>
    </head><body>
    <h2>STAY STOK'D</h2>
    <div class="klaviyo-form-YvyJ7e"></div>
    <p>By subscribing you confirm you're 19+.</p>
    </body></html>"""
    soup = BeautifulSoup(html, "lxml")
    cat = rc.score_email(html, soup)
    form_check = next(c for c in cat.checks if c.key == "newsletter_form")
    assert form_check.passed, f"Klaviyo placeholder div should count as a form: {form_check.detail}"


CHRONTACT_FIXTURE = """<!doctype html>
<html><head>
<title>Premium Cannabis &amp; Friendly Service - Chrontact</title>
<script src="https://ca.cdn.hifyreretail.com/app/main.js"></script>
<script src="https://www.googletagmanager.com/gtm.js?id=GTM-ABC1234"></script>
</head><body>
<a href="/spark">SPARK REWARDS</a>
<p>Join Spark Rewards and earn points on every purchase.</p>
<a href="/shop/flower">Flower</a>
</body></html>
"""


def test_platform_tier_hifyre_is_A():
    """Hifyre (FIKA family: FIKA, Chrontact, Fire & Flower) serves same-domain
    SSR /products/<slug> pages + a products sitemap — A-tier (22), not
    'unknown platform'. Verified against chrontact.ca."""
    soup = BeautifulSoup(CHRONTACT_FIXTURE, "lxml")
    product_urls = [
        "https://chrontact.ca/products/050-cal-gator-blood-double-infused",
        "https://chrontact.ca/products/1000mg-delta-9-distillate-softgels",
    ]
    tier, pts, label, _ = rc.classify_ecom_platform(CHRONTACT_FIXTURE, soup, product_urls)
    assert tier == "A", f"expected A-tier, got {tier} ({label})"
    assert pts == 22
    assert "Hifyre" in label

    # Without product URLs it should degrade to B, not A
    tier2, pts2, label2, _ = rc.classify_ecom_platform(CHRONTACT_FIXTURE, soup, [])
    assert tier2 == "B" and pts2 == 14, f"expected B/14 without sitemap, got {tier2}/{pts2}"


def test_spark_rewards_loyalty_detected():
    """Spark Rewards (FIKA/Hifyre first-party loyalty) must credit the loyalty
    category. chrontact.ca showed 'no loyalty platform detected' despite a
    /spark page and SPARK REWARDS branding on the homepage."""
    soup = BeautifulSoup(CHRONTACT_FIXTURE, "lxml")
    cat = rc.score_loyalty(CHRONTACT_FIXTURE, soup)
    check = cat.checks[0]
    assert check.points_earned == 12, f"expected 12 pts for Spark Rewards, got {check.points_earned} ({check.detail})"
    assert "Spark" in check.detail


def test_products_plural_urls_are_product_like():
    """/products/<slug> (Hifyre, Shopify) must match the product-URL filter,
    not just /product/<slug> (WooCommerce)."""
    xml = """<urlset>
    <url><loc>https://chrontact.ca/products/some-item</loc></url>
    <url><loc>https://chrontact.ca/about-us</loc></url>
    </urlset>"""
    urls = rc._extract_loc(xml)
    assert urls == ["https://chrontact.ca/products/some-item"], f"got: {urls}"


def test_gsc_and_pixels_are_advisory_not_penalties():
    """GSC verification via DNS/GA/GTM is invisible in HTML, so a missing
    GSC signal must be a zero-point advisory, not a deduction. Meta/TikTok
    pixels are informational only. When GSC IS visible, it still earns 3/3."""
    ids = {"ga4": [], "gtm": []}

    bare = "<html><head><title>x</title></head><body></body></html>"
    cat = rc.score_analytics(bare, ids)
    gsc = next(c for c in cat.checks if c.key == "gsc")
    assert gsc.points_possible == 0, "missing GSC must not shrink the score"
    assert "verify" in gsc.detail.lower() or "confirm" in gsc.detail.lower()
    for key in ("meta_pixel", "tiktok_pixel"):
        chk = next(c for c in cat.checks if c.key == key)
        assert chk.points_possible == 0, f"{key} should be informational"

    verified = '<html><head><meta name="google-site-verification" content="abc"></head></html>'
    cat2 = rc.score_analytics(verified, ids)
    gsc2 = next(c for c in cat2.checks if c.key == "gsc")
    assert gsc2.points_earned == 3 and gsc2.points_possible == 3


def test_fix_guidance_rendered_for_failing_checks():
    """Failing checks must show 'How to fix' guidance; the report must open
    with a prioritized 'Where to start' section; passing checks get no fix."""
    routes = {
        "stokd.ca/robots.txt": "User-agent: *\nAllow: /\nSitemap: https://stokd.ca/sitemap.xml",
        "stokd.ca/sitemap.xml": STOKD_SITEMAP,
        "stokd.ca/product-sitemap1.xml": STOKD_PRODUCT_SITEMAP,
        "stokd.ca/product/soar-widow-pop": STOKD_PRODUCT_PAGE,
        "stokd.ca/": STOKD_FIXTURE,
    }
    original_fetch = rc.fetch
    rc.fetch = make_fake_fetch(routes)
    try:
        report = rc.scan("https://stokd.ca/")
    finally:
        rc.fetch = original_fetch
    html = rc.render_html(report)
    assert "Where to start" in html, "priority fixes section missing"
    assert "How to fix:" in html, "per-check fix guidance missing"
    assert 'class="pdf-btn' in html, "PDF button missing"
    assert "@media print" in html, "print stylesheet missing"
    # every FIXES key must be a real check key or gbp key (guard against typos
    # that would silently never render)
    check_keys = {c.key for cat in report.categories for c in cat.checks}
    # gbp_* checks need an API key; esp_conflict only exists when two ESPs
    # collide — both legitimately absent from this fixture scan.
    conditional = {k for k in rc.FIXES if k.startswith("gbp_")} | {"esp_conflict"}
    for k in rc.FIXES:
        assert k in check_keys or k in conditional, f"FIXES key '{k}' matches no check"


def test_loyalty_aiq_bundled_only_does_not_credit_full():
    """The Breadstack bundled CSS class alone gets 3 pts, not 15."""
    soup = BeautifulSoup(STOKD_FIXTURE, "lxml")
    cat = rc.score_loyalty(STOKD_FIXTURE, soup)
    pts = cat.checks[0].points_earned
    assert pts <= 5, f"expected low partial credit, got {pts}"
    # And the branded loyalty page link should be found (better than just bundled CSS)
    assert "loyalty" in cat.checks[0].detail.lower() or pts in (3, 5)


def test_retention_automatewoo_credits():
    cat = rc.score_retention(LAKECITY_FIXTURE)
    cap = next(c for c in cat.checks if c.key == "automation_capability")
    # Lakecity has BOTH AutomateWoo and Klaviyo → top score 5
    assert cap.points_earned == 5, f"expected 5 (both), got {cap.points_earned}"


def test_clean_urls_detection():
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(STOKD_FIXTURE, "lxml")
    cat = rc.score_ecommerce(
        homepage_url="https://stokd.ca/",
        html=STOKD_FIXTURE,
        soup=soup,
        product_urls=[
            "https://stokd.ca/product/soar-widow-pop/",
            "https://stokd.ca/product/redecan-cbd-gems/",
            "https://stokd.ca/product/simply-bare-bc-organic-plumz/",
        ],
        product_html=STOKD_PRODUCT_PAGE,
    )
    clean = next(c for c in cat.checks if c.key == "clean_urls")
    assert clean.passed, f"all-clean URLs should pass: {clean.detail}"
    # Also confirm platform tier check is present and credits WooCommerce as S-tier
    tier = next(c for c in cat.checks if c.key == "platform_tier")
    assert "WooCommerce" in tier.label, f"got: {tier.label}"
    assert tier.points_earned >= 23, f"WooCommerce should be near full S-tier, got {tier.points_earned}"


def test_sitemap_index_with_lastmod_yields_product_urls():
    """REGRESSION: <lastmod> in a sitemap index must not corrupt child URLs.

    Real-world Rank Math/Yoast indexes always include <lastmod>. A bug that
    read `.text` off the whole <sitemap> element glued the timestamp onto the
    URL, every child fetch 404'd, and live scans reported 'no product URLs
    discovered' on sites with perfectly good /product/ pages (e.g. stokd.ca).
    Also verifies product-sitemaps are prioritized over post-/page-sitemaps.
    """
    routes = {
        "stokd.ca/product-sitemap1.xml": STOKD_PRODUCT_SITEMAP,
        # post-/page-sitemaps intentionally unrouted -> fetch returns None
    }
    original_fetch = rc.fetch
    rc.fetch = make_fake_fetch(routes)
    try:
        urls = rc.collect_product_urls(STOKD_SITEMAP, "https://stokd.ca/")
    finally:
        rc.fetch = original_fetch

    assert len(urls) == 4, f"expected 4 product URLs, got {len(urls)}: {urls}"
    assert all("/product/" in u for u in urls), f"non-product URLs leaked in: {urls}"
    assert all("lastmod" not in u and "+00:00" not in u for u in urls), \
        f"lastmod contaminated a URL: {urls}"


def test_full_scan_offline_stokd(monkeypatch=None):
    """End-to-end scan with the network mocked to return our stokd fixtures."""
    routes = {
        "stokd.ca/robots.txt": "User-agent: *\nAllow: /\nSitemap: https://stokd.ca/sitemap.xml",
        "stokd.ca/sitemap.xml": STOKD_SITEMAP,
        "stokd.ca/product-sitemap1.xml": STOKD_PRODUCT_SITEMAP,
        "stokd.ca/product/soar-widow-pop": STOKD_PRODUCT_PAGE,
        "stokd.ca/": STOKD_FIXTURE,
    }
    original_fetch = rc.fetch
    rc.fetch = make_fake_fetch(routes)
    try:
        report = rc.scan("https://stokd.ca/")
    finally:
        rc.fetch = original_fetch

    assert report.detected["klaviyo"], "stokd should detect Klaviyo"
    assert report.detected["ga4"]
    assert report.detected["gtm"]
    assert not report.detected["automatewoo"], "stokd shouldn't have AutomateWoo"
    assert not report.detected["mailchimp"]
    # AIQ should be flagged as bundled-only, not active
    assert report.detected["alpineiq_bundled_only"]
    assert not report.detected.get("alpineiq_active", False)
    # Overall: stokd has GREAT SEO + analytics + Klaviyo but no AutomateWoo.
    # Without a Places API key, the GBP category (20% weight) can only
    # earn the two website-visible sub-checks, so the floor is lower.
    assert report.overall_percent >= 55, f"stokd should score decently, got {report.overall_percent}"
    print(f"     stokd score: {report.overall_percent:.1f} ({report.overall_letter})")


def test_full_scan_offline_lakecity():
    routes = {
        "lakecitycannabis.ca/robots.txt": "User-agent: *\nAllow: /\nSitemap: https://lakecitycannabis.ca/sitemap.xml",
        "lakecitycannabis.ca/sitemap.xml": LAKECITY_SITEMAP,
        "lakecitycannabis.ca/shop/topicals/rebound": "<html><script type=\"application/ld+json\">{\"@type\":\"Product\"}</script></html>",
        "lakecitycannabis.ca/": LAKECITY_FIXTURE,
    }
    original_fetch = rc.fetch
    rc.fetch = make_fake_fetch(routes)
    try:
        report = rc.scan("https://lakecitycannabis.ca/")
    finally:
        rc.fetch = original_fetch

    assert report.detected["klaviyo"]
    assert report.detected["mailchimp"], "list-manage.com link should trigger Mailchimp"
    assert report.detected["automatewoo"]
    assert report.detected["site_kit"]
    # Should have an ESP conflict note
    has_conflict_note = any("klaviyo" in n.lower() and "mailchimp" in n.lower()
                             for n in report.notes)
    assert has_conflict_note, f"expected ESP conflict note, got: {report.notes}"
    print(f"     lakecity score: {report.overall_percent:.1f} ({report.overall_letter})")


def test_gbp_score_no_api_key():
    """Without an API key, only website-visible GBP signals score."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(LAKECITY_FIXTURE, "lxml")
    # Mock GBPData with found=False (no API key path)
    empty = rc.GBPData(found=False)
    cat = rc.score_gbp(empty, LAKECITY_FIXTURE, soup,
                       "https://lakecitycannabis.ca/", api_key_present=False)
    # Should still have social_proof + multi_store checks
    keys = [c.key for c in cat.checks]
    assert "social_proof_on_site" in keys
    assert "multi_store_pages" in keys
    # And an informational "skipped" check explaining the gap
    skip = [c for c in cat.checks if c.key == "gbp_api_status"]
    assert skip and "no GOOGLE_PLACES_API_KEY" in skip[0].detail.lower() \
        or "no google_places_api_key" in skip[0].detail.lower()


MULTISTORE_FIXTURE = """<!doctype html><html><head>
<meta property="og:site_name" content="Test Co" />
<title>Test Co Cannabis</title></head>
<body>
<a href="/locations/store-a/">Store A</a>
<a href="/locations/store-b/">Store B</a>
<a href="/locations/store-c/">Store C</a>
</body></html>"""


def test_gbp_score_with_full_data():
    """When Places API returns a complete profile, all checks score."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(MULTISTORE_FIXTURE, "lxml")
    gbp = rc.GBPData(
        found=True,
        place_id="ChIJfake123",
        display_name="Lake City Cannabis",
        address="123 Main St, Chestermere, AB",
        phone="+1 403-555-1234",
        website_uri="https://lakecitycannabis.ca/chestermere?utm_source=google&utm_medium=organic&utm_campaign=gbp",
        google_maps_uri="https://maps.google.com/...",
        rating=4.8,
        user_rating_count=225,
        photo_count=10,
        has_opening_hours=True,
        has_recent_review=True,
        review_count_sampled=5,
        business_status="OPERATIONAL",
    )
    cat = rc.score_gbp(gbp, MULTISTORE_FIXTURE, soup,
                       "https://lakecitycannabis.ca/", api_key_present=True)
    # Should award the UTM check
    utm_check = next(c for c in cat.checks if c.key == "gbp_website_utm")
    assert utm_check.points_earned == 5
    comp = next(c for c in cat.checks if c.key == "gbp_completeness")
    assert comp.points_earned == 35
    rating = next(c for c in cat.checks if c.key == "gbp_rating")
    assert rating.points_earned == 10
    deep = [c for c in cat.checks if c.key == "gbp_deep_link"]
    assert deep and deep[0].points_earned == 5


def test_gbp_score_with_partial_data():
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(MULTISTORE_FIXTURE, "lxml")
    gbp = rc.GBPData(
        found=True, place_id="ChIJfake456",
        display_name="Stok'd Cannabis",
        address="2978 Eglinton Ave E, Scarborough, ON",
        phone=None, website_uri="https://stokd.ca/",
        google_maps_uri="https://maps.google.com/...",
        rating=4.2, user_rating_count=12, photo_count=3,
        has_opening_hours=False, has_recent_review=False,
        business_status="OPERATIONAL",
    )
    cat = rc.score_gbp(gbp, MULTISTORE_FIXTURE, soup,
                       "https://stokd.ca/", api_key_present=True)
    comp = next(c for c in cat.checks if c.key == "gbp_completeness")
    assert comp.points_earned == 20
    rating = next(c for c in cat.checks if c.key == "gbp_rating")
    assert rating.points_earned == 5
    utm = next(c for c in cat.checks if c.key == "gbp_website_utm")
    assert utm.points_earned == 0
    deep = next(c for c in cat.checks if c.key == "gbp_deep_link")
    assert deep.points_earned == 0


def test_platform_tier_woocommerce_is_S():
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(STOKD_FIXTURE, "lxml")
    tier, pts, label, _ = rc.classify_ecom_platform(STOKD_FIXTURE, soup,
                                                    ["https://stokd.ca/product/x/"])
    assert tier == "S", f"WooCommerce should be S-tier, got {tier}"
    assert pts == 25, f"expected 25 pts, got {pts}"
    assert "WooCommerce" in label


def test_platform_tier_iframe_dutchie_is_C():
    """An iframe-embedded Dutchie menu should land in C tier with 5 pts."""
    html = '<html><body><iframe src="https://embed.dutchie.com/menu/xyz"></iframe></body></html>'
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    tier, pts, label, detail = rc.classify_ecom_platform(html, soup, [])
    assert tier == "C", f"got tier {tier}"
    assert pts == 5
    assert "Dutchie (iframe)" == label
    assert "invisible to crawlers" in detail.lower()


def test_platform_tier_iframe_jane_is_C():
    html = '<html><body><iframe src="https://www.iheartjane.com/embed/abc"></iframe></body></html>'
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    tier, pts, label, _ = rc.classify_ecom_platform(html, soup, [])
    assert tier == "C" and pts == 5 and "Jane" in label


def test_platform_tier_blaze_is_B():
    """Blaze Ecom as script (proxy redirect), not iframe → B tier."""
    html = '<html><script src="https://cdn.blaze.me/widget.js"></script></html>'
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    tier, pts, label, _ = rc.classify_ecom_platform(html, soup, [])
    assert tier == "B", f"got {tier}"
    assert pts == 15
    assert "Blaze" in label


def test_platform_tier_nextjs_with_products_is_A():
    """Next.js + product URLs in sitemap → A tier."""
    html = '<html><script src="/_next/static/chunks/main.js"></script><div>__NEXT_DATA__</div></html>'
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    tier, pts, label, _ = rc.classify_ecom_platform(
        html, soup, ["https://x.com/product/a/", "https://x.com/product/b/"])
    assert tier == "A", f"got {tier}"
    assert pts == 22
    assert "Next.js" in label



def test_platform_tier_nextjs_without_sitemap_is_C():
    """Next.js but no product URLs in sitemap = C (likely CSR without SEO setup)."""
    html = '<html><script src="/_next/static/chunks/main.js"></script></html>'
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    tier, pts, _, detail = rc.classify_ecom_platform(html, soup, [])
    assert tier == "C", f"got {tier}"
    assert pts == 8


def test_platform_tier_no_ecom_is_F():
    from bs4 import BeautifulSoup
    soup = BeautifulSoup("<html><body>nothing here</body></html>", "lxml")
    tier, pts, label, _ = rc.classify_ecom_platform("<html></html>", soup, [])
    assert tier == "F", f"got {tier}"
    assert pts == 0


def test_subdomain_penalty_applies():
    """Shop on subdomain = -5 from the platform tier."""
    from bs4 import BeautifulSoup
    html = STOKD_FIXTURE
    soup = BeautifulSoup(html, "lxml")
    cat = rc.score_ecommerce(
        homepage_url="https://example.com/",
        html=html, soup=soup,
        product_urls=["https://shop.example.com/product/x/"],
        product_html=None,
    )
    tier_check = next(c for c in cat.checks if c.key == "platform_tier")
    assert tier_check.points_earned == 20, \
        f"S-tier (25) minus 5 = 20, got {tier_check.points_earned}"
    assert "subdomain penalty" in tier_check.detail.lower()


def test_terpene_taxonomy_detection():
    html = "<html>filter by terpene: myrcene, limonene, pinene, caryophyllene</html>"
    has, found = rc.detect_terpene_taxonomy(html)
    assert has, f"should detect: {found}"
    assert len(found) == 4
    html2 = "<html>this strain has myrcene</html>"
    has2, _ = rc.detect_terpene_taxonomy(html2)
    assert not has2


def test_minor_cannabinoid_detection():
    html = "<html>filter by cannabinoid: CBN, CBG, CBC</html>"
    has, found = rc.detect_minor_cannabinoids(html)
    assert has, f"should detect: {found}"
    html2 = "<html>THC: 25%, CBD: 1%</html>"
    has2, _ = rc.detect_minor_cannabinoids(html2)
    assert not has2


def test_breadstack_cova_names_do_not_falsely_credit_cova():
    """REGRESSION: Breadstack's WordPress plugin uses 'cova' naming in file
    names, JS globals, and CSS classes even when the backend POS is
    Greenline / Tymber / something else. The scanner must NOT report Cova
    as the POS just because these Breadstack-bundled names appear.

    This test is named for the bug it prevents: lakecitycannabis.ca was
    incorrectly flagged as using Cova POS when it actually uses Greenline.
    """
    # Realistic Breadstack-frontend HTML with all the 'cova' patterns
    # but NO actual Cova SDK reference.
    html = """<html><body>
    <script src="/wp-content/plugins/breadstack-connect/assets/hashed-files/js/cova-woo-swatches-frontend-639f374f.js"></script>
    <script src="/wp-content/themes/lakecity-cannabis/assets/js/cova-scripts.js"></script>
    <script>var cova_wc_params = {"ajax_url": "/wp-admin/admin-ajax.php"};</script>
    <i class="cova-icon-location"></i>
    <div id="cova-age-gate"></div>
    </body></html>"""
    assert not rc.detect(html, "cova_pos"), \
        "Breadstack plugin's cova-named files must NOT trigger Cova detection"

    # But REAL Cova SDK loads (covasoft.com) should still trigger
    real_cova = '<script src="https://cdn.covasoft.com/cova-sdk.js"></script>'
    assert rc.detect(real_cova, "cova_pos"), \
        "Real Cova SDK from covasoft.com must still be detected"


def test_pos_undetermined_when_breadstack_without_specific_pos():
    """If Breadstack is present but no specific POS frontend signals,
    the scanner reports 'POS not determinable' instead of guessing."""
    from bs4 import BeautifulSoup
    html = """<html><script src="/wp-content/plugins/breadstack-connect/assets/js/foo.js"></script>
    <script src="/wp-content/themes/x/cova-scripts.js"></script></html>"""
    routes = {
        "test.com/robots.txt": "",
        "test.com/": html,
    }
    fake = make_fake_fetch(routes)
    original = rc.fetch
    rc.fetch = fake
    try:
        report = rc.scan("https://test.com/")
    finally:
        rc.fetch = original
    assert report.detected.get("pos_undetermined_breadstack"), \
        "Breadstack without specific POS frontend should mark POS as undetermined"
    assert not report.detected.get("cova_pos"), \
        "Should NOT credit Cova just from Breadstack-bundled names"
    # And a note should explain the situation
    assert any("not determinable" in n.lower() for n in report.notes), \
        f"Expected a 'not determinable' note. Got: {report.notes}"


def test_business_name_extraction():
    from bs4 import BeautifulSoup
    soup1 = BeautifulSoup(
        '<html><head><meta property="og:site_name" content="Stok&#39;d Cannabis"/>'
        '<title>Some Page | Different Title</title></head></html>', "lxml")
    name = rc._extract_business_name(soup1)
    assert name == "Stok'd Cannabis"
    soup2 = BeautifulSoup(
        '<html><head><title>Buy Weed | Lake City Cannabis</title></head></html>',
        "lxml")
    assert rc._extract_business_name(soup2) == "Lake City Cannabis"


def test_html_rendering_doesnt_crash():
    routes = {"stokd.ca/": STOKD_FIXTURE, "stokd.ca/sitemap.xml": STOKD_SITEMAP,
              "stokd.ca/product-sitemap.xml": STOKD_PRODUCT_SITEMAP,
              "stokd.ca/product/soar-widow-pop": STOKD_PRODUCT_PAGE}
    original = rc.fetch
    rc.fetch = make_fake_fetch(routes)
    try:
        r = rc.scan("https://stokd.ca/")
        html = rc.render_html(r)
        assert "<!doctype html>" in html.lower()
        assert "klaviyo" in html.lower()
        assert "E-commerce platform" in html, "categorized stack should show group label"
        text = rc.render_text(r)
        assert "OVERALL SCORE" in text
    finally:
        rc.fetch = original


TESTS = [
    ("Signature detection -- stokd", test_signature_detection),
    ("Signature detection -- lakecity", test_lakecity_signatures),
    ("Tracking ID extraction (GA4/GTM)", test_extract_ids),
    ("SEO scoring with sample product page", test_seo_scoring),
    ("Email scoring: Klaviyo wins over Mailchimp", test_email_scoring_klaviyo_beats_mailchimp),
    ("REGRESSION: Klaviyo JS-injected form placeholder counts", test_klaviyo_embed_placeholder_counts_as_newsletter_form),
    ("Loyalty scoring: bundled AIQ != active AIQ", test_loyalty_aiq_bundled_only_does_not_credit_full),
    ("Retention scoring: AutomateWoo + Klaviyo = full credit", test_retention_automatewoo_credits),
    ("E-commerce: clean URL detection + WooCommerce S-tier", test_clean_urls_detection),
    ("Platform tier: WooCommerce = S (25 pts)", test_platform_tier_woocommerce_is_S),
    ("Platform tier: Dutchie iframe = C (5 pts)", test_platform_tier_iframe_dutchie_is_C),
    ("Platform tier: Jane iframe = C (5 pts)", test_platform_tier_iframe_jane_is_C),
    ("Platform tier: Blaze script = B (15 pts)", test_platform_tier_blaze_is_B),
    ("Platform tier: Next.js + sitemap = A (22 pts)", test_platform_tier_nextjs_with_products_is_A),
    ("Platform tier: Next.js no sitemap = C", test_platform_tier_nextjs_without_sitemap_is_C),
    ("Platform tier: nothing = F", test_platform_tier_no_ecom_is_F),
    ("Platform tier: Hifyre (FIKA) = A (22 pts)", test_platform_tier_hifyre_is_A),
    ("Loyalty: Spark Rewards (FIKA/Hifyre) detected", test_spark_rewards_loyalty_detected),
    ("Product URL filter: /products/ plural matches", test_products_plural_urls_are_product_like),
    ("Analytics: GSC + pixels advisory, no deductions", test_gsc_and_pixels_are_advisory_not_penalties),
    ("Report: fix guidance + priority section + PDF button", test_fix_guidance_rendered_for_failing_checks),
    ("Subdomain penalty -5", test_subdomain_penalty_applies),
    ("Terpene taxonomy detection", test_terpene_taxonomy_detection),
    ("Minor cannabinoid detection", test_minor_cannabinoid_detection),
    ("REGRESSION: sitemap index with lastmod yields product URLs", test_sitemap_index_with_lastmod_yields_product_urls),
    ("Full offline scan -- stokd.ca", test_full_scan_offline_stokd),
    ("Full offline scan -- lakecitycannabis.ca", test_full_scan_offline_lakecity),
    ("GBP scoring: no API key", test_gbp_score_no_api_key),
    ("GBP scoring: complete profile", test_gbp_score_with_full_data),
    ("GBP scoring: partial profile", test_gbp_score_with_partial_data),
    ("REGRESSION: Breadstack 'cova' names DON'T trigger Cova POS", test_breadstack_cova_names_do_not_falsely_credit_cova),
    ("POS undetermined when Breadstack without specific POS", test_pos_undetermined_when_breadstack_without_specific_pos),
    ("Business name extraction", test_business_name_extraction),
    ("HTML + text rendering", test_html_rendering_doesnt_crash),
]


if __name__ == "__main__":
    print(f"Running {len(TESTS)} tests...\n")
    failures = 0
    for name, fn in TESTS:
        if not run_test(name, fn):
            failures += 1
    print(f"\n{'-'*60}")
    if failures:
        print(f"FAILED: {failures}/{len(TESTS)}")
        sys.exit(1)
    print(f"PASSED: {len(TESTS)}/{len(TESTS)}")
