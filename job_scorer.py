"""
Job Scoring Engine
Uses Claude AI to evaluate each new job against the candidate's profile.
Classifies jobs into: PRIME (85+), STRONG (65-84), EXPLORE (40-64), SKIP (<40)

Usage:
    python job_scorer.py
"""

import sqlite3
import json
import logging
import time
from pathlib import Path
from typing import Optional

import anthropic

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("logs/scorer.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

DB_PATH = Path("data/jobs.db")

# ── Candidate profile ──────────────────────────────────────────────
# This is sent to Claude as context for every scoring call.
# Update this section if your experience or preferences change.
CANDIDATE_PROFILE = """
NAME: Anurag Patil
LOCATION: California, USA
EDUCATION: MS Business Analytics, UC Irvine (Beta Gamma Sigma – top 10% honor)
TOTAL EXPERIENCE: 12 years (5+ years data science/analytics)

CURRENT ROLE: Data Analyst at AbbVie (Jul 2024 – Present)
- Builds indication-finding frameworks using embeddings, cosine similarity, PCA
- ETL optimization with SQL, Apache Spark, Hadoop, Cloudera CML, AWS
- Object-oriented Python framework for patient data transformation and hypothesis testing
- Propensity Score Matching, logistic regression, feature selection — deployed as GitHub package
- Statistical models for disease prevalence / Real World Evidence (RWE) generation
- Works with EHR/OMOP data, ICD codes, NDC codes, OHDSI governance

PREVIOUS: Tata Technologies – Analytics Lead (Feb 2022 – Jul 2023)
- NLP on complaint transcripts to extract customer pain points
- Regression-based failure prediction for automotive components (30% life extension)
- EDA on engine coolant temperature; automated analytics pipelines

PREVIOUS: Force Motors – Business Analyst, Validation Analytics (Dec 2019 – Jan 2022)
- Steering wheel data analysis; 20% improvement in functionality
- Brake and clutch testing and optimization

PREVIOUS: Tata Technologies – Sr. Engineer (Jul 2012 – Nov 2019)
- Hydraulic steering circuit optimization

TECHNICAL SKILLS:
- Languages: Python (advanced), SQL (advanced), R
- ML/DL: Scikit-learn, TensorFlow, PyTorch, Keras, XGBoost
- NLP: NLTK, SpaCy, embeddings, cosine similarity
- Big Data: Spark, Hadoop, Hive, PySpark, Cloudera CML
- Cloud: AWS, GCP (some familiarity)
- Viz: Plotly, Matplotlib, Tableau
- Stats: Hypothesis testing, regression, propensity score matching, survival analysis
- Domain: Healthcare/pharma, automotive, manufacturing

SALARY REQUIREMENT: $110,000+ per year
TARGET LOCATIONS: California, Texas, Illinois, Colorado, Ohio, Washington, North Carolina
TARGET INDUSTRIES: Tech, Healthcare/Pharma, Automotive, Manufacturing, Finance, Education
TARGET ROLES: Data Scientist, Data Analyst, Analytics Lead, ML Engineer, Senior Data Analyst

HARD FILTERS (auto-reject):
- "no sponsorship" or "no visa sponsorship" mentioned
- Salary clearly below $110K
- Location outside target states (unless remote)
"""

# ── Score thresholds ───────────────────────────────────────────────
SCORE_THRESHOLDS = {
    "PRIME":   (85, 100),
    "STRONG":  (65, 84),
    "EXPLORE": (40, 64),
    "SKIP":    (0,  39),
}


def get_category(score: int) -> str:
    """Map a numeric score to a job category label."""
    for category, (lo, hi) in SCORE_THRESHOLDS.items():
        if lo <= score <= hi:
            return category
    return "SKIP"


def score_job_with_claude(title: str, company: str, location: str,
                           description: str, client: anthropic.Anthropic) -> Optional[dict]:
    """Call Claude API to score and classify a single job posting."""
    prompt = f"""You are a career advisor evaluating job postings for a candidate.

CANDIDATE PROFILE:
{CANDIDATE_PROFILE}

JOB POSTING:
Title: {title}
Company: {company}
Location: {location}
Description:
{description[:3000]}

Return a JSON object with EXACTLY these fields:
{{
  "fit_score": <integer 0-100>,
  "category": <"PRIME" | "STRONG" | "EXPLORE" | "SKIP">,
  "top_matches": [<3-5 specific skills or experiences that directly match>],
  "gaps": [<1-3 areas where the candidate's background doesn't fully match>],
  "key_insight": <one sentence — the most important thing about this job for the candidate>,
  "salary_concern": <true if salary seems below $110K, false otherwise>,
  "visa_flag": <true if sponsorship is mentioned as not available, false otherwise>,
  "interview_angle": <one sentence — the unique angle the candidate should lead with>
}}

SCORING RUBRIC:
- 85-100 (PRIME):   Near-perfect skill match, right industry, right location, likely good salary
- 65-84  (STRONG):  Strong match on core skills, minor gaps, good industry fit
- 40-64  (EXPLORE): Partial match — transferable skills but clear gaps or uncertain salary
- 0-39   (SKIP):    Poor fit — major skill gaps, wrong industry, or red flags

Return ONLY the JSON object, no other text."""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=800,
            messages=[{"role": "user", "content": prompt}]
        )
        raw = response.content[0].text.strip().replace("```json", "").replace("```", "").strip()
        return json.loads(raw)
    except json.JSONDecodeError as e:
        log.error(f"JSON parse error for {title} at {company}: {e}")
        return {"fit_score": 0, "category": "SKIP", "top_matches": [], "gaps": [],
                "key_insight": "Scoring failed", "salary_concern": False,
                "visa_flag": False, "interview_angle": ""}
    except Exception as e:
        log.error(f"Claude API error: {e}")
        return None


def process_pending_jobs(api_key: str):
    """Score all pending (unscored) jobs in the database."""
    client = anthropic.Anthropic(api_key=api_key)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    rows = c.execute("""
        SELECT id, title, company, location, description
        FROM jobs
        WHERE category = 'pending' AND hard_rejected = 0 AND description != ''
        ORDER BY fetched_at DESC
        LIMIT 50
    """).fetchall()

    log.info(f"Found {len(rows)} jobs to score")

    for row in rows:
        job_id, title, company, location, description = row
        log.info(f"Scoring: {title} @ {company}")

        result = score_job_with_claude(title, company, location, description, client)
        if result is None:
            time.sleep(5)
            continue

        score = result.get("fit_score", 0)
        category = get_category(score)

        if result.get("visa_flag"):
            category = "SKIP"
            score = 0
            result["key_insight"] = "Auto-skipped: visa sponsorship not available"

        c.execute("""
            UPDATE jobs SET fit_score = ?, category = ?, fit_reasoning = ?, status = ?
            WHERE id = ?
        """, (score, category, json.dumps(result), "scored", job_id))
        conn.commit()
        log.info(f"  >> Score: {score} | Category: {category}")
        time.sleep(1.5)

    conn.close()
    log.info("Scoring complete.")


def load_api_key(config_file: str = "config/config.json") -> Optional[str]:
    """Load Anthropic API key from config file."""
    path = Path(config_file)
    if not path.exists():
        log.error(f"Config file not found: {config_file}")
        return None
    with open(path) as f:
        return json.load(f).get("anthropic_api_key")


if __name__ == "__main__":
    api_key = load_api_key()
    if api_key:
        process_pending_jobs(api_key)
    else:
        log.error("No API key found — create config/config.json with your anthropic_api_key.")
