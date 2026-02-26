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
    <!-- ====================================================================
         STYLES
         ==================================================================== -->
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

        /* Toast / notification (Item 29: stacking support) */
        .toast-container { position: fixed; bottom: 2rem; right: 2rem; z-index: 1000;
                           display: flex; flex-direction: column-reverse; gap: 0.5rem; max-width: 400px; }
        .toast { padding: 0.875rem 1.25rem; border-radius: 0.5rem; font-size: 0.875rem;
                 transform: translateX(120%); transition: transform 0.3s ease; }
        .toast.show { transform: translateX(0); }
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
            <button class="tab" onclick="switchTab('task')">Task</button>
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
                <button class="btn btn-primary" onclick="startAgent()" id="btn-start" style="padding: 0.375rem 0.875rem; font-size: 0.8125rem;">Start</button>
                <button class="btn btn-secondary" onclick="previewMessage()" id="btn-preview" style="padding: 0.375rem 0.875rem; font-size: 0.8125rem;">Preview</button>
                <button class="btn btn-secondary" onclick="dryRunMessage()" id="btn-dryrun" style="padding: 0.375rem 0.875rem; font-size: 0.8125rem;">Dry Run</button>
                <button class="btn btn-danger" onclick="stopAgent()" id="btn-stop" style="display:none; padding: 0.375rem 0.875rem; font-size: 0.8125rem;">Stop</button>
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
                    <div class="label">Tool Calls</div>
                    <div class="value blue" id="stat-tools">--</div>
                </div>
                <div class="stat-card">
                    <div class="label">Turns Used</div>
                    <div class="value yellow" id="stat-turns">--</div>
                </div>
                <div class="stat-card">
                    <div class="label">Failed</div>
                    <div class="value red" id="stat-failed">--</div>
                </div>
                <div class="stat-card">
                    <div class="label">Today</div>
                    <div class="value" id="stat-today">--</div>
                </div>
            </div>

            <!-- Token/Cost Display (Item 15) -->
            <div id="token-cost-bar" style="display:none; padding: 0.5rem 1rem; background: #171717; border: 1px solid #262626; border-radius: 0.5rem; margin-bottom: 1rem; font-size: 0.8125rem; color: #737373; display: flex; gap: 1.5rem;">
                <span>Tokens: <strong id="stat-tokens" style="color: #e5e5e5;">0</strong></span>
                <span>Cost: <strong id="stat-cost" style="color: #22c55e;">$0.000000</strong></span>
            </div>

            <!-- Progress Bar (Item 14) -->
            <div id="agent-progress-section" style="display:none; margin-bottom: 1rem;">
                <div style="display: flex; justify-content: space-between; font-size: 0.75rem; color: #737373; margin-bottom: 0.375rem;">
                    <span id="progress-label">Turn 0 / 50</span>
                    <span id="progress-pct">0%</span>
                </div>
                <div style="width: 100%; height: 6px; background: #262626; border-radius: 3px; overflow: hidden;">
                    <div id="agent-progress-bar" style="height: 100%; background: #7c3aed; border-radius: 3px; transition: width 0.3s ease; width: 0%;"></div>
                </div>
            </div>

            <!-- Live Agent Panel (Items 12+13) -->
            <div class="section" id="agent-live-panel" style="display:none;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.75rem;">
                    <h2 style="margin: 0;">Agent Live View</h2>
                    <span id="browser-state" style="font-size: 0.75rem; color: #737373;"></span>
                </div>
                <div id="agent-reasoning" style="max-height: 200px; overflow-y: auto; font-size: 0.8125rem; font-family: 'Consolas','Monaco',monospace; background: #0a0a0a; border: 1px solid #262626; border-radius: 0.5rem; padding: 0.75rem;">
                    <div style="color: #525252;">Waiting for agent reasoning...</div>
                </div>
            </div>

            <!-- Agent Stream -->
            <div class="section">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.75rem;">
                    <h2 style="margin: 0;">Agent Stream</h2>
                    <div style="display: flex; gap: 0.5rem;">
                        <button class="btn btn-secondary" onclick="clearActivityView()" style="font-size: 0.75rem; padding: 0.25rem 0.625rem;">Clear</button>
                    </div>
                </div>
                <div class="activity-log" id="activity-log">
                    <div class="activity-entry level-info"><span class="time">--:--:--</span>Waiting for agent to start...</div>
                </div>
            </div>

            <div class="section">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.75rem;">
                    <h2 style="margin: 0;">Leads</h2>
                    <div style="display: flex; gap: 0.5rem; align-items: center;">
                        <input type="text" class="form-input" id="lead-search" placeholder="Search leads..." style="width: 200px; padding: 0.375rem 0.625rem; font-size: 0.8125rem;" oninput="debounceSearchLeads()">
                        <span id="lead-count" style="font-size: 0.75rem; color: #737373;"></span>
                    </div>
                </div>
                <table>
                    <thead>
                        <tr>
                            <th>Name</th>
                            <th>Type</th>
                            <th>Location</th>
                            <th>Contact</th>
                            <th>Rating</th>
                            <th>Source</th>
                        </tr>
                    </thead>
                    <tbody id="leads-table">
                        <tr><td colspan="6" style="color: #525252">Loading...</td></tr>
                    </tbody>
                </table>
                <div id="leads-pagination" style="display: flex; justify-content: center; gap: 0.5rem; margin-top: 0.75rem;"></div>
            </div>
        </div>

        <!-- TASK TAB -->
        <div class="tab-content" id="tab-task">
            <div class="section">
                <h2>Task Configuration</h2>
                <p style="color: #737373; font-size: 0.875rem; margin-bottom: 1.25rem;">
                    Define what the AI agent should do. Write a natural-language task prompt and the
                    agent will use browser tools to execute it autonomously.
                </p>

                <div class="form-group">
                    <label for="task-name">Task Name</label>
                    <input type="text" class="form-input" id="task-name" placeholder="My Outreach Task">
                </div>

                <div class="form-group">
                    <label for="task-template-select">Quick Start Template</label>
                    <select class="form-select" id="task-template-select" onchange="applyTemplate()">
                        <option value="">-- Custom (blank) --</option>
                        <option value="instagram_dm">Instagram DM Outreach</option>
                        <option value="email_outreach">Email Outreach</option>
                        <option value="research">Business Research</option>
                        <option value="social_engagement">Social Media Engagement</option>
                    </select>
                </div>

                <div class="form-group">
                    <label for="task-prompt">Task Prompt (natural language instructions for the AI)</label>
                    <textarea class="form-textarea" id="task-prompt" rows="8"
                        placeholder="Example: Go to Instagram and send a personalized DM to each lead on my list. Mention their business type and location. Be friendly and professional. Offer a free consultation for our cleaning services."></textarea>
                    <div style="font-size: 0.7rem; color: #525252; margin-top: 0.375rem;">
                        This is the core instruction. The AI agent will read this and autonomously decide
                        which browser actions to take (navigate, click, type, etc.) to fulfill the task.
                    </div>
                </div>

                <div class="form-group">
                    <label for="task-notes">Additional Context (extra info for the AI)</label>
                    <textarea class="form-textarea" id="task-notes" rows="3"
                        placeholder="Our company is... We offer... Never mention pricing... Use a casual tone..."></textarea>
                    <div style="font-size: 0.7rem; color: #525252; margin-top: 0.375rem;">
                        Additional context: your company info, USPs, tone preferences, things to avoid, credentials, etc.
                    </div>
                </div>

                <div class="divider"></div>

                <h3 style="font-size: 1rem; margin-bottom: 1rem;">LLM Configuration</h3>
                <div class="form-cols">
                    <div class="form-group">
                        <label>Provider</label>
                        <div class="mode-toggle">
                            <button id="provider-openrouter" class="active" onclick="setProvider('openrouter')">OpenRouter (Cloud)</button>
                            <button id="provider-ollama" onclick="setProvider('ollama')">Ollama (Local)</button>
                        </div>
                    </div>
                    <div class="form-group">
                        <label for="task-model">Model</label>
                        <input type="text" class="form-input" id="task-model" value="qwen/qwen3-235b-a22b-2507"
                               placeholder="e.g. qwen/qwen3-235b-a22b-2507">
                    </div>
                </div>
                <div class="form-group" id="openrouter-key-group">
                    <label for="task-openrouter-key">OpenRouter API Key</label>
                    <input type="password" class="form-input" id="task-openrouter-key"
                           placeholder="sk-or-v1-xxxxxxxxxxxxxxxx">
                    <div style="font-size: 0.7rem; color: #525252; margin-top: 0.375rem;">
                        Get your key at <a href="https://openrouter.ai/keys" target="_blank" style="color: #7c3aed;">openrouter.ai/keys</a>.
                        This overrides the global key in Settings for this task only.
                    </div>
                </div>
                <div id="ollama-warning" style="display: none; padding: 0.875rem 1rem; background: #422006; border: 1px solid #854d0e; border-radius: 0.5rem; margin-bottom: 1.25rem;">
                    <div style="font-weight: 600; color: #fbbf24; font-size: 0.875rem; margin-bottom: 0.375rem;">Ollama Limitation</div>
                    <div style="font-size: 0.8125rem; color: #fde68a; line-height: 1.5;">
                        Local Ollama models do <strong>not support tool-calling</strong>. The agent will generate a single
                        text response instead of autonomously controlling the browser. For full agent capabilities
                        (navigate, click, type, send messages), use OpenRouter with a tool-capable model.
                    </div>
                </div>

                <div class="divider"></div>

                <h3 style="font-size: 1rem; margin-bottom: 1rem;">Context Canvases (Lead Source)</h3>
                <div class="form-group">
                    <label for="task-canvas-ids">Canvas IDs (comma-separated)</label>
                    <input type="text" class="form-input" id="task-canvas-ids"
                           placeholder="e.g. 42, 87 -- leave blank to use all imported leads">
                    <div style="font-size: 0.7rem; color: #525252; margin-top: 0.375rem;">
                        Specify which Cormass Leads canvases to use. The agent will have access to leads from these canvases.
                    </div>
                </div>

                <div class="divider"></div>

                <h3 style="font-size: 1rem; margin-bottom: 1rem;">Limits</h3>
                <div class="form-cols">
                    <div class="form-group">
                        <label for="task-daily">Daily Limit</label>
                        <input type="number" class="form-input" id="task-daily" value="50" min="1" max="500">
                    </div>
                    <div class="form-group">
                        <label for="task-session">Per Session Limit</label>
                        <input type="number" class="form-input" id="task-session" value="15" min="1" max="100">
                    </div>
                </div>
                <div class="form-cols">
                    <div class="form-group">
                        <label for="task-delay-min">Min Delay (seconds)</label>
                        <input type="number" class="form-input" id="task-delay-min" value="45" min="10" max="600">
                    </div>
                    <div class="form-group">
                        <label for="task-delay-max">Max Delay (seconds)</label>
                        <input type="number" class="form-input" id="task-delay-max" value="180" min="20" max="900">
                    </div>
                </div>

                <div class="divider"></div>

                <div style="display: flex; gap: 0.75rem; flex-wrap: wrap;">
                    <button class="btn btn-primary" onclick="saveTask()" id="btn-save-task">Save Task</button>
                    <button class="btn btn-secondary" onclick="newTask()">New Task</button>
                </div>

                <div id="task-status" style="margin-top: 0.75rem; font-size: 0.8125rem;"></div>
            </div>

            <!-- Saved Tasks -->
            <div class="section">
                <h2>Saved Tasks</h2>
                <div id="tasks-list" style="margin-top: 0.75rem;">
                    <div style="color: #525252; font-size: 0.875rem;">Loading tasks...</div>
                </div>
            </div>
        </div>

        <!-- IMPORT LEADS TAB -->
        <div class="tab-content" id="tab-import">
            <!-- Item 19: CSV Import -->
            <div class="section">
                <h2>Import from CSV File</h2>
                <p style="color: #737373; font-size: 0.875rem; margin-bottom: 1rem;">
                    Upload a CSV file with lead data. Required column: <strong>name</strong>.
                    Optional: instagram_handle, email, phone_number, business_type, location, website.
                </p>
                <div style="display: flex; gap: 0.75rem; align-items: center;">
                    <input type="file" id="csv-file-input" accept=".csv" style="font-size: 0.8125rem; color: #e5e5e5;">
                    <button class="btn btn-primary" onclick="importCSV()" id="btn-import-csv" style="font-size: 0.8125rem; padding: 0.375rem 0.875rem;">
                        Import CSV
                    </button>
                </div>
                <div id="csv-import-result" style="margin-top: 0.75rem; font-size: 0.8125rem;"></div>
            </div>

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
                <h2>OpenRouter API (LLM)</h2>
                <p style="color: #737373; font-size: 0.875rem; margin-bottom: 1.25rem;">
                    Configure the default OpenRouter API key for AI agent tasks.
                    Get a key at <a href="https://openrouter.ai/keys" target="_blank" style="color: #7c3aed;">openrouter.ai/keys</a>.
                </p>
                <div class="form-row">
                    <div class="form-group">
                        <label for="openrouter-key-input">OpenRouter API Key</label>
                        <input type="password" class="form-input" id="openrouter-key-input"
                               placeholder="sk-or-v1-xxxxxxxxxxxxxxxx">
                    </div>
                    <div style="padding-bottom: 0;">
                        <button class="btn btn-primary" onclick="saveOpenRouterKey()" id="btn-save-or-key">Save</button>
                    </div>
                    <div style="padding-bottom: 0;">
                        <button class="btn btn-secondary" onclick="testLLMConnection()" id="btn-test-llm">Test</button>
                    </div>
                </div>
                <div id="openrouter-key-status" style="margin-top: 0.75rem; font-size: 0.8125rem;"></div>

                <div class="form-cols" style="margin-top: 1rem;">
                    <div class="form-group">
                        <label for="default-model-input">Default Model</label>
                        <input type="text" class="form-input" id="default-model-input"
                               value="qwen/qwen3-235b-a22b-2507" placeholder="e.g. qwen/qwen3-235b-a22b-2507">
                    </div>
                    <div class="form-group">
                        <label for="default-provider-input">Default Provider</label>
                        <select class="form-select" id="default-provider-input">
                            <option value="openrouter">OpenRouter (Cloud)</option>
                            <option value="ollama">Ollama (Local)</option>
                        </select>
                    </div>
                </div>
                <button class="btn btn-secondary" onclick="saveLLMDefaults()" style="margin-top: 0.5rem;">Save LLM Defaults</button>
            </div>

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

            <!-- Item 18: Connect Instagram Account -->
            <div class="section">
                <h2>Instagram Account</h2>
                <p style="color: #737373; font-size: 0.875rem; margin-bottom: 1rem;">
                    OpenReach uses a real browser to automate Instagram. You must log in to Instagram
                    once in the agent browser so cookies are saved for future sessions.
                </p>
                <div style="padding: 1rem; background: #0a0a0a; border: 1px solid #262626; border-radius: 0.5rem; margin-bottom: 1rem;">
                    <div style="font-weight: 500; margin-bottom: 0.75rem;">How to connect your Instagram account:</div>
                    <ol style="color: #94a3b8; font-size: 0.8125rem; line-height: 1.8; padding-left: 1.25rem;">
                        <li>Create a simple task with prompt: <code style="background:#171717;padding:0.125rem 0.375rem;border-radius:0.25rem;">Navigate to instagram.com and wait</code></li>
                        <li>Start the agent -- a browser window will open</li>
                        <li>Log in to Instagram manually in that browser window</li>
                        <li>Stop the agent -- your login cookies are automatically saved</li>
                        <li>Future agent runs will reuse your saved login session</li>
                    </ol>
                </div>
                <div style="font-size: 0.75rem; color: #525252;">
                    Cookies are stored locally at: <code style="background:#171717;padding:0.125rem 0.375rem;border-radius:0.25rem;">~/.openreach/browser_state/</code>
                </div>
            </div>

            <!-- Item 23: Activity Log Cleanup -->
            <div class="section">
                <h2>Maintenance</h2>
                <p style="color: #737373; font-size: 0.875rem; margin-bottom: 1rem;">
                    Clean up old activity log entries to keep the database lean.
                </p>
                <div style="display: flex; gap: 0.75rem; align-items: center;">
                    <span style="font-size: 0.875rem;">Delete entries older than</span>
                    <input type="number" class="form-input" id="cleanup-days" value="30" min="1" max="365" style="width: 80px;">
                    <span style="font-size: 0.875rem;">days</span>
                    <button class="btn btn-danger" onclick="cleanupActivity()" style="font-size: 0.8125rem; padding: 0.375rem 0.875rem;">Clean Up</button>
                </div>
                <div id="cleanup-result" style="margin-top: 0.5rem; font-size: 0.8125rem; color: #737373;"></div>
            </div>
        </div>

        <div class="footer">
            <p>OpenReach v{{ version }} -- <a href="https://github.com/Coolcorbinian/OpenReach">GitHub</a></p>
        </div>
    </div>

    <!-- Toast container (Item 29: stacking) -->
    <div class="toast-container" id="toast-container"></div>

    <script>
        // ---- State ----
        let currentTaskId = null;
        let currentProvider = 'openrouter';
        let agentRunning = false;
        let lastActivityId = 0;
        let activityPollTimer = null;
        let statusPollTimer = null;
        let verboseMode = false;

        // ---- Task Templates ----
        const TASK_TEMPLATES = {
            instagram_dm: "Go to Instagram and send a personalized direct message to each lead. For each lead:\\n1. Navigate to their Instagram profile\\n2. Click the Message button\\n3. Write a short, friendly message referencing their business type and location\\n4. Send the message and log it\\n\\nBe human-like: wait a few seconds between actions, do not rush.",
            email_outreach: "For each lead that has an email address:\\n1. Navigate to Gmail (or the email service I am logged into)\\n2. Compose a new email to the lead's email address\\n3. Write a professional but friendly email offering our services\\n4. Send the email and log it",
            research: "Research each lead's online presence:\\n1. Search for their business on Google\\n2. Visit their website if available\\n3. Check their social media profiles\\n4. Report a summary of findings using report_progress",
            social_engagement: "Visit each lead's social media profiles and engage naturally:\\n1. Find their Instagram or Facebook page\\n2. Like 1-2 recent posts\\n3. Leave a genuine, relevant comment on one post\\n4. Report what you did"
        };

        // ---- Tab switching ----
        function switchTab(tabId) {
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
            document.getElementById('tab-' + tabId).classList.add('active');
            document.querySelector('.tab[onclick*="' + tabId + '"]').classList.add('active');

            if (tabId === 'import') { checkImportReady(); }
            if (tabId === 'settings') { loadSettings(); }
            if (tabId === 'task') { loadTasks(); }
        }

        // ---- Toast notifications (Item 29: stacking) ----
        function showToast(message, type) {
            var container = document.getElementById('toast-container');
            var toast = document.createElement('div');
            toast.className = 'toast toast-' + (type || 'info');
            toast.textContent = message;
            container.appendChild(toast);
            // Trigger animation
            requestAnimationFrame(function() { toast.classList.add('show'); });
            // Limit to 5 stacked toasts
            while (container.children.length > 5) { container.removeChild(container.firstChild); }
            setTimeout(function() {
                toast.classList.remove('show');
                setTimeout(function() { if (toast.parentNode) toast.parentNode.removeChild(toast); }, 350);
            }, 4000);
        }

        // ---- Dashboard: Stats + Leads ----
        async function loadStats() {
            try {
                const res = await fetch('/api/stats');
                const data = await res.json();
                document.getElementById('stat-leads').textContent = data.total_leads;
                document.getElementById('stat-sent').textContent = data.total_sent;
                document.getElementById('stat-tools').textContent = data.tool_calls || 0;
                document.getElementById('stat-turns').textContent = data.turns_used || 0;
                document.getElementById('stat-failed').textContent = data.total_failed;
                document.getElementById('stat-today').textContent = data.today_sent;
            } catch (e) { console.error('Failed to load stats', e); }
        }

        // loadLeads is defined below (Search & Pagination section) -- skip the old version

        // ---- Agent Controls ----
        async function startAgent() {
            // Item 17: Confirmation dialog before starting
            if (!confirm('Start the agent? It will control the browser autonomously using the active task prompt.')) {
                return;
            }
            try {
                const res = await fetch('/api/agent/start', { method: 'POST' });
                const data = await res.json();
                if (data.error) {
                    showToast(data.error, 'error');
                    return;
                }
                agentRunning = true;
                updateAgentUI('running');
                showToast('Agent started (' + data.provider + ' / ' + (data.model || 'default') + ')', 'success');
                startActivityPolling();
                startStatusPolling();
            } catch (e) {
                showToast('Failed to start agent', 'error');
            }
        }

        // Item 16: Preview button
        async function previewMessage() {
            try {
                var promptEl = document.getElementById('task-prompt');
                var prompt = promptEl ? promptEl.value.trim() : '';
                if (!prompt) { showToast('Save a task with a prompt first', 'error'); return; }
                showToast('Generating preview...', 'info');
                var res = await fetch('/api/agent/preview', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ user_prompt: prompt })
                });
                var data = await res.json();
                if (data.error) { showToast(data.error, 'error'); return; }
                // Poll for result
                var taskId = data.task_id;
                var poll = setInterval(async function() {
                    var r = await fetch('/api/agent/preview/' + taskId);
                    var d = await r.json();
                    if (d.status === 'done') {
                        clearInterval(poll);
                        alert('Preview message for ' + (d.lead_name || 'first lead') + ':\\n\\n' + d.message);
                    } else if (d.status === 'error') {
                        clearInterval(poll);
                        showToast(d.error || 'Preview failed', 'error');
                    }
                }, 1500);
            } catch (e) { showToast('Preview failed', 'error'); }
        }

        // Item 16: Dry run button
        async function dryRunMessage() {
            try {
                var promptEl = document.getElementById('task-prompt');
                var prompt = promptEl ? promptEl.value.trim() : '';
                if (!prompt) { showToast('Save a task with a prompt first', 'error'); return; }
                showToast('Running dry run...', 'info');
                var res = await fetch('/api/agent/dry-run', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ user_prompt: prompt })
                });
                var data = await res.json();
                if (data.error) { showToast(data.error, 'error'); return; }
                var taskId = data.task_id;
                var poll = setInterval(async function() {
                    var r = await fetch('/api/agent/preview/' + taskId);
                    var d = await r.json();
                    if (d.status === 'done') {
                        clearInterval(poll);
                        alert('[DRY RUN] Message for ' + (d.lead_name || 'first lead') + ':\\n\\n' + d.message + '\\n\\n(' + d.chars + ' chars)');
                    } else if (d.status === 'error') {
                        clearInterval(poll);
                        showToast(d.error || 'Dry run failed', 'error');
                    }
                }, 1500);
            } catch (e) { showToast('Dry run failed', 'error'); }
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
            const btnPreview = document.getElementById('btn-preview');
            const btnDryrun = document.getElementById('btn-dryrun');
            const statusHeader = document.getElementById('agent-status');
            const progressSection = document.getElementById('agent-progress-section');
            const livePanel = document.getElementById('agent-live-panel');
            const tokenBar = document.getElementById('token-cost-bar');

            if (state === 'running' || state === 'starting' || state === 'waiting') {
                pulse.className = 'pulse running';
                const labels = { running: 'Running', starting: 'Starting', waiting: 'Waiting for LLM' };
                text.textContent = 'Agent: ' + (labels[state] || 'Running');
                btnStart.style.display = 'none';
                btnPreview.style.display = 'none';
                btnDryrun.style.display = 'none';
                btnStop.style.display = '';
                agentRunning = true;
                if (progressSection) progressSection.style.display = '';
                if (livePanel) livePanel.style.display = '';
                if (tokenBar) tokenBar.style.display = 'flex';
            } else if (state === 'error') {
                pulse.className = 'pulse error';
                text.textContent = 'Agent: Error';
                btnStart.style.display = '';
                btnPreview.style.display = '';
                btnDryrun.style.display = '';
                btnStop.style.display = 'none';
                agentRunning = false;
                stopActivityPolling();
                stopStatusPolling();
            } else {
                pulse.className = 'pulse idle';
                text.textContent = 'Agent: Idle';
                btnStart.style.display = '';
                btnPreview.style.display = '';
                btnDryrun.style.display = '';
                btnStop.style.display = 'none';
                agentRunning = false;
                stopActivityPolling();
                stopStatusPolling();
                if (progressSection) progressSection.style.display = 'none';
                if (livePanel) livePanel.style.display = 'none';
                if (tokenBar) tokenBar.style.display = 'none';
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
                    const reasoningEl = document.getElementById('agent-reasoning');
                    const browserState = document.getElementById('browser-state');
                    // Remove placeholder
                    if (lastActivityId === 0) {
                        logEl.innerHTML = '';
                        if (reasoningEl) reasoningEl.innerHTML = '';
                    }
                    entries.forEach(e => {
                        const div = document.createElement('div');
                        div.className = 'activity-entry level-' + e.level;
                        const time = e.created_at ? new Date(e.created_at).toLocaleTimeString() : '--:--:--';
                        div.innerHTML = '<span class="time">' + time + '</span>' + esc(e.message);
                        logEl.appendChild(div);
                        lastActivityId = Math.max(lastActivityId, e.id);

                        // Item 12: Feed agent reasoning/tool calls into the live panel
                        if (reasoningEl && e.message && (
                            e.message.indexOf('[Agent]') >= 0 ||
                            e.message.indexOf('Calling ') >= 0 ||
                            e.message.indexOf('Tool ') >= 0 ||
                            e.message.indexOf('Navigated to') >= 0 ||
                            e.message.indexOf('Clicked') >= 0 ||
                            e.level === 'success' || e.level === 'error'
                        )) {
                            var rdiv = document.createElement('div');
                            rdiv.style.cssText = 'padding:0.25rem 0;border-bottom:1px solid #1a1a1a;color:' +
                                (e.level === 'error' ? '#f87171' : e.level === 'success' ? '#4ade80' : '#94a3b8');
                            rdiv.textContent = e.message;
                            reasoningEl.appendChild(rdiv);
                            reasoningEl.scrollTop = reasoningEl.scrollHeight;
                        }

                        // Item 13: Extract browser state from navigation messages
                        if (browserState && e.message) {
                            var navMatch = e.message.match(/Navigated to (\\S+)/);
                            if (navMatch) browserState.textContent = 'URL: ' + navMatch[1];
                        }
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
                    var s = data.stats;
                    detail.textContent = 'Tools: ' + (s.tool_calls_made || 0) +
                        ' | Turns: ' + (s.turns_used || 0) +
                        ' | Sent: ' + (s.messages_sent || 0);

                    // Item 14: Update progress bar
                    var maxTurns = 50; // default
                    var turns = s.turns_used || 0;
                    var pct = Math.min(100, Math.round(turns / maxTurns * 100));
                    var progressLabel = document.getElementById('progress-label');
                    var progressPct = document.getElementById('progress-pct');
                    var progressBar = document.getElementById('agent-progress-bar');
                    if (progressLabel) progressLabel.textContent = 'Turn ' + turns + ' / ' + maxTurns;
                    if (progressPct) progressPct.textContent = pct + '%';
                    if (progressBar) progressBar.style.width = pct + '%';

                    // Item 15: Update token/cost display
                    var tokensEl = document.getElementById('stat-tokens');
                    var costEl = document.getElementById('stat-cost');
                    if (tokensEl) tokensEl.textContent = (s.total_tokens || 0).toLocaleString();
                    if (costEl) costEl.textContent = '$' + (s.total_cost || 0).toFixed(6);
                }
                if (data.state === 'idle' || data.state === 'stopped' || data.state === 'error') {
                    loadStats(); // refresh dashboard stats after run
                }
            } catch (e) { console.error('Status poll error', e); }
        }

        // ---- Task Tab ----
        function setProvider(provider) {
            currentProvider = provider;
            document.getElementById('provider-openrouter').classList.toggle('active', provider === 'openrouter');
            document.getElementById('provider-ollama').classList.toggle('active', provider === 'ollama');
            document.getElementById('openrouter-key-group').style.display = provider === 'openrouter' ? '' : 'none';
            // Show/hide Ollama limitation warning
            var ollamaWarn = document.getElementById('ollama-warning');
            if (ollamaWarn) ollamaWarn.style.display = provider === 'ollama' ? '' : 'none';
            if (provider === 'ollama') {
                document.getElementById('task-model').value = 'qwen3:4b';
            } else {
                document.getElementById('task-model').value = 'qwen/qwen3-235b-a22b-2507';
            }
        }

        function applyTemplate() {
            const sel = document.getElementById('task-template-select').value;
            if (sel && TASK_TEMPLATES[sel]) {
                document.getElementById('task-prompt').value = TASK_TEMPLATES[sel];
            }
        }

        function getTaskFormData() {
            return {
                name: document.getElementById('task-name').value.trim() || 'Default Task',
                platform: 'browser',
                mode: 'agent',
                user_prompt: document.getElementById('task-prompt').value.trim(),
                additional_notes: document.getElementById('task-notes').value.trim(),
                context_canvas_ids: document.getElementById('task-canvas-ids').value.trim(),
                llm_provider: currentProvider,
                llm_model: document.getElementById('task-model').value.trim(),
                daily_limit: parseInt(document.getElementById('task-daily').value) || 50,
                session_limit: parseInt(document.getElementById('task-session').value) || 15,
                delay_min: parseInt(document.getElementById('task-delay-min').value) || 45,
                delay_max: parseInt(document.getElementById('task-delay-max').value) || 180,
            };
        }

        function loadTaskIntoForm(c) {
            currentTaskId = c.id;
            document.getElementById('task-name').value = c.name || '';
            document.getElementById('task-prompt').value = c.user_prompt || '';
            document.getElementById('task-notes').value = c.additional_notes || '';
            document.getElementById('task-canvas-ids').value = c.context_canvas_ids || '';
            setProvider(c.llm_provider || 'openrouter');
            document.getElementById('task-model').value = c.llm_model || 'qwen/qwen3-235b-a22b-2507';
            document.getElementById('task-daily').value = c.daily_limit || 50;
            document.getElementById('task-session').value = c.session_limit || 15;
            document.getElementById('task-delay-min').value = c.delay_min || 45;
            document.getElementById('task-delay-max').value = c.delay_max || 180;
            // Per-task OpenRouter key is not stored in DB, user enters per session
            document.getElementById('task-openrouter-key').value = '';
        }

        function newTask() {
            currentTaskId = null;
            document.getElementById('task-name').value = '';
            document.getElementById('task-prompt').value = '';
            document.getElementById('task-notes').value = '';
            document.getElementById('task-canvas-ids').value = '';
            document.getElementById('task-template-select').value = '';
            setProvider('openrouter');
            document.getElementById('task-model').value = 'qwen/qwen3-235b-a22b-2507';
            document.getElementById('task-openrouter-key').value = '';
            showToast('Form cleared for new task', 'info');
        }

        async function saveTask() {
            const data = getTaskFormData();
            const btn = document.getElementById('btn-save-task');
            btn.disabled = true; btn.textContent = 'Saving...';

            try {
                let url = '/api/campaigns';
                let method = 'POST';
                if (currentTaskId) {
                    url = '/api/campaigns/' + currentTaskId;
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
                    currentTaskId = result.id;
                    showToast('Task saved', 'success');
                    loadTasks();
                }
            } catch (e) {
                showToast('Failed to save task', 'error');
            }
            btn.disabled = false; btn.textContent = 'Save Task';
        }

        async function loadTasks() {
            try {
                const res = await fetch('/api/campaigns');
                const tasks = await res.json();
                const listEl = document.getElementById('tasks-list');
                if (!tasks.length) {
                    listEl.innerHTML = '<div style="color: #525252; font-size: 0.875rem;">No tasks yet. Configure one above and save.</div>';
                    return;
                }
                listEl.innerHTML = tasks.map(c => `
                    <div class="campaign-card ${c.is_active ? 'active-campaign' : ''}">
                        <div class="campaign-info">
                            <div class="campaign-name">${esc(c.name)} ${c.is_active ? '<span class="badge badge-sent">Active</span>' : ''}</div>
                            <div class="campaign-meta">${esc(c.llm_provider || 'openrouter')} / ${esc(c.llm_model || 'default')} ${c.context_canvas_ids ? '| Canvases: ' + esc(c.context_canvas_ids) : ''}</div>
                        </div>
                        <div style="display: flex; gap: 0.5rem;">
                            <button class="btn btn-secondary" onclick="editTask(${c.id})" style="font-size: 0.75rem; padding: 0.25rem 0.625rem;">Edit</button>
                            <button class="btn ${c.is_active ? 'btn-danger' : 'btn-success'}" onclick="toggleTaskActive(${c.id}, ${!c.is_active})" style="font-size: 0.75rem; padding: 0.25rem 0.625rem;">
                                ${c.is_active ? 'Deactivate' : 'Activate'}
                            </button>
                            <button class="btn btn-secondary" onclick="deleteTask(${c.id})" style="font-size: 0.75rem; padding: 0.25rem 0.625rem; color: #f87171;">Delete</button>
                        </div>
                    </div>
                `).join('');
            } catch (e) {
                console.error('Failed to load tasks', e);
            }
        }

        async function editTask(id) {
            try {
                const res = await fetch('/api/campaigns/' + id);
                const c = await res.json();
                if (c.error) { showToast(c.error, 'error'); return; }
                loadTaskIntoForm(c);
                showToast('Task loaded for editing', 'info');
                window.scrollTo(0, 0);
            } catch (e) { showToast('Failed to load task', 'error'); }
        }

        async function toggleTaskActive(id, active) {
            try {
                const res = await fetch('/api/campaigns/' + id, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ is_active: active })
                });
                const data = await res.json();
                if (data.error) { showToast(data.error, 'error'); return; }
                showToast(active ? 'Task activated' : 'Task deactivated', 'success');
                loadTasks();
            } catch (e) { showToast('Failed to update task', 'error'); }
        }

        async function deleteTask(id) {
            if (!confirm('Delete this task?')) return;
            try {
                const res = await fetch('/api/campaigns/' + id, { method: 'DELETE' });
                const data = await res.json();
                if (data.ok) {
                    if (currentTaskId === id) { currentTaskId = null; }
                    showToast('Task deleted', 'success');
                    loadTasks();
                } else {
                    showToast(data.error || 'Delete failed', 'error');
                }
            } catch (e) { showToast('Failed to delete task', 'error'); }
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
                // OpenRouter settings
                document.getElementById('openrouter-key-input').value = data.openrouter_key_masked || '';
                if (data.has_openrouter_key) {
                    document.getElementById('openrouter-key-input').placeholder = 'Key saved (enter new key to replace)';
                }
                document.getElementById('default-model-input').value = data.llm_model || 'qwen/qwen3-235b-a22b-2507';
                document.getElementById('default-provider-input').value = data.llm_provider || 'openrouter';
                // Verbose toggle
                verboseMode = !!data.verbose;
                document.getElementById('verbose-toggle').checked = verboseMode;
                document.getElementById('verbose-badge').classList.toggle('active', verboseMode);
            } catch (e) { console.error('Failed to load settings', e); }
        }

        async function saveOpenRouterKey() {
            const key = document.getElementById('openrouter-key-input').value.trim();
            if (!key || key.includes('*')) {
                showToast('Enter a valid OpenRouter API key', 'error');
                return;
            }
            const btn = document.getElementById('btn-save-or-key');
            btn.disabled = true; btn.textContent = 'Saving...';
            try {
                const res = await fetch('/api/settings', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ openrouter_api_key: key })
                });
                const data = await res.json();
                if (data.ok) {
                    showToast('OpenRouter API key saved', 'success');
                    document.getElementById('openrouter-key-input').value = data.openrouter_key_masked || '';
                } else {
                    showToast(data.error || 'Failed to save key', 'error');
                }
            } catch (e) { showToast('Network error', 'error'); }
            btn.disabled = false; btn.textContent = 'Save';
        }

        async function saveLLMDefaults() {
            const model = document.getElementById('default-model-input').value.trim();
            const provider = document.getElementById('default-provider-input').value;
            try {
                const res = await fetch('/api/settings', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ llm_model: model, llm_provider: provider })
                });
                const data = await res.json();
                if (data.ok) {
                    showToast('LLM defaults saved', 'success');
                } else {
                    showToast(data.error || 'Failed to save', 'error');
                }
            } catch (e) { showToast('Network error', 'error'); }
        }

        async function testLLMConnection() {
            const btn = document.getElementById('btn-test-llm');
            btn.disabled = true; btn.textContent = 'Testing...';
            const statusEl = document.getElementById('openrouter-key-status');
            statusEl.innerHTML = '<span class="status-dot checking"></span> Testing connection...';
            try {
                const res = await fetch('/api/llm/health');
                const data = await res.json();
                if (data.ok) {
                    statusEl.innerHTML = '<span class="status-dot connected"></span> Connected to ' + esc(data.provider);
                    showToast('LLM connection successful', 'success');
                } else {
                    statusEl.innerHTML = '<span class="status-dot disconnected"></span> ' + esc(data.error || 'Connection failed');
                    showToast(data.error || 'Connection failed', 'error');
                }
            } catch (e) {
                statusEl.innerHTML = '<span class="status-dot disconnected"></span> Network error';
            }
            btn.disabled = false; btn.textContent = 'Test';
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

        // ---- CSV Import (Item 19) ----
        async function importCSV() {
            var fileInput = document.getElementById('csv-file-input');
            var resultEl = document.getElementById('csv-import-result');
            if (!fileInput.files || !fileInput.files[0]) {
                showToast('Select a CSV file first', 'error');
                return;
            }
            var btn = document.getElementById('btn-import-csv');
            btn.disabled = true; btn.textContent = 'Importing...';
            resultEl.textContent = '';
            var formData = new FormData();
            formData.append('file', fileInput.files[0]);
            try {
                var res = await fetch('/api/leads/import-csv', { method: 'POST', body: formData });
                var data = await res.json();
                if (data.error) {
                    resultEl.innerHTML = '<span style="color:#f87171;">' + esc(data.error) + '</span>';
                    showToast(data.error, 'error');
                } else {
                    resultEl.innerHTML = '<span style="color:#4ade80;">Imported ' + data.imported + ' leads</span>';
                    showToast('Imported ' + data.imported + ' leads from CSV', 'success');
                    loadStats(); loadLeads();
                }
            } catch (e) { showToast('CSV import failed', 'error'); }
            btn.disabled = false; btn.textContent = 'Import CSV';
        }

        // ---- Lead Search & Pagination (Item 20) ----
        let leadSearchTimer = null;
        let currentLeadPage = 0;
        const LEADS_PER_PAGE = 20;

        function debounceSearchLeads() {
            if (leadSearchTimer) clearTimeout(leadSearchTimer);
            leadSearchTimer = setTimeout(function() { currentLeadPage = 0; loadLeads(); }, 400);
        }

        async function loadLeads(page) {
            if (page !== undefined) currentLeadPage = page;
            var search = (document.getElementById('lead-search') || {}).value || '';
            var offset = currentLeadPage * LEADS_PER_PAGE;
            try {
                var url = '/api/leads?limit=' + LEADS_PER_PAGE + '&offset=' + offset;
                if (search.trim()) url += '&search=' + encodeURIComponent(search.trim());
                const res = await fetch(url);
                const raw = await res.json();
                var leads = Array.isArray(raw) ? raw : (raw.leads || []);
                var total = raw.total || null;
                const tbody = document.getElementById('leads-table');
                var countEl = document.getElementById('lead-count');
                if (!leads.length) {
                    tbody.innerHTML = '<tr><td colspan="6" style="color:#525252">' + (search ? 'No leads match your search.' : 'No leads imported yet. Go to Import Leads tab to get started.') + '</td></tr>';
                    if (countEl) countEl.textContent = '';
                    document.getElementById('leads-pagination').innerHTML = '';
                    return;
                }
                if (countEl && total !== null) countEl.textContent = total + ' total';
                tbody.innerHTML = leads.map(function(l) {
                    var contact = '';
                    if (l.instagram_handle) contact += '@' + esc(l.instagram_handle);
                    if (l.email) contact += (contact ? ', ' : '') + esc(l.email);
                    if (l.phone_number) contact += (contact ? ', ' : '') + esc(l.phone_number);
                    if (!contact) contact = '-';
                    return '<tr style="cursor:pointer;" onclick="toggleLeadHistory(' + l.id + ', this)">' +
                        '<td>' + (esc(l.name) || '-') + '</td>' +
                        '<td>' + (esc(l.business_type) || '-') + '</td>' +
                        '<td>' + (esc(l.location) || '-') + '</td>' +
                        '<td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;">' + contact + '</td>' +
                        '<td>' + (l.rating != null ? l.rating.toFixed(1) : '-') + '</td>' +
                        '<td>' + (esc(l.source) || '-') + '</td></tr>';
                }).join('');
                // Pagination controls
                var pagDiv = document.getElementById('leads-pagination');
                if (total && total > LEADS_PER_PAGE) {
                    var pages = Math.ceil(total / LEADS_PER_PAGE);
                    var html = '';
                    for (var p = 0; p < pages && p < 10; p++) {
                        html += '<button class="btn btn-secondary" style="font-size:0.75rem;padding:0.25rem 0.5rem;' +
                            (p === currentLeadPage ? 'background:#7c3aed;color:#fff;' : '') +
                            '" onclick="loadLeads(' + p + ')">' + (p + 1) + '</button>';
                    }
                    pagDiv.innerHTML = html;
                } else {
                    pagDiv.innerHTML = '';
                }
            } catch (e) { console.error('Failed to load leads', e); }
        }

        // Item 21: Outreach history per lead (expandable row)
        async function toggleLeadHistory(leadId, rowEl) {
            var nextRow = rowEl.nextElementSibling;
            if (nextRow && nextRow.classList.contains('lead-history-row')) {
                nextRow.remove();
                return;
            }
            var tr = document.createElement('tr');
            tr.className = 'lead-history-row';
            tr.innerHTML = '<td colspan="6" style="background:#0a0a0a;padding:0.75rem;font-size:0.8125rem;"><span class="spinner"></span> Loading history...</td>';
            rowEl.after(tr);
            try {
                var res = await fetch('/api/leads/' + leadId + '/history');
                var history = await res.json();
                if (!history.length) {
                    tr.innerHTML = '<td colspan="6" style="background:#0a0a0a;padding:0.75rem;font-size:0.8125rem;color:#525252;">No outreach history for this lead.</td>';
                } else {
                    var html = '<td colspan="6" style="background:#0a0a0a;padding:0.75rem;"><div style="font-size:0.75rem;color:#737373;margin-bottom:0.5rem;">Outreach History (' + history.length + ' entries)</div>';
                    html += '<table style="width:100%;font-size:0.8125rem;">';
                    history.forEach(function(h) {
                        var badge = h.state === 'sent' ? 'badge-sent' : h.state === 'replied' ? 'badge-replied' : h.state === 'failed' ? 'badge-failed' : 'badge-pending';
                        html += '<tr><td><span class="badge ' + badge + '">' + esc(h.state) + '</span></td>' +
                            '<td>' + esc(h.channel) + '</td>' +
                            '<td style="max-width:300px;overflow:hidden;text-overflow:ellipsis;">' + (esc(h.message) || '-') + '</td>' +
                            '<td style="color:#525252;">' + (h.created_at ? new Date(h.created_at).toLocaleString() : '-') + '</td></tr>';
                    });
                    html += '</table></td>';
                    tr.innerHTML = html;
                }
            } catch (e) { tr.innerHTML = '<td colspan="6" style="background:#0a0a0a;color:#f87171;">Failed to load history</td>'; }
        }

        // Item 23: Activity log cleanup
        async function cleanupActivity() {
            var days = parseInt(document.getElementById('cleanup-days').value) || 30;
            if (!confirm('Delete activity log entries older than ' + days + ' days?')) return;
            try {
                var res = await fetch('/api/activity/cleanup', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ max_age_days: days })
                });
                var data = await res.json();
                if (data.ok) {
                    document.getElementById('cleanup-result').innerHTML = '<span style="color:#4ade80;">Deleted ' + data.deleted + ' old entries.</span>';
                    showToast('Cleaned up ' + data.deleted + ' entries', 'success');
                } else {
                    showToast(data.error || 'Cleanup failed', 'error');
                }
            } catch (e) { showToast('Cleanup failed', 'error'); }
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
        stats = store.get_stats()
        # Always include agent runtime keys with defaults (Item 2)
        stats.setdefault("tool_calls", 0)
        stats.setdefault("turns_used", 0)
        # Merge live agent runtime stats so dashboard cards reflect current run
        with _agent_lock:
            if _agent_engine:
                st = _agent_engine.stats
                stats["tool_calls"] = st.tool_calls_made
                stats["turns_used"] = st.turns_used
        return jsonify(stats)

    @app.route("/api/leads")
    def api_leads():  # type: ignore[no-untyped-def]
        limit = request.args.get("limit", 50, type=int)
        offset = request.args.get("offset", 0, type=int)
        search = request.args.get("search", "", type=str).strip() or None
        leads = store.get_leads(limit=limit, offset=offset, search=search)
        total = store.count_leads(search=search) if search or offset else None
        result = leads
        if total is not None:
            return jsonify({"leads": leads, "total": total})
        return jsonify(leads)

    @app.route("/api/leads/<int:lead_id>/history")
    def api_lead_history(lead_id: int):  # type: ignore[no-untyped-def]
        """Get outreach history for a lead (Item 21)."""
        history = store.get_lead_outreach_history(lead_id)
        return jsonify(history)

    @app.route("/api/leads/import-csv", methods=["POST"])
    def api_leads_import_csv():  # type: ignore[no-untyped-def]
        """Import leads from a CSV file upload (Item 19)."""
        if "file" not in request.files:
            return jsonify({"error": "No file uploaded"}), 400
        f = request.files["file"]
        if not f.filename or not f.filename.endswith(".csv"):
            return jsonify({"error": "File must be a .csv"}), 400
        try:
            import csv
            import io
            content = f.stream.read().decode("utf-8-sig")
            reader = csv.DictReader(io.StringIO(content))
            leads_data = []
            for row in reader:
                lead = {
                    "name": row.get("name", row.get("Name", row.get("business_name", ""))).strip(),
                    "instagram_handle": row.get("instagram_handle", row.get("instagram", "")).strip().lstrip("@"),
                    "phone_number": row.get("phone_number", row.get("phone", "")).strip(),
                    "email": row.get("email", row.get("Email", "")).strip(),
                    "business_type": row.get("business_type", row.get("type", row.get("category", ""))).strip(),
                    "location": row.get("location", row.get("address", row.get("city", ""))).strip(),
                    "website": row.get("website", row.get("url", "")).strip(),
                    "source": "csv",
                }
                if lead["name"]:
                    leads_data.append(lead)
            if not leads_data:
                return jsonify({"error": "No valid leads found in CSV. Ensure a 'name' column exists."}), 400
            imported = store.add_leads(leads_data)
            return jsonify({"imported": imported, "total_rows": len(leads_data)})
        except Exception as e:
            logger.error("CSV import failed: %s", e)
            return jsonify({"error": f"CSV parse error: {e}"}), 400

    @app.route("/api/activity/cleanup", methods=["POST"])
    def api_activity_cleanup():  # type: ignore[no-untyped-def]
        """Delete old activity log entries (Item 23)."""
        body = request.get_json(force=True, silent=True) or {}
        max_age_days = body.get("max_age_days", 30)
        try:
            deleted = store.cleanup_activity_log(max_age_days=int(max_age_days))
            return jsonify({"ok": True, "deleted": deleted})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

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

            # Find active task (campaign)
            campaign = store.get_active_campaign()
            if not campaign:
                return jsonify({"error": "No active task. Go to Task tab and activate one."}), 400

            if not campaign.get("user_prompt", "").strip():
                return jsonify({"error": "Active task has no prompt. Edit the task and add a task prompt."}), 400

            # Get leads for context
            leads = store.get_leads(limit=10000)

            from openreach.llm.client import LLMClient, LLMProvider
            from openreach.browser.session import BrowserSession
            from openreach.agent.engine import AgentEngine

            # Determine LLM config -- task-level overrides > global config
            current_cfg = load_config()
            llm_cfg = current_cfg.get("llm", {})

            provider_str = campaign.get("llm_provider") or llm_cfg.get("provider", "openrouter")
            provider = LLMProvider(provider_str)

            if provider == LLMProvider.OPENROUTER:
                api_key = llm_cfg.get("openrouter_api_key", "")
                if not api_key:
                    return jsonify({"error": "No OpenRouter API key configured. Add one in Settings."}), 400
                model = campaign.get("llm_model") or llm_cfg.get("model", "qwen/qwen3-235b-a22b-2507")
                base_url = "https://openrouter.ai/api/v1"
            else:
                api_key = ""
                model = campaign.get("llm_model") or llm_cfg.get("ollama_model", "qwen3:4b")
                base_url = llm_cfg.get("ollama_base_url", "http://localhost:11434")

            llm = LLMClient(
                provider=provider,
                api_key=api_key,
                model=model,
                base_url=base_url,
                temperature=llm_cfg.get("temperature", 0.4),
                max_tokens=llm_cfg.get("max_tokens", 4096),
                max_turns=llm_cfg.get("max_turns", 50),
            )
            browser = BrowserSession(config=current_cfg)
            cormass_client = _get_client()
            _agent_engine = AgentEngine(
                llm=llm, browser=browser, store=store, cormass_api=cormass_client
            )

            def _run():
                try:
                    asyncio.run(_agent_engine.start(campaign, leads))
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

        return jsonify({
            "status": "started",
            "leads_available": len(leads),
            "provider": provider_str,
            "model": model,
        })

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
                    "tool_calls_made": st.tool_calls_made,
                    "turns_used": st.turns_used,
                    "total_tokens": st.total_tokens,
                    "total_cost": round(st.total_cost, 6),
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

    # ---- Preview & Dry Run (Legacy - kept for backward compat) ----

    @app.route("/api/agent/preview", methods=["POST"])
    def api_agent_preview():  # type: ignore[no-untyped-def]
        """Generate a quick one-shot LLM response for preview purposes."""
        body = request.get_json(force=True, silent=True) or {}

        # Grab a sample lead
        all_leads = store.get_leads(limit=1)
        if not all_leads:
            return jsonify({"error": "No leads in database. Import some first."}), 400

        lead = all_leads[0]

        prompt = body.get("user_prompt", "").strip()
        if not prompt:
            return jsonify({"error": "No task prompt provided"}), 400

        # One-shot generation using configured LLM
        import uuid
        task_id = str(uuid.uuid4())[:8]
        with _preview_lock:
            _preview_tasks[task_id] = {"status": "generating", "result": None}

        def _generate_preview():
            try:
                from openreach.llm.client import LLMClient, LLMProvider
                current = load_config()
                llm_cfg = current.get("llm", {})
                provider_str = llm_cfg.get("provider", "openrouter")
                if provider_str == "openrouter":
                    api_key = llm_cfg.get("openrouter_api_key", "")
                    if not api_key:
                        with _preview_lock:
                            _preview_tasks[task_id] = {"status": "error", "result": {"error": "No OpenRouter API key"}}
                        return
                    llm = LLMClient(provider=LLMProvider.OPENROUTER, api_key=api_key,
                                     model=llm_cfg.get("model", "qwen/qwen3-235b-a22b-2507"))
                else:
                    llm = LLMClient(provider=LLMProvider.OLLAMA,
                                     base_url=llm_cfg.get("ollama_base_url", "http://localhost:11434"),
                                     model=llm_cfg.get("ollama_model", "qwen3:4b"))

                system = f"You are a helpful outreach assistant. Write a short message based on these instructions: {prompt}"
                lead_info = f"Lead: {lead.get('name', 'Unknown')} - {lead.get('business_type', '')} in {lead.get('location', '')}"
                msg = llm.generate_sync(prompt=lead_info, system=system)
                import re as _re
                msg = _re.sub(r'<think>.*?</think>', '', msg, flags=_re.DOTALL).strip()
                msg = msg.strip('"').strip("'")

                with _preview_lock:
                    _preview_tasks[task_id] = {
                        "status": "done",
                        "result": {"message": msg, "chars": len(msg), "mode": "agent", "lead_name": lead.get("name", "")},
                    }
            except Exception as e:
                logger.error("Preview generation failed: %s", e)
                with _preview_lock:
                    _preview_tasks[task_id] = {"status": "error", "result": {"error": f"LLM generation failed: {e}"}}

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
        """Dry run -- generate a message for one lead without sending."""
        body = request.get_json(force=True, silent=True) or {}
        prompt = body.get("user_prompt", "").strip()

        all_leads = store.get_leads(limit=1)
        if not all_leads:
            return jsonify({"error": "No leads in database. Import some first."}), 400

        lead = all_leads[0]

        if not prompt:
            return jsonify({"error": "No task prompt provided"}), 400

        import uuid
        task_id = str(uuid.uuid4())[:8]
        with _preview_lock:
            _preview_tasks[task_id] = {"status": "generating", "result": None}

        def _generate_dry_run():
            try:
                from openreach.llm.client import LLMClient, LLMProvider
                current = load_config()
                llm_cfg = current.get("llm", {})
                provider_str = llm_cfg.get("provider", "openrouter")
                if provider_str == "openrouter":
                    api_key = llm_cfg.get("openrouter_api_key", "")
                    if not api_key:
                        with _preview_lock:
                            _preview_tasks[task_id] = {"status": "error", "result": {"error": "No OpenRouter API key"}}
                        return
                    llm = LLMClient(provider=LLMProvider.OPENROUTER, api_key=api_key,
                                     model=llm_cfg.get("model", "qwen/qwen3-235b-a22b-2507"))
                else:
                    llm = LLMClient(provider=LLMProvider.OLLAMA,
                                     base_url=llm_cfg.get("ollama_base_url", "http://localhost:11434"),
                                     model=llm_cfg.get("ollama_model", "qwen3:4b"))

                system = f"You are a helpful outreach assistant. Write a short message for this task: {prompt}"
                lead_info = f"Lead: {lead.get('name', 'Unknown')} - {lead.get('business_type', '')} in {lead.get('location', '')}"
                msg = llm.generate_sync(prompt=lead_info, system=system)
                import re as _re
                msg = _re.sub(r'<think>.*?</think>', '', msg, flags=_re.DOTALL).strip()
                msg = msg.strip('"').strip("'")
                store.log_activity(
                    campaign_id=None, session_id=None, level="info",
                    message=f"[DRY RUN] Preview message for {lead.get('name', 'Unknown')}: {msg[:100]}..."
                )
                with _preview_lock:
                    _preview_tasks[task_id] = {
                        "status": "done",
                        "result": {
                            "message": msg, "chars": len(msg), "mode": "agent",
                            "lead_name": lead.get("name", ""), "dry_run": True,
                        },
                    }
            except Exception as e:
                logger.error("Dry run generation failed: %s", e)
                with _preview_lock:
                    _preview_tasks[task_id] = {"status": "error", "result": {"error": f"LLM generation failed: {e}"}}

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
        llm = current.get("llm", {})
        api_key = cormass.get("api_key", "")
        masked = ""
        if api_key:
            if len(api_key) > 16:
                masked = api_key[:8] + "*" * (len(api_key) - 12) + api_key[-4:]
            else:
                masked = "*" * len(api_key)
        # OpenRouter key masking
        or_key = llm.get("openrouter_api_key", "")
        or_masked = ""
        if or_key:
            if len(or_key) > 16:
                or_masked = or_key[:8] + "*" * (len(or_key) - 12) + or_key[-4:]
            else:
                or_masked = "*" * len(or_key)
        verbose_raw = current.get("debug", {}).get("verbose", "False")
        verbose = str(verbose_raw).lower() in ("true", "1", "yes")
        return jsonify({
            "has_api_key": bool(api_key),
            "api_key_masked": masked,
            "base_url": cormass.get("base_url", "https://cormass.com/wp-json/leads/v1"),
            "has_openrouter_key": bool(or_key),
            "openrouter_key_masked": or_masked,
            "llm_model": llm.get("model", "qwen/qwen3-235b-a22b-2507"),
            "llm_provider": llm.get("provider", "openrouter"),
            "verbose": verbose,
        })

    @app.route("/api/settings", methods=["POST"])
    def api_settings_post():  # type: ignore[no-untyped-def]
        body = request.get_json(force=True, silent=True) or {}

        api_key = body.get("api_key")
        base_url = body.get("base_url")
        openrouter_api_key = body.get("openrouter_api_key")
        llm_model = body.get("llm_model")
        llm_provider = body.get("llm_provider")

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

        if openrouter_api_key is not None:
            openrouter_api_key = str(openrouter_api_key).strip()
            if not openrouter_api_key.startswith("sk-"):
                return jsonify({"ok": False, "error": "OpenRouter key must start with 'sk-'"})
            save_config_value("llm.openrouter_api_key", openrouter_api_key)

        if llm_model is not None:
            save_config_value("llm.model", str(llm_model).strip())

        if llm_provider is not None:
            if llm_provider not in ("openrouter", "ollama"):
                return jsonify({"ok": False, "error": "Provider must be 'openrouter' or 'ollama'"})
            save_config_value("llm.provider", llm_provider)

        # Return updated masked keys
        current = load_config()
        key = current.get("cormass", {}).get("api_key", "")
        masked = ""
        if key and len(key) > 16:
            masked = key[:8] + "*" * (len(key) - 12) + key[-4:]

        or_key = current.get("llm", {}).get("openrouter_api_key", "")
        or_masked = ""
        if or_key and len(or_key) > 16:
            or_masked = or_key[:8] + "*" * (len(or_key) - 12) + or_key[-4:]

        return jsonify({"ok": True, "api_key_masked": masked, "openrouter_key_masked": or_masked})

    # ---- LLM Health Check ----

    @app.route("/api/llm/health")
    def api_llm_health():  # type: ignore[no-untyped-def]
        current = load_config()
        llm_cfg = current.get("llm", {})
        provider = llm_cfg.get("provider", "openrouter")

        from openreach.llm.client import LLMClient, LLMProvider
        try:
            if provider == "openrouter":
                api_key = llm_cfg.get("openrouter_api_key", "")
                if not api_key:
                    return jsonify({"ok": False, "error": "No OpenRouter API key configured"})
                llm = LLMClient(
                    provider=LLMProvider.OPENROUTER,
                    api_key=api_key,
                    model=llm_cfg.get("model", "qwen/qwen3-235b-a22b-2507"),
                )
            else:
                llm = LLMClient(
                    provider=LLMProvider.OLLAMA,
                    base_url=llm_cfg.get("ollama_base_url", "http://localhost:11434"),
                    model=llm_cfg.get("ollama_model", "qwen3:4b"),
                )
            # check_health() is async -- must run in event loop from sync Flask context
            healthy = asyncio.run(llm.check_health())
            if healthy:
                return jsonify({"ok": True, "provider": provider})
            else:
                return jsonify({"ok": False, "error": f"{provider} health check failed"})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)})

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
