#!/usr/bin/env python3
"""
ny-pay-hub/scripts/search-greenhouse.py
Greenhouse job board scraper — New York State edition.

Strategy:
  1. Seed slugs for known NY-present companies on Greenhouse
  2. Greenhouse public boards JSON API → all jobs per company (no auth needed)
  3. Salary extracted from job content HTML (regex) with double-unescape
  4. NY filter: location field OR content mentions "New York" / "NYC"

Run: python3 ~/ny-pay-hub/scripts/search-greenhouse.py
"""

import html as html_mod
import json
import os
import re
import sys
import time
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(__file__))
from _common import (
    make_logger, acquire_lock, load_existing_keys,
    write_job, TODAY, OUTPUT_FILE, NY_TERMS,
)

from scrapling import Fetcher

LOG_FILE  = os.path.expanduser("~/ny-pay-hub/scripts/greenhouse.log")
LOCK_FILE = os.path.expanduser("~/ny-pay-hub/scripts/.greenhouse.lock")
LOOKBACK_DATE = (date.today() - timedelta(days=60)).isoformat() + "T00:00:00.000Z"

log = make_logger(LOG_FILE)
fetcher = Fetcher()

SEED_SLUGS = [
    # ── Finance / Wall Street ─────────────────────────────────────────────────
    ("jpmorgan", None),            # JP Morgan Chase, NYC HQ
    ("goldmansachs", None),        # Goldman Sachs, NYC HQ
    ("morganstanley", None),       # Morgan Stanley, NYC HQ
    ("blackrock", None),           # BlackRock, NYC HQ
    ("bloomberg", None),           # Bloomberg LP, NYC HQ
    ("citadel", None),             # Citadel, Chicago/NYC
    ("twosigma", None),            # Two Sigma, NYC
    ("deshaw", None),              # D.E. Shaw, NYC
    ("pointtwo2", None),           # Point72, Stamford/NYC
    ("virtu", None),               # Virtu Financial, NYC
    ("fidelityinvestments", None), # Fidelity Investments
    ("vanguard", None),            # Vanguard, Valley Forge/remote
    ("pimco", None),               # PIMCO, Newport Beach/NYC
    ("blackstone", None),          # Blackstone, NYC
    ("apolloglobal", None),        # Apollo Global, NYC
    # ── Fintech / Payments ────────────────────────────────────────────────────
    ("stripe", None),              # Stripe, NYC office
    ("plaid", None),               # Plaid, NYC
    ("brex", None),                # Brex, NYC
    ("ramp", None),                # Ramp, NYC HQ
    ("navan", None),               # Navan (TripActions), NYC
    ("rippling", None),            # Rippling, NYC office
    ("bettercom", None),           # Better.com, NYC
    ("lemonade", None),            # Lemonade, NYC HQ
    ("oscar", None),               # Oscar Health, NYC HQ
    ("etsy", None),                # Etsy, NYC HQ
    ("squarespace", None),         # Squarespace, NYC HQ
    ("shutterstock", None),        # Shutterstock, NYC HQ
    # ── Big Tech NYC offices ──────────────────────────────────────────────────
    ("google", None),              # Google, NYC large office
    ("meta", None),                # Meta, NYC office
    ("amazon", None),              # Amazon, NYC large office
    ("apple", None),               # Apple, NYC
    ("microsoft", None),           # Microsoft, NYC
    ("salesforce", None),          # Salesforce, NYC
    ("databricks", None),          # Databricks, NYC
    ("datadog", None),             # Datadog, NYC HQ
    ("mongodb", None),             # MongoDB, NYC HQ
    ("cloudflare", None),          # Cloudflare, NYC
    ("twilio", None),              # Twilio, NYC office
    ("hashicorp", None),           # HashiCorp, NYC
    ("confluent", None),           # Confluent, NYC office
    ("snowflake", None),           # Snowflake, NYC office
    # ── Media / AdTech ───────────────────────────────────────────────────────
    ("nytimes", None),             # NY Times, NYC HQ
    ("buzzfeed", None),            # BuzzFeed, NYC
    ("voxmedia", None),            # Vox Media, NYC
    ("nbcuniversal", None),        # NBCUniversal, NYC HQ
    ("condenastvacancies", None),  # Condé Nast, NYC
    ("warnermedia", None),         # Warner Bros Discovery
    ("iheartmedia", None),         # iHeartMedia, NYC
    ("spotifyjobs", None),         # Spotify, NYC
    ("pandora", None),             # Pandora, NYC
    # ── Healthcare / Pharma ───────────────────────────────────────────────────
    ("pfizer", None),              # Pfizer, NYC HQ
    ("merck", None),               # Merck, Rahway NJ/NYC
    ("moodys", None),              # Moody's, NYC
    ("cvs", None),                 # CVS Health (NYC operations)
    # ── E-commerce / Retail ───────────────────────────────────────────────────
    ("warbyparker", None),         # Warby Parker, NYC HQ
    ("glossier", None),            # Glossier, NYC HQ
    ("rent-the-runway", None),     # Rent the Runway, NYC
    ("theredefinedgroup", None),   # NYC retail/fashion
    # ── Real Estate / PropTech ────────────────────────────────────────────────
    ("compass", None),             # Compass, NYC HQ
    ("streeteasy", None),          # StreetEasy/Zillow, NYC
    ("commonliving", None),        # Common Living, NYC
    # ── B2B / Enterprise SaaS ─────────────────────────────────────────────────
    ("pagerduty", None),           # PagerDuty, NYC
    ("gitlab", None),              # GitLab, remote/NYC
    ("atlassian", None),           # Atlassian, NYC
    ("zendesk", None),             # Zendesk, NYC
    ("brainware", None),
    ("hubspot", None),             # HubSpot, NYC
    ("intercom", None),            # Intercom, NYC
    ("amplitude", None),           # Amplitude, NYC
    ("mixpanel", None),            # Mixpanel, NYC
    # ── Travel / Hospitality ─────────────────────────────────────────────────
    ("airbnb", None),              # Airbnb, NYC office
    ("tripadvisor", None),         # TripAdvisor, NYC
    ("marriott", None),            # Marriott, NYC
    ("hilton", None),              # Hilton, NYC
]


SALARY_PATTERNS = [
    r'\$\s*([\d,]+)\s*[-–—]\s*\$\s*([\d,]+)',
    r'([\d,]+)\s*[-–—]\s*([\d,]+)\s*(?:USD|usd)',
    r'salary[:\s]+\$?([\d,]+)[kK]?\s*[-–—]\s*\$?([\d,]+)[kK]?',
    r'compensation[:\s]+\$?([\d,]+)[kK]?\s*[-–—]\s*\$?([\d,]+)[kK]?',
    r'pay range[:\s]+\$?([\d,]+)[kK]?\s*[-–—]\s*\$?([\d,]+)[kK]?',
    r'pay scale[:\s]+\$?([\d,]+)[kK]?\s*[-–—]\s*\$?([\d,]+)[kK]?',
    r'"salary_min":\s*(\d+).*?"salary_max":\s*(\d+)',
    r'"min_salary":\s*(\d+).*?"max_salary":\s*(\d+)',
]


def parse_salary_from_text(text: str):
    if not text:
        return None, None
    text = html_mod.unescape(html_mod.unescape(text))
    for pat in SALARY_PATTERNS:
        m = re.search(pat, text, re.IGNORECASE | re.DOTALL)
        if m:
            try:
                raw_min = m.group(1).replace(",", "")
                raw_max = m.group(2).replace(",", "")
                val_min = int(float(raw_min))
                val_max = int(float(raw_max))
                if raw_min.lower().endswith('k') or (val_min < 1000 and val_max < 1000):
                    val_min *= 1000
                    val_max *= 1000
                if val_min < 1000:
                    val_min *= 1000
                if val_max < 1000:
                    val_max *= 1000
                if 30_000 <= val_min < val_max <= 1_500_000:
                    return val_min, val_max
            except (ValueError, IndexError):
                continue
    return None, None



_CANADA_EXCL = [
    "british columbia", "ontario, canada", "alberta, canada", "quebec, canada",
    "toronto", "vancouver", "montreal", "calgary", "ottawa", "edmonton",
    ", canada", "canada,", "remote - canada", "remote - alberta",
    "remote - ontario", "remote - british columbia", "remote - quebec",
]

_REMOTE_TERMS = ("remote", "distributed", "virtual", "anywhere", "work from", "wfh")

def is_ny_job(title: str, location: str, content: str) -> bool:
    loc_low = location.lower()
    if any(t in loc_low for t in _CANADA_EXCL):
        return False
    # Location-first: only match if location field explicitly names NY
    if any(t in loc_low for t in NY_TERMS):
        return True
    # Remote/unspecified jobs are NY-eligible (NY law covers remote roles open to NY workers)
    if not loc_low or any(r in loc_low for r in _REMOTE_TERMS):
        return True
    return False


def fetch_company_jobs(slug: str, company_name_override=None):
    url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
    try:
        resp = fetcher.get(url, timeout=20)
        data = resp.json()
    except Exception as e:
        log(f"  [{slug}] API error: {e}")
        return []

    jobs_raw = data.get("jobs", [])
    if not jobs_raw:
        return []

    company_name = company_name_override or data.get("company", {}).get("name") or slug.title()
    results = []

    for j in jobs_raw:
        updated_at = j.get("updated_at", "")
        if updated_at and updated_at < LOOKBACK_DATE:
            continue

        title = j.get("title", "").strip()
        location_obj = j.get("location", {})
        location = location_obj.get("name", "") if isinstance(location_obj, dict) else str(location_obj)
        content_html = j.get("content", "")
        content_text = re.sub(r'<[^>]+>', ' ', content_html)
        content_text = html_mod.unescape(content_text)

        if not is_ny_job(title, location, content_text):
            continue

        val_min, val_max = parse_salary_from_text(content_html + " " + content_text)
        if val_min is None:
            val_min, val_max = parse_salary_from_text(str(j))

        if val_min is None:
            continue

        posted_date = updated_at[:10] if updated_at else TODAY
        job_url = j.get("absolute_url") or f"https://boards.greenhouse.io/{slug}/jobs/{j.get('id','')}"

        results.append({
            "role": title,
            "company": company_name,
            "min": val_min,
            "max": val_max,
            "location": location or "New York, NY",
            "source_url": job_url,
            "posted": posted_date,
            "source_platform": "greenhouse",
        })

    return results


def main():
    if not acquire_lock(LOCK_FILE, log):
        return

    log("=== NY Greenhouse scraper started ===")
    existing = load_existing_keys()
    log(f"Existing dedup keys: {len(existing)}")

    new_count = 0
    for slug, name_override in SEED_SLUGS:
        log(f"[{slug}] fetching...")
        jobs = fetch_company_jobs(slug, name_override)
        for job in jobs:
            key = f"{job['role'].lower().strip()}|{job['company'].lower().strip()}"
            if key in existing:
                continue
            write_job(OUTPUT_FILE, job)
            existing.add(key)
            new_count += 1
            log(f"  + {job['role']} @ {job['company']} | ${job['min']:,}–${job['max']:,} | {job['location']}")
        time.sleep(0.5)

    log(f"=== Done. {new_count} new NY jobs written to {OUTPUT_FILE} ===")


if __name__ == "__main__":
    main()
