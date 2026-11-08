"""One-shot, read-only Playwright task. Runs only in a disposable browser container.

Never run this on the CAPSULA control-plane host. A network egress firewall is
required to enforce the origin allowlist beyond application-level request routing.
"""
import base64
import ipaddress
import json
import socket
import sys
from urllib.parse import urlparse


def safe_target(url, allowed):
    u=urlparse(url)
    if u.scheme!='https' or not u.hostname or u.username or u.password or u.port not in (None,443):
        raise ValueError('HTTPS URL without credentials required')
    if u.hostname.lower() not in allowed:
        raise ValueError('Origin is outside the browser policy')
    for item in socket.getaddrinfo(u.hostname,443):
        if not ipaddress.ip_address(item[4][0]).is_global:
            raise ValueError('Non-public address blocked')
    return u.hostname.lower()


def execute(job):
    url=job['url'];allowed=set(job['allowed_hosts']);selector=job.get('selector','')
    safe_target(url,allowed)
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        browser=playwright.chromium.launch(headless=True,args=['--no-sandbox'])
        try:
            context=browser.new_context(viewport={'width':1000,'height':720},accept_downloads=False,
                                        service_workers='block',permissions=[],java_script_enabled=True)
            context.set_default_timeout(7000)
            page=context.new_page()
            def filter_request(route):
                u=urlparse(route.request.url)
                if u.scheme!='https' or u.hostname not in allowed:
                    route.abort()
                else:
                    route.continue_()
            page.route('**/*',filter_request)
            response=page.goto(url,wait_until='domcontentloaded',timeout=11000)
            safe_target(page.url,allowed)
            if selector:page.locator(selector).first.wait_for(timeout=3000)
            image=page.screenshot(type='jpeg',quality=48,full_page=False,timeout=8000)
            if len(image)>290_000:raise ValueError('Screenshot exceeded bounded output size')
            return {'status':'completed','title':page.title()[:200], 'final_url':page.url[:300],
                    'http_status':response.status if response else None,'selector_found':bool(selector),
                    'stdout':page.locator('body').inner_text(timeout=4000)[:8000], 'stderr':'','exit_code':0,
                    'screenshot_b64':base64.b64encode(image).decode('ascii'), 'image_mime':'image/jpeg',
                    'read_only':True}
        finally:
            browser.close()


def main():
    try:
        with open(sys.argv[1],encoding='utf-8') as handle:job=json.load(handle)
        data=execute(job)
    except Exception as exc:
        data={'status':'failed','reason':type(exc).__name__, 'stdout':'','stderr':'Browser task denied or failed','exit_code':1}
    print(json.dumps(data,sort_keys=True,separators=(',',':')))

if __name__=='__main__':main()
