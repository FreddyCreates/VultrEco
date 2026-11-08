#!/usr/bin/env bash
set -euo pipefail
# Run as the dot user INSIDE its VM. This is optional and requires public network access.
: "${DOT_PLAYWRIGHT_VERSION:?Set DOT_PLAYWRIGHT_VERSION to an exact tested Playwright release}"
python3 -m venv "$HOME/.dot/browser-venv"
"$HOME/.dot/browser-venv/bin/python" -m pip install "playwright==$DOT_PLAYWRIGHT_VERSION"
"$HOME/.dot/browser-venv/bin/python" -m playwright install chromium
printf '%s\n' 'Browser installed. Guest browser calls use ~/.dot/browser-venv/bin/python.'
