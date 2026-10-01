-- seed.sql : 미리 넣어 둘 데이터. schema.sql을 적용한 뒤 실행한다(mysql -u root -p content_ai < db/seed.sql).
-- 로그인 기능이 없는 프로토타입이라 테스트 사용자 한 명만 둔다. 수정 이력과 승인 기록의 "누가"에 쓰인다.
-- prompt_template 4행(outline, scene_detail, narration, manual)은 2단계 구현 때 Pydantic 출력 스키마와 함께
-- scripts/seed_prompts.py로 넣는다. 스키마 JSON을 코드에서 만들어야 모델 정의와 어긋나지 않기 때문이다.
USE content_ai;

INSERT INTO app_user (name, email) VALUES ('테스트 사용자', 'tester@example.com');
