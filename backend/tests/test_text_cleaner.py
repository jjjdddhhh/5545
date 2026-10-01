# text_cleaner 테스트. 원고에 형식이 없다는 가정(설계서 4절)을 여러 입력으로 확인한다.
import zipfile

import pytest

from app.pipeline import text_cleaner as tc


def test_blob_without_structure_is_split_into_even_paragraphs():
    blob = ("전동드릴을 쓰기 전에는 배터리가 끝까지 끼워졌는지 확인해야 한다. 딸깍 소리가 나지 않으면 작업 중에 빠질 수 있다. "
            "비트는 척에 깊이 넣고 척 키로 세 군데를 조인다. 보호안경과 장갑은 반드시 착용한다. ") * 5
    r = tc.clean_pasted(blob)
    assert len(r.paragraphs) >= 2
    assert all(p["kind"] == "body" for p in r.paragraphs)
    assert all(len(p["text"]) <= tc.MAX_LEN for p in r.paragraphs)
    assert [p["id"] for p in r.paragraphs] == [f"p{i}" for i in range(1, len(r.paragraphs) + 1)]


def test_transcript_without_periods_is_split():
    stt = ("자 오늘은 드릴 쓰는 법을 볼 건데요 먼저 배터리를 끼웁니다 딸깍 소리 날 때까지 끝까지 넣어야 돼요 "
           "그다음에 비트를 척에 넣고요 척 키로 돌려서 조여 줍니다 ") * 8
    r = tc.clean_pasted(stt)
    assert len(r.paragraphs) >= 2
    assert all(len(p["text"]) <= tc.MAX_LEN for p in r.paragraphs)


def test_headings_bullets_and_broken_lines():
    text = """전동드릴 안전교육

1. 작업 전 점검
배터리가 끝까지
끼워졌는지 확인한다. 딸깍 소리가 나야 한다.
• 비트 고정 상태
• 척 키 사용 여부

2. 보호구
보호안경과 장갑을 착용한다. 헐렁한 장갑은 회전부에 말려 들어갈 수 있으므로 손에 맞는 것을 쓴다."""
    ps = tc.clean_pasted(text).paragraphs
    kinds = [(p["kind"], p["text"].split("\n")[0][:10]) for p in ps]
    assert kinds[0] == ("heading", "전동드릴 안전교육")
    assert kinds[1] == ("heading", "1. 작업 전 점검")
    body = ps[2]["text"]
    assert body.startswith("배터리가 끝까지 끼워졌는지")      # 끊긴 줄이 이어졌다
    assert "\n- 비트 고정 상태\n- 척 키 사용 여부" in body   # 글머리표는 통일되고 줄이 유지된다
    assert ps[3]["kind"] == "heading" and ps[3]["text"] == "2. 보호구"


def test_docx_table_becomes_table_paragraph(tmp_path):
    docx = pytest.importorskip("docx")
    d = docx.Document()
    d.add_paragraph("작업 종류에 따라 착용할 보호구가 다르다. 아래 표를 따른다.")
    t = d.add_table(rows=2, cols=2)
    t.cell(0, 0).text, t.cell(0, 1).text = "작업", "보호구"
    t.cell(1, 0).text, t.cell(1, 1).text = "천공", "보안경, 장갑"
    d.add_paragraph("표에 없는 작업은 관리자에게 먼저 묻는다. 확인 전에는 작업을 시작하지 않는다.")
    path = tmp_path / "s.docx"
    d.save(path)
    ps = tc.clean_file(str(path)).paragraphs
    table = [p for p in ps if p["kind"] == "table"]
    assert table and table[0]["text"] == "작업 | 보호구\n천공 | 보안경, 장갑"


def test_hwpx_table_and_order(tmp_path):
    ns = ('xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph" '
          'xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section"')
    xml = (f"<hs:sec {ns}><hp:p><hp:run><hp:t>작업 전 점검 순서는 다음과 같다. 순서를 바꾸지 않는다.</hp:t></hp:run></hp:p>"
           "<hp:p><hp:run><hp:tbl><hp:tr><hp:tc><hp:subList><hp:p><hp:run><hp:t>배터리 체결 확인</hp:t></hp:run></hp:p>"
           "</hp:subList></hp:tc><hp:tc><hp:subList><hp:p><hp:run><hp:t>비트 고정 확인</hp:t></hp:run></hp:p></hp:subList>"
           "</hp:tc></hp:tr></hp:tbl></hp:run></hp:p>"
           "<hp:p><hp:run><hp:t>점검이 끝나면 시운전을 3초간 한다.</hp:t></hp:run></hp:p></hs:sec>")
    path = tmp_path / "s.hwpx"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("Contents/section0.xml", xml)
    ps = tc.clean_file(str(path)).paragraphs
    assert [p["kind"] for p in ps] == ["body", "table", "body"]
    assert ps[1]["text"] == "배터리 체결 확인 | 비트 고정 확인"


def test_cp949_txt(tmp_path):
    path = tmp_path / "s.txt"
    path.write_bytes("보안경은 작업 내내 쓴다. 벗으면 파편이 눈에 들어갈 수 있다.".encode("cp949"))
    assert tc.clean_file(str(path)).paragraphs[0]["text"].startswith("보안경은")


def test_pdf_header_footer_and_page_break(tmp_path):
    pytest.importorskip("pypdf")
    rl = pytest.importorskip("reportlab")  # 테스트용 PDF를 만들 때만 쓴다(개발용 의존성)
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.pdfgen import canvas
    import textwrap
    pdfmetrics.registerFont(UnicodeCIDFont("HYGothic-Medium"))
    # 본문 문장은 서로 다르게 둔다. 같은 문장이 여러 쪽의 가장자리에 반복되면 머리말로 오인될 수 있기 때문이다.
    sents = ["배터리가 끝까지 끼워졌는지 확인하고 딸깍 소리가 나지 않으면 다시 끼운다.",
             "비트는 척에 깊이 넣고 척 키로 세 군데를 고르게 조인다.",
             "작업물은 클램프로 고정하고 손으로 잡은 채 구멍을 뚫지 않는다.",
             "보안경은 작업을 마칠 때까지 벗지 않는다.",
             "장갑은 손에 꼭 맞는 것을 골라 회전부에 말려 들어가지 않게 한다.",
             "처음에는 낮은 속도로 자리를 잡은 뒤 속도를 올린다.",
             "드릴은 작업면에 수직으로 유지하고 옆으로 비틀지 않는다.",
             "작업이 끝나면 배터리를 먼저 분리하고 비트를 뺀 뒤 케이스에 넣는다.",
             "배터리가 뜨거우면 충분히 식힌 다음 지정된 충전기로만 충전한다.",
             "이상한 소리나 냄새가 나면 즉시 작업을 멈추고 관리자에게 알린다.",
             "전선이 손상된 충전기는 쓰지 말고 바로 교체를 요청한다.",
             "작업장 바닥의 부스러기는 작업이 끝날 때마다 치운다."]
    lines = textwrap.wrap(" ".join(sents), 34)
    per = len(lines) // 3 + 1
    path = tmp_path / "s.pdf"
    c = canvas.Canvas(str(path))
    for pg in range(3):
        c.setFont("HYGothic-Medium", 9)
        c.drawString(50, 800, "사내 교안 (대외비)")
        c.drawString(290, 30, f"- {pg + 1} -")
        c.setFont("HYGothic-Medium", 11)
        y = 760
        for line in lines[pg * per:(pg + 1) * per]:
            c.drawString(50, y, line)
            y -= 18
        c.showPage()
    c.save()
    r = tc.clean_file(str(path))
    assert r.stats["removed_lines"] == 6                       # 머리말 3줄과 쪽번호 3줄
    assert "대외비" not in r.clean_text
    assert all(p["text"].endswith("다.") for p in r.paragraphs)  # 쪽을 넘어간 문장도 이어졌다


def test_hwp_is_rejected_with_guidance():
    with pytest.raises(tc.UnsupportedFormat, match="hwpx"):
        tc.extract_pages("x.hwp")


def test_to_prompt_labels_and_wraps():
    ps = [{"id": "p1", "kind": "heading", "text": "보호구"}, {"id": "p2", "kind": "body", "text": "장갑을 낀다."}]
    assert tc.to_prompt(ps) == "<source>\n[p1 · 제목 후보] 보호구\n[p2] 장갑을 낀다.\n</source>"
