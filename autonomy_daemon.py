"""CAPSULA opt-in autonomy runner. Run as a separate process with operator key.

All actions execute through the authenticated control plane. This worker deliberately
has no Docker socket, filesystem access to model secrets, or arbitrary shell tools.
"""
import os
import sys
import time
import httpx


def main():
    url=os.getenv('CAPSULA_CONTROL_URL','http://127.0.0.1:8080').rstrip('/')
    token=os.getenv('CAPSULA_API_KEY','')
    private=(os.getenv('CAPSULA_CONTROL_ALLOW_INTERNAL_HTTP')=='1' and url.startswith('http://'+os.getenv('CAPSULA_CONTROL_HOST','__none__')+':'))
    if not token or not (url.startswith('https://') or url.startswith('http://127.0.0.1:') or url.startswith('http://localhost:') or private):
        raise SystemExit('A trusted CAPSULA_CONTROL_URL and CAPSULA_API_KEY are required')
    delay=max(2,min(120,int(os.getenv('CAPSULA_AUTONOMY_POLL_SECONDS','15'))))
    with httpx.Client(timeout=50,follow_redirects=False,trust_env=False) as client:
        while True:
            try:
                response=client.post(url+'/api/autonomy/scheduler/tick',headers={'Authorization':'Bearer '+token})
                response.raise_for_status()
                print('autonomy.tick',response.json().get('processed',0),flush=True)
            except httpx.HTTPError as exc:
                print('autonomy.poll_failed',type(exc).__name__,file=sys.stderr,flush=True)
            time.sleep(delay)

if __name__=='__main__':main()
