"""
Job Tracker API
Flask server that serves the dashboard and provides REST endpoints
for reading and updating job data from SQLite.

Usage:
    python api.py
    Open http://localhost:5000 in your browser.
"""

import sqlite3
import json
from pathlib import Path
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

app = Flask(__name__, static_folder=".")
CORS(app)

DB_PATH = Path("data/jobs.db")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def row_to_dict(row):
    """Convert a database row to a dict, parsing JSON fields."""
    d = dict(row)
    for field in ["fit_reasoning", "tailored_bullets"]:
        if d.get(field):
            try:
                d[field] = json.loads(d[field])
            except (json.JSONDecodeError, TypeError):
                pass
    return d


@app.route("/")
def index():
    return send_from_directory(".", "dashboard.html")


@app.route("/api/jobs", methods=["GET"])
def get_jobs():
    """Return all non-rejected jobs, optionally filtered by category or status."""
    conn = get_db()
    category = request.args.get("category")
    status = request.args.get("status")

    query = "SELECT * FROM jobs WHERE hard_rejected = 0"
    params = []

    if category:
        query += " AND category = ?"
        params.append(category)
    if status:
        query += " AND status = ?"
        params.append(status)

    query += " ORDER BY fit_score DESC, fetched_at DESC"

    rows = conn.execute(query, params).fetchall()
    conn.close()
    return jsonify([row_to_dict(r) for r in rows])


@app.route("/api/jobs/<job_id>", methods=["GET"])
def get_job(job_id):
    """Return a single job by ID."""
    conn = get_db()
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    conn.close()
    if not row:
        return jsonify({"error": "Not found"}), 404
    return jsonify(row_to_dict(row))


@app.route("/api/jobs/<job_id>", methods=["PATCH"])
def update_job(job_id):
    """Update application tracking fields for a job."""
    data = request.json
    allowed = ["applied_at", "interview_status", "notes", "status"]
    updates = {k: v for k, v in data.items() if k in allowed}

    if not updates:
        return jsonify({"error": "No valid fields provided"}), 400

    conn = get_db()
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [job_id]
    conn.execute(f"UPDATE jobs SET {set_clause} WHERE id = ?", values)
    conn.commit()
    conn.close()
    return jsonify({"success": True})


@app.route("/api/stats", methods=["GET"])
def get_stats():
    """Return summary counts for the dashboard header."""
    conn = get_db()
    c = conn.cursor()
    stats = {
        "total":      c.execute("SELECT COUNT(*) FROM jobs WHERE hard_rejected = 0").fetchone()[0],
        "prime":      c.execute("SELECT COUNT(*) FROM jobs WHERE category = 'PRIME'").fetchone()[0],
        "strong":     c.execute("SELECT COUNT(*) FROM jobs WHERE category = 'STRONG'").fetchone()[0],
        "explore":    c.execute("SELECT COUNT(*) FROM jobs WHERE category = 'EXPLORE'").fetchone()[0],
        "applied":    c.execute("SELECT COUNT(*) FROM jobs WHERE applied_at IS NOT NULL").fetchone()[0],
        "interviews": c.execute("SELECT COUNT(*) FROM jobs WHERE interview_status IN ('phone_screen','technical','final','offer')").fetchone()[0],
        "offers":     c.execute("SELECT COUNT(*) FROM jobs WHERE interview_status = 'offer'").fetchone()[0],
        "rejected":   c.execute("SELECT COUNT(*) FROM jobs WHERE hard_rejected = 1").fetchone()[0],
        "last_scrape": c.execute("SELECT MAX(fetched_at) FROM jobs").fetchone()[0],
    }
    conn.close()
    return jsonify(stats)


@app.route("/api/generate/<job_id>", methods=["POST"])
def generate_materials(job_id):
    """Trigger on-demand resume and cover letter generation for a specific job."""
    try:
        from resume_builder import generate_application_materials, load_api_key
        api_key = load_api_key()
        if not api_key:
            return jsonify({"error": "No API key configured in config/config.json"}), 400
        success = generate_application_materials(job_id, api_key)
        return jsonify({"success": success})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    print("Starting Job Tracker API at http://localhost:5000")
    print("Open http://localhost:5000 in your browser to view the dashboard.")
    app.run(debug=True, port=5000)
