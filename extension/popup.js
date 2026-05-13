/**
 * popup.js — Job Scorer Chrome Extension
 * Handles scoring and material generation via the local api.py backend.
 */

const API_BASE = 'http://localhost:5000';

let jobData = null;     // raw data from LinkedIn page
let scoredJob = null;   // score result + job_id from /api/score

// ── Helpers ──────────────────────────────────────────────────────────

function showView(id) {
  document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
  document.getElementById(id).classList.add('active');
}

function showToast(msg, isError = false) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.style.background = isError ? '#ef4444' : '#334155';
  t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), isError ? 4000 : 2200);
}

function setLoadingMsg(msg) {
  document.getElementById('loading-msg').innerHTML = msg;
}

const CATEGORY_LABEL = {
  PRIME:   '🎯 PRIME — Apply now',
  STRONG:  '💪 STRONG — Good fit',
  EXPLORE: '🔍 EXPLORE — Review first',
  SKIP:    '⏭ SKIP — Poor fit',
};

// ── Get job data — injects content script if not already present ──────

async function getJobData(tab) {
  // Try messaging the already-injected content script first
  try {
    return await chrome.tabs.sendMessage(tab.id, { action: 'getJobData' });
  } catch (_) {
    // Content script not injected yet (tab was open before extension loaded).
    // Inject it now, then retry.
    await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      files: ['content.js']
    });
    return await chrome.tabs.sendMessage(tab.id, { action: 'getJobData' });
  }
}

// ── Init: read job from page ─────────────────────────────────────────

document.addEventListener('DOMContentLoaded', async () => {
  showView('view-loading');
  setLoadingMsg('Reading job from page…');

  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });

    if (!tab.url?.includes('linkedin.com/jobs')) {
      setLoadingMsg('Open a LinkedIn job posting to use Job Scorer.');
      return;
    }

    jobData = await getJobData(tab);

    if (!jobData?.title) {
      setLoadingMsg('Could not read job data.<br>Try scrolling the page, then reopen the extension.');
      return;
    }

    if (!jobData.description || jobData.description.length < 100) {
      setLoadingMsg('Job description not loaded yet.<br>Scroll down to the description section, then reopen.');
      return;
    }

    document.getElementById('job-title').textContent = jobData.title;
    document.getElementById('job-company').textContent =
      [jobData.company, jobData.location].filter(Boolean).join(' · ');

    showView('view-job');

  } catch (e) {
    setLoadingMsg('Could not read job data.<br>Try scrolling down to the full description, then reopen.');
    console.error(e);
  }
});

// ── Score ─────────────────────────────────────────────────────────────

document.getElementById('btn-score').addEventListener('click', async () => {
  showView('view-scoring');

  try {
    const resp = await fetch(`${API_BASE}/api/score`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(jobData)
    });

    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      throw new Error(err.error || `HTTP ${resp.status}`);
    }

    scoredJob = await resp.json();

    const score    = scoredJob.fit_score;
    const category = scoredJob.category;

    // Populate scored view
    document.getElementById('scored-title').textContent = jobData.title;
    document.getElementById('scored-company').textContent =
      [jobData.company, jobData.location].filter(Boolean).join(' · ');

    const fill = document.getElementById('score-fill');
    fill.style.width = `${score}%`;
    fill.className = `score-fill ${category.toLowerCase()}`;

    document.getElementById('score-value').textContent = `${score} / 100`;

    const badge = document.getElementById('score-badge');
    badge.textContent = CATEGORY_LABEL[category] || category;
    badge.className = `badge ${category.toLowerCase()}`;

    // Matches
    document.getElementById('score-matches').innerHTML =
      (scoredJob.top_matches || []).map(m => `<li>✅ ${m}</li>`).join('') ||
      '<li style="color:#64748b">None identified</li>';

    // Gaps
    document.getElementById('score-gaps').innerHTML =
      (scoredJob.gaps || []).map(g => `<li>⚠️ ${g}</li>`).join('') ||
      '<li style="color:#64748b">None identified</li>';

    document.getElementById('key-insight').textContent     = scoredJob.key_insight    || '—';
    document.getElementById('interview-angle').textContent = scoredJob.interview_angle || '—';

    // Hide generate button for SKIP
    document.getElementById('btn-generate').style.display =
      category === 'SKIP' ? 'none' : 'block';

    showView('view-scored');

  } catch (e) {
    showView('view-job');
    showToast(
      e.message.includes('Failed to fetch')
        ? 'Cannot reach api.py — run: python api.py'
        : `Scoring failed: ${e.message}`,
      true
    );
  }
});

// ── Generate materials ────────────────────────────────────────────────

document.getElementById('btn-generate').addEventListener('click', async () => {
  showView('view-generating');

  try {
    // Step 1: generate (saves bullets + cover letter to DB)
    const genResp = await fetch(`${API_BASE}/api/generate/${scoredJob.job_id}`, {
      method: 'POST'
    });
    if (!genResp.ok) {
      const err = await genResp.json().catch(() => ({}));
      throw new Error(err.error || `HTTP ${genResp.status}`);
    }

    // Step 2: fetch the saved materials
    const jobResp = await fetch(`${API_BASE}/api/jobs/${scoredJob.job_id}`);
    if (!jobResp.ok) throw new Error(`Could not load job (HTTP ${jobResp.status})`);
    const job = await jobResp.json();

    const tb = job.tailored_bullets || {};

    // Summary
    document.getElementById('summary-text').textContent = tb.summary || '—';

    // Bullets
    const bullets = tb.abbvie_bullets || [];
    document.getElementById('bullets-text').innerHTML =
      bullets.map(b => `<p>• ${b}</p>`).join('') ||
      '<p style="color:#64748b">No bullets generated.</p>';

    // Cover letter
    document.getElementById('cover-text').textContent = job.cover_letter || '—';

    showView('view-materials');

  } catch (e) {
    showView('view-scored');
    showToast(`Generation failed: ${e.message}`, true);
  }
});

// ── Back ──────────────────────────────────────────────────────────────

document.getElementById('btn-back').addEventListener('click', () => showView('view-scored'));

// ── Dashboard buttons ─────────────────────────────────────────────────

document.getElementById('btn-dashboard').addEventListener('click', () => {
  chrome.tabs.create({ url: `${API_BASE}` });
});
document.getElementById('btn-dashboard-2').addEventListener('click', () => {
  chrome.tabs.create({ url: `${API_BASE}` });
});

// ── Copy buttons ──────────────────────────────────────────────────────

document.getElementById('btn-copy-summary').addEventListener('click', () => {
  const text = document.getElementById('summary-text').textContent;
  navigator.clipboard.writeText(text).then(() => showToast('Summary copied!'));
});

document.getElementById('btn-copy-bullets').addEventListener('click', () => {
  const bullets = document.getElementById('bullets-text');
  // Join all bullet paragraphs as plain text
  const text = [...bullets.querySelectorAll('p')]
    .map(p => p.textContent)
    .join('\n');
  navigator.clipboard.writeText(text).then(() => showToast('Bullets copied!'));
});

document.getElementById('btn-copy-cover').addEventListener('click', () => {
  const text = document.getElementById('cover-text').textContent;
  navigator.clipboard.writeText(text).then(() => showToast('Cover letter copied!'));
});
