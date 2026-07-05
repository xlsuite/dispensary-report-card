# Dispensary E-Commerce Report Card

The scanner behind **[dispensarystack.com](https://dispensarystack.com)** — a
free tool that reads a cannabis dispensary's public website and grades its
e-commerce and marketing setup from A to F, with a prioritized fix list.

Paste a URL, get a report: which e-commerce platform the site runs (and
whether Google can actually see its products), SEO fundamentals, email
capture and ESP quality, loyalty program, retention tooling, analytics, and
Google Business Profile health. Every failing check comes with plain-English
remediation advice. [Sample report (PDF)](samples/sample-report.pdf).

Everything is detected from **raw HTML only** — no JavaScript execution, no
headless browser, no logins. If it can't be seen in view-source or a public
API, the scanner treats it as unknowable and says so rather than guessing.

## How it works

```
GET /scan?url=...
  ├─ SSRF guard + rate limit (5/hr/IP) + 1-hour same-URL cache
  ├─ report_card.scan()
  │    ├─ fetch homepage, robots.txt, sitemap(s), sample product page,
  │    │  per-store menu pages, shop.* subdomains   (age-gate cookies set,
  │    │  1.5 MB/page cap, 40 s wall budget, browser-UA retry if a WAF
  │    │  blocks the scanner's honest user-agent)
  │    ├─ ~30 regex signature detectors (SIGS dict)
  │    ├─ optional Google Places lookup (GOOGLE_PLACES_API_KEY)
  │    └─ score 7 weighted categories
  ├─ store report in SQLite → shareable /r/<token> URL
  └─ teaser page (grade + category scores) → email gate → full report
```

Three moving parts:

| File | What it is |
|---|---|
| `report_card.py` | The scanner. Signature detection, scoring, HTML/text/JSON rendering, fix-guidance library. Self-contained — has its own CLI. |
| `app.py` | FastAPI wrapper: landing page, scan endpoint, stored reports, email gate, admin dashboard, safety rails. |
| `db.py` | SQLite persistence: stored scans + captured leads (with explicit marketing-consent flag). |

## What it checks

Seven categories: **Local Search & Google Business Profile**, **SEO
Fundamentals**, **E-commerce & Platform**, **Email Marketing**, **Loyalty
Program**, **Retention & Reviews**, and **Analytics & Tracking**. Weights
live in the `Category(...)` constructors in `report_card.py`.

The most opinionated piece is the **e-commerce platform tier**, because it
decides whether a dispensary's products exist in Google's eyes:

| Tier | What it is | Points | Examples |
|---|---|---|---|
| **S** | True on-domain e-commerce | 23–25 | WooCommerce, Shopify, BigCommerce, Magento |
| **A** | Custom platform, same-domain SSR product pages + sitemap | 22 | Hifyre (FIKA), Next.js/Nuxt builds done right |
| **B** | Proxy/redirect cannabis platform | 14–16 | Blaze, Dispense (AIQ), Tymber, Greenline, Cova-hosted |
| **C** | Iframe embed or client-rendered SPA | 5–8 | Dutchie embed, Jane embed, Buddi, CSR React |
| **F** | No e-commerce detected | 0 | |

Modifiers: −5 for shop-on-subdomain, +3 for searchable terpene taxonomy,
+2 for minor-cannabinoid taxonomy.

Things it deliberately does **not** score: ad pixels (reported as info —
paid-social tracking is a strategy choice), and Google Search Console when
it isn't visible in the HTML (GSC is often verified via DNS/GA/GTM, which
no scanner can see — so absence is a zero-point advisory, never a penalty).

## Run it yourself

Requires Python 3.10+.

```bash
git clone https://github.com/xlsuite/dispensary-report-card.git
cd dispensary-report-card
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

**CLI — scan one site, no web server:**

```bash
python report_card.py https://some-dispensary.com            # text + HTML report
python report_card.py https://some-dispensary.com --json     # machine-readable
```

**Web app — the full dispensarystack.com experience locally:**

```bash
export DB_PATH=./reports.db          # where SQLite lives
export ADMIN_KEY=dev-secret          # enables /admin?key=... locally
# export GOOGLE_PLACES_API_KEY=...   # optional: unlocks deep GBP checks
uvicorn app:app --reload --port 8000
# open http://localhost:8000
```

**Tests** (fully offline — the network is mocked with realistic fixtures):

```bash
python -m pytest test_report_card.py
```

Hosting it for real (Render, custom domain, persistent disk, Places API
setup) is a separate, deliberately hand-holdy guide: see [DEPLOY.md](DEPLOY.md).

## Using the scanner in your own code

`report_card.py` has no web dependencies — import it directly:

```python
import report_card

report = report_card.scan("https://some-dispensary.com")
print(report.overall_percent, report.overall_letter)
for cat in report.categories:
    print(cat.label, cat.percent, cat.letter)
html = report_card.render_html(report)   # self-contained report page
```

The `--json` CLI output is stable enough to pipe into your own dashboards.

## Contributing

The highest-value contribution is a **detection signature** for a platform
we don't recognize yet — POS systems, cannabis e-commerce providers, loyalty
programs, ESPs. It's usually a few lines: a regex in the `SIGS` dict, a
scoring hook, and a test with a realistic HTML fixture.

[CONTRIBUTING.md](CONTRIBUTING.md) walks through it, including the two rules
we've learned the hard way:

1. **Detect against raw HTML, not the rendered DOM.** The scanner never runs
   JavaScript. Modern Klaviyo forms, for example, exist in raw HTML only as
   an empty placeholder div — that's what the signature must match.
2. **Fixtures must mirror reality.** A sanitized fixture once hid a bug that
   broke product discovery on every real WordPress site (real sitemap
   indexes include `<lastmod>`; our test fixture didn't).

Found a site the scanner grades wrongly? Open an issue with the URL and a
view-source snippet — false positives and false negatives are both bugs.

## Honest limitations

- Detects that abandoned-cart / post-purchase **capability** is installed;
  can't verify the flows actually fire.
- Can't see server-side analytics (Measurement Protocol et al.).
- Local pack *ranking* isn't checked (needs a SERP API; deferred).
- A site behind an aggressive firewall may refuse both our honest
  user-agent and the browser-UA retry; the report says so rather than
  grading garbage.

## License & credits

MIT. Built by [BudMafia.com](https://budmafia.com) in partnership with
[Poof.ca](https://poof.ca) and
[FullBloomAdvisory.com](https://fullbloomadvisory.com). Use it, fork it,
run it for your own market.
