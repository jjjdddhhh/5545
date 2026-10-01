# text_cleaner.py : 1단계 텍스트 정제.
# 원고에는 정해진 형식이 없다고 가정한다. 제목, 절, 번호, 빈 줄, 마침표가 있을 수도 없을 수도 있다.
# 그래서 코드는 구조를 추측해 장면을 나누지 않고, 글을 고른 크기의 문단으로 나눠 번호만 붙인다.
# 어떤 문단들을 한 장면으로 묶을지는 3단계(구조화)의 LLM이 정한다.
import re
import unicodedata
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree

TARGET_LEN = 300     # 문단 목표 길이(자). 30초 장면(내레이션 약 150자) 한두 개의 근거가 되는 크기로,
                     # 이보다 크면 근거가 흐려지고 작으면 번호가 너무 많아져 LLM이 엉뚱한 번호를 고르기 쉽다
MAX_LEN = 450        # 목표의 1.5배. 이보다 긴 덩어리는 문장 단위로 다시 나눈다
MIN_LEN = 40         # 이보다 짧은 본문 조각은 다음 문단에 붙인다(제목 후보와 표는 따로 둔다)
HEADING_MAX = 30     # 이 길이 이하이고 문장 끝맺음이 없는 줄을 제목 후보로 본다
EDGE_LINES = 2       # 각 쪽의 위아래 두 줄만 머리말·바닥글 후보로 본다(본문의 반복 문장을 지우지 않도록)
HEADER_RATIO = 0.5   # 쪽이 3장 이상일 때, 절반 이상의 쪽 위아래에 똑같이 나오는 줄은 머리말·바닥글로 본다
SCAN_PDF_CHARS = 50  # 쪽당 평균 글자가 이보다 적으면 글자 없는 스캔 PDF일 가능성이 크다
TXT_ENCODINGS = ("utf-8-sig", "cp949", "euc-kr")  # 한국어 Windows에서 만든 txt는 cp949인 경우가 많다

BULLET = re.compile(r"^[•●◦▪■□◆◇▶►·※\*]\s*")
LIST_ITEM = re.compile(r"^(-\s|\d{1,2}[.)]\s|[가-하][.)]\s|\(\d{1,2}\)\s|[①-⑳])")
NUMBERED_HEADING = re.compile(r"^(제\s*\d+\s*[장절편]|[IVX]+\.|\d+(\.\d+)*\.?\s)")
PAGE_NO = re.compile(r"^[-–—\s]*(p\.?\s*)?\d{1,4}(\s*/\s*\d{1,4})?[-–—\s]*$", re.IGNORECASE)
SENT_END_CHAR = re.compile(r"[.!?。…\"”’)\]]$")
KOREAN_END = re.compile(r"(다|요|죠|까|니다)$")        # 마침표 없이 받아쓴 원고에서 문장 끝으로 볼 어미
# 조사나 연결어미로 끝나는 줄은 문장이 이어지는 중이므로 제목으로 보지 않는다.
# 명사로도 흔히 끝나는 '이, 가, 서, 지'는 넣지 않아 짧은 제목을 본문에 붙이는 실수를 줄였다.
CONTINUES = re.compile(r"(을|를|은|는|에|의|와|과|로|고|며|면|도록|까지|부터|처럼|하고|해서|하여|에서)$")
SENT_SPLIT = re.compile(r"(?<=[.!?。…])\s+")
SENT_SPLIT_LOOSE = re.compile(r"(?<=다|요|죠)\s+")        # 마침표가 전혀 없는 덩어리에만 쓴다
TABLE_SEP = " | "                                          # 표의 한 행은 셀을 이 기호로 이은 한 줄이 된다


class UnsupportedFormat(Exception):
    pass


@dataclass
class CleanResult:
    clean_text: str
    paragraphs: list[dict]
    stats: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


# ---------- 1. 글자 뽑기: 파일 형식마다 다르고, 결과는 쪽(page) 단위 문자열 목록이다 ----------
def extract_pages(path: str) -> list[str]:
    p = Path(path)
    ext = p.suffix.lower()
    if ext in (".txt", ".md"):
        raw = p.read_bytes()
        for enc in TXT_ENCODINGS:
            try:
                return [raw.decode(enc)]
            except UnicodeDecodeError:
                continue
        return [raw.decode("utf-8", errors="replace")]
    if ext == ".docx":
        return [_docx_text(p)]
    if ext == ".pdf":
        from pypdf import PdfReader
        return [page.extract_text() or "" for page in PdfReader(str(p)).pages]
    if ext == ".hwpx":
        return [_hwpx_text(p)]
    if ext == ".hwp":
        raise UnsupportedFormat("hwp 파일은 한글 프로그램에서 hwpx, docx, pdf 중 하나로 저장해 올려 주세요.")
    raise UnsupportedFormat(f"지원하지 않는 형식입니다: {ext}")


def _docx_text(path: Path) -> str:
    """본문의 문단과 표를 문서에 나온 순서대로 읽는다. 표 하나는 행마다 한 줄인 덩어리가 된다."""
    import docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph
    d = docx.Document(str(path))
    blocks = []
    for el in d.element.body.iterchildren():
        tag = _local(el.tag)
        if tag == "p":
            blocks.append(Paragraph(el, d).text)
        elif tag == "tbl":
            rows = []
            for row in Table(el, d).rows:
                cells = dict.fromkeys(c.text.strip() for c in row.cells)  # 병합 셀이 겹쳐 나오는 것을 없앤다
                rows.append(TABLE_SEP.join(c for c in cells if c))
            blocks.append("\n".join(r for r in rows if r))
    return "\n\n".join(blocks)


def _hwpx_text(path: Path) -> str:
    """hwpx는 XML 묶음(zip)이다. 문단(p) 안의 글자(t)를 모으고, 표(tbl)는 행마다 한 줄인 덩어리로 만든다."""
    blocks: list[str] = []

    def cell_text(tc) -> str:
        return " ".join("".join(t.itertext()) for t in tc.iter() if _local(t.tag) == "t").strip()

    def walk(p_el):
        idx = len(blocks)
        blocks.append("")
        buf: list[str] = []
        tables: list[str] = []

        def collect(el):
            for ch in el:
                tag = _local(ch.tag)
                if tag == "t":
                    buf.append("".join(ch.itertext()))
                elif tag == "tbl":
                    rows = []
                    for tr in (x for x in ch.iter() if _local(x.tag) == "tr"):
                        cells = [cell_text(tc) for tc in tr if _local(tc.tag) == "tc"]
                        rows.append(TABLE_SEP.join(c for c in cells if c))
                    tables.append("\n".join(r for r in rows if r))
                elif tag == "p":
                    walk(ch)          # 글상자처럼 문단 안에 든 문단은 따로 한 문단으로 센다
                else:
                    collect(ch)
        collect(p_el)
        blocks[idx] = "".join(buf)
        blocks.extend(tables)

    with zipfile.ZipFile(path) as z:
        sections = sorted((n for n in z.namelist() if re.match(r"Contents/section\d+\.xml$", n)),
                          key=lambda n: int(re.findall(r"\d+", n)[-1]))
        for name in sections:
            for ch in ElementTree.fromstring(z.read(name)):
                if _local(ch.tag) == "p":
                    walk(ch)
    return "\n\n".join(b for b in blocks if b)


# ---------- 2. 글자 정리: 보이지 않는 문자와 공백, 글머리표를 통일한다 ----------
def normalize(text: str) -> str:
    text = unicodedata.normalize("NFC", text)  # Mac에서 만든 파일의 풀어쓴 한글 자모를 합친다
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[\u200b-\u200d\ufeff]", "", text)          # 폭 없는 공백과 BOM
    text = re.sub(r"[\u00a0\u3000\t]", " ", text)             # 줄바꿈 없는 공백, 전각 공백, 탭
    text = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", text)
    lines = []
    for line in text.split("\n"):
        line = re.sub(r" {2,}", " ", line).strip()
        lines.append(BULLET.sub("- ", line))
    return "\n".join(lines)


def drop_page_furniture(pages: list[str]) -> tuple[list[str], int]:
    """쪽번호 줄을 지우고, 여러 쪽의 위아래에 되풀이되는 머리말·바닥글 줄을 지운다."""
    key = lambda s: re.sub(r"\d+", "#", s)

    def edges(lines: list[str]) -> set[int]:
        idx = [i for i, l in enumerate(lines) if l]
        return set(idx[:EDGE_LINES] + idx[-EDGE_LINES:])

    split = [pg.split("\n") for pg in pages]
    counts: Counter = Counter()
    for lines in split:
        counts.update({key(lines[i]) for i in edges(lines)})
    repeated = {k for k, c in counts.items() if len(pages) >= 3 and c / len(pages) >= HEADER_RATIO}
    removed, out = 0, []
    for lines in split:
        edge = edges(lines)
        kept = []
        for i, l in enumerate(lines):
            if l and (PAGE_NO.match(l) or (i in edge and key(l) in repeated)):
                removed += 1
                continue
            kept.append(l)
        out.append("\n".join(kept))
    return out, removed


# ---------- 3. 줄 잇기: PDF나 복사한 글에서 문장 중간에 끊긴 줄을 다시 붙인다 ----------
def ends_sentence(line: str) -> bool:
    return bool(SENT_END_CHAR.search(line) or KOREAN_END.search(line))


def heading_limit(text: str) -> int:
    """제목 후보로 볼 최대 길이. 좁은 단으로 줄바꿈된 PDF는 보통 줄도 짧으므로,
    줄 길이 중앙값의 60%와 HEADING_MAX 중 작은 값을 써서 끊긴 본문 줄을 제목으로 오해하지 않게 한다."""
    lens = sorted(len(l) for l in text.split("\n") if l.strip() and TABLE_SEP not in l)
    if len(lens) < 10:
        return HEADING_MAX
    return min(HEADING_MAX, int(lens[len(lens) // 2] * 0.6))


def looks_heading(line: str, limit: int = HEADING_MAX) -> bool:
    """짧고 문장 끝맺음이 없는 줄을 제목 후보로 본다. 글머리표 항목, 표의 행,
    조사나 연결어미로 끝나 문장이 이어지는 줄은 제목으로 보지 않는다."""
    if (not line or line.startswith("- ") or TABLE_SEP in line
            or ends_sentence(line) or CONTINUES.search(line)):
        return False
    if NUMBERED_HEADING.match(line) and len(line) <= limit + 10:
        return True
    return len(line) <= limit


def join_broken_lines(text: str, limit: int) -> tuple[str, int]:
    out, joined = [], 0
    for line in text.split("\n"):
        prev = out[-1] if out else ""
        if (prev and line and not ends_sentence(prev) and not looks_heading(prev, limit)
                and not LIST_ITEM.match(line) and TABLE_SEP not in prev and TABLE_SEP not in line):
            out[-1] = prev + " " + line
            joined += 1
        else:
            out.append(line)
    return "\n".join(out), joined


# ---------- 4. 문단 나누기: 형식이 없어도 고른 크기의 번호 붙은 문단을 만든다 ----------
def _split_long(block: str) -> list[str]:
    sents = SENT_SPLIT.split(block)
    if len(sents) == 1:                        # 마침표가 없는 받아쓰기 원고
        sents = SENT_SPLIT_LOOSE.split(block)
    pieces: list[str] = []
    for s in sents:                            # 문장 하나가 너무 길면 띄어쓰기 자리에서 자른다
        while len(s) > MAX_LEN:
            cut = s.rfind(" ", 0, TARGET_LEN)
            cut = cut if cut > 0 else TARGET_LEN
            pieces.append(s[:cut].strip())
            s = s[cut:].strip()
        if s:
            pieces.append(s)
    chunks, cur = [], ""
    for s in pieces:                           # 문장들을 목표 길이까지 모은다
        if cur and len(cur) + 1 + len(s) > TARGET_LEN:
            chunks.append(cur)
            cur = s
        else:
            cur = f"{cur} {s}".strip()
    if cur:
        chunks.append(cur)
    return chunks


def segment(text: str, limit: int = HEADING_MAX) -> list[dict]:
    """빈 줄로 나뉜 덩어리 안에서 제목 후보 줄과 표는 따로 떼고, 나머지 줄은 본문으로 묶는다.
    빈 줄이 없는 원고도 같은 규칙으로 처리되며, 긴 본문은 길이 기준으로 다시 나뉜다."""
    items: list[dict] = []

    def flush(lines: list[str], kind: str):
        if not lines:
            return
        if kind == "table":
            body = "\n".join(lines)
        else:  # 본문 줄은 띄어쓰기로 잇고, 목록 항목만 줄을 바꿔 둔다
            body = lines[0]
            for l in lines[1:]:
                body += ("\n" if LIST_ITEM.match(l) else " ") + l
        if kind == "body" and len(body) > MAX_LEN:
            items.extend({"kind": "body", "text": c} for c in _split_long(body))
        else:
            items.append({"kind": kind, "text": body})

    for block in re.split(r"\n\s*\n", text):
        group, table = [], []
        for line in (l.strip() for l in block.split("\n")):
            if not line:
                continue
            if TABLE_SEP in line:
                flush(group, "body")
                group = []
                table.append(line)
                continue
            flush(table, "table")
            table = []
            if looks_heading(line, limit):
                flush(group, "body")
                group = []
                items.append({"kind": "heading", "text": line})
            else:
                group.append(line)
        flush(group, "body")
        flush(table, "table")

    merged: list[dict] = []                    # 너무 짧은 본문 조각은 다음 본문에 붙인다
    carry = ""
    for it in items:
        if it["kind"] != "body":
            if carry:
                merged.append({"kind": "body", "text": carry})
                carry = ""
            merged.append(it)
            continue
        text_ = f"{carry} {it['text']}".strip() if carry else it["text"]
        if len(text_) < MIN_LEN:
            carry = text_
        else:
            merged.append({"kind": "body", "text": text_})
            carry = ""
    if carry:
        if merged and merged[-1]["kind"] == "body":
            merged[-1]["text"] += " " + carry
        else:
            merged.append({"kind": "body", "text": carry})
    return [{"id": f"p{i}", **m} for i, m in enumerate(merged, 1)]


# ---------- 전체 흐름 ----------
def clean(pages: list[str], is_pdf: bool = False) -> CleanResult:
    warnings: list[str] = []
    raw_chars = sum(len(p) for p in pages)
    if is_pdf and pages and raw_chars / len(pages) < SCAN_PDF_CHARS:
        warnings.append("글자가 거의 없습니다. 이미지로만 된 스캔 PDF일 수 있습니다.")
    pages = [normalize(p) for p in pages]
    pages, removed = drop_page_furniture(pages)
    merged = "\n".join(p.strip() for p in pages)  # 쪽 경계의 빈 줄을 없애야 쪽을 넘어간 문장이 이어진다
    limit = heading_limit(merged)
    text, joined = join_broken_lines(merged, limit)
    paragraphs = segment(text, limit)
    clean_text = "\n\n".join(p["text"] for p in paragraphs)
    if not paragraphs:
        warnings.append("뽑아낸 글자가 없습니다.")
    return CleanResult(clean_text, paragraphs,
                       {"raw_chars": raw_chars, "clean_chars": len(clean_text),
                        "removed_lines": removed, "joined_lines": joined,
                        "paragraphs": len(paragraphs),
                        "headings": sum(p["kind"] == "heading" for p in paragraphs),
                        "tables": sum(p["kind"] == "table" for p in paragraphs)},
                       warnings)


def clean_file(path: str) -> CleanResult:
    return clean(extract_pages(path), is_pdf=path.lower().endswith(".pdf"))


def clean_pasted(text: str) -> CleanResult:
    return clean([text])


# ---------- LLM에 넘기는 모양 ----------
KIND_LABEL = {"body": "", "heading": " · 제목 후보", "table": " · 표"}


def to_prompt(paragraphs: list[dict]) -> str:
    """구조화 단계 프롬프트에 넣을 원고. 문단 번호와 종류를 앞에 붙이고, 전체를 source 태그로 감싼다.
    태그 안의 문장은 자료일 뿐 지시가 아니라는 규칙을 시스템 프롬프트에 함께 둔다(프롬프트 인젝션 대비)."""
    body = "\n".join(f"[{p['id']}{KIND_LABEL[p['kind']]}] {p['text']}" for p in paragraphs)
    return f"<source>\n{body}\n</source>"
