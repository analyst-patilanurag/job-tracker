"""
Job Tracker Scheduler
Runs the full pipeline every 6 hours:
  1. Scrape LinkedIn for new jobs
  2. Score new jobs with Claude AI
  3. Generate resume materials for PRIME + STRONG jobs
"""

import schedule
import time
import logging
import json
from pathlib import Path
from datetime import datetime

from scraper.linkedin_scraper import init_db, run_scraper, load_cookies
from scorer.job_scorer import process_pending_jobs
from resume_builder.resume_builder import generate_for_prime_and_strong

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("logs/scheduler.log"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)


def load_config() -> dict:
    config_path = Path("config/config.json")
    if not config_path.exists():
        log.error("config/config.json not found. See README for setup.")
        return {}
    with open(config_path) as f:
        return json.load(f)


def run_full_pipeline():
    log.info("▶ Pipeline starting...")
    config = load_config()
    if not config:
        return

    cookies = load_cookies()
    if not cookies:
        log.error("No cookies — skipping scrape")
        return

    api_key = config.get("anthropic_api_key")
    if not api_key:
        log.error("No Anthropic API key — skipping scoring")

    # Phase 1: Scrape
    log.info("Phase 1 — Scraping LinkedIn")
    run_scraper(cookies)

    # Phase 2: Score
    if api_key:
        log.info("Phase 2 — Scoring with Claude AI")
        process_pending_jobs(api_key)

        # Phase 3: Generate resume materials
        log.info("Phase 3 — Generating ATS-optimized resume materials")
        generate_for_prime_and_strong(api_key)

    log.info(f"▶ Pipeline complete at {datetime.now().strftime('%Y-%m-%d %H:%M')}")


def main():
    log.info("Job Tracker Scheduler starting...")
    init_db()

    # Run immediately on start
    run_full_pipeline()

    # Schedule every 6 hours
    schedule.every(6).hours.do(run_full_pipeline)

    log.info("Scheduler running. Pipeline will execute every 6 hours.")
    log.info("Press Ctrl+C to stop.")

    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    main()
