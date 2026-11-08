import argparse
import json
import os
import subprocess
from .core import Runtime, load_config
from .vm import Libvirt
from .server import serve


def main():
    parser = argparse.ArgumentParser(description='ITSNotAI Dot — persistent VM agents')
    parser.add_argument('action', choices=['doctor', 'serve', 'login', 'shell', 'verify-receipts'])
    parser.add_argument('--config', default='config.json')
    parser.add_argument('--agent')
    parser.add_argument('--provider', choices=['chatgpt', 'gemini'])
    parser.add_argument('--port', type=int, default=8787)
    args = parser.parse_args()
    os.umask(0o077)
    config = load_config(args.config)
    if args.action == 'doctor':
        state = Libvirt(config).doctor()
        print(json.dumps(state, indent=2))
        return 0 if state['ready'] else 1
    lock_handle = None
    if args.action == 'serve':
        from pathlib import Path
        import fcntl
        Path(config['state_dir']).mkdir(parents=True, exist_ok=True, mode=0o700)
        lock_handle = open(Path(config['state_dir']) / 'runtime.lock', 'a')
        try:
            fcntl.flock(lock_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit('Another Dot control plane is already running')
    runtime = Runtime(config, recover=args.action == 'serve')
    if args.action == 'serve':
        serve(runtime, args.port)
        return 0
    try:
        if args.action == 'verify-receipts':
            import hashlib
            previous = '0' * 64
            for receipt in runtime.receipts():
                data = json.dumps(receipt['data'], sort_keys=True, separators=(',', ':'))
                digest = hashlib.sha256((previous + str(receipt['at']) + data).encode()).hexdigest()
                if receipt['prev'] != previous or receipt['hash'] != digest:
                    raise RuntimeError('Receipt chain mismatch at ' + str(receipt['seq']))
                previous = digest
            print('Receipt chain verified:', previous)
            return 0
        agent = runtime.agent(args.agent or '')
        provider = args.provider or agent['provider']
        command = ('codex', 'login', '--device-auth') if provider == 'chatgpt' else ('env', 'NO_BROWSER=true', 'gemini')
        if args.action == 'shell':
            command = ('bash', '-l')
        # Interactive sign-in stays in the VM terminal, never in HTTP logs.
        return subprocess.call(runtime.backend.ssh_command(agent, *command, tty=True))
    finally:
        runtime.close()


if __name__ == '__main__':
    raise SystemExit(main())
