#!/usr/bin/env python3
"""Render and interact with the actual dashboard inside a credential-free VM."""
import hashlib
import json
import os
from pathlib import Path
import sys
import threading
sys.path[:0]=['/app','/browser-python']
from dot.core import Runtime
from dot.server import make_server
from dot.computer import operate
from playwright.sync_api import sync_playwright


def run():
    assert os.getuid()==1000
    root=Path('/data')
    config={'state_dir':'/data/controller-state','vm_root':'/data/no-host-vms','image':'/data/no-image.qcow2',
        'image_sha256':'0'*64,'codex_version':'1.0.0','gemini_version':'1.0.0',
        'network':'default','gateway':'192.168.122.1','subnet':'192.168.122.0/24',
        'max_agents':8,'max_vcpus':16,'max_memory_mb':32768,'max_disk_gb':400}
    runtime=Runtime(config)
    server=make_server(runtime,8787)
    thread=threading.Thread(target=server.serve_forever);thread.start()
    os.environ['DOT_BROWSER_EXECUTABLE']='/chrome/chrome'
    receipt={'schema':'dot.actual-browser-proof.v1','kernel_release':os.uname().release,
        'uid':os.getuid(),'vm_boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
        'execution':'actual Chromium and actual controller inside QEMU Linux guest',
        'provider_inference_verified':False,'hardware_kvm_verified':False,
        'source_sha256':{str(p.relative_to('/app')):hashlib.sha256(p.read_bytes()).hexdigest() for p in Path('/app/dot').rglob('*') if p.is_file()}}
    try:
        desktop=operate('/data/browser-profile',{'actions':[
            {'action':'goto','url':'http://127.0.0.1:8787'},
            {'action':'fill','selector':'#token','text':runtime.token},
            {'action':'click','selector':'#connect-form button'},
            {'action':'wait','selector':'#workspace','timeout_ms':8000},
            {'action':'read'},{'action':'screenshot'}]})
        assert 'Independent minds.' in desktop['actions'][-1]['text']
        import base64
        (root/'desktop.png').write_bytes(base64.b64decode(desktop['screenshot_base64']))
        receipt['desktop_authenticated']=True
        with sync_playwright() as p:
            browser=p.chromium.launch(executable_path='/chrome/chrome',headless=True)
            receipt['browser_version']=browser.version
            page=browser.new_page(viewport={'width':390,'height':844})
            errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
            page.goto('http://127.0.0.1:8787',wait_until='domcontentloaded')
            page.locator('#token').fill(runtime.token);page.locator('#connect-form button').click()
            page.locator('#workspace').wait_for(state='visible')
            assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth'), 'Mobile page overflows'
            page.locator('[data-view="missions"]').click()
            page.get_by_text('One objective, separate computers.').wait_for()
            page.screenshot(path='/data/mobile.png')
            page.locator('[data-view="host"]').click()
            page.get_by_text('The host needs setup.').wait_for()
            receipt['host_unavailable_truthful']=True
            page.locator('[data-view="agents"]').click()
            page.locator('#new-agent').click()
            page.locator('#create-form [name="name"]').fill('Host unavailable test')
            page.locator('#create-form .primary').click()
            page.locator('#notice').wait_for(state='visible')
            assert not runtime.agents(), 'Unavailable host created an agent'
            assert not errors, errors
            receipt.update(mobile_authenticated=True,mobile_no_horizontal_overflow=True,
                unavailable_host_creates_no_agent=True,javascript_errors=errors)
            browser.close()
        receipt['screenshots']={name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in ('desktop.png','mobile.png')}
        receipt['status']='desktop_mobile_and_browser_controls_verified'
        (root/'browser-receipt.json').write_text(json.dumps(receipt,indent=2))
        print('DOT_BROWSER_PROOF '+json.dumps(receipt),flush=True)
    finally:
        server.shutdown();server.server_close();thread.join();runtime.close()


if __name__=='__main__':run()
