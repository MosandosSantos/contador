"""Operação local isolada do App Contábil.

Este arquivo nunca administra o serviço PostgreSQL do Windows: ele usa somente
o cluster guardado em .runtime/pgdata.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / ".runtime"
DATA = RUNTIME / "pgdata"
STATE_FILE = RUNTIME / "estado.json"
SECRETS_FILE = RUNTIME / "segredos.json"
DB_NAME = "app_contabil"
DB_USER = "app_contabil"
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def secrets_data() -> dict:
    existing = read_json(SECRETS_FILE)
    if existing.get("database_password") and existing.get("secret_key"):
        return existing
    data = {
        "database_password": secrets.token_urlsafe(32),
        "secret_key": secrets.token_urlsafe(48),
    }
    write_json(SECRETS_FILE, data)
    try:
        os.chmod(SECRETS_FILE, 0o600)
    except OSError:
        pass
    return data


def postgres_bin() -> Path:
    configured = os.environ.get("APP_POSTGRES_BIN")
    candidates = [Path(configured)] if configured else []
    program_files = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
    postgres_root = program_files / "PostgreSQL"
    if postgres_root.exists():
        candidates.extend(sorted(postgres_root.glob("*/bin"), reverse=True))
    for directory in candidates:
        if (directory / "pg_ctl.exe").exists() and (directory / "initdb.exe").exists():
            return directory
    raise RuntimeError("PostgreSQL não foi encontrado. Defina APP_POSTGRES_BIN para a pasta bin do PostgreSQL.")


def executable(name: str) -> str:
    path = postgres_bin() / name
    if not path.exists():
        raise RuntimeError("A instalação PostgreSQL encontrada está incompleta.")
    return str(path)


def run(args: list[str], *, env: dict | None = None, quiet: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        args, cwd=ROOT, env=env, text=True,
        stdout=subprocess.DEVNULL if quiet else None,
        stderr=subprocess.DEVNULL if quiet else None,
        creationflags=CREATE_NO_WINDOW, check=False,
    )


def port_is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return sock.connect_ex(("127.0.0.1", port)) != 0


def choose_port(previous: int | None) -> int:
    if previous and port_is_free(previous):
        return previous
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def pg_ready(port: int) -> bool:
    return run([executable("pg_isready.exe"), "-h", "127.0.0.1", "-p", str(port)]).returncode == 0


def pg_running() -> bool:
    return DATA.exists() and run([executable("pg_ctl.exe"), "status", "-D", str(DATA)]).returncode == 0


def query_scalar(port: int, credentials: dict, sql: str) -> str:
    env = os.environ.copy()
    env["PGPASSWORD"] = credentials["database_password"]
    result = subprocess.run(
        [executable("psql.exe"), "-h", "127.0.0.1", "-p", str(port), "-U", DB_USER,
         "-d", "postgres", "-tAc", sql],
        env=env, text=True, capture_output=True, creationflags=CREATE_NO_WINDOW,
    )
    if result.returncode:
        raise RuntimeError("Não foi possível consultar o banco local.")
    return result.stdout.strip()


def initialise_database(state: dict, credentials: dict) -> int:
    RUNTIME.mkdir(exist_ok=True)
    if not DATA.exists():
        password_file = RUNTIME / "initdb-password.txt"
        password_file.write_text(credentials["database_password"], encoding="utf-8")
        try:
            completed = run([
                executable("initdb.exe"), "-D", str(DATA), "-U", DB_USER,
                "--auth=scram-sha-256", "--encoding=UTF8", f"--pwfile={password_file}",
            ])
            if completed.returncode:
                raise RuntimeError("Não foi possível criar o banco local isolado.")
        finally:
            password_file.unlink(missing_ok=True)

    port = int(state.get("postgres_port", 0) or 0)
    if not pg_running():
        port = choose_port(port)
        config = DATA / "postgresql.conf"
        text = config.read_text(encoding="utf-8")
        marker = "# app-contabil-local"
        if marker not in text:
            config.write_text(text + f"\n{marker}\nlisten_addresses = '127.0.0.1'\nport = {port}\n", encoding="utf-8")
        else:
            import re
            text = re.sub(r"(?m)^port = \d+$", f"port = {port}", text)
            config.write_text(text, encoding="utf-8")
        if run([executable("pg_ctl.exe"), "start", "-D", str(DATA), "-l", str(RUNTIME / "postgres.log")]).returncode:
            raise RuntimeError("Não foi possível iniciar o banco local isolado.")
    else:
        # A porta gravada pode ser antiga apenas se o usuário alterou o cluster.
        port = int(state.get("postgres_port", 0) or 0)
        if not port:
            raise RuntimeError("O banco isolado está ativo, mas sua porta não foi registrada.")

    for _ in range(30):
        if pg_ready(port):
            break
        time.sleep(0.2)
    else:
        raise RuntimeError("O banco local não respondeu a tempo.")

    if query_scalar(port, credentials, "SHOW server_encoding") != "UTF8":
        raise RuntimeError("O cluster local existente não usa UTF-8; ele precisa ser migrado antes de reiniciar.")
    # createdb é idempotente aqui: somente é chamado se a consulta anterior não o encontrou.
    if query_scalar(port, credentials, f"SELECT 1 FROM pg_database WHERE datname='{DB_NAME}'") != "1" and run([
        executable("createdb.exe"), "-h", "127.0.0.1", "-p", str(port), "-U", DB_USER, DB_NAME
    ], env={**os.environ, "PGPASSWORD": credentials["database_password"]}).returncode:
        raise RuntimeError("Não foi possível criar o banco da aplicação.")
    return port


def process_started_at(pid: int) -> int | None:
    """Identifica o processo iniciado por nós sem CIM/WMI nem portas compartilhadas."""
    process = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not process:
        return None
    try:
        created = ctypes.c_ulonglong()
        ignored = ctypes.c_ulonglong()
        if not ctypes.windll.kernel32.GetProcessTimes(process, ctypes.byref(created), ctypes.byref(ignored), ctypes.byref(ignored), ctypes.byref(ignored)):
            return None
        return created.value
    finally:
        ctypes.windll.kernel32.CloseHandle(process)


def app_alive(state: dict) -> bool:
    pid = state.get("app_pid")
    created_at = state.get("app_started_at")
    if not isinstance(pid, int) or not isinstance(created_at, int):
        return False
    return process_started_at(pid) == created_at


def healthcheck(url: str) -> bool:
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/health", timeout=1.5) as response:
            return 200 <= response.status < 300
    except (urllib.error.URLError, TimeoutError):
        return False


def start_app(state: dict, credentials: dict, db_port: int) -> dict:
    app = ROOT / "app.py"
    venv_python = ROOT / ".venv" / "Scripts" / "python.exe"
    if not app.exists():
        raise RuntimeError("A aplicação ainda não existe; crie app.py antes de iniciar o ambiente local.")
    if not venv_python.exists():
        raise RuntimeError("O ambiente Python não existe. Rode preparar_ambiente.bat antes de iniciar.")
    if app_alive(state):
        if not healthcheck(str(state.get("url", ""))):
            raise RuntimeError("A aplicação já existe, mas não respondeu em /health.")
        return state
    prepare = ROOT / "scripts" / "preparar.py"
    env = os.environ.copy()
    nvidia = read_json(RUNTIME / "nvidia.json")
    for key in ("NVIDIA_API_KEY", "NVIDIA_MODEL"):
        if not env.get(key) and isinstance(nvidia.get(key), str):
            env[key] = nvidia[key]
    env.update({
        "DATABASE_URL": f"postgresql://{DB_USER}:{credentials['database_password']}@127.0.0.1:{db_port}/{DB_NAME}",
        "SECRET_KEY": credentials["secret_key"], "HOST": "127.0.0.1",
        "APP_ENV": "development",
    })
    if prepare.exists() and run([str(venv_python), str(prepare)], env=env).returncode:
        raise RuntimeError("A preparação inicial da aplicação falhou.")
    port = choose_port(int(state.get("app_port", 0) or 0))
    env["PORT"] = str(port)
    log = open(RUNTIME / "app.log", "ab")
    process = subprocess.Popen([str(venv_python), str(app)], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, creationflags=CREATE_NO_WINDOW)
    log.close()
    started_at = process_started_at(process.pid)
    if started_at is None:
        raise RuntimeError("Não foi possível registrar o processo da aplicação.")
    state.update({"app_pid": process.pid, "app_started_at": started_at, "app_port": port, "url": f"http://127.0.0.1:{port}"})
    # Mantém a identidade do processo no disco mesmo se o healthcheck falhar,
    # permitindo que --stop encerre somente esta instância posteriormente.
    write_json(STATE_FILE, state)
    for _ in range(20):
        if healthcheck(state["url"]):
            return state
        if not app_alive(state):
            break
        time.sleep(0.25)
    raise RuntimeError("A aplicação não respondeu em /health; consulte .runtime/app.log.")


def stop_app(state: dict) -> None:
    if app_alive(state):
        result = subprocess.run(["taskkill", "/F", "/PID", str(state["app_pid"]), "/T"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW)
        if result.returncode:
            raise RuntimeError("Não foi possível encerrar a aplicação local registrada.")
        for _ in range(40):
            if not app_alive(state):
                break
            time.sleep(0.25)
        else:
            raise RuntimeError("A aplicação local não encerrou a tempo.")
    for key in ("app_pid", "app_started_at", "url"):
        state.pop(key, None)


def migrate_utf8() -> None:
    """Migra o único banco do cluster local, mantendo o cluster anterior intacto."""
    state = read_json(STATE_FILE)
    credentials = secrets_data()
    old_port = int(state.get("postgres_port", 0) or 0)
    if not old_port or not pg_running() or not pg_ready(old_port):
        raise RuntimeError("O cluster local atual precisa estar ativo para a migração UTF-8.")
    if query_scalar(old_port, credentials, "SHOW server_encoding") == "UTF8":
        start()
        return
    legacy_data = RUNTIME / "pgdata_win1252"
    dump_file = RUNTIME / "app_contabil_win1252.dump"
    if legacy_data.exists():
        raise RuntimeError("Já existe uma cópia do cluster WIN1252; a migração não será sobrescrita.")
    dump_env = {**os.environ, "PGPASSWORD": credentials["database_password"]}
    if run([executable("pg_dump.exe"), "-h", "127.0.0.1", "-p", str(old_port), "-U", DB_USER,
            "-Fc", "-f", str(dump_file), DB_NAME], env=dump_env).returncode:
        raise RuntimeError("Não foi possível salvar o banco antes da migração UTF-8.")

    # Este PID foi criado pela versão anterior deste próprio controlador, antes do
    # registro de tempo de criação existir. A migração foi explicitamente autorizada.
    if isinstance(state.get("app_pid"), int) and "app_started_at" not in state:
        created_at = process_started_at(state["app_pid"])
        if created_at is None:
            raise RuntimeError("Não foi possível verificar o processo da aplicação para reiniciá-la.")
        state["app_started_at"] = created_at
    stop_app(state)
    if run([executable("pg_ctl.exe"), "stop", "-D", str(DATA), "-m", "fast"]).returncode:
        raise RuntimeError("Não foi possível parar o cluster local para a migração UTF-8.")
    for _ in range(40):
        if not pg_running():
            break
        time.sleep(0.25)
    else:
        raise RuntimeError("O cluster local não encerrou a tempo para a migração UTF-8.")

    shutil.move(str(DATA), str(legacy_data))
    fresh_state = {"postgres_port": old_port}
    new_port = initialise_database(fresh_state, credentials)
    fresh_state["postgres_port"] = new_port
    write_json(STATE_FILE, fresh_state)
    if run([executable("pg_restore.exe"), "-h", "127.0.0.1", "-p", str(new_port), "-U", DB_USER,
            "-d", DB_NAME, str(dump_file)], env=dump_env).returncode:
        raise RuntimeError("A restauração UTF-8 falhou; o cluster anterior está preservado em .runtime/pgdata_win1252.")
    fresh_state["app_port"] = state.get("app_port")
    fresh_state = start_app(fresh_state, credentials, new_port)
    write_json(STATE_FILE, fresh_state)
    print("Migração UTF-8 concluída.")
    if fresh_state.get("url"):
        print("URL: " + fresh_state["url"])


def start() -> None:
    state = read_json(STATE_FILE)
    credentials = secrets_data()
    port = initialise_database(state, credentials)
    state["postgres_port"] = port
    # Persiste o banco antes da preparação/semente da aplicação: uma falha posterior não perde o rastro.
    write_json(STATE_FILE, state)
    state = start_app(state, credentials, port)
    write_json(STATE_FILE, state)
    print("Ambiente local ativo.")
    if state.get("url"):
        print("URL: " + state["url"])


def stop() -> None:
    state = read_json(STATE_FILE)
    stop_app(state)
    if pg_running():
        run([executable("pg_ctl.exe"), "stop", "-D", str(DATA), "-m", "fast"])
    write_json(STATE_FILE, state)
    print("Ambiente local parado.")


def status() -> None:
    state = read_json(STATE_FILE)
    database = bool(state.get("postgres_port")) and pg_ready(int(state["postgres_port"]))
    application = app_alive(state)
    print("Banco local: " + ("ativo" if database else "parado"))
    print("Aplicação: " + ("ativa" if application else "não iniciada"))
    if application and state.get("url"):
        print("URL: " + state["url"])


def main() -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--start", action="store_true")
    group.add_argument("--stop", action="store_true")
    group.add_argument("--status", action="store_true")
    group.add_argument("--migrate-utf8", action="store_true")
    args = parser.parse_args()
    try:
        if args.start:
            start()
        elif args.stop:
            stop()
        elif args.migrate_utf8:
            migrate_utf8()
        else:
            status()
    except RuntimeError as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
