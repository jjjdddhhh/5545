# docs

- design.md: claude.ai에 있는 설계서("AI 콘텐츠 기획·제작 자동화 플랫폼 시스템 설계서", 2026-09-30 판)를 Markdown으로 내보낸 것이다. 원래 그림 7개는 Markdown으로 옮겨지지 않아 같은 내용을 글로 풀어 넣었다. claude.ai에서 설계서를 고치면 다시 내보내 이 파일을 바꾼다. Claude Code는 claude.ai 문서 링크를 열 수 없으므로 이 파일이 설계의 기준이다.
- decisions.md: 구현 중 설계서와 다르게 정한 것을 한 줄씩 기록한다. Claude Code가 만든다.
- progress.md: 구현 단계별 진행 상황을 적는다. 새 대화에서 이어서 작업할 때 Claude Code가 가장 먼저 읽는다. Claude Code가 만든다.
- eval/: 평가 자료를 둔다. 합성 샘플 원고, 테스트 요청 20개(requests.json), 모델 비교 결과(model_test.md)가 여기에 들어간다.
- eval/originals/: 호롱불에서 받은 실제 원고와 결과물을 둔다. 이 폴더는 .gitignore에 들어 있어 저장소에 올라가지 않는다.
