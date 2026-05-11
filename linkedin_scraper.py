"""
LinkedIn Job Scraper
Fetches jobs posted within the last 1-2 days based on configured search URLs.
Run manually whenever you want fresh jobs. Uses session cookies — no password required.

Usage:
    python linkedin_scraper.py
"""

import sqlite3
import json
import time
import hashlib
import logging
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse, parse_qs, quote

import requests
from bs4 import BeautifulSoup

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("logs/scraper.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

DB_PATH = Path("data/jobs.db")

# ── Search configuration ───────────────────────────────────────────
# Add or modify searches by role and location.
# Use LinkedIn job search URLs with filters applied.
SEARCH_CONFIGS = [
    {
        "label": "Data Scientist - USA",
        "url": "https://www.linkedin.com/jobs/search/?keywords=Data%20Scientist&location=United%20States&f_TPR=r86400",
    },
    {
        "label": "Data Analyst - USA",
        "url": "https://www.linkedin.com/jobs/search/?keywords=Data%20Analyst&location=United%20States&f_TPR=r86400",
    },
    {
        "label": "ML Engineer - USA",
        "url": "https://www.linkedin.com/jobs/search/?keywords=Machine%20Learning%20Engineer&location=United%20States&f_TPR=r86400",
    },
    {
        "label": "Analytics Lead - USA",
        "url": "https://www.linkedin.com/jobs/search/?keywords=Analytics%20Lead&location=United%20States&f_TPR=r86400",
    },
    {
        "label": "Data Scientist Healthcare - USA",
        "url": "https://www.linkedin.com/jobs/search/?keywords=Data%20Scientist%20Healthcare&location=United%20States&f_TPR=r86400",
        "title_filter": ["data scientist"],
    },
]

# ── Hard rejection filters ─────────────────────────────────────────
# Jobs containing any of these phrases (in title or description)
# are automatically rejected and not sent for scoring.
HARD_REJECT_PHRASES = [
    "no sponsorship",
    "no visa sponsorship",
    "must be authorized to work",
    "us citizen only",
    "secret clearance",
    "top secret",
]

# ── Location exclusions ────────────────────────────────────────────
# Jobs in these states are rejected regardless of role or score.
EXCLUDED_STATES = [
    "Hawaii", "HI",
    "Florida", "FL",
]

# Maximum age of job postings to accept (in days).
# Jobs older than this are skipped even if LinkedIn returns them.
MAX_JOB_AGE_DAYS = 1


def init_db():
    """Create the jobs table if it doesn't exist."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            title TEXT,
            company TEXT,
            location TEXT,
            url TEXT,
            description TEXT,
            salary_text TEXT,
            posted_date TEXT,
            fetched_at TEXT,
            search_label TEXT,
            status TEXT DEFAULT 'new',
            category TEXT DEFAULT 'pending',
            fit_score INTEGER DEFAULT 0,
            fit_reasoning TEXT,
            applied_at TEXT,
            interview_status TEXT,
            notes TEXT,
            resume_version TEXT,
            cover_letter TEXT,
            tailored_bullets TEXT,
            hard_rejected INTEGER DEFAULT 0,
            reject_reason TEXT
        )
    """)
    conn.commit()
    conn.close()
    log.info("Database initialized.")


def make_job_id(title: str, company: str, url: str) -> str:
    """Generate a stable unique ID for a job based on title, company, and URL."""
    raw = f"{title}|{company}|{url}"
    return hashlib.md5(raw.encode()).hexdigest()


def is_too_old(posted_date: str, max_days: int = MAX_JOB_AGE_DAYS) -> bool:
    """Return True if the posted_date text indicates the job is older than max_days."""
    if not posted_date:
        return False  # unknown date — let it through
    text = posted_date.lower().strip()
    if any(k in text for k in ("just now", "moment", "second", "minute", "hour")):
        return False
    match = re.search(r"(\d+)\s*(day|week|month)", text)
    if not match:
        return False
    num, unit = int(match.group(1)), match.group(2)
    if unit == "day":
        return num > max_days
    if unit == "week":
        return num * 7 > max_days
    return True  # months are always too old


def is_hard_rejected(text: str) -> tuple[bool, str]:
    """Check if a job's text contains any hard rejection phrases."""
    text_lower = text.lower()
    for phrase in HARD_REJECT_PHRASES:
        if phrase in text_lower:
            return True, phrase
    return False, ""


def is_excluded_location(location: str) -> tuple[bool, str]:
    """Check if a job's location is in an excluded state."""
    for state in EXCLUDED_STATES:
        if state.lower() in location.lower():
            return True, state
    return False, ""


def extract_salary_text(text: str) -> str:
    """Extract a salary range string from job description text, if present."""
    patterns = [
        r"\$[\d,]+\s*[-–]\s*\$[\d,]+",
        r"\$[\d,]+[kK]?\s*[-–]\s*\$?[\d,]+[kK]?",
        r"[\d,]+\s*[-–]\s*[\d,]+\s*per year",
        r"salary[:\s]+\$[\d,]+",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(0).strip()
    return ""


def fetch_jobs_from_search(config: dict, cookies: dict) -> list[dict]:
    """Scrape job listings using LinkedIn's guest jobs API."""
    params = parse_qs(urlparse(config["url"]).query)
    keywords = params.get("keywords", [""])[0]
    location = params.get("location", ["United States"])[0]

    guest_url = (
        "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
        f"?keywords={quote(keywords)}&location={quote(location)}&start=0"
    )
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/124.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    }

    jobs = []
    try:
        resp = requests.get(guest_url, headers=headers, timeout=15)
        if resp.status_code != 200:
            log.warning(f"Got status {resp.status_code} for {config['label']}")
            return jobs

        soup = BeautifulSoup(resp.text, "html.parser")
        job_cards = soup.find_all("li")
        log.info(f"Found {len(job_cards)} cards for: {config['label']}")

        title_filter = config.get("title_filter")
        for card in job_cards[:25]:
            try:
                title_el = card.find("h3", class_="base-search-card__title")
                company_el = card.find("h4", class_="base-search-card__subtitle")
                location_el = card.find("span", class_="job-search-card__location")
                link_el = card.find("a", class_="base-card__full-link")

                title = title_el.get_text(strip=True) if title_el else "Unknown Title"
                company = company_el.get_text(strip=True) if company_el else "Unknown Company"
                location = location_el.get_text(strip=True) if location_el else ""
                url = link_el["href"].split("?")[0] if link_el else ""

                if not url:
                    continue
                if title_filter and not any(kw in title.lower() for kw in title_filter):
                    continue

                jobs.append({
                    "title": title,
                    "company": company,
                    "location": location,
                    "url": url,
                    "search_label": config["label"],
                })
            except Exception as e:
                log.debug(f"Card parse error: {e}")
                continue

    except Exception as e:
        log.error(f"Request failed for {config['label']}: {e}")

    return jobs


def _extract_job_id(url: str) -> str:
    """Extract LinkedIn numeric job ID from a job URL.

    Handles both formats:
      /jobs/view/1234567890
      /jobs/view/data-scientist-at-company-1234567890
    """
    match = re.search(r"/jobs/view/[^/]*?-?(\d{6,})", url)
    return match.group(1) if match else ""


def fetch_job_description(url: str, cookies: dict) -> tuple[str, str]:
    """Fetch full job description and posted date using LinkedIn's guest job posting API."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/124.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    }

    job_id = _extract_job_id(url)
    if not job_id:
        return "", ""

    api_url = f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"
    try:
        resp = requests.get(api_url, headers=headers, cookies=cookies, timeout=15)
        if resp.status_code != 200:
            log.debug(f"Job detail API returned {resp.status_code} for job {job_id}")
            return "", ""

        soup = BeautifulSoup(resp.text, "html.parser")

        desc_el = (
            soup.find("div", class_=re.compile(r"show-more-less-html__markup")) or
            soup.find("section", class_=re.compile(r"description")) or
            soup.find("div", class_=re.compile(r"description"))
        )
        description = desc_el.get_text(separator="\n", strip=True) if desc_el else ""

        posted_date = ""
        time_el = soup.find("time")
        if time_el:
            posted_date = time_el.get("datetime") or time_el.get_text(strip=True)
        if not posted_date:
            span_el = soup.find("span", class_=re.compile(r"posted|time-ago"))
            if span_el:
                posted_date = span_el.get_text(strip=True)

        return description, posted_date

    except Exception as e:
        log.debug(f"Description fetch failed for job {job_id}: {e}")
        return "", ""


def save_job(job: dict) -> bool:
    """Insert a job into the database. Returns False if already exists."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    job_id = make_job_id(job["title"], job["company"], job["url"])

    if c.execute("SELECT id FROM jobs WHERE id = ?", (job_id,)).fetchone():
        conn.close()
        return False

    loc_excluded, loc_reason = is_excluded_location(job.get("location", ""))
    rejected, reason = is_hard_rejected(job.get("description", "") + " " + job["title"])
    if loc_excluded:
        rejected, reason = True, f"excluded state: {loc_reason}"

    salary_text = extract_salary_text(job.get("description", ""))

    c.execute("""
        INSERT INTO jobs (
            id, title, company, location, url, description,
            salary_text, posted_date, fetched_at, search_label,
            status, category, hard_rejected, reject_reason
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        job_id,
        job["title"],
        job["company"],
        job["location"],
        job["url"],
        job.get("description", ""),
        salary_text,
        job.get("posted_date", ""),
        datetime.now().isoformat(),
        job["search_label"],
        "rejected" if rejected else "new",
        "rejected" if rejected else "pending",
        1 if rejected else 0,
        reason if rejected else "",
    ))
    conn.commit()
    conn.close()
    return True


def run_scraper(cookies: dict):
    """Main scrape loop — fetches and saves jobs for all configured searches."""
    log.info("-" * 50)
    log.info(f"Scrape run started at {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    total_new = 0
    total_rejected = 0

    for config in SEARCH_CONFIGS:
        log.info(f"Fetching: {config['label']}")
        jobs = fetch_jobs_from_search(config, cookies)

        total_skipped_old = 0
        for job in jobs:
            if job["url"]:
                desc, posted = fetch_job_description(job["url"], cookies)
                job["description"] = desc
                job["posted_date"] = posted
                time.sleep(1.5)

            if is_too_old(job.get("posted_date", "")):
                total_skipped_old += 1
                continue

            is_new = save_job(job)
            if is_new:
                rejected, _ = is_hard_rejected(job.get("description", ""))
                if rejected:
                    total_rejected += 1
                else:
                    total_new += 1

        if total_skipped_old:
            log.info(f"  Skipped {total_skipped_old} jobs older than {MAX_JOB_AGE_DAYS} day(s)")

        time.sleep(3)

    log.info(f"Done. New jobs: {total_new} | Auto-rejected: {total_rejected}")
    log.info("-" * 50)


def load_cookies(cookie_file: str = "config/cookies.json") -> dict:
    """Load LinkedIn session cookies from config file."""
    path = Path(cookie_file)
    if not path.exists():
        log.error(f"Cookie file not found: {cookie_file}")
        log.error("Create config/cookies.json with your li_at and JSESSIONID values.")
        return {}
    with open(path) as f:
        return json.load(f)


if __name__ == "__main__":
    init_db()
    cookies = load_cookies()
    if cookies:
        run_scraper(cookies)
    else:
        log.error("No cookies found — scraper cannot run.")
