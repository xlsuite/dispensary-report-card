# Deploy Guide

Numbered, no-prior-experience-required path from "these files on my laptop"
to "a working public website at dispensarystack.com". Budget for the
whole thing: under 1 hour, $0/month for hosting + ~$10-15/year for the
domain.

You will need:
- A computer with internet (Mac/Windows/Linux)
- A credit card (for the domain)
- About 45 minutes
- Free accounts on GitHub, Namecheap (or any registrar), and Render

The plan, at a glance:
1. Buy the domain
2. Put the code in a GitHub repo
3. Connect that repo to Render
4. Point the domain at Render

---

## Part 1 — Buy the domain

You said you'd buy a separate domain. Cheapest reputable registrars in
Canada/US: **Namecheap**, **Cloudflare Registrar**, or **Porkbun**.
Cloudflare is the cheapest (sells at cost, no markup) but requires you to
use Cloudflare's DNS. Namecheap and Porkbun are very close in price and
easier for a first-timer. Pick one.

This guide uses **Namecheap** as the example. The steps are nearly identical
on the others.

1. Go to https://www.namecheap.com
2. Create an account if you don't have one. Use a real email — you'll need
   it for domain verification (ICANN requires this).
3. Search for `dispensarystack.com` (the domain this project is configured for). If you're starting fresh and that's taken, the code's references will need updating — search for `dispensarystack.com` across the repo and replace.
4. Add to cart. Make sure "Domain Privacy" (WHOIS Guard) is **on** — it's
   free at Namecheap and hides your home address from public WHOIS lookups.
5. Skip every upsell: don't add web hosting, don't add email, don't add SSL
   (Render gives you that free), don't add VPN.
6. Check out. Cost: ~$10-15 USD for the first year.
7. After purchase, look for the verification email from Namecheap. Click
   the link inside within 15 days or the domain gets suspended.

You now own the domain. We'll point it at Render later in Part 4.

---

## Part 2 — Put the code in GitHub

Render deploys from a Git repository. If you've never used GitHub: it's
free for public code, and a public repo is fine here — there's nothing
secret in this code.

### 2a. Install Git (if you don't have it)

- **Mac:** open Terminal, type `git --version` and press Enter. If it
  prompts to install Command Line Tools, click Install. Done.
- **Windows:** download https://git-scm.com/download/win and run the
  installer with all defaults.

### 2b. Create the GitHub account + repo

1. Go to https://github.com and sign up (or log in if you have an account).
2. Top-right, click the **+** icon → **New repository**.
3. Repository name: `dispensary-report-card`
4. Description (optional): "Free scoring tool for cannabis dispensary
   websites."
5. Visibility: **Public** is fine (and required for the free Render plan
   to read it without a token). Pick Private only if you have a strong
   reason; you'll need to grant Render access manually.
6. Don't check "Add README" or "Add .gitignore" — we already have those.
7. Click **Create repository**. GitHub shows a setup page; leave it open.

### 2c-alt. Upload without installing anything (recommended for non-developers)

You can skip Git entirely and upload through the browser:

1. On the new repo's setup page, click the **"uploading an existing file"**
   link (it's in the "Quick setup" box).
2. Drag ALL the files from this folder into the upload area — including
   the `samples` folder (drag the folder itself; GitHub keeps the structure).
3. Note: `.gitignore` starts with a dot, so Windows Explorer may hide it.
   It's nice to include but NOT required for the deploy to work — skip it
   if you can't see it.
4. Commit message: "Initial commit". Click **Commit changes**.
5. Skip section 2c below and go straight to Part 3.

### 2c. Push the code (terminal option)

On your computer, open Terminal (Mac) or Command Prompt (Windows) and run
these commands one by one. Replace `YOUR-USERNAME` with your actual GitHub
username. The folder path on the first line should be the folder where
these files live on your computer.

```bash
cd /path/to/the/folder/with/these/files
git init
git add .
git commit -m "Initial commit: dispensary report card"
git branch -M main
git remote add origin https://github.com/YOUR-USERNAME/dispensary-report-card.git
git push -u origin main
```

GitHub will prompt for your username and a "Personal Access Token" instead
of a password. To make one:
1. https://github.com/settings/tokens → **Generate new token (classic)**
2. Name: "deploy push", expiration: 30 days, scope: check the box for
   **repo** (that's all you need).
3. Copy the token. Paste it as the "password" when git asks.

After `git push` succeeds, refresh the GitHub repo page in your browser.
You should see `app.py`, `report_card.py`, `render.yaml`, etc. listed.

---

## Part 3 — Deploy to Render

1. Go to https://render.com and sign up. Use **"Sign in with GitHub"** —
   this gives Render the permission to read your repo without separate
   credentials.
2. Once logged in, click **+ New** in the top right → **Blueprint**.
3. Render shows your GitHub repos. Pick `dispensary-report-card`.
4. Render detects `render.yaml` automatically and proposes one Web Service.
5. Service name: `dispensary-report-card` (already set from render.yaml).
6. Region: pick **Oregon (US West)** or the one closest to your audience.
7. Click **Apply**.

Render now does these things automatically:
- Pulls your code
- Installs Python 3.11
- Runs `pip install -r requirements.txt` (~1 minute)
- Starts the server with the command in render.yaml
- Assigns you a default URL like `dispensary-report-card-xxxx.onrender.com`

Watch the build log on the Render dashboard. You're looking for the
final line saying **Your service is live**.

Once it's live, click the default URL. You should see the report card
landing page. **Test it once**: paste `https://stokd.ca/` and submit.
Wait 10-30 seconds. You should get a real report back.

If something errors out, scroll the Render logs — the error message tells
you exactly what's wrong. Most common issues:
- Free instance OOM (out of memory): rare for our scan, but if it happens,
  the fix is upgrade to Starter ($7/mo) or reduce the work the scanner does.
- DNS timeout: a target site is too slow. Not a bug in our code; the user
  just needs to try a different URL.

---

## Part 4 — Point your domain at Render

You have two URLs right now:
- Render's: `dispensary-report-card-xxxx.onrender.com` (works)
- Yours: `dispensarystack.com` (doesn't go anywhere yet)

We're going to make your domain point to Render's URL.

### 4a. Tell Render about your domain

1. In the Render dashboard, click your service.
2. Left sidebar: **Settings** → scroll to **Custom Domains** → **Add Custom Domain**.
3. Enter `dispensarystack.com` (no `https://`, no slashes).
4. Render gives you a CNAME target — something like
   `dispensary-report-card-xxxx.onrender.com`. **Copy it.**
5. Render also adds an entry for `www.dispensarystack.com` if you
   want. Yes, add it — most people type www without thinking.

### 4b. Add DNS records at Namecheap

1. Log into Namecheap → **Domain List** → click **Manage** next to your domain.
2. Click the **Advanced DNS** tab.
3. **Delete any existing CNAME or URL Redirect entries** (Namecheap adds
   defaults that interfere).
4. Add a new record:
   - Type: **CNAME Record**
   - Host: `www`
   - Value: `dispensary-report-card-xxxx.onrender.com` (paste from step 4a)
   - TTL: Automatic
5. Add another record for the root domain. Namecheap's free DNS doesn't
   support CNAME at the root (this is a longstanding DNS limitation), so
   use Namecheap's **ALIAS Record** (or "URL Redirect" → 301 → `https://www.dispensarystack.com`):
   - Type: **ALIAS Record** (if available)
   - Host: `@`
   - Value: `dispensary-report-card-xxxx.onrender.com`
   - TTL: Automatic
   - If ALIAS isn't an option, use **URL Redirect** with Type 301
     pointing to `https://www.dispensarystack.com`.

6. **Save** the changes.

### 4c. Wait for DNS, then verify

DNS changes propagate in 5 minutes to 24 hours; usually under an hour.

To check progress:
- https://dnschecker.org/#CNAME/www.dispensarystack.com — should
  eventually show the Render hostname globally.
- Or in Terminal: `dig www.dispensarystack.com CNAME`

Once DNS resolves:
1. Go back to Render → your service → **Settings** → **Custom Domains**.
2. The status next to your domain should change from **Pending** to
   **Verified**. Render auto-issues an SSL certificate via Let's Encrypt
   (takes ~1 minute after DNS resolves).
3. Open `https://dispensarystack.com` in a browser. Should work.

If the cert keeps showing **Pending** after an hour, the most likely cause
is a leftover Namecheap default record. Go back to Advanced DNS, look for
any extra records (CNAME `@`, URL redirect, parking page), delete them.

---

## Part 5 — Optional: Enable Google Business Profile checks

The scanner works without this step, but the "Local Search & GBP" category
(20% of the score) will only credit website-visible signals (Google Reviews
widget, embedded Maps, multi-store location pages). To unlock the deeper
checks — photos, ratings, review activity, UTM-on-website-link, multi-store
deep-link accuracy — connect Google's Places API.

Cost: Google gives you $200/month in free credit. One scan uses about
$0.04 of that, so the free tier covers ~5,000 scans/month. For a soft
launch this is effectively $0 ongoing.

### 5a. Create a Google Cloud project + enable Places API

1. Go to https://console.cloud.google.com/
2. Sign in with a Google account (use a real email — don't use a throwaway).
3. Top of the page next to the "Google Cloud" logo, click the project
   dropdown -> **New Project**.
4. Project name: `dispensary-report-card`. Click Create.
5. Wait ~20 seconds. The page header should now show the new project name.
6. In the left sidebar, **APIs & Services** -> **Library**.
7. Search for "Places API (New)" (the "New" one — not the legacy version).
8. Click it, then click **Enable**. Wait 30 seconds.

### 5b. Add a billing account

Google requires a billing account on file even to use the free tier.
You will NOT be charged unless usage exceeds the $200/mo free credit, and
you can set a budget alert in step 5d to make sure.

1. Left sidebar: **Billing** -> **Link a billing account** (or
   **Manage billing accounts** -> **Add billing account**).
2. Add a payment method. Google will pre-authorize $1 and refund it.
3. After billing is linked, the Places API will work.

### 5c. Create an API key

1. Left sidebar: **APIs & Services** -> **Credentials**.
2. Top of page: **+ Create Credentials** -> **API key**.
3. Google generates a key. **Copy it.** Treat it like a password.
4. Click **Edit API key** (or the pencil icon on the key row).
5. Under **API restrictions**, choose **Restrict key**.
6. Tick **Places API (New)** only. Save.
7. Under **Application restrictions**: leave as **None** for now (Render's
   IP changes per deploy; restricting by IP would break on every redeploy).
   If you want extra hardening later, restrict by HTTP referrer to
   `https://dispensarystack.com/*` and `https://*.onrender.com/*`.
8. Click **Save**.

### 5d. Set a budget alert (optional, recommended)

1. Left sidebar: **Billing** -> **Budgets & alerts** -> **+ Create budget**.
2. Name: "Places API safeguard". Budget amount: $10/month.
3. Alert thresholds: keep defaults (50%, 90%, 100%).
4. You'll get an email if a single month spends > $5 of real money, which
   would mean ~30,000 scans (way past anything reasonable for a soft
   launch). Acts as an early warning if something's looping.

### 5e. Add the key to Render

1. https://dashboard.render.com -> your `dispensary-report-card` service.
2. Left sidebar: **Environment** -> **Add Environment Variable**.
3. Key: `GOOGLE_PLACES_API_KEY`
   Value: paste the key from step 5c.
4. Click **Save Changes**. Render will redeploy automatically (~90 sec).

### 5f. Verify the key is working

1. After the redeploy finishes, run a scan on any dispensary with a
   physical storefront (e.g. `https://thehunnypot.com`).
2. In the report, scroll to the **Local Search & GBP** category. With the
   key active you should see Google-sourced checks (star rating, review
   count, photo count). Without it, those checks say the API key isn't
   configured.
3. If they still show as unconfigured: check the Render **Environment**
   tab for typos in the variable name, and check the Google Cloud console
   that **Places API (New)** is enabled and billing is linked.

---

## Part 6 — Lead capture (email gate + admin page)

The app stores every scan and gates the full report behind an email.
Two things to set up, both one-time:

### 6a. The persistent disk

`render.yaml` declares a 1 GB disk mounted at `/data` — the SQLite database
(reports + leads) lives there and survives deploys. When you push a commit
after adding the disk config, Render may ask you to approve the blueprint
change; approve it. Cost: about $0.25/month. Note: services with disks
have ~30-60 seconds of downtime during each deploy (no zero-downtime
deploys with disks) — a non-issue at this stage.

### 6b. The admin key

1. Render dashboard -> your service -> **Environment** -> **Add Environment
   Variable**.
2. Key: `ADMIN_KEY`. Value: a long random string (30+ characters — use a
   password generator). Treat it like a password; anyone with it can see
   your leads.
3. Save. After the redeploy:
   - Leads dashboard: `https://dispensarystack.com/admin?key=YOUR_KEY`
   - CSV export: `https://dispensarystack.com/admin.csv?key=YOUR_KEY`

If `ADMIN_KEY` is never set, the admin pages simply don't exist (404).

### 6c. CASL note (Canada)

The email gate stores a `marketing_consent` flag: it's 1 only when the
visitor ticked the optional "send me tips" checkbox. Emails with
consent=0 unlocked a report and nothing more — don't import those into
marketing campaigns. The CSV includes the flag so you can filter.

---

Done. The site is live, on your domain, with SSL, capturing leads.