"""Flask web application for OpenReach."""

from __future__ import annotations

import logging
from typing import Any

from flask import Flask, jsonify, render_template_string, request

from openreach.config import load_config, save_config_value
from openreach.data.cormass_api import CormassApiClient
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
        .btn-secondary { background: #262626; color: #e5e5e5; border: 1px solid #404040; }
        .btn-secondary:hover { background: #333333; }
        .btn-success { background: #16a34a; color: white; }
        .btn-success:hover { background: #15803d; }
        .btn:disabled { opacity: 0.5; cursor: not-allowed; }
        .actions { display: flex; gap: 0.75rem; margin-bottom: 1.5rem; }
        .footer { text-align: center; padding: 2rem; color: #525252; font-size: 0.75rem; }
        .footer a { color: #737373; text-decoration: none; }

        /* Tabs */
        .tabs { display: flex; gap: 0; margin-bottom: 1.5rem; border-bottom: 1px solid #262626; }
        .tab { padding: 0.75rem 1.25rem; font-size: 0.875rem; font-weight: 500; cursor: pointer;
               color: #737373; border-bottom: 2px solid transparent; transition: all 0.15s;
               background: none; border-top: none; border-left: none; border-right: none; }
        .tab:hover { color: #e5e5e5; }
        .tab.active { color: #7c3aed; border-bottom-color: #7c3aed; }
        .tab-content { display: none; }
        .tab-content.active { display: block; }

        /* Forms */
        .form-group { margin-bottom: 1.25rem; }
        .form-group label { display: block; font-size: 0.75rem; color: #737373;
                            text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 0.5rem; }
        .form-input { width: 100%; padding: 0.625rem 0.75rem; background: #0a0a0a;
                      border: 1px solid #404040; border-radius: 0.5rem; color: #e5e5e5;
                      font-size: 0.875rem; font-family: inherit; }
        .form-input:focus { outline: none; border-color: #7c3aed; }
        .form-input::placeholder { color: #525252; }
        .form-row { display: flex; gap: 0.75rem; align-items: flex-end; }
        .form-row .form-group { flex: 1; margin-bottom: 0; }

        /* Canvas list */
        .canvas-list { display: flex; flex-direction: column; gap: 0.5rem; }
        .canvas-item { display: flex; justify-content: space-between; align-items: center;
                       padding: 0.875rem 1rem; background: #0a0a0a; border: 1px solid #262626;
                       border-radius: 0.5rem; transition: border-color 0.15s; }
        .canvas-item:hover { border-color: #404040; }
        .canvas-info { flex: 1; }
        .canvas-name { font-weight: 500; font-size: 0.9375rem; }
        .canvas-meta { font-size: 0.75rem; color: #737373; margin-top: 0.25rem; }
        .canvas-actions { display: flex; gap: 0.5rem; align-items: center; }

        /* Status indicators */
        .status-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%;
                      margin-right: 0.5rem; }
        .status-dot.connected { background: #22c55e; }
        .status-dot.disconnected { background: #ef4444; }
        .status-dot.checking { background: #eab308; }

        /* Toast / notification */
        .toast { position: fixed; bottom: 2rem; right: 2rem; padding: 0.875rem 1.25rem;
                 border-radius: 0.5rem; font-size: 0.875rem; z-index: 1000;
                 transform: translateY(120%); transition: transform 0.3s ease; max-width: 400px; }
        .toast.show { transform: translateY(0); }
        .toast-success { background: #14532d; color: #4ade80; border: 1px solid #166534; }
        .toast-error { background: #450a0a; color: #f87171; border: 1px solid #7f1d1d; }
        .toast-info { background: #1e3a5f; color: #60a5fa; border: 1px solid #1e40af; }

        /* Loading spinner */
        .spinner { display: inline-block; width: 16px; height: 16px; border: 2px solid #404040;
                   border-top-color: #7c3aed; border-radius: 50%; animation: spin 0.6s linear infinite; }
        @keyframes spin { to { transform: rotate(360deg); } }

        /* Import progress */
        .import-progress { padding: 1rem; background: #0a0a0a; border: 1px solid #262626;
                           border-radius: 0.5rem; margin-top: 1rem; display: none; }
        .progress-bar-container { width: 100%; height: 6px; background: #262626;
                                   border-radius: 3px; overflow: hidden; margin-top: 0.5rem; }
        .progress-bar { height: 100%; background: #7c3aed; border-radius: 3px;
                        transition: width 0.3s ease; width: 0%; }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>Open<span>Reach</span></h1>
            <div class="status" id="agent-status">Agent: Idle</div>
        </header>

        <div class="tabs">
            <button class="tab active" onclick="switchTab('dashboard')">Dashboard</button>
            <button class="tab" onclick="switchTab('import')">Import Leads</button>
            <button class="tab" onclick="switchTab('settings')">Settings</button>
        </div>

        <!-- DASHBOARD TAB -->
        <div class="tab-content active" id="tab-dashboard">
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
                            <th>Rating</th>
                            <th>Source</th>
                        </tr>
                    </thead>
                    <tbody id="leads-table">
                        <tr><td colspan="6" style="color: #525252">Loading...</td></tr>
                    </tbody>
                </table>
            </div>
        </div>

        <!-- IMPORT LEADS TAB -->
        <div class="tab-content" id="tab-import">
            <div class="section">
                <h2>Import from Cormass Leads</h2>
                <p style="color: #737373; font-size: 0.875rem; margin-bottom: 1.25rem;">
                    Pull leads directly from your Cormass Leads canvases using your API key.
                    Configure your API key in the Settings tab first.
                </p>

                <div id="import-connection-status" style="margin-bottom: 1.25rem;">
                    <span class="status-dot checking"></span>
                    <span style="color: #737373; font-size: 0.875rem;">Checking connection...</span>
                </div>

                <div id="canvas-section" style="display: none;">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem;">
                        <h3 style="font-size: 1rem; font-weight: 500;">Available Canvases</h3>
                        <button class="btn btn-secondary" onclick="loadCanvases()" style="font-size: 0.75rem; padding: 0.375rem 0.75rem;">
                            Refresh
                        </button>
                    </div>
                    <div class="canvas-list" id="canvas-list">
                        <div style="color: #525252; font-size: 0.875rem;">Loading canvases...</div>
                    </div>
                </div>

                <div id="no-api-key-notice" style="display: none;">
                    <div style="padding: 1.5rem; background: #1a1a2e; border: 1px solid #262650; border-radius: 0.5rem; text-align: center;">
                        <p style="color: #737373; font-size: 0.875rem; margin-bottom: 1rem;">
                            No API key configured. Add your Cormass Leads API key in Settings to import leads.
                        </p>
                        <button class="btn btn-primary" onclick="switchTab('settings')" style="font-size: 0.8125rem;">
                            Go to Settings
                        </button>
                    </div>
                </div>

                <div class="import-progress" id="import-progress">
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <span id="import-progress-text" style="font-size: 0.875rem;">Importing...</span>
                        <span class="spinner"></span>
                    </div>
                    <div class="progress-bar-container">
                        <div class="progress-bar" id="import-progress-bar"></div>
                    </div>
                </div>
            </div>
        </div>

        <!-- SETTINGS TAB -->
        <div class="tab-content" id="tab-settings">
            <div class="section">
                <h2>Cormass Leads API</h2>
                <p style="color: #737373; font-size: 0.875rem; margin-bottom: 1.25rem;">
                    Connect your Cormass Leads account to import business leads.
                    Generate an API key at
                    <a href="https://cormass.com/leads" target="_blank" style="color: #7c3aed;">cormass.com/leads</a>
                    with <strong>read_canvases</strong> permission enabled.
                </p>
                <div class="form-row">
                    <div class="form-group">
                        <label for="api-key-input">API Key</label>
                        <input type="password" class="form-input" id="api-key-input"
                               placeholder="clk_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx">
                    </div>
                    <div style="padding-bottom: 0;">
                        <button class="btn btn-primary" onclick="saveApiKey()" id="btn-save-key">Save</button>
                    </div>
                    <div style="padding-bottom: 0;">
                        <button class="btn btn-secondary" onclick="testConnection()" id="btn-test-key">Test</button>
                    </div>
                </div>
                <div id="api-key-status" style="margin-top: 0.75rem; font-size: 0.8125rem;"></div>
            </div>

            <div class="section">
                <h2>API Base URL</h2>
                <div class="form-row">
                    <div class="form-group">
                        <label for="base-url-input">Base URL</label>
                        <input type="text" class="form-input" id="base-url-input"
                               placeholder="https://cormass.com/wp-json/leads/v1">
                    </div>
                    <div style="padding-bottom: 0;">
                        <button class="btn btn-secondary" onclick="saveBaseUrl()">Save</button>
                    </div>
                </div>
            </div>
        </div>

        <div class="footer">
            <p>OpenReach v{{ version }} -- <a href="https://github.com/Coolcorbinian/OpenReach">GitHub</a></p>
        </div>
    </div>

    <!-- Toast notification -->
    <div class="toast" id="toast"></div>

    <script>
        // ---- Tab switching ----
        function switchTab(tabId) {
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
            document.getElementById('tab-' + tabId).classList.add('active');
            document.querySelector('.tab[onclick*=\"' + tabId + '\"]').classList.add('active');

            // Load data when switching to import tab
            if (tabId === 'import') { checkImportReady(); }
            if (tabId === 'settings') { loadSettings(); }
        }

        // ---- Toast notifications ----
        function showToast(message, type) {
            const toast = document.getElementById('toast');
            toast.textContent = message;
            toast.className = 'toast toast-' + (type || 'info') + ' show';
            setTimeout(() => { toast.classList.remove('show'); }, 4000);
        }

        // ---- Dashboard: Stats + Leads ----
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
                    tbody.innerHTML = '<tr><td colspan="6" style="color:#525252">No leads imported yet. Go to Import Leads tab to get started.</td></tr>';
                    return;
                }
                tbody.innerHTML = leads.map(l => `
                    <tr>
                        <td>${esc(l.name) || '-'}</td>
                        <td>${l.instagram_handle ? '@' + esc(l.instagram_handle) : '-'}</td>
                        <td>${esc(l.business_type) || '-'}</td>
                        <td>${esc(l.location) || '-'}</td>
                        <td>${l.rating != null ? l.rating.toFixed(1) : '-'}</td>
                        <td>${esc(l.source) || '-'}</td>
                    </tr>
                `).join('');
            } catch (e) { console.error('Failed to load leads', e); }
        }

        // ---- Agent controls ----
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

        // ---- Settings ----
        async function loadSettings() {
            try {
                const res = await fetch('/api/settings');
                const data = await res.json();
                document.getElementById('api-key-input').value = data.api_key_masked || '';
                document.getElementById('base-url-input').value = data.base_url || '';
                if (data.has_api_key) {
                    document.getElementById('api-key-input').placeholder = 'Key saved (enter new key to replace)';
                }
            } catch (e) { console.error('Failed to load settings', e); }
        }

        async function saveApiKey() {
            const key = document.getElementById('api-key-input').value.trim();
            if (!key || key.includes('*')) {
                showToast('Enter a valid API key', 'error');
                return;
            }
            const btn = document.getElementById('btn-save-key');
            btn.disabled = true;
            btn.textContent = 'Saving...';
            try {
                const res = await fetch('/api/settings', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ api_key: key })
                });
                const data = await res.json();
                if (data.ok) {
                    showToast('API key saved successfully', 'success');
                    document.getElementById('api-key-input').value = data.api_key_masked || '';
                } else {
                    showToast(data.error || 'Failed to save API key', 'error');
                }
            } catch (e) {
                showToast('Network error saving API key', 'error');
            }
            btn.disabled = false;
            btn.textContent = 'Save';
        }

        async function saveBaseUrl() {
            const url = document.getElementById('base-url-input').value.trim();
            if (!url) {
                showToast('Enter a valid URL', 'error');
                return;
            }
            try {
                const res = await fetch('/api/settings', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ base_url: url })
                });
                const data = await res.json();
                if (data.ok) {
                    showToast('Base URL saved', 'success');
                } else {
                    showToast(data.error || 'Failed to save', 'error');
                }
            } catch (e) {
                showToast('Network error', 'error');
            }
        }

        async function testConnection() {
            const btn = document.getElementById('btn-test-key');
            btn.disabled = true;
            btn.textContent = 'Testing...';
            const statusEl = document.getElementById('api-key-status');
            statusEl.innerHTML = '<span class="status-dot checking"></span> Testing connection...';
            try {
                const res = await fetch('/api/cormass/test');
                const data = await res.json();
                if (data.connected) {
                    statusEl.innerHTML = '<span class="status-dot connected"></span> Connected -- ' + data.canvases + ' canvas(es) accessible';
                    showToast('Connection successful', 'success');
                } else {
                    statusEl.innerHTML = '<span class="status-dot disconnected"></span> ' + (data.error || 'Connection failed');
                    showToast(data.error || 'Connection failed', 'error');
                }
            } catch (e) {
                statusEl.innerHTML = '<span class="status-dot disconnected"></span> Network error';
                showToast('Network error testing connection', 'error');
            }
            btn.disabled = false;
            btn.textContent = 'Test';
        }

        // ---- Import: Canvas listing + import ----
        async function checkImportReady() {
            const statusEl = document.getElementById('import-connection-status');
            const canvasSection = document.getElementById('canvas-section');
            const noKeyNotice = document.getElementById('no-api-key-notice');

            statusEl.innerHTML = '<span class="status-dot checking"></span> <span style="color:#737373;font-size:0.875rem;">Checking connection...</span>';
            canvasSection.style.display = 'none';
            noKeyNotice.style.display = 'none';

            try {
                const res = await fetch('/api/cormass/test');
                const data = await res.json();
                if (data.connected) {
                    statusEl.innerHTML = '<span class="status-dot connected"></span> <span style="color:#737373;font-size:0.875rem;">Connected (' + data.canvases + ' canvases)</span>';
                    canvasSection.style.display = 'block';
                    loadCanvases();
                } else if (data.error && data.error.includes('No API key')) {
                    statusEl.innerHTML = '<span class="status-dot disconnected"></span> <span style="color:#737373;font-size:0.875rem;">Not connected</span>';
                    noKeyNotice.style.display = 'block';
                } else {
                    statusEl.innerHTML = '<span class="status-dot disconnected"></span> <span style="color:#ef4444;font-size:0.875rem;">' + esc(data.error || 'Connection failed') + '</span>';
                }
            } catch (e) {
                statusEl.innerHTML = '<span class="status-dot disconnected"></span> <span style="color:#ef4444;font-size:0.875rem;">Network error</span>';
            }
        }

        async function loadCanvases() {
            const listEl = document.getElementById('canvas-list');
            listEl.innerHTML = '<div style="color:#525252;font-size:0.875rem;"><span class="spinner"></span> Loading canvases...</div>';
            try {
                const res = await fetch('/api/cormass/canvases');
                const data = await res.json();
                if (data.error) {
                    listEl.innerHTML = '<div style="color:#ef4444;font-size:0.875rem;">' + esc(data.error) + '</div>';
                    return;
                }
                if (!data.length) {
                    listEl.innerHTML = '<div style="color:#525252;font-size:0.875rem;">No canvases found. Create canvases in Cormass Leads first.</div>';
                    return;
                }
                listEl.innerHTML = data.map(c => `
                    <div class="canvas-item">
                        <div class="canvas-info">
                            <div class="canvas-name">${esc(c.name)}</div>
                            <div class="canvas-meta">${c.itemCount} leads -- Updated ${formatDate(c.updatedAt)}</div>
                        </div>
                        <div class="canvas-actions">
                            <button class="btn btn-success" onclick="importCanvas(${c.id}, '${esc(c.name)}')"
                                    id="btn-import-${c.id}" style="font-size: 0.8125rem; padding: 0.375rem 0.875rem;">
                                Import ${c.itemCount} Leads
                            </button>
                        </div>
                    </div>
                `).join('');
            } catch (e) {
                listEl.innerHTML = '<div style="color:#ef4444;font-size:0.875rem;">Failed to load canvases</div>';
            }
        }

        async function importCanvas(canvasId, canvasName) {
            const btn = document.getElementById('btn-import-' + canvasId);
            const progressEl = document.getElementById('import-progress');
            const progressText = document.getElementById('import-progress-text');
            const progressBar = document.getElementById('import-progress-bar');

            btn.disabled = true;
            btn.textContent = 'Importing...';
            progressEl.style.display = 'block';
            progressText.textContent = 'Importing leads from "' + canvasName + '"...';
            progressBar.style.width = '30%';

            try {
                const res = await fetch('/api/cormass/import', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ canvas_id: canvasId })
                });
                progressBar.style.width = '90%';

                const data = await res.json();
                progressBar.style.width = '100%';

                if (data.error) {
                    showToast(data.error, 'error');
                    progressText.textContent = 'Import failed: ' + data.error;
                } else {
                    showToast('Imported ' + data.imported + ' leads from "' + canvasName + '"', 'success');
                    progressText.textContent = 'Done -- ' + data.imported + ' leads imported' + (data.skipped ? ' (' + data.skipped + ' duplicates skipped)' : '');
                    // Refresh stats on dashboard
                    loadStats();
                    loadLeads();
                }
            } catch (e) {
                showToast('Network error during import', 'error');
                progressText.textContent = 'Import failed: network error';
            }

            btn.disabled = false;
            btn.textContent = 'Import';
            setTimeout(() => { progressEl.style.display = 'none'; progressBar.style.width = '0%'; }, 5000);
        }

        // ---- Utility ----
        function esc(s) {
            if (!s) return '';
            const d = document.createElement('div');
            d.textContent = String(s);
            return d.innerHTML;
        }

        function formatDate(iso) {
            if (!iso) return 'N/A';
            const d = new Date(iso);
            return d.toLocaleDateString() + ' ' + d.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'});
        }

        // ---- Init ----
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
    cfg = config or load_config()
    store = DataStore(cfg.get("data", {}).get("db_path", ""))

    def _get_client() -> CormassApiClient | None:
        """Build a CormassApiClient from current config, or None if no key."""
        current = load_config()
        api_key = current.get("cormass", {}).get("api_key", "")
        if not api_key:
            return None
        base_url = current.get("cormass", {}).get("base_url", "https://cormass.com/wp-json/leads/v1")
        return CormassApiClient(api_key=api_key, base_url=base_url)

    # ---- Dashboard ----

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

    # ---- Agent ----

    @app.route("/api/agent/start", methods=["POST"])
    def api_agent_start():  # type: ignore[no-untyped-def]
        # TODO: Start agent in background thread
        return jsonify({"status": "started"})

    @app.route("/api/agent/stop", methods=["POST"])
    def api_agent_stop():  # type: ignore[no-untyped-def]
        # TODO: Signal agent to stop
        return jsonify({"status": "stopping"})

    # ---- Settings ----

    @app.route("/api/settings", methods=["GET"])
    def api_settings_get():  # type: ignore[no-untyped-def]
        current = load_config()
        cormass = current.get("cormass", {})
        api_key = cormass.get("api_key", "")
        masked = ""
        if api_key:
            # Show prefix + last 4, mask the rest
            if len(api_key) > 16:
                masked = api_key[:8] + "*" * (len(api_key) - 12) + api_key[-4:]
            else:
                masked = "*" * len(api_key)
        return jsonify({
            "has_api_key": bool(api_key),
            "api_key_masked": masked,
            "base_url": cormass.get("base_url", "https://cormass.com/wp-json/leads/v1"),
        })

    @app.route("/api/settings", methods=["POST"])
    def api_settings_post():  # type: ignore[no-untyped-def]
        body = request.get_json(force=True, silent=True) or {}

        api_key = body.get("api_key")
        base_url = body.get("base_url")

        if api_key is not None:
            api_key = str(api_key).strip()
            if not api_key.startswith("clk_"):
                return jsonify({"ok": False, "error": "API key must start with 'clk_'"})
            save_config_value("cormass.api_key", api_key)

        if base_url is not None:
            base_url = str(base_url).strip().rstrip("/")
            if not base_url.startswith("http"):
                return jsonify({"ok": False, "error": "Base URL must start with http:// or https://"})
            save_config_value("cormass.base_url", base_url)

        # Return updated masked key
        current = load_config()
        key = current.get("cormass", {}).get("api_key", "")
        masked = ""
        if key and len(key) > 16:
            masked = key[:8] + "*" * (len(key) - 12) + key[-4:]

        return jsonify({"ok": True, "api_key_masked": masked})

    # ---- Cormass API proxy routes ----

    @app.route("/api/cormass/test")
    def api_cormass_test():  # type: ignore[no-untyped-def]
        client = _get_client()
        if client is None:
            return jsonify({"connected": False, "error": "No API key configured"})

        try:
            canvases = client.list_canvases()
            return jsonify({
                "connected": True,
                "canvases": len(canvases),
            })
        except Exception as e:
            logger.warning("Connection test failed: %s", e)
            return jsonify({"connected": False, "error": str(e)})

    @app.route("/api/cormass/canvases")
    def api_cormass_canvases():  # type: ignore[no-untyped-def]
        client = _get_client()
        if client is None:
            return jsonify({"error": "No API key configured"}), 400

        try:
            canvases = client.list_canvases()
            return jsonify(canvases)
        except Exception as e:
            logger.warning("Failed to list canvases: %s", e)
            return jsonify({"error": str(e)}), 500

    @app.route("/api/cormass/import", methods=["POST"])
    def api_cormass_import():  # type: ignore[no-untyped-def]
        client = _get_client()
        if client is None:
            return jsonify({"error": "No API key configured"}), 400

        body = request.get_json(force=True, silent=True) or {}
        canvas_id = body.get("canvas_id")
        if not canvas_id:
            return jsonify({"error": "canvas_id is required"}), 400

        try:
            canvas_id = int(canvas_id)
        except (TypeError, ValueError):
            return jsonify({"error": "canvas_id must be a number"}), 400

        try:
            leads = client.pull_canvas(canvas_id)
        except Exception as e:
            logger.error("Failed to pull canvas %d: %s", canvas_id, e)
            return jsonify({"error": f"Failed to fetch canvas: {e}"}), 500

        if not leads:
            return jsonify({"imported": 0, "skipped": 0, "error": None})

        # Deduplicate: skip leads already imported from same canvas with same business_id
        existing = store.get_leads(source="cormass_api", canvas_id=canvas_id, limit=100000)
        existing_biz_ids = {
            l["cormass_business_id"]
            for l in existing
            if l.get("cormass_business_id")
        }

        new_leads = []
        skipped = 0
        for lead in leads:
            biz_id = lead.get("cormass_business_id", "")
            if biz_id and biz_id in existing_biz_ids:
                skipped += 1
            else:
                new_leads.append(lead)
                if biz_id:
                    existing_biz_ids.add(biz_id)

        imported = store.add_leads(new_leads) if new_leads else 0

        logger.info(
            "Imported %d leads from canvas %d (%d skipped as duplicates)",
            imported, canvas_id, skipped,
        )

        return jsonify({
            "imported": imported,
            "skipped": skipped,
            "canvas_id": canvas_id,
        })

    return app
