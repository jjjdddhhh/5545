# prompt_store.py : 단계별 프롬프트 템플릿을 읽고 값을 채운다(설계서 9절).
# 실행할 때는 prompt_template 테이블의 활성 버전을 먼저 쓰고, DB에 없으면 llm/prompts/의 파일(버전 1 원문)을 쓴다.
# 어떤 템플릿을 썼는지는 PromptSet.template_id로 agent_step_log.prompt_template_id에 남는다.
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

PROMPT_DIR = Path(__file__).resolve().parent / "prompts"

# 화면과 DB에는 영어 코드로 저장하고, 프롬프트에는 모델이 이해하기 쉬운 한국어 이름으로 넣는다.
LEVEL_LABEL = {"beginner": "초급", "intermediate": "중급", "advanced": "고급"}
LANGUAGE_LABEL = {"ko": "한국어", "en": "영어", "ja": "일본어", "zh": "중국어", "vi": "베트남어"}

# {이름} 자리만 찾는다. 이름은 영문, 숫자, 밑줄로만 이루어진다고 정해, 템플릿 속 다른 중괄호(JSON 예시 등)는 건드리지 않는다.
_PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


@dataclass
class PromptSet:
    stage: str
    system: str              # 시스템 프롬프트 템플릿(값을 채우기 전)
    user: str                # 사용자 프롬프트 템플릿(값을 채우기 전)
    template_id: Optional[int] = None   # DB에서 읽었으면 prompt_template.id, 파일에서 읽었으면 None
    version: int = 1


def render(template: str, values: dict) -> str:
    """템플릿의 {이름} 자리를 values 값으로 바꾼다.
    str.format을 쓰지 않는 이유: 사용자가 템플릿을 고치다 중괄호를 넣거나, 원고에 중괄호가 있으면
    format이 KeyError나 ValueError를 내기 때문이다. 여기서는 values에 있는 이름만 바꾸고 나머지는 그대로 둔다."""
    def repl(match: re.Match) -> str:
        key = match.group(1)
        if key not in values:
            return match.group(0)
        value = values[key]
        return "" if value is None else str(value)
    return _PLACEHOLDER.sub(repl, template)


def placeholders(template: str) -> set[str]:
    """템플릿에 들어 있는 {이름} 목록. 프롬프트를 고칠 때 빠진 변수가 없는지 알려 주는 데 쓴다."""
    return set(_PLACEHOLDER.findall(template))


def file_prompt(stage: str) -> PromptSet:
    """llm/prompts/의 원문(버전 1)을 읽는다. 파일이 없으면 FileNotFoundError가 그대로 올라간다(설치 오류이므로)."""
    system = (PROMPT_DIR / f"{stage}.system.txt").read_text(encoding="utf-8").strip()
    user = (PROMPT_DIR / f"{stage}.user.txt").read_text(encoding="utf-8").strip()
    return PromptSet(stage=stage, system=system, user=user, template_id=None, version=1)


def active_prompt(db: Optional[Session], stage: str) -> PromptSet:
    """실행에 쓸 템플릿. DB의 활성 버전이 있으면 그것을, 없으면 파일 원문을 돌려준다.
    db가 None이면(스크립트에서 DB 없이 부를 때) 바로 파일을 쓴다."""
    if db is not None:
        from app.db import models as m  # 순환 import를 피하려고 함수 안에서 불러온다
        row = db.scalars(select(m.PromptTemplate)
                         .where(m.PromptTemplate.stage == stage, m.PromptTemplate.is_active.is_(True))
                         .order_by(m.PromptTemplate.version.desc()).limit(1)).first()
        if row is not None:
            return PromptSet(stage=stage, system=row.system_prompt, user=row.user_template,
                             template_id=row.id, version=row.version)
    return file_prompt(stage)


def common_values(setting) -> dict:
    """여러 단계가 함께 쓰는 값. setting은 GenerationSetting 행이나 같은 속성을 가진 객체다."""
    keywords = setting.keywords or []
    return {
        "audience": setting.audience,
        "level": LEVEL_LABEL.get(setting.difficulty, setting.difficulty),
        "language": LANGUAGE_LABEL.get(setting.output_language, setting.output_language),
        # 톤을 비워 두면 "알아서" 대신 무난한 기본값을 준다. 빈칸으로 두면 모델이 규칙 문장을 어색하게 읽는다.
        "tone": setting.tone or "친절하고 차분한 설명체",
        "keywords": ", ".join(keywords) if keywords else "없음",
    }
