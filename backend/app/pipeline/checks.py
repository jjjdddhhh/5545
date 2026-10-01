# checks.py : 6단계 검수(설계서 10절). 모든 검사는 코드로 하며 LLM을 부르지 않는다.
# 이 파일의 검사 함수는 DB를 모르는 순수 함수다. 딕셔너리와 문자열을 받아 CheckResult 목록을 돌려준다.
# 그래서 DB 없이 단위 테스트할 수 있고, 생성 단계(바로 다시 요청할지 판단), 6단계(결과 저장),
# 수정 요청 에이전트(제안 검수)가 같은 함수를 함께 쓴다.
import re
from dataclasses import dataclass, field
from typing import Optional

PASS, WARN, FAIL = "pass", "warn", "fail"


@dataclass
class CheckResult:
    code: str                          # C01~C12
    result: str                        # pass, warn, fail (저장할 때 정책에 따라 fail이 warn으로 바뀔 수 있다)
    message: str = ""                  # 사람이 읽을 설명. review_check.message VARCHAR(500)에 맞춰 자른다
    target_type: Optional[str] = None  # scene, narration, subtitle, manual, manual_step, schedule, outline, run
    target_ref: Optional[int] = None   # 대상 식별값. 생성 중에는 장면·단계 순서(seq), 저장 뒤에는 DB id를 쓴다
    data: dict = field(default_factory=dict)   # 재요청 문장을 만들 때 쓰는 세부 정보(예: 틀린 문단 번호)

    @property
    def failed(self) -> bool:
        return self.result == FAIL


# ---------- C02 장면 수 ----------
def check_scene_count(scene_count: int, expected: int) -> CheckResult:
    """C02: 구성안의 장면 수가 분량 계산 결과와 같은지. 실패하면 구성안 단계를 1회 다시 요청한다."""
    if scene_count == expected:
        return CheckResult("C02", PASS, f"장면 수 {scene_count}개가 분량 계산 결과와 같습니다.", "outline")
    return CheckResult("C02", FAIL, f"장면 수가 {scene_count}개입니다. 분량 계산 결과는 {expected}개입니다.",
                       "outline", data={"got": scene_count, "expected": expected})


# ---------- C03 근거 문단 ----------
def check_sources(items: list[dict], paragraph_ids: set[str], target_type: str = "scene") -> list[CheckResult]:
    """C03: 모든 장면(또는 매뉴얼 단계)에 근거 문단이 있고, 그 번호가 실제 문단 목록에 있는지.
    items의 각 원소는 {"seq": 순서, "source_paragraphs": [...], "id": (있으면 DB id)} 모양이다.
    대상마다 결과를 하나씩 돌려줘, 어느 장면이 틀렸는지 장면 목록의 점 색으로 보여 줄 수 있게 한다."""
    out = []
    for it in items:
        ref = it.get("id", it.get("seq"))
        ids = list(it.get("source_paragraphs") or [])
        unknown = [p for p in ids if p not in paragraph_ids]
        label = "장면" if target_type == "scene" else "단계"
        if not ids:
            out.append(CheckResult("C03", FAIL, f"{label} {it.get('seq')}에 근거 문단이 없습니다.", target_type, ref,
                                   {"seq": it.get("seq"), "missing": True}))
        elif unknown:
            out.append(CheckResult("C03", FAIL,
                                   f"{label} {it.get('seq')}의 근거 문단 {', '.join(unknown)}이(가) 원고에 없습니다.",
                                   target_type, ref, {"seq": it.get("seq"), "unknown": unknown}))
        else:
            out.append(CheckResult("C03", PASS, f"근거 문단 {', '.join(ids)}", target_type, ref))
    return out


# ---------- C11 출력 언어 ----------
HANGUL = re.compile(r"[가-힣ㄱ-ㆎ]")         # 완성형 한글과 자모
LATIN = re.compile(r"[A-Za-z]")
KANA = re.compile(r"[぀-ヿ]")                         # 히라가나와 가타카나
HAN = re.compile(r"[一-鿿]")                          # 한자
# 한국어 결과에도 "LED", "rpm" 같은 영문 용어가 섞이므로, 한글이 글자의 60% 이상이면 한국어로 본다.
# 영어 결과는 고유명사로 한글이 섞일 일이 거의 없어 라틴 문자 80% 이상을 기준으로 잡았다.
LANG_MIN_RATIO = {"ko": 0.6, "en": 0.8, "ja": 0.5, "zh": 0.6}
# 비율을 믿을 수 있는 최소 글자 수. "OK" 같은 아주 짧은 글은 비율이 의미가 없어 통과로 본다.
LANG_MIN_LETTERS = 10


def language_ratio(text: str, language: str) -> Optional[float]:
    """글자(숫자, 기호, 공백 제외) 가운데 그 언어의 문자가 차지하는 비율. 검사 규칙이 없는 언어면 None."""
    counts = {"ko": len(HANGUL.findall(text)), "en": len(LATIN.findall(text)),
              "kana": len(KANA.findall(text)), "han": len(HAN.findall(text))}
    letters = sum(counts.values())
    if letters < LANG_MIN_LETTERS:
        return 1.0
    if language == "ko":
        return counts["ko"] / letters
    if language == "en":
        return counts["en"] / letters
    if language == "ja":
        return (counts["kana"] + counts["han"]) / letters   # 일본어는 가나와 한자를 함께 쓴다
    if language == "zh":
        return counts["han"] / letters
    return None


def check_language(text: str, language: str, target_type: str, target_ref: Optional[int] = None) -> CheckResult:
    """C11: 출력 언어가 설정한 언어와 같은지 문자 종류의 비율로 확인한다."""
    ratio = language_ratio(text, language)
    if ratio is None:
        return CheckResult("C11", PASS, f"'{language}'은(는) 문자 비율 검사 규칙이 없어 확인하지 않았습니다.",
                           target_type, target_ref)
    need = LANG_MIN_RATIO[language]
    if ratio >= need:
        return CheckResult("C11", PASS, f"설정 언어 문자 비율 {ratio:.0%}", target_type, target_ref)
    return CheckResult("C11", FAIL, f"설정 언어({language}) 문자 비율이 {ratio:.0%}로 기준 {need:.0%}보다 낮습니다.",
                       target_type, target_ref, {"ratio": ratio})


def feedback_text(results: list[CheckResult]) -> str:
    """실패한 검사 결과를 LLM에게 다시 요청할 때 붙일 문장으로 바꾼다(llm_step.call_llm의 feedback)."""
    return "\n".join(f"- {r.message}" for r in results if r.failed)
