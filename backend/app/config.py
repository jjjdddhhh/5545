# config.py : 저장소 루트의 .env를 읽고, 분량·자막 기본값을 한곳에 모은다.
# 다른 모듈은 os.getenv를 직접 부르지 않고 이 모듈의 값을 쓴다. llm_client는 키트 인터페이스를 지키려고
# os.getenv를 그대로 쓰지만, 이 모듈을 먼저 import해 .env가 읽힌 뒤에 값을 가져가게 했다.
import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
ENV_FILE = REPO_ROOT / ".env"

# override=False: 테스트나 셸에서 이미 넣은 환경변수가 .env보다 앞선다.
load_dotenv(ENV_FILE, encoding="utf-8", override=False)

DATABASE_URL = os.getenv("DATABASE_URL", "")
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:8b")
OLLAMA_NUM_CTX = int(os.getenv("OLLAMA_NUM_CTX", "8192"))
FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")

# 로그인 기능이 없는 프로토타입이라 db/seed.sql이 넣은 테스트 사용자(id 1)를 모든 수정의 주체로 쓴다.
DEFAULT_USER_ID = int(os.getenv("DEFAULT_USER_ID", "1"))

# ---------- 분량 기본값 (설계서 4절) ----------
# 장면당 30초: 학습 포인트 하나를 설명하고 화면 한 컷을 보여 주기에 알맞은 길이로 잡은 출발점이다.
SCENE_DEFAULT_SEC = 30
# 분당 300자: 교육 영상 내레이션의 보통 낭독 속도를 가정한 값이다. 실제 녹음 속도를 재면 바꾼다.
# 글자 수는 공백을 뺀 글자로 센다. 소리 내어 읽는 것은 글자(음절)이고 띄어쓰기는 읽지 않기 때문이다.
NARRATION_CPM = 300
# 내레이션 허용 오차 ±15%: 30초 장면(150자)에서 ±22자, 약 ±4.5초다. 문장을 다듬을 여유를 주면서도
# 장면 시간을 크게 벗어나지 않는 범위로 잡았다(검수 C04).
NARRATION_TOLERANCE = 0.15

# ---------- 자막 기본값 (설계서 4절) ----------
# 한 줄 16자: 방송 자막에서 흔히 쓰는 한 줄 길이로, 화면 아래에서 한눈에 읽히는 폭이다. 공백도 화면 폭을
# 차지하므로 자막 줄 길이는 공백을 포함해 센다.
SUBTITLE_MAX_CHARS = 16
# 최대 2줄: 두 줄을 넘으면 화면을 가리고 읽는 시간이 모자란다.
SUBTITLE_MAX_LINES = 2

# ---------- 입력 범위 ----------
# 장면 수 상한 40개: 30초 장면이면 20분 분량이다. 장면마다 LLM을 두세 번 부르므로, 노트북 GPU 한 대에서
# 한 번 생성하는 시간이 지나치게 길어지지 않게 막는 값이다.
MAX_SCENES = 40
MAX_DURATION_SEC = MAX_SCENES * 60
# ICS로 반복 일정을 내보낼 때 반복 횟수. 끝이 없는 반복은 캘린더를 끝없이 채우므로 12회(주 단위면 약 석 달)로 끊는다.
ICS_REPEAT_COUNT = 12
