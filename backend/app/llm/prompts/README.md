# 프롬프트 원문

단계별 프롬프트 원문이다. `{이름}` 자리는 코드가 값을 채운다. 파일 안에는 주석을 쓰지 않는다. 파일 내용이 그대로 LLM에게 가기 때문이다.

이 파일들은 버전 1의 원문이며, `scripts/seed_prompts.py`가 출력 스키마와 함께 prompt_template 테이블에 버전 1로 넣는다. 실행 중에는 DB의 활성 버전을 쓰고, DB에 없을 때만 이 파일을 쓴다. 화면이나 `PUT /api/prompts/{stage}`로 고치면 DB에 새 버전이 생기고 이 파일은 바뀌지 않는다.

| 파일 | 단계 | 채우는 값 |
| --- | --- | --- |
| outline.system.txt, outline.user.txt | 3. 구조화·구성안 | scene_count, audience, level, keywords, language, tone, clean_paragraphs |
| scene_detail.system.txt, scene_detail.user.txt | 4. 장면 상세 | audience, level, tone, language, outline_title, seq, scene_title, key_point, duration_sec, fixed_fields, source_text |
| narration.system.txt, narration.user.txt | 5a. 내레이션 | char_budget, char_min, char_max, duration_sec, audience, level, tone, language, seq, scene_title, key_point, screen_description, on_screen_text, source_text |
| manual.system.txt, manual.user.txt | 5b. 맞춤 매뉴얼 | audience, level, language, tone, outline, source_text |
| chunk_summary.system.txt, chunk_summary.user.txt | 긴 원고 요약(설계서 12절) | clean_paragraphs |

chunk_summary는 prompt_template의 stage 값(outline, scene_detail, narration, manual, quiz)에 없어 DB에 넣지 않고 이 파일만 쓴다.
