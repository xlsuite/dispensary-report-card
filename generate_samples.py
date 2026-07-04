"""
Generate the two sample HTML reports against fixtures we captured from
stokd.ca and lakecitycannabis.ca via Chrome inspection. Saves
report_stokd_ca.html and report_lakecitycannabis_ca.html.
"""
import report_card as rc
from test_report_card import (
    STOKD_FIXTURE, STOKD_SITEMAP, STOKD_PRODUCT_SITEMAP, STOKD_PRODUCT_PAGE,
    LAKECITY_FIXTURE, LAKECITY_SITEMAP, make_fake_fetch,
)

cases = [
    ("https://stokd.ca/", "report_stokd_ca.html", {
        "stokd.ca/robots.txt": "User-agent: *\nAllow: /\nSitemap: https://stokd.ca/sitemap.xml",
        "stokd.ca/sitemap.xml": STOKD_SITEMAP,
        "stokd.ca/product-sitemap.xml": STOKD_PRODUCT_SITEMAP,
        "stokd.ca/product/soar-widow-pop": STOKD_PRODUCT_PAGE,
        "stokd.ca/": STOKD_FIXTURE,
    }),
    ("https://lakecitycannabis.ca/", "report_lakecitycannabis_ca.html", {
        "lakecitycannabis.ca/robots.txt": "User-agent: *\nAllow: /\nSitemap: https://lakecitycannabis.ca/sitemap.xml",
        "lakecitycannabis.ca/sitemap.xml": LAKECITY_SITEMAP,
        "lakecitycannabis.ca/shop/topicals/rebound": '<html><script type="application/ld+json">{"@type":"Product"}</script></html>',
        "lakecitycannabis.ca/": LAKECITY_FIXTURE,
    }),
]

for url, out_path, routes in cases:
    original = rc.fetch
    rc.fetch = make_fake_fetch(routes)
    try:
        report = rc.scan(url)
    finally:
        rc.fetch = original

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(rc.render_html(report))
    print(f"{url} → {report.overall_percent:.1f} ({report.overall_letter}) → {out_path}")
