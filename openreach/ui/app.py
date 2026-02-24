"""Flask web application for OpenReach."""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any

from flask import Flask, jsonify, render_template_string, request

from openreach.config import load_config, save_config_value
from openreach.data.cormass_api import CormassApiClient
from openreach.data.store import DataStore

logger = logging.getLogger(__name__)

# Global agent reference for background thread management
_agent_engine = None
_agent_thread = None
_agent_lock = threading.Lock()

# Background preview/dry-run tasks
_preview_tasks: dict[str, dict] = {}
_preview_lock = threading.Lock()

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

        /* Activity log */
        .activity-log { max-height: 350px; overflow-y: auto; font-size: 0.8125rem;
                        font-family: 'Consolas', 'Monaco', monospace; }
        .activity-entry { padding: 0.375rem 0.5rem; border-bottom: 1px solid #1a1a1a; }
        .activity-entry .time { color: #525252; margin-right: 0.5rem; }
        .activity-entry.level-success { color: #4ade80; }
        .activity-entry.level-error { color: #f87171; }
        .activity-entry.level-warning { color: #fbbf24; }
        .activity-entry.level-info { color: #94a3b8; }
        .activity-entry.level-debug { color: #525252; font-style: italic; }

        /* Verbose badge */
        .verbose-badge { display: none; background: #7c3aed; color: #fff; font-size: 0.625rem;
                         padding: 0.125rem 0.5rem; border-radius: 9999px; margin-left: 0.5rem;
                         text-transform: uppercase; letter-spacing: 0.05em; font-weight: 600; }
        .verbose-badge.active { display: inline-block; }

        /* Toggle switch */
        .toggle-row { display: flex; align-items: center; justify-content: space-between;
                      padding: 0.75rem 0; }
        .toggle-label { font-size: 0.875rem; font-weight: 500; color: #e5e5e5; }
        .toggle-desc { font-size: 0.75rem; color: #737373; margin-top: 0.25rem; }
        .toggle-switch { position: relative; width: 44px; height: 24px; flex-shrink: 0; }
        .toggle-switch input { opacity: 0; width: 0; height: 0; }
        .toggle-slider { position: absolute; cursor: pointer; top: 0; left: 0; right: 0; bottom: 0;
                         background: #404040; border-radius: 12px; transition: 0.2s; }
        .toggle-slider:before { position: absolute; content: ''; height: 18px; width: 18px;
                                left: 3px; bottom: 3px; background: #e5e5e5; border-radius: 50%;
                                transition: 0.2s; }
        .toggle-switch input:checked + .toggle-slider { background: #7c3aed; }
        .toggle-switch input:checked + .toggle-slider:before { transform: translateX(20px); }

        /* Campaign form */
        .form-textarea { width: 100%; padding: 0.625rem 0.75rem; background: #0a0a0a;
                         border: 1px solid #404040; border-radius: 0.5rem; color: #e5e5e5;
                         font-size: 0.875rem; font-family: inherit; min-height: 80px; resize: vertical; }
        .form-textarea:focus { outline: none; border-color: #7c3aed; }
        .form-select { width: 100%; padding: 0.625rem 0.75rem; background: #0a0a0a;
                       border: 1px solid #404040; border-radius: 0.5rem; color: #e5e5e5;
                       font-size: 0.875rem; font-family: inherit; appearance: none;
                       background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' fill='%23737373' viewBox='0 0 16 16'%3E%3Cpath d='M8 11L3 6h10z'/%3E%3C/svg%3E");
                       background-repeat: no-repeat; background-position: right 0.75rem center; }
        .form-select:focus { outline: none; border-color: #7c3aed; }
        .mode-toggle { display: flex; gap: 0; border: 1px solid #404040; border-radius: 0.5rem; overflow: hidden; }
        .mode-toggle button { flex: 1; padding: 0.625rem 1rem; background: #0a0a0a; color: #737373;
                               border: none; font-size: 0.875rem; cursor: pointer; transition: all 0.15s; }
        .mode-toggle button.active { background: #7c3aed; color: white; }
        .mode-toggle button:hover:not(.active) { background: #171717; color: #e5e5e5; }
        .campaign-card { background: #0a0a0a; border: 1px solid #262626; border-radius: 0.5rem;
                         padding: 1rem; margin-bottom: 0.75rem; display: flex;
                         justify-content: space-between; align-items: center; }
        .campaign-card.active-campaign { border-color: #7c3aed; }
        .campaign-info .campaign-name { font-weight: 500; font-size: 0.9375rem; }
        .campaign-info .campaign-meta { font-size: 0.75rem; color: #737373; margin-top: 0.25rem; }
        .form-cols { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }
        @media (max-width: 700px) { .form-cols { grid-template-columns: 1fr; } }
        .divider { border-top: 1px solid #262626; margin: 1.5rem 0; }
        .agent-status-bar { display: flex; align-items: center; gap: 0.75rem; padding: 0.75rem 1rem;
                           background: #171717; border: 1px solid #262626; border-radius: 0.5rem;
                           margin-bottom: 1rem; }
        .agent-status-bar .pulse { width: 10px; height: 10px; border-radius: 50%; }
        .agent-status-bar .pulse.running { background: #22c55e; animation: pulse 1.5s infinite; }
        .agent-status-bar .pulse.idle { background: #525252; }
        .agent-status-bar .pulse.error { background: #ef4444; }
        @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>Open<span>Reach</span></h1>
            <span class="verbose-badge" id="verbose-badge">Verbose</span>
            <div class="status" id="agent-status">Agent: Idle</div>
        </header>

        <div class="tabs">
            <button class="tab active" onclick="switchTab('dashboard')">Dashboard</button>
            <button class="tab" onclick="switchTab('campaign')">Campaign</button>
            <button class="tab" onclick="switchTab('import')">Import Leads</button>
            <button class="tab" onclick="switchTab('settings')">Settings</button>
        </div>

        <!-- DASHBOARD TAB -->
        <div class="tab-content active" id="tab-dashboard">
            <!-- Agent Status Bar -->
            <div class="agent-status-bar" id="agent-bar">
                <div class="pulse idle" id="agent-pulse"></div>
                <span id="agent-status-text" style="font-size: 0.875rem; font-weight: 500;">Agent Idle</span>
                <span id="agent-detail" style="font-size: 0.75rem; color: #737373; margin-left: auto;"></span>
                <button class="btn btn-primary" id="btn-start" onclick="startAgent()" style="padding: 0.375rem 0.875rem; font-size: 0.8125rem;">Start</button>
                <button class="btn btn-danger" id="btn-stop" onclick="stopAgent()" style="display:none; padding: 0.375rem 0.875rem; font-size: 0.8125rem;">Stop</button>
            </div>

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

            <!-- Activity Log -->
            <div class="section">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.75rem;">
                    <h2 style="margin: 0;">Activity Log</h2>
                    <button class="btn btn-secondary" onclick="clearActivityView()" style="font-size: 0.75rem; padding: 0.25rem 0.625rem;">Clear</button>
                </div>
                <div class="activity-log" id="activity-log">
                    <div class="activity-entry level-info"><span class="time">--:--:--</span>Waiting for agent to start...</div>
                </div>
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

        <!-- CAMPAIGN TAB -->
        <div class="tab-content" id="tab-campaign">
            <div class="section">
                <h2>Campaign Configuration</h2>
                <p style="color: #737373; font-size: 0.875rem; margin-bottom: 1.25rem;">
                    Configure your outreach campaign. Set the platform, mode, message prompt, and sender credentials.
                    The agent will use this configuration when processing leads.
                </p>

                <div class="form-group">
                    <label for="camp-name">Campaign Name</label>
                    <input type="text" class="form-input" id="camp-name" placeholder="My Outreach Campaign">
                </div>

                <div class="form-cols">
                    <div class="form-group">
                        <label>Platform</label>
                        <select class="form-select" id="camp-platform" onchange="onPlatformChange()">
                            <option value="instagram">Instagram</option>
                            <option value="linkedin" disabled>LinkedIn (coming soon)</option>
                            <option value="twitter" disabled>Twitter / X (coming soon)</option>
                            <option value="email" disabled>Email (coming soon)</option>
                        </select>
                    </div>
                    <div class="form-group">
                        <label>Outreach Mode</label>
                        <div class="mode-toggle">
                            <button id="mode-dynamic" class="active" onclick="setMode('dynamic')">Dynamic (AI)</button>
                            <button id="mode-static" onclick="setMode('static')">Static (Template)</button>
                        </div>
                    </div>
                </div>

                <div class="divider"></div>

                <!-- Dynamic mode fields -->
                <div id="dynamic-fields">
                    <div class="form-group">
                        <label for="camp-prompt">AI Prompt (defines the AI's role and behavior)</label>
                        <textarea class="form-textarea" id="camp-prompt" rows="4"
                            placeholder="You are a sales outreach assistant for [Your Company]. You help connect with businesses that need [your service]. Be friendly, concise, and reference something specific about their business."></textarea>
                        <div style="font-size: 0.7rem; color: #525252; margin-top: 0.375rem;">
                            This becomes the AI's system instructions. Tell it who you are, what you offer, and how to approach leads.
                        </div>
                    </div>

                    <div class="form-group">
                        <label for="camp-notes">Additional Notes (extra context for the AI)</label>
                        <textarea class="form-textarea" id="camp-notes" rows="3"
                            placeholder="Our main USP is... We target businesses that... Never mention pricing..."></textarea>
                        <div style="font-size: 0.7rem; color: #525252; margin-top: 0.375rem;">
                            Additional information the AI should know. Pricing details, USPs, tone preferences, things to avoid, etc.
                        </div>
                    </div>
                </div>

                <!-- Static mode fields -->
                <div id="static-fields" style="display: none;">
                    <div class="form-group">
                        <label for="camp-template">Message Template</label>
                        <textarea class="form-textarea" id="camp-template" rows="5"
                            placeholder="Hi {{name}}! I noticed your {{business_type}} business in {{location}}. We help businesses like yours with [service]. Would you be open to a quick chat?"></textarea>
                        <div style="font-size: 0.7rem; color: #525252; margin-top: 0.375rem;">
                            Use {{name}}, {{business_type}}, {{location}}, {{rating}}, {{website}}, {{instagram_handle}}, {{notes}}, {{pain_points}} as placeholders.
                        </div>
                    </div>
                </div>

                <div class="divider"></div>

                <h3 style="font-size: 1rem; margin-bottom: 1rem;">Sender Account</h3>
                <div class="form-cols">
                    <div class="form-group">
                        <label for="camp-username">Username</label>
                        <input type="text" class="form-input" id="camp-username" placeholder="your_instagram_handle">
                    </div>
                    <div class="form-group">
                        <label for="camp-password">Password</label>
                        <input type="password" class="form-input" id="camp-password" placeholder="Account password">
                    </div>
                </div>

                <div class="divider"></div>

                <h3 style="font-size: 1rem; margin-bottom: 1rem;">Limits</h3>
                <div class="form-cols">
                    <div class="form-group">
                        <label for="camp-daily">Daily Limit</label>
                        <input type="number" class="form-input" id="camp-daily" value="50" min="1" max="500">
                    </div>
                    <div class="form-group">
                        <label for="camp-session">Per Session Limit</label>
                        <input type="number" class="form-input" id="camp-session" value="15" min="1" max="100">
                    </div>
                </div>
                <div class="form-cols">
                    <div class="form-group">
                        <label for="camp-delay-min">Min Delay (seconds)</label>
                        <input type="number" class="form-input" id="camp-delay-min" value="45" min="10" max="600">
                    </div>
                    <div class="form-group">
                        <label for="camp-delay-max">Max Delay (seconds)</label>
                        <input type="number" class="form-input" id="camp-delay-max" value="180" min="20" max="900">
                    </div>
                </div>

                <div class="divider"></div>

                <div style="display: flex; gap: 0.75rem; flex-wrap: wrap;">
                    <button class="btn btn-primary" onclick="saveCampaign()" id="btn-save-campaign">Save Campaign</button>
                    <button class="btn btn-secondary" onclick="previewMessage()" id="btn-preview">Preview Message</button>
                    <button class="btn btn-secondary" onclick="dryRun()" id="btn-dry-run">Dry Run (1 Lead)</button>
                </div>

                <div id="campaign-status" style="margin-top: 0.75rem; font-size: 0.8125rem;"></div>

                <!-- Message Preview -->
                <div id="preview-result" style="display: none; margin-top: 1rem;">
                    <div class="section" style="background: #0f0f0f;">
                        <h3 style="font-size: 0.875rem; margin-bottom: 0.5rem;">Message Preview</h3>
                        <div id="preview-text" style="font-size: 0.875rem; white-space: pre-wrap; line-height: 1.5;"></div>
                        <div id="preview-meta" style="font-size: 0.75rem; color: #525252; margin-top: 0.5rem;"></div>
                    </div>
                </div>
            </div>

            <!-- Saved Campaigns -->
            <div class="section">
                <h2>Saved Campaigns</h2>
                <div id="campaigns-list" style="margin-top: 0.75rem;">
                    <div style="color: #525252; font-size: 0.875rem;">Loading campaigns...</div>
                </div>
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

            <div class="section">
                <h2>Debug Mode</h2>
                <div class="toggle-row">
                    <div>
                        <div class="toggle-label">Verbose Logging</div>
                        <div class="toggle-desc">Show detailed browser automation output in the Activity Log. Enable this to diagnose crashes and login failures.</div>
                    </div>
                    <label class="toggle-switch">
                        <input type="checkbox" id="verbose-toggle" onchange="toggleVerbose(this.checked)">
                        <span class="toggle-slider"></span>
                    </label>
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
        // ---- State ----
        let currentCampaignId = null;
        let currentMode = 'dynamic';
        let agentRunning = false;
        let lastActivityId = 0;
        let activityPollTimer = null;
        let statusPollTimer = null;
        let verboseMode = false;

        // ---- Tab switching ----
        function switchTab(tabId) {
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
            document.getElementById('tab-' + tabId).classList.add('active');
            document.querySelector('.tab[onclick*="' + tabId + '"]').classList.add('active');

            if (tabId === 'import') { checkImportReady(); }
            if (tabId === 'settings') { loadSettings(); }
            if (tabId === 'campaign') { loadCampaigns(); }
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

        // ---- Agent Controls ----
        async function startAgent() {
            try {
                const res = await fetch('/api/agent/start', { method: 'POST' });
                const data = await res.json();
                if (data.error) {
                    showToast(data.error, 'error');
                    return;
                }
                agentRunning = true;
                updateAgentUI('running');
                showToast('Agent started', 'success');
                startActivityPolling();
                startStatusPolling();
            } catch (e) {
                showToast('Failed to start agent', 'error');
            }
        }

        async function stopAgent() {
            try {
                await fetch('/api/agent/stop', { method: 'POST' });
                showToast('Stopping agent...', 'info');
            } catch (e) {
                showToast('Failed to stop agent', 'error');
            }
        }

        function updateAgentUI(state) {
            const pulse = document.getElementById('agent-pulse');
            const text = document.getElementById('agent-status-text');
            const btnStart = document.getElementById('btn-start');
            const btnStop = document.getElementById('btn-stop');
            const statusHeader = document.getElementById('agent-status');

            if (state === 'running' || state === 'planning' || state === 'executing' ||
                state === 'scraping' || state === 'waiting' || state === 'logging_in' || state === 'starting') {
                pulse.className = 'pulse running';
                const labels = { running: 'Running', planning: 'Planning Message', executing: 'Sending Message',
                                 scraping: 'Scraping Profile', waiting: 'Waiting', logging_in: 'Logging In', starting: 'Starting' };
                text.textContent = 'Agent: ' + (labels[state] || 'Running');
                btnStart.style.display = 'none';
                btnStop.style.display = '';
                agentRunning = true;
            } else if (state === 'error') {
                pulse.className = 'pulse error';
                text.textContent = 'Agent: Error';
                btnStart.style.display = '';
                btnStop.style.display = 'none';
                agentRunning = false;
                stopActivityPolling();
                stopStatusPolling();
            } else {
                pulse.className = 'pulse idle';
                text.textContent = 'Agent: Idle';
                btnStart.style.display = '';
                btnStop.style.display = 'none';
                agentRunning = false;
                stopActivityPolling();
                stopStatusPolling();
            }
            if (statusHeader) { statusHeader.textContent = text.textContent; }
        }

        // ---- Activity Log ----
        function startActivityPolling() {
            if (activityPollTimer) return;
            activityPollTimer = setInterval(pollActivity, 2000);
            pollActivity(); // immediate first poll
        }

        function stopActivityPolling() {
            if (activityPollTimer) { clearInterval(activityPollTimer); activityPollTimer = null; }
        }

        async function pollActivity() {
            try {
                const url = '/api/activity?after_id=' + lastActivityId + (verboseMode ? '&include_debug=1' : '');
                const res = await fetch(url);
                const entries = await res.json();
                if (entries.length > 0) {
                    const logEl = document.getElementById('activity-log');
                    // Remove placeholder
                    if (lastActivityId === 0) { logEl.innerHTML = ''; }
                    entries.forEach(e => {
                        const div = document.createElement('div');
                        div.className = 'activity-entry level-' + e.level;
                        const time = e.created_at ? new Date(e.created_at).toLocaleTimeString() : '--:--:--';
                        div.innerHTML = '<span class="time">' + time + '</span>' + esc(e.message);
                        logEl.appendChild(div);
                        lastActivityId = Math.max(lastActivityId, e.id);
                    });
                    logEl.scrollTop = logEl.scrollHeight;
                }
            } catch (e) { console.error('Activity poll error', e); }
        }

        function clearActivityView() {
            document.getElementById('activity-log').innerHTML =
                '<div class="activity-entry level-info"><span class="time">--:--:--</span>Waiting for agent to start...</div>';
            lastActivityId = 0;
        }

        // ---- Agent Status Polling ----
        function startStatusPolling() {
            if (statusPollTimer) return;
            statusPollTimer = setInterval(pollAgentStatus, 3000);
        }

        function stopStatusPolling() {
            if (statusPollTimer) { clearInterval(statusPollTimer); statusPollTimer = null; }
        }

        async function pollAgentStatus() {
            try {
                const res = await fetch('/api/agent/status');
                const data = await res.json();
                updateAgentUI(data.state);
                const detail = document.getElementById('agent-detail');
                if (data.stats) {
                    detail.textContent = 'Sent: ' + data.stats.messages_sent +
                        ' | Failed: ' + data.stats.messages_failed +
                        ' | Processed: ' + data.stats.leads_processed;
                }
                if (data.state === 'idle' || data.state === 'stopped' || data.state === 'error') {
                    loadStats(); // refresh dashboard stats after run
                }
            } catch (e) { console.error('Status poll error', e); }
        }

        // ---- Campaign Tab ----
        function setMode(mode) {
            currentMode = mode;
            document.getElementById('mode-dynamic').classList.toggle('active', mode === 'dynamic');
            document.getElementById('mode-static').classList.toggle('active', mode === 'static');
            document.getElementById('dynamic-fields').style.display = mode === 'dynamic' ? '' : 'none';
            document.getElementById('static-fields').style.display = mode === 'static' ? '' : 'none';
        }

        function onPlatformChange() {
            // Future: update UI based on platform
        }

        function getCampaignFormData() {
            return {
                name: document.getElementById('camp-name').value.trim() || 'Default Campaign',
                platform: document.getElementById('camp-platform').value,
                mode: currentMode,
                user_prompt: document.getElementById('camp-prompt').value.trim(),
                additional_notes: document.getElementById('camp-notes').value.trim(),
                message_template: document.getElementById('camp-template').value.trim(),
                sender_username: document.getElementById('camp-username').value.trim(),
                sender_password: document.getElementById('camp-password').value.trim(),
                daily_limit: parseInt(document.getElementById('camp-daily').value) || 50,
                session_limit: parseInt(document.getElementById('camp-session').value) || 15,
                delay_min: parseInt(document.getElementById('camp-delay-min').value) || 45,
                delay_max: parseInt(document.getElementById('camp-delay-max').value) || 180,
            };
        }

        function loadCampaignIntoForm(c) {
            currentCampaignId = c.id;
            document.getElementById('camp-name').value = c.name || '';
            document.getElementById('camp-platform').value = c.platform || 'instagram';
            setMode(c.mode || 'dynamic');
            document.getElementById('camp-prompt').value = c.user_prompt || '';
            document.getElementById('camp-notes').value = c.additional_notes || '';
            document.getElementById('camp-template').value = c.message_template || '';
            document.getElementById('camp-username').value = c.sender_username || '';
            document.getElementById('camp-password').value = c.sender_password ? '********' : '';
            document.getElementById('camp-daily').value = c.daily_limit || 50;
            document.getElementById('camp-session').value = c.session_limit || 15;
            document.getElementById('camp-delay-min').value = c.delay_min || 45;
            document.getElementById('camp-delay-max').value = c.delay_max || 180;
        }

        async function saveCampaign() {
            const data = getCampaignFormData();
            // Don't overwrite password if user didn't change it
            if (data.sender_password === '********') { delete data.sender_password; }

            const btn = document.getElementById('btn-save-campaign');
            btn.disabled = true; btn.textContent = 'Saving...';

            try {
                let url = '/api/campaigns';
                let method = 'POST';
                if (currentCampaignId) {
                    url = '/api/campaigns/' + currentCampaignId;
                    method = 'PUT';
                }
                const res = await fetch(url, {
                    method: method,
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(data)
                });
                const result = await res.json();
                if (result.error) {
                    showToast(result.error, 'error');
                } else {
                    currentCampaignId = result.id;
                    showToast('Campaign saved', 'success');
                    loadCampaigns();
                }
            } catch (e) {
                showToast('Failed to save campaign', 'error');
            }
            btn.disabled = false; btn.textContent = 'Save Campaign';
        }

        async function loadCampaigns() {
            try {
                const res = await fetch('/api/campaigns');
                const campaigns = await res.json();
                const listEl = document.getElementById('campaigns-list');
                if (!campaigns.length) {
                    listEl.innerHTML = '<div style="color: #525252; font-size: 0.875rem;">No campaigns yet. Configure one above and save.</div>';
                    return;
                }
                listEl.innerHTML = campaigns.map(c => `
                    <div class="campaign-card ${c.is_active ? 'active-campaign' : ''}">
                        <div class="campaign-info">
                            <div class="campaign-name">${esc(c.name)} ${c.is_active ? '<span class="badge badge-sent">Active</span>' : ''}</div>
                            <div class="campaign-meta">${esc(c.platform)} / ${esc(c.mode)} -- ${c.sender_username ? '@' + esc(c.sender_username) : 'No sender'}</div>
                        </div>
                        <div style="display: flex; gap: 0.5rem;">
                            <button class="btn btn-secondary" onclick="editCampaign(${c.id})" style="font-size: 0.75rem; padding: 0.25rem 0.625rem;">Edit</button>
                            <button class="btn ${c.is_active ? 'btn-danger' : 'btn-success'}" onclick="toggleCampaignActive(${c.id}, ${!c.is_active})" style="font-size: 0.75rem; padding: 0.25rem 0.625rem;">
                                ${c.is_active ? 'Deactivate' : 'Activate'}
                            </button>
                            <button class="btn btn-secondary" onclick="deleteCampaign(${c.id})" style="font-size: 0.75rem; padding: 0.25rem 0.625rem; color: #f87171;">Delete</button>
                        </div>
                    </div>
                `).join('');
            } catch (e) {
                console.error('Failed to load campaigns', e);
            }
        }

        async function editCampaign(id) {
            try {
                const res = await fetch('/api/campaigns/' + id);
                const c = await res.json();
                if (c.error) { showToast(c.error, 'error'); return; }
                loadCampaignIntoForm(c);
                showToast('Campaign loaded for editing', 'info');
                window.scrollTo(0, 0);
            } catch (e) { showToast('Failed to load campaign', 'error'); }
        }

        async function toggleCampaignActive(id, active) {
            try {
                const res = await fetch('/api/campaigns/' + id, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ is_active: active })
                });
                const data = await res.json();
                if (data.error) { showToast(data.error, 'error'); return; }
                showToast(active ? 'Campaign activated' : 'Campaign deactivated', 'success');
                loadCampaigns();
            } catch (e) { showToast('Failed to update campaign', 'error'); }
        }

        async function deleteCampaign(id) {
            if (!confirm('Delete this campaign?')) return;
            try {
                const res = await fetch('/api/campaigns/' + id, { method: 'DELETE' });
                const data = await res.json();
                if (data.ok) {
                    if (currentCampaignId === id) { currentCampaignId = null; }
                    showToast('Campaign deleted', 'success');
                    loadCampaigns();
                } else {
                    showToast(data.error || 'Delete failed', 'error');
                }
            } catch (e) { showToast('Failed to delete campaign', 'error'); }
        }

        async function previewMessage() {
            const data = getCampaignFormData();
            const btn = document.getElementById('btn-preview');
            btn.disabled = true; btn.textContent = 'Generating...';
            try {
                const res = await fetch('/api/agent/preview', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(data)
                });
                const initial = await res.json();
                if (initial.error) {
                    document.getElementById('preview-text').textContent = 'Error: ' + initial.error;
                    document.getElementById('preview-meta').textContent = '';
                    document.getElementById('preview-result').style.display = '';
                    btn.disabled = false; btn.textContent = 'Preview Message';
                    return;
                }
                // Static mode returns immediately with status=done
                if (initial.status === 'done') {
                    document.getElementById('preview-text').textContent = initial.message;
                    document.getElementById('preview-meta').textContent = initial.chars + ' characters | Mode: ' + initial.mode + ' | Lead: ' + (initial.lead_name || 'N/A');
                    document.getElementById('preview-result').style.display = '';
                    btn.disabled = false; btn.textContent = 'Preview Message';
                    return;
                }
                // Dynamic mode - poll for result
                const taskId = initial.task_id;
                let elapsed = 0;
                const poll = setInterval(async () => {
                    elapsed += 3;
                    btn.textContent = 'Generating... (' + elapsed + 's)';
                    try {
                        const pr = await fetch('/api/agent/preview/' + taskId);
                        const pdata = await pr.json();
                        if (pdata.status === 'generating') return;
                        clearInterval(poll);
                        if (pdata.status === 'done') {
                            document.getElementById('preview-text').textContent = pdata.message;
                            document.getElementById('preview-meta').textContent = pdata.chars + ' characters | Mode: ' + pdata.mode + ' | Lead: ' + (pdata.lead_name || 'N/A');
                            document.getElementById('preview-result').style.display = '';
                        } else {
                            document.getElementById('preview-text').textContent = 'Error: ' + (pdata.error || 'Unknown error');
                            document.getElementById('preview-meta').textContent = '';
                            document.getElementById('preview-result').style.display = '';
                        }
                        btn.disabled = false; btn.textContent = 'Preview Message';
                    } catch (pe) {
                        clearInterval(poll);
                        showToast('Preview polling failed', 'error');
                        btn.disabled = false; btn.textContent = 'Preview Message';
                    }
                }, 3000);
            } catch (e) {
                showToast('Preview failed', 'error');
                btn.disabled = false; btn.textContent = 'Preview Message';
            }
        }

        async function dryRun() {
            const data = getCampaignFormData();
            const btn = document.getElementById('btn-dry-run');
            btn.disabled = true; btn.textContent = 'Running...';
            try {
                const res = await fetch('/api/agent/dry-run', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(data)
                });
                const initial = await res.json();
                if (initial.error) {
                    showToast('Dry run error: ' + initial.error, 'error');
                    btn.disabled = false; btn.textContent = 'Dry Run (1 Lead)';
                    return;
                }
                // Static mode returns immediately
                if (initial.status === 'done') {
                    showToast('Dry run complete -- message: ' + (initial.message || '').substring(0, 80) + '...', 'success');
                    document.getElementById('preview-text').textContent = initial.message;
                    document.getElementById('preview-meta').textContent =
                        (initial.chars || 0) + ' chars | Would send to: @' + (initial.handle || 'N/A') + ' | Mode: ' + (initial.mode || 'dynamic');
                    document.getElementById('preview-result').style.display = '';
                    btn.disabled = false; btn.textContent = 'Dry Run (1 Lead)';
                    return;
                }
                // Dynamic mode - poll for result
                const taskId = initial.task_id;
                let elapsed = 0;
                const poll = setInterval(async () => {
                    elapsed += 3;
                    btn.textContent = 'Running... (' + elapsed + 's)';
                    try {
                        const pr = await fetch('/api/agent/preview/' + taskId);
                        const pdata = await pr.json();
                        if (pdata.status === 'generating') return;
                        clearInterval(poll);
                        if (pdata.status === 'done') {
                            showToast('Dry run complete -- message: ' + (pdata.message || '').substring(0, 80) + '...', 'success');
                            document.getElementById('preview-text').textContent = pdata.message;
                            document.getElementById('preview-meta').textContent =
                                (pdata.chars || 0) + ' chars | Would send to: @' + (pdata.handle || 'N/A') + ' | Mode: ' + (pdata.mode || 'dynamic');
                            document.getElementById('preview-result').style.display = '';
                        } else {
                            showToast('Dry run error: ' + (pdata.error || 'Unknown error'), 'error');
                        }
                        btn.disabled = false; btn.textContent = 'Dry Run (1 Lead)';
                    } catch (pe) {
                        clearInterval(poll);
                        showToast('Dry run polling failed', 'error');
                        btn.disabled = false; btn.textContent = 'Dry Run (1 Lead)';
                    }
                }, 3000);
            } catch (e) {
                showToast('Dry run failed', 'error');
                btn.disabled = false; btn.textContent = 'Dry Run (1 Lead)';
            }
        }

        // ---- Verbose mode ----
        async function toggleVerbose(on) {
            try {
                await fetch('/api/settings/verbose', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ verbose: on })
                });
                verboseMode = on;
                document.getElementById('verbose-badge').classList.toggle('active', on);
                showToast('Verbose mode ' + (on ? 'enabled' : 'disabled'), 'success');
                // Re-poll activity to pick up debug entries
                if (on) { lastActivityId = 0; clearActivityView(); pollActivity(); }
            } catch (e) { showToast('Failed to toggle verbose mode', 'error'); }
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
                // Verbose toggle
                verboseMode = !!data.verbose;
                document.getElementById('verbose-toggle').checked = verboseMode;
                document.getElementById('verbose-badge').classList.toggle('active', verboseMode);
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
        setInterval(loadStats, 15000);

        // Load verbose state on startup
        (async function() {
            try {
                const res = await fetch('/api/settings');
                const data = await res.json();
                verboseMode = !!data.verbose;
                document.getElementById('verbose-badge').classList.toggle('active', verboseMode);
            } catch(e) {}
        })();

        // Check agent status on load
        (async function() {
            try {
                const res = await fetch('/api/agent/status');
                const data = await res.json();
                updateAgentUI(data.state);
                if (data.state !== 'idle' && data.state !== 'stopped') {
                    startActivityPolling();
                    startStatusPolling();
                }
            } catch(e) {}
        })();
    </script>
</body>
</html>"""


def create_app(config: dict[str, Any] | None = None) -> Flask:
    """Create the Flask application."""
    from openreach import __version__

    app = Flask(__name__)
    cfg = config or load_config()
    store = DataStore(cfg.get("data", {}).get("db_path", ""))

    # Configure Python logging based on verbose setting
    verbose_raw = cfg.get("debug", {}).get("verbose", "False")
    verbose = str(verbose_raw).lower() in ("true", "1", "yes")
    log_level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        force=True,
    )
    # Quiet down noisy libraries
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("werkzeug").setLevel(logging.WARNING)

    # Custom handler that forwards browser/agent debug logs to the activity DB
    class _ActivityDBHandler(logging.Handler):
        """Forward log records from openreach.browser.* and openreach.agent.* to activity DB."""
        def emit(self, record: logging.LogRecord) -> None:
            if not record.name.startswith(("openreach.browser", "openreach.agent")):
                return
            level_map = {logging.DEBUG: "debug", logging.INFO: "info",
                         logging.WARNING: "warning", logging.ERROR: "error"}
            level = level_map.get(record.levelno, "info")
            try:
                store.log_activity(message=self.format(record), level=level)
            except Exception:
                pass

    db_handler = _ActivityDBHandler()
    db_handler.setLevel(logging.DEBUG)
    db_handler.setFormatter(logging.Formatter("%(message)s"))
    logging.getLogger("openreach.browser").addHandler(db_handler)
    # Note: openreach.agent.engine uses _log() which already writes to DB,
    # so we skip adding the handler there to avoid duplicates.

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

    # ---- Campaigns ----

    @app.route("/api/campaigns", methods=["GET"])
    def api_campaigns_list():  # type: ignore[no-untyped-def]
        campaigns = store.get_campaigns()
        return jsonify(campaigns)

    @app.route("/api/campaigns", methods=["POST"])
    def api_campaigns_create():  # type: ignore[no-untyped-def]
        body = request.get_json(force=True, silent=True) or {}
        required = ["name"]
        for f in required:
            if not body.get(f):
                return jsonify({"error": f"'{f}' is required"}), 400
        try:
            campaign = store.create_campaign(body)
            return jsonify(campaign), 201
        except Exception as e:
            logger.error("Failed to create campaign: %s", e)
            return jsonify({"error": str(e)}), 500

    @app.route("/api/campaigns/<int:cid>", methods=["GET"])
    def api_campaign_get(cid):  # type: ignore[no-untyped-def]
        c = store.get_campaign(cid)
        if not c:
            return jsonify({"error": "Campaign not found"}), 404
        return jsonify(c)

    @app.route("/api/campaigns/<int:cid>", methods=["PUT"])
    def api_campaign_update(cid):  # type: ignore[no-untyped-def]
        body = request.get_json(force=True, silent=True) or {}
        try:
            updated = store.update_campaign(cid, body)
            if not updated:
                return jsonify({"error": "Campaign not found"}), 404
            return jsonify(updated)
        except Exception as e:
            logger.error("Failed to update campaign %d: %s", cid, e)
            return jsonify({"error": str(e)}), 500

    @app.route("/api/campaigns/<int:cid>", methods=["DELETE"])
    def api_campaign_delete(cid):  # type: ignore[no-untyped-def]
        ok = store.delete_campaign(cid)
        if ok:
            return jsonify({"ok": True})
        return jsonify({"error": "Campaign not found"}), 404

    # ---- Agent ----

    @app.route("/api/agent/start", methods=["POST"])
    def api_agent_start():  # type: ignore[no-untyped-def]
        global _agent_engine, _agent_thread
        with _agent_lock:
            if _agent_engine:
                from openreach.agent.engine import AgentState
                if _agent_engine.state not in (AgentState.IDLE, AgentState.STOPPED, AgentState.ERROR):
                    return jsonify({"error": "Agent is already running"}), 400

            # Find active campaign
            campaign = store.get_active_campaign()
            if not campaign:
                return jsonify({"error": "No active campaign. Go to Campaign tab and activate one."}), 400

            # Get unreached leads with instagram handles
            unsent_leads = [
                l for l in store.get_unreached_leads(limit=10000)
                if l.get("instagram_handle")
            ]

            if not unsent_leads:
                return jsonify({"error": "No unsent leads with Instagram handles available"}), 400

            from openreach.llm.client import OllamaClient
            from openreach.browser.session import BrowserSession
            from openreach.agent.engine import AgentEngine

            llm_cfg = cfg.get("llm", {})
            llm = OllamaClient(
                model=llm_cfg.get("model", "qwen3:4b"),
                base_url=llm_cfg.get("base_url", "http://localhost:11434"),
                temperature=llm_cfg.get("temperature", 0.7),
            )
            browser = BrowserSession(config=cfg)
            _agent_engine = AgentEngine(llm=llm, browser=browser, store=store)

            def _run():
                try:
                    asyncio.run(_agent_engine.start(campaign, unsent_leads))
                except Exception as e:
                    import traceback
                    tb = traceback.format_exc()
                    logger.error("Agent thread error: %s\n%s", e, tb)
                    store.log_activity(
                        message=f"Agent thread crashed: {e}",
                        level="error",
                        details=tb,
                    )

            _agent_thread = threading.Thread(target=_run, daemon=True)
            _agent_thread.start()

        return jsonify({"status": "started", "leads_queued": len(unsent_leads)})

    @app.route("/api/agent/stop", methods=["POST"])
    def api_agent_stop():  # type: ignore[no-untyped-def]
        global _agent_engine
        with _agent_lock:
            if _agent_engine:
                _agent_engine.stop()
        return jsonify({"status": "stopping"})

    @app.route("/api/agent/status")
    def api_agent_status():  # type: ignore[no-untyped-def]
        with _agent_lock:
            if _agent_engine:
                st = _agent_engine.stats
                stats_dict = {
                    "messages_sent": st.messages_sent,
                    "messages_failed": st.messages_failed,
                    "leads_processed": st.leads_processed,
                }
                return jsonify({
                    "state": _agent_engine.state.value if hasattr(_agent_engine.state, 'value') else str(_agent_engine.state),
                    "stats": stats_dict,
                })
        return jsonify({"state": "idle", "stats": {}})

    # ---- Activity Log ----

    @app.route("/api/activity")
    def api_activity():  # type: ignore[no-untyped-def]
        after_id = request.args.get("after_id", 0, type=int)
        limit = request.args.get("limit", 100, type=int)
        include_debug = request.args.get("include_debug", "0") == "1"
        entries = store.get_activity_log(after_id=after_id, limit=limit)
        if not include_debug:
            entries = [e for e in entries if e.get("level") != "debug"]
        return jsonify(entries)

    # ---- Preview & Dry Run (Async Background Tasks) ----

    @app.route("/api/agent/preview", methods=["POST"])
    def api_agent_preview():  # type: ignore[no-untyped-def]
        body = request.get_json(force=True, silent=True) or {}
        mode = body.get("mode", "dynamic")

        # Grab a sample lead
        all_leads = store.get_leads(limit=1)
        if not all_leads:
            return jsonify({"error": "No leads in database. Import some first."}), 400

        lead = all_leads[0]
        from openreach.llm.prompts import build_static_message, build_dynamic_prompt, build_system_prompt

        if mode == "static":
            template = body.get("message_template", "")
            if not template:
                return jsonify({"error": "No message template provided"}), 400
            msg = build_static_message(template, lead)
            return jsonify({
                "message": msg,
                "chars": len(msg),
                "mode": "static",
                "lead_name": lead.get("name", ""),
                "status": "done",
            })

        # Dynamic mode - start background generation
        import uuid
        task_id = str(uuid.uuid4())[:8]
        with _preview_lock:
            _preview_tasks[task_id] = {"status": "generating", "result": None}

        def _generate_preview():
            try:
                from openreach.llm.client import OllamaClient
                system = build_system_prompt(body)
                user_msg = build_dynamic_prompt(lead, None)
                llm_cfg = cfg.get("llm", {})
                llm = OllamaClient(
                    model=llm_cfg.get("model", "qwen3:4b"),
                    base_url=llm_cfg.get("base_url", "http://localhost:11434"),
                    temperature=llm_cfg.get("temperature", 0.7),
                )
                msg = llm.generate_sync(prompt=user_msg, system=system)
                import re as _re
                msg = _re.sub(r'<think>.*?</think>', '', msg, flags=_re.DOTALL).strip()
                msg = msg.strip('"').strip("'")
                with _preview_lock:
                    _preview_tasks[task_id] = {
                        "status": "done",
                        "result": {
                            "message": msg,
                            "chars": len(msg),
                            "mode": "dynamic",
                            "lead_name": lead.get("name", ""),
                        },
                    }
            except Exception as e:
                logger.error("Preview generation failed: %s", e)
                with _preview_lock:
                    _preview_tasks[task_id] = {
                        "status": "error",
                        "result": {"error": f"LLM generation failed: {e}"},
                    }

        t = threading.Thread(target=_generate_preview, daemon=True)
        t.start()
        return jsonify({"task_id": task_id, "status": "generating"})

    @app.route("/api/agent/preview/<task_id>")
    def api_agent_preview_poll(task_id: str):  # type: ignore[no-untyped-def]
        with _preview_lock:
            task = _preview_tasks.get(task_id)
        if not task:
            return jsonify({"error": "Task not found"}), 404
        if task["status"] == "generating":
            return jsonify({"status": "generating"})
        # Done or error - return result and clean up
        with _preview_lock:
            _preview_tasks.pop(task_id, None)
        return jsonify({"status": task["status"], **(task["result"] or {})})

    @app.route("/api/agent/dry-run", methods=["POST"])
    def api_agent_dry_run():  # type: ignore[no-untyped-def]
        body = request.get_json(force=True, silent=True) or {}
        mode = body.get("mode", "dynamic")

        all_leads = store.get_leads(limit=1)
        if not all_leads:
            return jsonify({"error": "No leads in database. Import some first."}), 400

        lead = all_leads[0]
        handle = lead.get("instagram_handle", "unknown")
        from openreach.llm.prompts import build_static_message, build_dynamic_prompt, build_system_prompt

        if mode == "static":
            template = body.get("message_template", "")
            if not template:
                return jsonify({"error": "No message template provided"}), 400
            msg = build_static_message(template, lead)
            store.log_activity(
                campaign_id=None, session_id=None, level="info",
                message=f"[DRY RUN] Would send to @{handle}: {msg[:100]}..."
            )
            return jsonify({
                "message": msg, "chars": len(msg), "mode": "static",
                "handle": handle, "lead_name": lead.get("name", ""),
                "dry_run": True, "status": "done",
            })

        # Dynamic mode - background generation
        import uuid
        task_id = str(uuid.uuid4())[:8]
        with _preview_lock:
            _preview_tasks[task_id] = {"status": "generating", "result": None}

        def _generate_dry_run():
            try:
                from openreach.llm.client import OllamaClient
                system = build_system_prompt(body)
                user_msg = build_dynamic_prompt(lead, None)
                llm_cfg = cfg.get("llm", {})
                llm = OllamaClient(
                    model=llm_cfg.get("model", "qwen3:4b"),
                    base_url=llm_cfg.get("base_url", "http://localhost:11434"),
                    temperature=llm_cfg.get("temperature", 0.7),
                )
                msg = llm.generate_sync(prompt=user_msg, system=system)
                import re as _re
                msg = _re.sub(r'<think>.*?</think>', '', msg, flags=_re.DOTALL).strip()
                msg = msg.strip('"').strip("'")
                store.log_activity(
                    campaign_id=None, session_id=None, level="info",
                    message=f"[DRY RUN] Would send to @{handle}: {msg[:100]}..."
                )
                with _preview_lock:
                    _preview_tasks[task_id] = {
                        "status": "done",
                        "result": {
                            "message": msg, "chars": len(msg), "mode": "dynamic",
                            "handle": handle, "lead_name": lead.get("name", ""),
                            "dry_run": True,
                        },
                    }
            except Exception as e:
                logger.error("Dry run generation failed: %s", e)
                with _preview_lock:
                    _preview_tasks[task_id] = {
                        "status": "error",
                        "result": {"error": f"LLM generation failed: {e}"},
                    }

        t = threading.Thread(target=_generate_dry_run, daemon=True)
        t.start()
        return jsonify({"task_id": task_id, "status": "generating"})

    # ---- Settings ----

    @app.route("/api/settings/verbose", methods=["POST"])
    def api_verbose_toggle():  # type: ignore[no-untyped-def]
        body = request.get_json(force=True, silent=True) or {}
        verbose = bool(body.get("verbose", False))
        save_config_value("debug.verbose", str(verbose))
        # Reconfigure Python logging level on the fly
        root = logging.getLogger()
        root.setLevel(logging.DEBUG if verbose else logging.INFO)
        logger.info("Verbose mode %s", "ENABLED" if verbose else "DISABLED")
        return jsonify({"ok": True, "verbose": verbose})

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
        verbose_raw = current.get("debug", {}).get("verbose", "False")
        verbose = str(verbose_raw).lower() in ("true", "1", "yes")
        return jsonify({
            "has_api_key": bool(api_key),
            "api_key_masked": masked,
            "base_url": cormass.get("base_url", "https://cormass.com/wp-json/leads/v1"),
            "verbose": verbose,
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
