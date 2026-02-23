"""
OpenReach Launcher -- handles first-run setup, Ollama verification,
legal acceptance, and application startup with user-friendly error messages.

This script is called by 'Start OpenReach.bat' and should never need to be
run manually.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
CONFIG_DIR = Path.home() / ".openreach"
CONFIG_FILE = CONFIG_DIR / "config.yaml"
LEGAL_ACCEPTED_FILE = CONFIG_DIR / ".legal_accepted"
OLLAMA_URL = "http://localhost:11434"
DEFAULT_MODEL = "qwen3:4b"
FLASK_HOST = "127.0.0.1"
FLASK_PORT = 5000

# ---------------------------------------------------------------------------
# Pretty output helpers (no external deps -- this runs before rich is loaded)
# ---------------------------------------------------------------------------

def _banner() -> None:
    print()
    print("  ╔══════════════════════════════════════════════════════════╗")
    print("  ║                                                        ║")
    print("  ║     O P E N R E A C H                                  ║")
    print("  ║     Social Media Outreach Agent                        ║")
    print("  ║                                                        ║")
    print("  ╚══════════════════════════════════════════════════════════╝")
    print()


def _step(msg: str) -> None:
    print(f"  [*] {msg}")


def _ok(msg: str) -> None:
    print(f"  [OK] {msg}")


def _warn(msg: str) -> None:
    print(f"  [!!] {msg}")


def _error(msg: str) -> None:
    print(f"  [ERROR] {msg}")


def _info(msg: str) -> None:
    print(f"      {msg}")


def _fatal(msg: str, hint: str = "") -> None:
    """Print error and exit."""
    print()
    print("  ============================================================")
    _error(msg)
    if hint:
        print()
        _info(hint)
    print("  ============================================================")
    print()
    input("  Press Enter to close...")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Legal acceptance (first-run only)
# ---------------------------------------------------------------------------

LEGAL_TEXT = """
  ============================================================
  IMPORTANT -- PLEASE READ BEFORE CONTINUING
  ============================================================

  OpenReach is an automation tool. By using it you acknowledge:

  1. YOU are solely responsible for complying with all applicable
     laws (CAN-SPAM, GDPR, CASL, etc.) and platform Terms of
     Service (Instagram, LinkedIn, etc.).

  2. Automated outreach may result in account suspension or bans
     on social media platforms. The authors accept NO liability.

  3. This software is provided "AS IS" under the MIT License with
     NO WARRANTY of any kind.

  4. You will NOT use this tool for spam, harassment, or any
     form of illegal or unwanted communication.

  Full details: See DISCLAIMER.md in the OpenReach folder.
  ============================================================
"""


def _check_legal_acceptance() -> None:
    """Show legal notice on first run and require explicit acceptance."""
    if LEGAL_ACCEPTED_FILE.exists():
        return

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    print(LEGAL_TEXT)

    while True:
        response = input('  Type "I ACCEPT" to continue, or "QUIT" to exit: ').strip()
        if response.upper() == "I ACCEPT":
            LEGAL_ACCEPTED_FILE.write_text(
                f"accepted={time.strftime('%Y-%m-%dT%H:%M:%S')}\n",
                encoding="utf-8",
            )
            _ok("Legal terms accepted.")
            print()
            break
        elif response.upper() == "QUIT":
            print()
            print("  Exiting. You must accept the terms to use OpenReach.")
            sys.exit(0)
        else:
            print('  Please type exactly "I ACCEPT" or "QUIT".')


# ---------------------------------------------------------------------------
# Ollama detection and model management
# ---------------------------------------------------------------------------

def _check_ollama() -> bool:
    """Check if Ollama is installed."""
    return shutil.which("ollama") is not None


def _ollama_is_running() -> bool:
    """Check if the Ollama server is responding."""
    try:
        import httpx
        with httpx.Client(timeout=5.0) as client:
            r = client.get(f"{OLLAMA_URL}/api/tags")
            return r.status_code == 200
    except Exception:
        return False


def _start_ollama() -> bool:
    """Try to start Ollama in the background."""
    try:
        ollama_path = shutil.which("ollama")
        if not ollama_path:
            return False

        # On Windows, launch 'ollama serve' detached
        if sys.platform == "win32":
            subprocess.Popen(
                [ollama_path, "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
            )
        else:
            subprocess.Popen(
                [ollama_path, "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

        # Wait for it to come up
        for _ in range(15):
            time.sleep(1)
            if _ollama_is_running():
                return True
        return False

    except Exception:
        return False


def _model_available(model: str) -> bool:
    """Check if the required model is already pulled."""
    try:
        import httpx
        with httpx.Client(timeout=10.0) as client:
            r = client.get(f"{OLLAMA_URL}/api/tags")
            if r.status_code != 200:
                return False
            data = r.json()
            models = [m.get("name", "") for m in data.get("models", [])]
            return any(model in m for m in models)
    except Exception:
        return False


def _pull_model(model: str) -> bool:
    """Pull the model with progress output."""
    try:
        ollama_path = shutil.which("ollama")
        if not ollama_path:
            return False

        _step(f"Downloading AI model '{model}' (this may take several minutes)...")
        _info("The model is ~2-3 GB. Please be patient.")
        print()

        result = subprocess.run(
            [ollama_path, "pull", model],
            timeout=1800,  # 30 minute timeout
        )
        return result.returncode == 0

    except subprocess.TimeoutExpired:
        _warn("Model download timed out. Please try again with a stable connection.")
        return False
    except Exception as e:
        _warn(f"Model download failed: {e}")
        return False


def _setup_ollama() -> bool:
    """Full Ollama setup flow with user-friendly guidance."""

    # Step 1: Is Ollama installed?
    if not _check_ollama():
        print()
        print("  ============================================================")
        print("  Ollama is not installed.")
        print()
        print("  Ollama runs an AI model locally on your computer.")
        print("  It's free and takes about 2 minutes to install.")
        print()
        print("  1. Go to: https://ollama.com/download")
        print("  2. Download and install Ollama for Windows")
        print("  3. After installation, come back and run OpenReach again")
        print("  ============================================================")
        print()

        response = input("  Open the download page in your browser? (Y/n): ").strip().lower()
        if response != "n":
            webbrowser.open("https://ollama.com/download")

        print()
        print("  After installing Ollama, run 'Start OpenReach.bat' again.")
        input("  Press Enter to close...")
        sys.exit(0)

    _ok("Ollama is installed.")

    # Step 2: Is Ollama running?
    if not _ollama_is_running():
        _step("Starting Ollama...")
        if _start_ollama():
            _ok("Ollama started.")
        else:
            print()
            _warn("Could not start Ollama automatically.")
            _info("Please start Ollama manually:")
            _info("  - Look for the Ollama icon in your system tray, OR")
            _info("  - Open a terminal and run: ollama serve")
            print()
            input("  Press Enter after Ollama is running...")

            if not _ollama_is_running():
                _fatal(
                    "Ollama is still not responding.",
                    "Make sure Ollama is running and try again.",
                )
    else:
        _ok("Ollama is running.")

    # Step 3: Is the model downloaded?
    if not _model_available(DEFAULT_MODEL):
        _step(f"AI model '{DEFAULT_MODEL}' not found locally.")
        print()
        _info("OpenReach needs a small AI model to generate personalized messages.")
        _info(f"Model: {DEFAULT_MODEL} (~2.5 GB download, runs on most computers)")
        print()

        response = input("  Download the AI model now? (Y/n): ").strip().lower()
        if response == "n":
            print()
            _info(f"You can download it later by running: ollama pull {DEFAULT_MODEL}")
            _info("OpenReach will work but cannot generate messages without it.")
            print()
            return False

        print()
        if _pull_model(DEFAULT_MODEL):
            _ok(f"Model '{DEFAULT_MODEL}' is ready.")
        else:
            print()
            _warn("Model download failed. You can try manually later:")
            _info(f"  ollama pull {DEFAULT_MODEL}")
            _info("OpenReach will start but message generation won't work.")
            print()
            return False
    else:
        _ok(f"AI model '{DEFAULT_MODEL}' is ready.")

    return True


# ---------------------------------------------------------------------------
# Application startup
# ---------------------------------------------------------------------------

def _start_app() -> None:
    """Start the Flask web UI and open the browser."""
    # Add the project root to the path
    project_root = Path(__file__).resolve().parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    try:
        from openreach.config import load_config
        from openreach.ui.app import create_app
        from openreach import __version__
    except ImportError as e:
        _fatal(
            f"Failed to load OpenReach modules: {e}",
            "Try deleting the .venv folder and running Start OpenReach.bat again.",
        )

    config = load_config()
    app = create_app(config)

    host = config.get("ui", {}).get("host", FLASK_HOST)
    port = config.get("ui", {}).get("port", FLASK_PORT)
    url = f"http://{host}:{port}"

    print()
    print("  ============================================================")
    print(f"  OpenReach v{__version__} is running!")
    print()
    print(f"  Open in your browser:  {url}")
    print()
    print("  Press Ctrl+C to stop the server.")
    print("  ============================================================")
    print()

    # Open browser after a short delay
    import threading
    def _open_browser() -> None:
        time.sleep(1.5)
        webbrowser.open(url)
    threading.Thread(target=_open_browser, daemon=True).start()

    try:
        # Suppress Flask's default banner for cleaner output
        import logging
        log = logging.getLogger("werkzeug")
        log.setLevel(logging.WARNING)

        app.run(host=host, port=port, debug=False, use_reloader=False)

    except KeyboardInterrupt:
        print()
        _ok("OpenReach stopped.")
    except OSError as e:
        if "address already in use" in str(e).lower() or "10048" in str(e):
            _fatal(
                f"Port {port} is already in use.",
                f"Another program (or another OpenReach instance) is using port {port}.\n"
                f"      Close it first, or change the port in:\n"
                f"      {CONFIG_FILE}",
            )
        else:
            _fatal(f"Server error: {e}")
    except Exception as e:
        _fatal(f"Unexpected error: {e}")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main() -> None:
    try:
        _banner()

        # Step 1: Legal acceptance on first run
        _check_legal_acceptance()

        # Step 2: Ollama setup
        _setup_ollama()

        print()

        # Step 3: Launch the app
        _start_app()

    except KeyboardInterrupt:
        print()
        _ok("Cancelled by user.")
        sys.exit(0)
    except SystemExit:
        raise
    except Exception as e:
        _fatal(
            f"An unexpected error occurred: {e}",
            "Please report this issue at:\n"
            "      https://github.com/cormass/openreach/issues",
        )


if __name__ == "__main__":
    main()
