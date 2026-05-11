"""
Resume Builder
Generates ATS-optimized resume bullets and cover letters tailored to each job.
Runs automatically for all PRIME and STRONG jobs after scoring.

Usage:
    python resume_builder.py
"""

import sqlite3
import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import anthropic

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("logs/resume_builder.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

DB_PATH = Path("data/jobs.db")

# ── Resume bullet format rules ─────────────────────────────────────
# Based on Anurag's actual resume style. Every generated bullet must
# follow this exact pattern.
ATS_RULES = """
BULLET FORMAT RULES (match exactly):

1. ACTION VERB FIRST: Start with a strong past-tense verb.
   Good verbs: Designed, Built, Implemented, Trained, Automated, Led, Collaborated,
               Utilized, Spearheaded, Optimized, Deployed, Developed.

2. TOOLS IN CONTEXT: Never list tools alone. Show them doing work.
   BAD:  "Used Python and SQL."
   GOOD: "Built Python machine learning pipelines for patient data transformation."

3. QUANTIFY WITH SPECIFICS: Every bullet needs a real metric — %, count, time, or scale.
   BAD:  "Improved performance."
   GOOD: "Cutting analytical turnaround time by 40% across 5 research projects."
   GOOD: "Reducing target identification time across 3+ therapeutic areas."

4. KEYWORD MIRROR: Use the job description's exact phrasing — not synonyms.
   If JD says "machine learning models" write "machine learning models", not "ML algorithms".

5. LENGTH: One sentence per bullet, max two lines. No sub-bullets.

6. PROFESSIONAL SUMMARY: 2 sentences. First: role + years + core skills.
   Second: domain expertise and value delivered. Use exact keywords from JD.

EXAMPLE BULLETS (from Anurag's actual resume — match this style):
- "Designed and implemented an indication-finding analytical framework for drug development
   using embeddings, cosine similarity, and ranked scoring, reducing target identification
   time across 3+ therapeutic areas."
- "Built Python machine learning pipelines for patient data transformation and causal
   inference, deploying a Propensity Score Matching package on GitHub used across
   2 internal research teams."
- "Automated hypothesis testing workflows in Python using Chi-square and z-tests within
   an OOP framework, cutting analytical turnaround time by 40% across 5 research projects."
"""

# ── Candidate experience ───────────────────────────────────────────
# Raw experience bullets used as source material for tailored generation.
# Update this section if your experience changes.
CANDIDATE_EXPERIENCE = """
CURRENT: AbbVie | Data Analyst | Jul 2024 – Present
- Built indication finding framework for drug development using feature creation, linear algebra, embeddings, cosine similarity, ranked lists
- Collaborated with data engineers on ETL, SQL, Apache Spark, Hadoop, Cloudera CML, cloud services
- Developed OOP Python framework for patient data transformation and hypothesis tests (Chi-square, z-test)
- Deployed Python package on GitHub with feature selection, logistic regression, Propensity Score Matching
- Implemented statistical models for disease prevalence, generating Real World Evidence
- Works with EHR/OMOP data, ICD codes, NDC codes, OHDSI framework

PREVIOUS: Tata Technologies | Lead – Analytics | Feb 2022 – Jul 2023
- NLP to extract and prioritize top 10 customer pain points from complaint transcripts
- Created SOP for data acquirement; EDA on engine coolant temperature data
- Regression-based model for failure prediction, extending fan life by 30%
- Linear regression to model coolant temperature as function of engine load, RPM, ambient conditions

PREVIOUS: Force Motors | Business Analyst, Validation Analytics | Dec 2019 – Jan 2022
- Led team to enhance steering wheel returnability; data logging protocols; 20% improvement in steering functionality
- Spearheaded testing and data analysis of brake and clutch systems; reduced clutch pedal effort by 1kg

PREVIOUS: Tata Technologies | Sr. Engineer | Jul 2012 – Nov 2019
- Optimized minimum length flow path for hydraulic steering circuit; 5% reduction in circuit length
- Analyzed steering oil temperature data; recommended cooling loop integration

EDUCATION:
- MS Business Analytics, UC Irvine — Beta Gamma Sigma Award Recipient
- BE Engineering, Govt. College of Engineering, MH, India

SKILLS:
Python, SQL, R, Machine Learning, NLP, Git, Neural Networks, Deep Learning, LLM,
Data Visualization, Hadoop, Hive, AWS, PySpark, Cloudera CML, Keras, PyTorch,
TensorFlow, Scikit-learn, NumPy, Pandas, Statsmodels, Scipy, Matplotlib, Plotly, NLTK, SpaCy
"""

# ── Cover letter style ─────────────────────────────────────────────
# Based on Anurag's actual cover letter (Lyft application).
COVER_LETTER_STYLE = """
COVER LETTER FORMAT (follow exactly):

OPENING: "Dear Hiring Team,"

PARAGRAPH 1 — Why THIS company/role (3-4 sentences):
- Open with a specific detail about the company or team — not generic praise
- Name what drew you to this specific role/mission
- Connect it to the work you have been doing
- End with why this feels like the natural next step

PARAGRAPH 2 — Relevant experience (4-5 sentences):
- Lead with your most directly relevant experience for THIS job
- Name specific tools, methods, and outcomes with numbers
- Reference a second role/experience that maps to another requirement
- Be specific — mention actual techniques (propensity score matching, NLP, Spark, etc.)

PARAGRAPH 3 — The differentiator (3-4 sentences):
- What makes Anurag unusual or unexpected for this role
- Turn a potential weakness into a strength (e.g., clinical background for a tech role)
- Show a unique angle that other candidates won't have

PARAGRAPH 4 — Close (2 sentences):
- Thank them briefly
- Express interest in a conversation

SIGN-OFF: "Warmly,\nAnurag Patil"

STRICT RULES:
- Never use: "I am writing to express my interest", "I believe I would be a great fit",
  "Please find attached", "Do not hesitate to contact me", "passion for"
- Always use: specific company name, specific role name, at least one specific detail from JD
- Tone: confident and warm — like a smart colleague, not a formal applicant
- Length: 300-350 words exactly

EXAMPLE OPENING (match this style, not this content):
"Google Health and Fitbit sit at a rare intersection --- consumer technology with genuine
clinical stakes. When I read about the Health Data Science Team's mission to make everyone
in the world healthier by illuminating consumer and product understanding, I recognized
the exact problem I've been working on from the clinical side."
"""


def generate_application_materials(job_id: str, api_key: str) -> bool:
    """Generate tailored resume bullets and cover letter for a specific job."""
    client = anthropic.Anthropic(api_key=api_key)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    row = c.execute("""
        SELECT title, company, location, description, fit_reasoning
        FROM jobs WHERE id = ?
    """, (job_id,)).fetchone()

    if not row:
        log.error(f"Job {job_id} not found in database")
        conn.close()
        return False

    title, company, location, description, fit_reasoning_raw = row
    fit_reasoning = json.loads(fit_reasoning_raw) if fit_reasoning_raw else {}
    log.info(f"Generating materials for: {title} @ {company}")

    bullets_prompt = f"""You are writing ATS-optimized resume bullets for a candidate.

{ATS_RULES}

CANDIDATE EXPERIENCE (raw):
{CANDIDATE_EXPERIENCE}

TARGET JOB:
Title: {title}
Company: {company}
Location: {location}
Description:
{description[:3000]}

KEY MATCHES IDENTIFIED: {json.dumps(fit_reasoning.get('top_matches', []))}
INTERVIEW ANGLE: {fit_reasoning.get('interview_angle', '')}

Rewrite the candidate's resume bullets tailored to this specific job.
Return a JSON object with this structure:
{{
  "summary": "<2-sentence professional summary using keywords from this JD>",
  "abbvie_bullets": ["<bullet 1>", "<bullet 2>", "<bullet 3>", "<bullet 4>", "<bullet 5>"],
  "tata_analytics_bullets": ["<bullet 1>", "<bullet 2>", "<bullet 3>"],
  "force_motors_bullets": ["<bullet 1>", "<bullet 2>"],
  "tata_engineer_bullets": ["<bullet 1>"],
  "ats_keywords_used": ["<keyword1>", "<keyword2>"],
  "skills_to_highlight": ["<skill1>", "<skill2>"]
}}

Return ONLY the JSON object."""

    cover_prompt = f"""You are writing a cover letter for a candidate applying to a job.

{COVER_LETTER_STYLE}

CANDIDATE BACKGROUND:
- 12 years experience, 5+ in data science
- Currently: Data Analyst at AbbVie (EHR/OMOP data, RWE, Python, SQL, ML)
- Previous: Analytics Lead at Tata Technologies (NLP, predictive modeling, automotive)
- Previous: Business Analyst at Force Motors (validation analytics, automotive)
- MS Business Analytics, UC Irvine (Beta Gamma Sigma honor)
- Strong cross-functional communicator — bridges technical and clinical/business teams

TARGET JOB:
Title: {title}
Company: {company}
Location: {location}
Description:
{description[:2500]}

INTERVIEW ANGLE: {fit_reasoning.get('interview_angle', '')}
KEY MATCHES: {json.dumps(fit_reasoning.get('top_matches', []))}

Write the complete cover letter text only. No subject line, no date, no address block.
Start with "Dear Hiring Team," and end with "Warmly,\nAnurag Patil"."""

    try:
        bullets_resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1500,
            messages=[{"role": "user", "content": bullets_prompt}]
        )
        bullets_raw = bullets_resp.content[0].text.strip().replace("```json", "").replace("```", "").strip()
        bullets_data = json.loads(bullets_raw)

        cover_resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=700,
            messages=[{"role": "user", "content": cover_prompt}]
        )
        cover_letter = cover_resp.content[0].text.strip()

        c.execute("""
            UPDATE jobs SET tailored_bullets = ?, cover_letter = ?, resume_version = ?, status = 'ready'
            WHERE id = ?
        """, (json.dumps(bullets_data), cover_letter, f"tailored_{datetime.now().strftime('%Y%m%d')}", job_id))
        conn.commit()
        log.info(f"  >> Materials generated for {title} @ {company}")
        conn.close()
        return True

    except Exception as e:
        log.error(f"Generation failed for job {job_id}: {e}")
        conn.close()
        return False


def generate_for_prime_and_strong(api_key: str):
    """Auto-generate materials for all PRIME and STRONG jobs that don't have them yet."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    rows = c.execute("""
        SELECT id, title, company FROM jobs
        WHERE category IN ('PRIME', 'STRONG')
        AND (tailored_bullets IS NULL OR tailored_bullets = '')
        AND hard_rejected = 0
        ORDER BY fit_score DESC
        LIMIT 20
    """).fetchall()
    conn.close()

    log.info(f"Generating materials for {len(rows)} PRIME/STRONG jobs")
    for job_id, title, company in rows:
        log.info(f"Processing: {title} @ {company}")
        generate_application_materials(job_id, api_key)
        time.sleep(2)


def load_api_key(config_file: str = "config/config.json") -> Optional[str]:
    """Load Anthropic API key from config file."""
    path = Path(config_file)
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f).get("anthropic_api_key")


if __name__ == "__main__":
    api_key = load_api_key()
    if api_key:
        generate_for_prime_and_strong(api_key)
    else:
        log.error("No API key found — create config/config.json with your anthropic_api_key.")
