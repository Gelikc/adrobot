"""Local development launcher: python run.py. Ctrl+C stops only its own processes."""
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser

ROOT = Path(__file__).resolve().parent


def run(args, cwd=ROOT):
    subprocess.run([str(x) for x in args], cwd=cwd, check=True)


def main():
    for port in (8000, 5173):
        with socket.socket() as sock:
            if sock.connect_ex(('127.0.0.1', port)) == 0:
                raise SystemExit(f'Port {port} is already in use. Stop the existing process first.')
    npm = shutil.which('npm.cmd' if os.name == 'nt' else 'npm')
    if not npm:
        raise SystemExit('Install Node.js 22+ first.')
    venv = ROOT / '.venv'
    python = venv / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    if not python.exists():
        run([sys.executable, '-m', 'venv', venv])
    check = subprocess.run([str(python), '-c', 'import fastapi, sqlalchemy, greenlet, alembic, asyncpg, pycountry'], capture_output=True)
    if check.returncode:
        run([python, '-m', 'pip', 'install', '-r', ROOT / 'backend/requirements.lock'])
    if not (ROOT / 'frontend/node_modules').exists():
        run([npm, 'ci'], ROOT / 'frontend')
    run([python, '-m', 'alembic', 'upgrade', 'head'], ROOT / 'backend')
    processes = []
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0
    try:
        processes.append(subprocess.Popen([str(python), '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8000'], cwd=ROOT / 'backend', creationflags=flags))
        processes.append(subprocess.Popen([npm, 'run', 'dev', '--', '--port', '5173', '--strictPort'], cwd=ROOT / 'frontend', creationflags=flags))
        for _ in range(90):
            if any(p.poll() is not None for p in processes):
                raise RuntimeError('A server exited. Check its output above.')
            try:
                urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=1).close()
                urllib.request.urlopen('http://127.0.0.1:5173', timeout=1).close()
                break
            except OSError:
                time.sleep(.5)
        else:
            raise RuntimeError('Startup timed out.')
        print('\nAdrobot: http://127.0.0.1:5173\nAPI docs: http://127.0.0.1:8000/docs\nCtrl+C to stop.\n')
        webbrowser.open('http://127.0.0.1:5173')
        while all(p.poll() is None for p in processes):
            time.sleep(1)
    except KeyboardInterrupt:
        print('\nStopping Adrobot...')
    finally:
        for process in reversed(processes):
            if process.poll() is None:
                if os.name == 'nt':
                    subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True)
                else:
                    process.terminate()
                process.wait(timeout=10)


if __name__ == '__main__':
    main()
