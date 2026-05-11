# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Is

A personal job search automation pipeline for a single user (Anurag Patil). It scrapes LinkedIn, scores jobs with Claude AI, generates tailored resumes/cover letters, and provides a dashboard to track applications. All local, no cloud deployment.

## Running the Project

```bash
# Run full pipeline (scrape → score → generate), then repeat every 6 hours
python scheduler.py

# Run individual phases
python linkedin_scraper.py    # Phase 1: Scrape LinkedIn
python job_scorer.py          # Phase 2: Score with Claude API
python resume_builder.py      # Phase 3: Generate tailored materials

# Dashboard API only
python api.py                 # Starts Flask server at http://localhost:5000
```

No build step, no linting config, no test suite.

## Required Config Files (User-Created)

```
config/cookies.json   — LinkedIn session tokens: { "li_at": "...", "JSESSIONID": "..." }
config/config.json    — Anthropic API key: { "anthropic_api_key": "..." }
```

## Architecture

### Pipeline Phases

Data flows one-way through 4 phases, each updating the `jobs` SQLite table:

1. **`linkedin_scraper.py`** — Fetches job listings using LinkedIn session cookies (no password). Parses HTML with BeautifulSoup, applies hard rejection filters (no sponsorship, salary < $110K, location), deduplicates by MD5 hash of `title|company|url`. Inserts with `status='new'`, `category='pending'`.

2. **`job_scorer.py`** — Takes `category='pending'` jobs, sends to Claude API with `ANURAG_PROFILE` context. Returns `fit_score` (0–100) and `category` (PRIME/STRONG/EXPLORE/SKIP). Updates DB with score and reasoning JSON.

3. **`resume_builder.py`** — Runs on PRIME and STRONG jobs only. Generates ATS-optimized tailored resume bullets and a cover letter (300–350 words) per job. Stores as JSON in `tailored_bullets` and `cover_letter` columns.

4. **`api.py` + `dashboard.html`** — Flask REST API serves a single-page dashboard. User reviews scored jobs, copies tailored materials, and manually applies. User updates `applied_at`, `interview_status`, `notes` via the UI.

### Key Architectural Decisions

- **Database:** SQLite at `data/jobs.db`, raw SQL (no ORM), JSON stored as TEXT in columns
- **Scheduling:** `schedule` library, single-threaded, blocking — everything runs synchronously
- **Rate limiting:** `time.sleep()` between requests (1.5s scraper, 1.5s scorer, 2s resume builder)
- **No auth:** Single-user local tool; LinkedIn auth is cookie-based
- **Dashboard:** Self-contained `dashboard.html` (~45KB), no build step, vanilla JS

### Job Categories

| Category | Score | Meaning |
|----------|-------|---------|
| PRIME | 85–100 | Apply immediately |
| STRONG | 65–84 | Good fit, generate materials |
| EXPLORE | 40–64 | Partial fit, manual review |
| SKIP | 0–39 | Poor fit |

### Hardcoded Profile Data

`ANURAG_PROFILE` in `job_scorer.py` and `ANURAG_FULL_EXPERIENCE` in `resume_builder.py` contain the candidate's background, target roles, and hard filter criteria. These must be updated if the user's profile changes.

### REST API Endpoints

```
GET  /api/jobs?category=PRIME&status=new  — List jobs with filters
GET  /api/jobs/<id>                        — Job detail
PATCH /api/jobs/<id>                       — Update application status
GET  /api/stats                            — Summary counts
POST /api/generate/<id>                    — On-demand material generation
```

### Running from Project Root

All modules use `Path("data/jobs.db")` and `Path("config/...")` relative to cwd. Always run scripts from the project root directory.
