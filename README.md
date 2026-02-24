# OpenReach

**Open-source social media outreach agent powered by local LLMs.**

OpenReach automates cold DM outreach on Instagram using a local AI agent running entirely on your machine. No cloud AI costs, no data leaves your computer, full control over your outreach campaigns.

---

## Features

- **Local LLM** -- Runs Qwen 3 4B (or any Ollama model) locally. No API keys, no cloud costs, no data exfiltration.
- **Browser Automation** -- Real browser sessions via Playwright. No unofficial APIs, no scraping hacks.
- **Instagram DM** -- Personalized cold outreach at scale with AI-generated messages tailored to each prospect.
- **Smart Scheduling** -- Human-like delays and randomization to maintain natural interaction patterns.
- **Contact Tracking** -- Track outreach status (sent, delivered, replied, rejected) per lead per channel.
- **Standalone Mode** -- Works with CSV imports. No external service required.
- **Cormass Leads Integration** -- Optionally connect to Cormass Leads for access to 215M+ business profiles with contact data, review intelligence, and geographic targeting.

## Architecture

```
+------------------+      +-------------------+
|   Flask Web UI   | <--> |   Agent Engine    |
|   (localhost)    |      |   (Python)        |
+------------------+      +--------+----------+
                                   |
                    +--------------+--------------+
                    |                             |
            +-------+-------+           +---------+---------+
            |  Ollama LLM   |           |   Playwright      |
            |  (Qwen 3 4B)  |           |   (Chromium)      |
            +---------------+           +-------------------+
                    |
            +-------+-------+
            |  Data Layer   |
            |  SQLite local |
            |  + CSV import |
            |  + Cormass API|
            +---------------+
```

## Requirements

- Python 3.11+
- [Ollama](https://ollama.com/) with a supported model (default: `qwen3:4b`)
- 4GB+ RAM (8GB recommended)
- Modern GPU optional but recommended for faster inference

## Quick Start

```bash
# 1. Clone the repository
git clone https://github.com/Coolcorbinian/OpenReach.git
cd openreach

# 2. Install dependencies
pip install -r requirements.txt

# 3. Install Playwright browsers
playwright install chromium

# 4. Pull the default LLM model
ollama pull qwen3:4b

# 5. Run OpenReach
python -m openreach
```

Open `http://localhost:5000` in your browser.

## Standalone Mode (CSV)

OpenReach works completely standalone without any external services:

```bash
# Import leads from CSV
python -m openreach --import leads.csv

# CSV format: name, instagram_handle, business_type, notes
```

## Cormass Leads Integration (Optional)

For access to 215M+ business profiles with AI-powered review intelligence:

1. Create a free account at [cormass.com/leads](https://cormass.com/leads/)
2. Generate an API key in Settings > API Keys
3. Configure OpenReach:

```bash
# Set your API key
python -m openreach config set api_key clk_your_api_key_here

# Pull leads from a canvas
python -m openreach pull --canvas 42
```

## Configuration

```yaml
# config.yaml
llm:
  model: qwen3:4b          # Ollama model name
  temperature: 0.7          # Response creativity (0.0-1.0)
  base_url: http://localhost:11434  # Ollama server URL

browser:
  headless: false           # Show browser window
  slow_mo: 50               # Milliseconds between actions

outreach:
  delay_min: 45             # Min seconds between messages
  delay_max: 180            # Max seconds between messages
  daily_limit: 50           # Max messages per day
  session_limit: 15         # Max messages per session

instagram:
  username: ""              # Your Instagram username
  password: ""              # Your Instagram password (stored locally)
```

## Project Structure

```
openreach/
  __init__.py
  __main__.py              # Entry point
  cli.py                   # CLI interface
  config.py                # Configuration management
  agent/
    __init__.py
    engine.py              # Core agent loop
    planner.py             # Task planning with LLM
    executor.py            # Action execution
  browser/
    __init__.py
    session.py             # Playwright session management
    instagram.py           # Instagram-specific actions
  llm/
    __init__.py
    client.py              # Ollama client wrapper
    prompts.py             # System/user prompt templates
  data/
    __init__.py
    models.py              # SQLAlchemy models
    store.py               # Local SQLite operations
    csv_import.py          # CSV import/export
    cormass_api.py         # Cormass Leads API client
  ui/
    __init__.py
    app.py                 # Flask application
    templates/             # Jinja2 templates
    static/                # CSS/JS assets
```

## Legal

**READ [DISCLAIMER.md](DISCLAIMER.md) BEFORE USING THIS SOFTWARE.**

OpenReach is a tool. You are responsible for how you use it. Automated outreach may violate platform Terms of Service and/or applicable laws in your jurisdiction. The authors accept no liability.

## License

[MIT License](LICENSE) -- Free to use, modify, and distribute.

## Contributing

Contributions welcome. Please read [CONTRIBUTING.md](CONTRIBUTING.md) before submitting PRs.

---

Built by [Cormass Group](https://cormass.com)
