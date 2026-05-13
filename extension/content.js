/**
 * content.js — runs on LinkedIn job pages
 * Extracts job title, company, location, and description from the DOM.
 * Responds to messages from popup.js.
 */

function extractJobData() {
  // ── Title ──────────────────────────────────────────────
  const titleSelectors = [
    'h1.job-details-jobs-unified-top-card__job-title',
    '.job-details-jobs-unified-top-card__job-title',
    'h1.t-24',
    'h1'
  ];
  let title = '';
  for (const sel of titleSelectors) {
    const el = document.querySelector(sel);
    if (el && el.innerText.trim()) { title = el.innerText.trim(); break; }
  }

  // ── Company ────────────────────────────────────────────
  const companySelectors = [
    '.job-details-jobs-unified-top-card__company-name a',
    '.job-details-jobs-unified-top-card__company-name',
    '.jobs-unified-top-card__company-name a',
    '.jobs-unified-top-card__company-name'
  ];
  let company = '';
  for (const sel of companySelectors) {
    const el = document.querySelector(sel);
    if (el && el.innerText.trim()) { company = el.innerText.trim(); break; }
  }

  // ── Location ───────────────────────────────────────────
  // LinkedIn puts location in the primary description container, separated by ·
  // e.g. "San Francisco, CA (Hybrid) · 2 days ago · 312 applicants"
  let location = '';
  const primaryDesc = document.querySelector(
    '.job-details-jobs-unified-top-card__primary-description-container'
  );
  if (primaryDesc) {
    const parts = primaryDesc.innerText.split('·').map(s => s.trim()).filter(Boolean);
    for (const part of parts) {
      if (!part.match(/ago|applicant|repost/i) && part.length < 80) {
        location = part;
        break;
      }
    }
  }
  if (!location) {
    const bullets = document.querySelectorAll(
      '.job-details-jobs-unified-top-card__bullet, .jobs-unified-top-card__bullet'
    );
    for (const b of bullets) {
      const text = b.innerText.trim();
      if (text && !text.match(/ago|applicant/i)) { location = text; break; }
    }
  }

  // ── Description ────────────────────────────────────────
  const descSelectors = [
    '.jobs-description__content',
    '#job-details',
    '.jobs-box__html-content',
    '.job-details-jobs-unified-top-card__job-insight'
  ];
  let description = '';
  for (const sel of descSelectors) {
    const el = document.querySelector(sel);
    if (el && el.innerText.trim().length > 100) {
      description = el.innerText.trim();
      break;
    }
  }

  // ── Job URL (clean, no query params) ──────────────────
  const url = window.location.href.split('?')[0];

  return { title, company, location, description, url };
}

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.action === 'getJobData') {
    sendResponse(extractJobData());
  }
  return true;
});
