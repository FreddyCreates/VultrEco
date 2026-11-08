"""Optional real Chromium browser inside an agent VM. Missing dependencies are errors, never images of fake results."""
import base64
import ipaddress
import json
import os
from pathlib import Path
import time
from urllib.parse import urlsplit


def validate_actions(data):
    if not isinstance(data, dict) or not isinstance(data.get('actions'), list) or not 1 <= len(data['actions']) <= 12:
        raise ValueError('Computer request requires 1–12 actions')
    for step in data['actions']:
        if not isinstance(step, dict) or step.get('action') not in ('goto', 'click', 'fill', 'wait', 'read', 'screenshot'):
            raise ValueError('Invalid computer action')
        if step['action'] == 'goto':
            url = step.get('url')
            if not isinstance(url, str) or len(url) > 2000:
                raise ValueError('Invalid browser URL')
            parts = urlsplit(url)
            if parts.scheme not in ('https', 'http') or not parts.hostname or parts.username or parts.password:
                raise ValueError('Browser supports HTTP(S) URLs without credentials only')
            try:
                address = ipaddress.ip_address(parts.hostname)
            except ValueError:
                address = None
            if address and not (address.is_global or address == ipaddress.ip_address('127.0.0.1')):
                raise ValueError('Browser refuses private-network IPs')
        if step['action'] in ('click', 'fill', 'wait'):
            if not isinstance(step.get('selector'), str) or not 1 <= len(step['selector']) <= 500:
                raise ValueError('Browser selector required')
        if step['action'] == 'wait' and (type(step.get('timeout_ms', 3000)) is not int or not 1 <= step.get('timeout_ms', 3000) <= 8000):
            raise ValueError('Wait timeout must be 1–8000 milliseconds')
        if step['action'] == 'fill' and (not isinstance(step.get('text'), str) or len(step['text']) > 4000):
            raise ValueError('Browser fill text too long')
    return data


def operate(root, data):
    validate_actions(data)
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise RuntimeError('Guest browser is not installed. Run scripts/install_guest_browser.sh inside this VM.')
    profile = Path(root) / 'browser'
    profile.mkdir(parents=True, exist_ok=True, mode=0o700)
    results, screenshot = [], None
    started = time.time()
    launch = {}
    executable = os.environ.get('DOT_BROWSER_EXECUTABLE')
    if executable:
        path = Path(executable)
        if not path.is_absolute() or not path.is_file():
            raise ValueError('DOT_BROWSER_EXECUTABLE must name an existing absolute browser executable')
        launch['executable_path'] = str(path)
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(str(profile), headless=True,
            viewport={'width': 1440, 'height': 900}, accept_downloads=False, **launch)
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.set_default_timeout(3000)
            for step in data['actions']:
                if time.time() - started > 30:
                    raise TimeoutError('Computer operation deadline exceeded')
                action = step['action']
                if action == 'goto':
                    response = page.goto(step['url'], wait_until='domcontentloaded', timeout=8000)
                    results.append({'action': action, 'url': page.url, 'status': response.status if response else None})
                elif action == 'click':
                    page.locator(step['selector']).click()
                    results.append({'action': action})
                elif action == 'fill':
                    page.locator(step['selector']).fill(step['text'])
                    results.append({'action': action})
                elif action == 'wait':
                    page.locator(step['selector']).wait_for(state='visible', timeout=step.get('timeout_ms', 3000))
                    results.append({'action': action})
                elif action == 'read':
                    results.append({'action': action, 'url': page.url, 'title': page.title(), 'text': page.locator('body').inner_text()[:16000]})
                elif action == 'screenshot':
                    image = page.screenshot(full_page=False)
                    if len(image) > 4 * 1024 * 1024:
                        raise ValueError('Browser screenshot exceeds output limit')
                    screenshot = base64.b64encode(image).decode()
            return {'actions': results, 'screenshot_base64': screenshot}
        finally:
            context.close()


if __name__ == '__main__':
    import sys
    print(json.dumps(operate(Path.home() / '.dot', json.load(sys.stdin))))
