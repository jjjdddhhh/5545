# dev.py : 설치와 실행을 명령 하나로 하는 도우미(Windows, macOS, Linux 공통).
# 저장소 루트에서 실행한다. Windows에서는 setup.bat, start.bat을 더블클릭하거나,
# VS Code에서 Ctrl+Shift+B(실행)나 "작업 실행"(설치)을 고르면 이 파일이 불린다.
#
#   python dev.py setup    (비밀번호 입력이 안 되면 python dev.py setup --show)
#                          처음 한 번: 백엔드 가상환경과 패키지, 화면 패키지, .env, MySQL DB와 사용자, 프롬프트를 준비한다
#   python dev.py start    백엔드(8000)와 화면(5173)을 함께 켜고 브라우저를 연다. Ctrl+C로 둘 다 끈다
#   python dev.py check    DB, Ollama, 모델 준비 상태만 확인한다
#
# 셸 스크립트 대신 Python으로 만든 이유: CLAUDE.md 작업 규칙("셸 스크립트 대신 Python 스크립트")을 따르고,
# Windows PowerShell과 macOS 터미널에서 똑같이 돌게 하기 위해서다.
# MySQL 작업은 mysql 명령(CLI) 대신 pymysql로 직접 접속해 한다. Windows에서는 mysql 명령이 PATH에 없는
# 경우가 많아, 설치는 되어 있는데 명령을 찾지 못하는 문제가 자주 생기기 때문이다.
import getpass
import os
import re
import secrets
import shutil
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
ENV_FILE = ROOT / ".env"
ENV_EXAMPLE = ROOT / ".env.example"
IS_WIN = os.name == "nt"
# 가상환경 안의 python 위치는 운영체제마다 다르다(Windows는 Scripts, 나머지는 bin).
VENV_PY = BACKEND / ".venv" / ("Scripts/python.exe" if IS_WIN else "bin/python")
# Windows의 npm은 npm.cmd라는 배치 파일이라, subprocess로 부를 때 이 이름을 써야 찾는다.
NPM = "npm.cmd" if IS_WIN else "npm"

DB_NAME = "content_ai"
DB_USER = "content_ai"
BACKEND_URL = "http://localhost:8000"
FRONTEND_URL = "http://localhost:5173"


# ---------- 출력 도우미 ----------
def say(msg: str) -> None:
    print(f"\n=== {msg}", flush=True)


def fail(msg: str) -> None:
    """사용자가 고쳐야 하는 문제를 알리고 멈춘다. 창이 바로 닫히지 않게 bat 파일에서 pause로 기다린다."""
    print(f"\n[중단] {msg}", flush=True)
    sys.exit(1)


def run(cmd: list, cwd: Path = ROOT) -> None:
    """명령을 실행하고, 실패하면 어떤 명령이 실패했는지 알리고 멈춘다."""
    print("  $ " + " ".join(str(c) for c in cmd), flush=True)
    result = subprocess.run([str(c) for c in cmd], cwd=str(cwd))
    if result.returncode != 0:
        fail(f"명령이 실패했습니다: {' '.join(str(c) for c in cmd)}")


# ---------- .env 읽고 쓰기 ----------
def read_env() -> dict:
    """KEY=VALUE 줄만 읽는다. 주석과 빈 줄은 건너뛴다."""
    if not ENV_FILE.exists():
        return {}
    out = {}
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def set_env_value(key: str, value: str) -> None:
    """.env에서 key 줄만 바꾼다. 다른 줄과 주석은 그대로 둔다. 줄이 없으면 끝에 더한다."""
    lines = ENV_FILE.read_text(encoding="utf-8").splitlines() if ENV_FILE.exists() else []
    for i, line in enumerate(lines):
        if line.strip().startswith(f"{key}="):
            lines[i] = f"{key}={value}"
            break
    else:
        lines.append(f"{key}={value}")
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def db_password_from_env() -> str | None:
    """DATABASE_URL에서 content_ai 사용자의 비밀번호를 꺼낸다. 아직 예시 값("비밀번호")이면 None."""
    url = read_env().get("DATABASE_URL", "")
    m = re.match(r"mysql\+pymysql://[^:]+:([^@]*)@", url)
    if not m or m.group(1) in ("", "비밀번호"):
        return None
    return m.group(1)


# ---------- setup ----------
def setup() -> None:
    """처음 한 번 실행한다. 이미 끝난 단계는 건너뛰므로 여러 번 실행해도 안전하다."""
    say("1/5 필요한 프로그램 확인")
    if sys.version_info < (3, 11):
        fail(f"Python 3.11 이상이 필요합니다(지금 {sys.version.split()[0]}). python.org에서 새 버전을 설치해 주세요.")
    if shutil.which(NPM) is None:
        fail("Node.js(npm)를 찾지 못했습니다. nodejs.org에서 20 이상 버전을 설치하고 창을 새로 열어 주세요.")
    print("  Python과 Node.js가 있습니다.")

    say("2/5 백엔드 가상환경과 패키지")
    if not VENV_PY.exists():
        run([sys.executable, "-m", "venv", ".venv"], cwd=BACKEND)
    run([VENV_PY, "-m", "pip", "install", "-q", "-r", "requirements.txt"], cwd=BACKEND)

    say("3/5 화면 패키지")
    if not (FRONTEND / "node_modules").exists():
        run([NPM, "install"], cwd=FRONTEND)
    else:
        print("  이미 설치되어 있습니다.")
    if not (FRONTEND / ".env").exists():
        shutil.copy(FRONTEND / ".env.example", FRONTEND / ".env")

    say("4/5 .env와 MySQL DB")
    if not ENV_FILE.exists():
        shutil.copy(ENV_EXAMPLE, ENV_FILE)
        print("  저장소 루트에 .env를 만들었습니다.")
    # DB 작업에는 pymysql이 필요하므로, 방금 패키지를 설치한 가상환경의 python으로 이 파일을 다시 부른다.
    run([VENV_PY, str(ROOT / "dev.py"), "_db"])

    say("5/5 프롬프트 버전 1과 DB 확인")
    run([VENV_PY, "scripts/seed_prompts.py"], cwd=BACKEND)
    run([VENV_PY, "-m", "alembic", "stamp", "head"], cwd=BACKEND)
    run([VENV_PY, "scripts/check_db.py"], cwd=BACKEND)

    print("\n설치가 끝났습니다. 이제 start.bat을 더블클릭하거나(또는 python dev.py start) VS Code에서 Ctrl+Shift+B로 실행하세요.")
    check_ollama(verbose=True)


def setup_db() -> None:
    """가상환경 안에서 실행된다(dev.py _db). root 계정으로 접속해 DB, 테이블, 사용자, 테스트 사용자를 준비하고
    content_ai 사용자의 비밀번호를 .env와 맞춘다. 이미 있는 것은 건너뛰거나 맞춰 놓기만 한다."""
    import pymysql

    sys.path.insert(0, str(BACKEND))
    from app.db.schema_sql import table_statements, table_names  # schema.sql 하나를 기준으로 쓴다

    print("  MySQL root 계정으로 DB를 준비합니다. MySQL을 설치할 때 정한 root 비밀번호를 넣어 주세요.")
    if os.environ.get("DEV_SHOW_PASSWORD") != "1":
        print("  (입력하는 글자는 화면에 보이지 않습니다. 보이지 않아도 끝까지 치고 Enter를 누르세요.")
        print("   입력이 아예 안 되면 Ctrl+C로 멈추고 python dev.py setup --show 로 다시 실행하세요.)")
    # 비밀번호를 잘못 넣어도 처음부터 다시 실행하지 않도록 세 번까지 다시 묻는다.
    # 세 번이면 오타는 충분히 바로잡을 수 있고, 비밀번호를 정말 모르는 경우에는 끝없이 묻지 않고 멈추기 위해서다.
    conn = None
    for attempt in range(1, 4):
        if os.environ.get("DEV_SHOW_PASSWORD") == "1":
            # --show 옵션: 일부 터미널(VS Code 작업 터미널 등)에서 감춘 입력이 받아지지 않을 때를 위해 글자를 보이게 받는다.
            root_pw = input("  root 비밀번호(입력이 보입니다): ")
        else:
            root_pw = getpass.getpass("  root 비밀번호: ")
        try:
            conn = pymysql.connect(host="localhost", port=3306, user="root", password=root_pw, charset="utf8mb4",
                                   autocommit=True)
            break
        except pymysql.err.OperationalError as exc:
            code = exc.args[0] if exc.args else None
            if code != 1045:   # 1045는 비밀번호 오류. 그 밖의 오류(서버 꺼짐 등)는 다시 물어도 소용이 없다
                fail(f"MySQL에 연결하지 못했습니다. MySQL 서비스가 켜져 있는지 확인해 주세요"
                     f"(Windows: 서비스 앱에서 MySQL80). ({exc})")
            if attempt < 3:
                print(f"  root 비밀번호가 맞지 않습니다. 다시 넣어 주세요({attempt}/3).")
    if conn is None:
        fail("root 비밀번호가 세 번 맞지 않았습니다. 비밀번호를 확인한 뒤 다시 실행해 주세요.")

    with conn.cursor() as cur:
        cur.execute("SELECT VERSION()")
        version = cur.fetchone()[0]
        nums = [int(x) for x in re.findall(r"\d+", version)[:3]]
        print(f"  MySQL 버전: {version}")
        if nums < [8, 0, 16]:
            fail("MySQL 8.0.16 이상이 필요합니다(utf8mb4_0900_ai_ci와 CHECK 제약).")

        # DB와 테이블. 이미 있는 테이블은 건너뛴다(앞에서 schema.sql을 일부만 적용한 경우도 이어서 만든다).
        cur.execute(f"CREATE DATABASE IF NOT EXISTS {DB_NAME} DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci")
        cur.execute(f"USE {DB_NAME}")
        cur.execute("SHOW TABLES")
        have = {r[0] for r in cur.fetchall()}
        made = 0
        for name, stmt in zip(table_names(), table_statements()):
            if name not in have:
                cur.execute(stmt)
                made += 1
        print(f"  테이블: 새로 만든 것 {made}개, 이미 있던 것 {len(have & set(table_names()))}개")

        # content_ai 사용자. .env에 비밀번호가 있으면 그것을 쓰고, 없으면 새로 만든다.
        # 사용자가 이미 있으면 비밀번호를 .env 값으로 맞춘다(접속 거절 1045의 흔한 원인이 비밀번호 불일치다).
        app_pw = db_password_from_env() or secrets.token_urlsafe(12)
        cur.execute("SELECT COUNT(*) FROM mysql.user WHERE user=%s AND host='localhost'", (DB_USER,))
        if cur.fetchone()[0]:
            cur.execute(f"ALTER USER '{DB_USER}'@'localhost' IDENTIFIED BY %s", (app_pw,))
            print("  content_ai 사용자가 이미 있어 비밀번호를 .env와 맞췄습니다.")
        else:
            cur.execute(f"CREATE USER '{DB_USER}'@'localhost' IDENTIFIED BY %s", (app_pw,))
            print("  content_ai 사용자를 만들었습니다.")
        cur.execute(f"GRANT ALL ON {DB_NAME}.* TO '{DB_USER}'@'localhost'")

        # 테스트 사용자(db/seed.sql과 같은 내용). 이미 있으면 그대로 둔다.
        cur.execute("SELECT COUNT(*) FROM app_user")
        if cur.fetchone()[0] == 0:
            cur.execute("INSERT INTO app_user (name, email) VALUES ('테스트 사용자', 'tester@example.com')")
            print("  테스트 사용자를 넣었습니다.")
    conn.close()

    set_env_value("DATABASE_URL", f"mysql+pymysql://{DB_USER}:{app_pw}@localhost:3306/{DB_NAME}")
    print("  .env의 DATABASE_URL을 저장했습니다.")


# ---------- check ----------
def check_ollama(verbose: bool = False) -> bool:
    """Ollama가 켜져 있고 .env의 모델을 받아 두었는지 본다. 없어도 화면은 켜지므로 경고만 한다."""
    env = read_env()
    host = env.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
    model = env.get("OLLAMA_MODEL", "qwen3:8b")
    try:
        with urllib.request.urlopen(f"{host}/api/tags", timeout=2) as r:
            body = r.read().decode("utf-8")
    except Exception:
        print(f"\n[주의] Ollama({host})에 연결하지 못했습니다. 화면은 쓸 수 있지만 생성은 안 됩니다."
              f" Ollama를 켜고 'ollama pull {model}'을 해 주세요.")
        return False
    if f'"{model}"' not in body and f'"{model}:latest"' not in body:
        print(f"\n[주의] Ollama는 켜져 있지만 모델 {model}이 없습니다. 'ollama pull {model}'을 실행해 주세요.")
        return False
    if verbose:
        print(f"\nOllama와 모델 {model}이 준비되어 있습니다.")
    return True


def check() -> None:
    if not VENV_PY.exists():
        fail("아직 설치하지 않았습니다. 먼저 setup.bat(또는 python dev.py setup)을 실행해 주세요.")
    run([VENV_PY, "scripts/check_db.py"], cwd=BACKEND)
    check_ollama(verbose=True)


# ---------- start ----------
def wait_http(url: str, seconds: int) -> bool:
    """url이 응답할 때까지 최대 seconds초 기다린다."""
    end = time.time() + seconds
    while time.time() < end:
        try:
            urllib.request.urlopen(url, timeout=1)
            return True
        except Exception:
            time.sleep(0.5)
    return False


def start() -> None:
    """백엔드와 화면을 함께 켠다. 두 프로그램의 출력이 이 창 하나에 섞여 나온다. Ctrl+C로 둘 다 끈다."""
    if not VENV_PY.exists() or not (FRONTEND / "node_modules").exists():
        fail("아직 설치하지 않았습니다. 먼저 setup.bat(또는 python dev.py setup)을 실행해 주세요.")
    if db_password_from_env() is None:
        fail(".env의 DB 비밀번호가 비어 있습니다. setup.bat을 다시 실행해 주세요.")
    check_ollama()

    say("백엔드(8000)와 화면(5173)을 켭니다. 끌 때는 이 창에서 Ctrl+C를 누르세요.")
    procs = [
        subprocess.Popen([str(VENV_PY), "-m", "uvicorn", "app.main:app", "--reload", "--port", "8000"],
                         cwd=str(BACKEND)),
        subprocess.Popen([NPM, "run", "dev"], cwd=str(FRONTEND)),
    ]
    try:
        if wait_http(f"{BACKEND_URL}/api/health", 40) and wait_http(FRONTEND_URL, 40):
            print(f"\n준비되었습니다. 브라우저에서 {FRONTEND_URL} 을 엽니다.", flush=True)
            webbrowser.open(FRONTEND_URL)
        else:
            print("\n[주의] 서버가 40초 안에 켜지지 않았습니다. 위의 오류 메시지를 확인해 주세요.", flush=True)
        while all(p.poll() is None for p in procs):   # 둘 중 하나라도 꺼지면 함께 끈다
            time.sleep(1)
        print("\n[주의] 서버 하나가 멈췄습니다. 위의 오류 메시지를 확인해 주세요.")
    except KeyboardInterrupt:
        print("\n끄는 중입니다.")
    finally:
        for p in procs:
            if p.poll() is None:
                p.terminate()
        for p in procs:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()


COMMANDS = {"setup": setup, "start": start, "check": check, "_db": setup_db}

if __name__ == "__main__":
    if "--show" in sys.argv:
        # 비밀번호를 보이게 입력한다. 환경변수로 넘겨, setup이 다시 부르는 dev.py _db(자식 프로세스)도 같은 방식으로 받게 한다.
        os.environ["DEV_SHOW_PASSWORD"] = "1"
        sys.argv.remove("--show")
    cmd = sys.argv[1] if len(sys.argv) > 1 else "start"
    if cmd not in COMMANDS:
        print("사용법: python dev.py [setup | start | check]")
        sys.exit(2)
    COMMANDS[cmd]()
