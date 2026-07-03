# ETF Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local static dashboard for the ETF theme pool, momentum ranking, and today's ETF pick.

**Architecture:** Use plain HTML/CSS/JavaScript in `web/` and read the existing CSV files from `outputs/`. Keep CSV parsing and formatting helpers in `web/app.js` so they can be unit-tested with Node.

**Tech Stack:** Static HTML, CSS, vanilla JavaScript, Node built-in `assert`, Python `http.server`.

---

### Tasks

- [ ] Create failing Node tests for CSV parsing, percentage formatting, money formatting, and ranking metrics.
- [ ] Implement `web/app.js` helper functions and browser rendering.
- [ ] Create `web/index.html` with dashboard sections for today pick, ranking, theme pool, and charts.
- [ ] Create `web/styles.css` with dense research-terminal layout.
- [ ] Run `node tests/web_dashboard.test.js`.
- [ ] Run `python -m unittest discover -s tests -v`.
- [ ] Serve locally with `python -m http.server 8000` and verify `http://localhost:8000/web/`.
