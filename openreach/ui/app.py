"""Flask web application for OpenReach."""

from __future__ import annotations

import logging
from typing import Any

from flask import Flask, jsonify, render_template_string, request

from openreach.data.store import DataStore

logger = logging.getLogger(__name__)

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>OpenReach</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
               background: #0a0a0a; color: #e5e5e5; min-height: 100vh; }
        .container { max-width: 1200px; margin: 0 auto; padding: 2rem; }
        header { display: flex; justify-content: space-between; align-items: center;
                 margin-bottom: 2rem; border-bottom: 1px solid #262626; padding-bottom: 1rem; }
        h1 { font-size: 1.5rem; font-weight: 600; }
        h1 span { color: #7c3aed; }
        .status { font-size: 0.875rem; color: #737373; }
        .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                      gap: 1rem; margin-bottom: 2rem; }
        .stat-card { background: #171717; border: 1px solid #262626; border-radius: 0.75rem;
                     padding: 1.5rem; }
        .stat-card .label { font-size: 0.75rem; color: #737373; text-transform: uppercase;
                            letter-spacing: 0.05em; margin-bottom: 0.5rem; }
        .stat-card .value { font-size: 2rem; font-weight: 700; }
        .stat-card .value.green { color: #22c55e; }
        .stat-card .value.blue { color: #3b82f6; }
        .stat-card .value.yellow { color: #eab308; }
        .stat-card .value.red { color: #ef4444; }
        .section { background: #171717; border: 1px solid #262626; border-radius: 0.75rem;
                   padding: 1.5rem; margin-bottom: 1.5rem; }
        .section h2 { font-size: 1.125rem; margin-bottom: 1rem; }
        table { width: 100%; border-collapse: collapse; }
        th, td { text-align: left; padding: 0.75rem; border-bottom: 1px solid #262626; }
        th { font-size: 0.75rem; color: #737373; text-transform: uppercase;
             letter-spacing: 0.05em; }
        td { font-size: 0.875rem; }
        .badge { display: inline-block; padding: 0.125rem 0.5rem; border-radius: 9999px;
                 font-size: 0.75rem; font-weight: 500; }
        .badge-sent { background: #1e3a5f; color: #60a5fa; }
        .badge-replied { background: #14532d; color: #4ade80; }
        .badge-failed { background: #450a0a; color: #f87171; }
        .badge-pending { background: #422006; color: #fbbf24; }
        .btn { display: inline-flex; align-items: center; gap: 0.5rem; padding: 0.625rem 1.25rem;
               border-radius: 0.5rem; font-size: 0.875rem; font-weight: 500; cursor: pointer;
               border: none; transition: all 0.15s; }
        .btn-primary { background: #7c3aed; color: white; }
        .btn-primary:hover { background: #6d28d9; }
        .btn-danger { background: #dc2626; color: white; }
        .btn-danger:hover { background: #b91c1c; }
        .actions { display: flex; gap: 0.75rem; margin-bottom: 1.5rem; }
        .footer { text-align: center; padding: 2rem; color: #525252; font-size: 0.75rem; }
        .footer a { color: #737373; text-decoration: none; }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>Open<span>Reach</span></h1>
            <div class="status" id="agent-status">Agent: Idle</div>
        </header>

        <div class="stats-grid" id="stats">
            <div class="stat-card">
                <div class="label">Total Leads</div>
                <div class="value" id="stat-leads">--</div>
            </div>
            <div class="stat-card">
                <div class="label">Messages Sent</div>
                <div class="value green" id="stat-sent">--</div>
            </div>
            <div class="stat-card">
                <div class="label">Replies</div>
                <div class="value blue" id="stat-replied">--</div>
            </div>
            <div class="stat-card">
                <div class="label">Today</div>
                <div class="value yellow" id="stat-today">--</div>
            </div>
            <div class="stat-card">
                <div class="label">Failed</div>
                <div class="value red" id="stat-failed">--</div>
            </div>
            <div class="stat-card">
                <div class="label">Reply Rate</div>
                <div class="value" id="stat-rate">--%</div>
            </div>
        </div>

        <div class="actions">
            <button class="btn btn-primary" id="btn-start" onclick="startAgent()">Start Agent</button>
            <button class="btn btn-danger" id="btn-stop" onclick="stopAgent()" style="display:none">Stop Agent</button>
        </div>

        <div class="section">
            <h2>Recent Leads</h2>
            <table>
                <thead>
                    <tr>
                        <th>Name</th>
                        <th>Handle</th>
                        <th>Type</th>
                        <th>Location</th>
                        <th>Source</th>
                    </tr>
                </thead>
                <tbody id="leads-table">
                    <tr><td colspan="5" style="color: #525252">Loading...</td></tr>
                </tbody>
            </table>
        </div>

        <div class="footer">
            <p>OpenReach v{{ version }} -- <a href="https://github.com/Coolcorbinian/OpenReach">GitHub</a></p>
        </div>
    </div>

    <script>
        async function loadStats() {
            try {
                const res = await fetch('/api/stats');
                const data = await res.json();
                document.getElementById('stat-leads').textContent = data.total_leads;
                document.getElementById('stat-sent').textContent = data.total_sent;
                document.getElementById('stat-replied').textContent = data.total_replied;
                document.getElementById('stat-today').textContent = data.today_sent;
                document.getElementById('stat-failed').textContent = data.total_failed;
                document.getElementById('stat-rate').textContent = data.reply_rate + '%';
            } catch (e) { console.error('Failed to load stats', e); }
        }

        async function loadLeads() {
            try {
                const res = await fetch('/api/leads?limit=20');
                const leads = await res.json();
                const tbody = document.getElementById('leads-table');
                if (!leads.length) {
                    tbody.innerHTML = '<tr><td colspan="5" style="color:#525252">No leads imported yet. Use CLI: openreach import leads.csv</td></tr>';
                    return;
                }
                tbody.innerHTML = leads.map(l => `
                    <tr>
                        <td>${l.name || '-'}</td>
                        <td>${l.instagram_handle ? '@' + l.instagram_handle : '-'}</td>
                        <td>${l.business_type || '-'}</td>
                        <td>${l.location || '-'}</td>
                        <td>${l.source || '-'}</td>
                    </tr>
                `).join('');
            } catch (e) { console.error('Failed to load leads', e); }
        }

        async function startAgent() {
            document.getElementById('btn-start').style.display = 'none';
            document.getElementById('btn-stop').style.display = '';
            document.getElementById('agent-status').textContent = 'Agent: Running...';
            await fetch('/api/agent/start', { method: 'POST' });
        }

        async function stopAgent() {
            document.getElementById('btn-start').style.display = '';
            document.getElementById('btn-stop').style.display = 'none';
            document.getElementById('agent-status').textContent = 'Agent: Stopping...';
            await fetch('/api/agent/stop', { method: 'POST' });
        }

        loadStats();
        loadLeads();
        setInterval(loadStats, 10000);
    </script>
</body>
</html>"""


def create_app(config: dict[str, Any] | None = None) -> Flask:
    """Create the Flask application."""
    from openreach import __version__

    app = Flask(__name__)
    store = DataStore(config.get("data", {}).get("db_path", "") if config else "")

    @app.route("/")
    def index():  # type: ignore[no-untyped-def]
        return render_template_string(DASHBOARD_HTML, version=__version__)

    @app.route("/api/stats")
    def api_stats():  # type: ignore[no-untyped-def]
        return jsonify(store.get_stats())

    @app.route("/api/leads")
    def api_leads():  # type: ignore[no-untyped-def]
        limit = request.args.get("limit", 50, type=int)
        leads = store.get_leads(limit=limit)
        return jsonify(leads)

    @app.route("/api/agent/start", methods=["POST"])
    def api_agent_start():  # type: ignore[no-untyped-def]
        # TODO: Start agent in background thread
        return jsonify({"status": "started"})

    @app.route("/api/agent/stop", methods=["POST"])
    def api_agent_stop():  # type: ignore[no-untyped-def]
        # TODO: Signal agent to stop
        return jsonify({"status": "stopping"})

    return app
