from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import base64
import hmac
import json
from pathlib import Path
import threading
from urllib.parse import urlparse

STATIC = Path(__file__).with_name('static')


def make_server(runtime, port=8787):
    class Handler(BaseHTTPRequestHandler):
        server_version = 'Dot/0.4'

        def log_message(self, *_):
            pass  # No request bodies or credentials in access logs.

        def send(self, code, data, mime='application/json'):
            raw = json.dumps(data).encode() if mime == 'application/json' else data
            self.send_response(code)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(raw)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; img-src 'self' blob:; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            self.end_headers()
            self.wfile.write(raw)

        def allowed(self):
            allowed = {f'localhost:{self.server.server_port}', f'127.0.0.1:{self.server.server_port}'}
            if self.headers.get('Host', '') not in allowed:
                self.send(403, {'error': 'Unexpected host'})
                return False
            origin = self.headers.get('Origin')
            if origin and origin not in {'http://' + host for host in allowed}:
                self.send(403, {'error': 'Unexpected origin'})
                return False
            return True

        def authorized(self):
            auth = self.headers.get('Authorization', '')
            if not hmac.compare_digest(auth, 'Bearer ' + runtime.token):
                self.send(401, {'error': 'Enter your owner access token'})
                return False
            return True

        def do_GET(self):
            if not self.allowed():
                return
            path = urlparse(self.path).path
            assets = {'/': ('index.html', 'text/html; charset=utf-8'), '/app.js': ('app.js', 'text/javascript'), '/style.css': ('style.css', 'text/css')}
            if path in assets:
                file, mime = assets[path]
                return self.send(200, (STATIC / file).read_bytes(), mime)
            if not self.authorized():
                return
            try:
                if path == '/api/state':
                    return self.send(200, {'agents': runtime.agents(), 'jobs': runtime.jobs(), 'missions': runtime.graphs.list()})
                if path == '/api/host':
                    return self.send(200, runtime.backend.doctor())
                if path == '/api/receipts':
                    return self.send(200, runtime.receipts())
                self.send(404, {'error': 'Not found'})
            except Exception:
                self.send(500, {'error': 'Could not read runtime state'})

        def do_POST(self):
            if not self.allowed() or not self.authorized():
                return
            try:
                if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                    raise ValueError('Use application/json')
                length = int(self.headers.get('Content-Length', '0'))
                if not 1 <= length <= 140000:
                    raise ValueError('Invalid body size')
                self.connection.settimeout(10)
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict):
                    raise ValueError('Expected JSON object')
                parts = urlparse(self.path).path.strip('/').split('/')
                if parts == ['api', 'missions']:
                    return self.send(202, runtime.graphs.create(body))
                if len(parts) == 4 and parts[:2] == ['api', 'missions'] and parts[3] == 'cancel':
                    return self.send(202, runtime.graphs.cancel(parts[2]))
                if parts == ['api', 'agents']:
                    return self.send(202, runtime.create(body))
                if len(parts) == 4 and parts[:2] == ['api', 'agents']:
                    if parts[3] == 'workspace':
                        return self.send(200, runtime.import_workspace(parts[2], body))
                    if parts[3] == 'improvement':
                        if body.get('action', 'list') not in ('list', 'create', 'edit', 'show', 'evaluate', 'promote', 'rollback', 'revoke'):
                            raise ValueError('Unknown improvement action')
                        agent = runtime.agent(parts[2])
                        result = runtime.backend.guest(agent, 'improvement', data=body)
                        if body.get('action', 'list') not in ('list', 'show'):
                            runtime.event('improvement_' + body['action'], agent_id=agent['id'], capsule_id=result.get('id'), status=result.get('status'))
                        return self.send(200, result)
                    if parts[3] == 'computer':
                        from .computer import validate_actions
                        validate_actions(body)
                        agent = runtime.agent(parts[2])
                        return self.send(200, runtime.backend.guest(agent, 'computer', data=body))
                    if parts[3] == 'mission':
                        return self.send(200, runtime.mission(parts[2], body))
                    if parts[3] == 'checkpoints':
                        return self.send(200, runtime.workspace_action(parts[2], body.get('action', 'list'), body.get('checkpoint_id')))
                    if parts[3] == 'reconcile':
                        return self.send(200, runtime.reconcile(parts[2]))
                    if parts[3] == 'export':
                        agent = runtime.agent(parts[2])
                        data = runtime.backend.guest(agent, 'export')
                        return self.send(200, base64.b64decode(data['zip_base64'], validate=True), 'application/zip')
                    if parts[3] == 'capsule':
                        agent = runtime.agent(parts[2])
                        receipt = runtime.kernel.accept_sealed(body, agent['id'])
                        transport = runtime.backend.guest(agent, 'capsule', data=body)
                        runtime.event('capsule_import', agent_id=agent['id'], content_hash=receipt['content_hash'])
                        return self.send(200, {'receipt': receipt, 'transport': transport})
                    if parts[3] == 'tasks':
                        return self.send(202, runtime.submit(parts[2], body))
                    if parts[3] in ('start', 'stop'):
                        return self.send(202, runtime.power(parts[2], parts[3]))
                if len(parts) == 4 and parts[:2] == ['api', 'jobs'] and parts[3] == 'cancel':
                    return self.send(202, runtime.cancel(parts[2]))
                self.send(404, {'error': 'Not found'})
            except (ValueError, KeyError) as exc:
                self.send(400, {'error': str(exc)})
            except Exception:
                self.send(500, {'error': 'Operation failed. Inspect host journal and VM status.'})
    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    server.daemon_threads = True
    return server


def serve(runtime, port):
    server = make_server(runtime, port)
    watcher = threading.Thread(target=runtime.watch, daemon=True)
    watcher.start()
    print(f'Dot dashboard: http://127.0.0.1:{server.server_port}', flush=True)
    print(f'Owner token is in {runtime.root / "owner.token"}; it is never printed by the server.', flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        runtime.stop_event.set()
        watcher.join(timeout=1)
        runtime.close()
