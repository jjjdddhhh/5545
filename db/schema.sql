-- schema.sql : MySQL 8.0.16 이상. 설계서 7절(테이블 18개)과 13절(에이전트 테이블 3개)을 합친 전체 스키마다.
-- 적용 방법: mysql -u root -p < db/schema.sql
-- utf8mb4_0900_ai_ci 정렬 규칙과 CHECK 제약이 MySQL 8.0.16부터 동작하므로 버전을 먼저 확인한다(SELECT VERSION();).
-- MySQL은 외래키 동작(ON DELETE)이 걸린 컬럼에 CHECK를 허용하지 않으므로,
-- caution의 "manual_id와 scene_id 중 하나는 있어야 한다" 규칙은 애플리케이션에서 검사한다.

CREATE DATABASE IF NOT EXISTS content_ai DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
USE content_ai;

-- ---------- 입력과 설정 ----------
CREATE TABLE app_user (
  id          BIGINT AUTO_INCREMENT PRIMARY KEY,
  name        VARCHAR(50)  NOT NULL,
  email       VARCHAR(120) NOT NULL UNIQUE,
  created_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE project (
  id          BIGINT AUTO_INCREMENT PRIMARY KEY,
  user_id     BIGINT       NOT NULL,
  title       VARCHAR(200) NOT NULL,
  status      ENUM('draft','generating','ready','error') NOT NULL DEFAULT 'draft',
  created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  FOREIGN KEY (user_id) REFERENCES app_user(id)
);

CREATE TABLE source_document (
  id          BIGINT AUTO_INCREMENT PRIMARY KEY,
  project_id  BIGINT NOT NULL,
  source_type ENUM('paste','file') NOT NULL,
  file_name   VARCHAR(255),
  raw_text    MEDIUMTEXT NOT NULL,
  clean_text  MEDIUMTEXT NOT NULL,
  paragraphs  JSON NOT NULL,              -- [{"id":"p1","kind":"body","text":"..."}] kind는 body·heading·table
  char_count  INT  NOT NULL,
  created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (project_id) REFERENCES project(id) ON DELETE CASCADE
);

CREATE TABLE generation_setting (
  id                  BIGINT AUTO_INCREMENT PRIMARY KEY,
  project_id          BIGINT NOT NULL,
  content_type        ENUM('video','manual','both') NOT NULL,
  audience            VARCHAR(100) NOT NULL,       -- 예: 신입 사원, 현장 관리자
  difficulty          ENUM('beginner','intermediate','advanced') NOT NULL,
  target_duration_sec INT,                         -- 목표 분량과 장면 수 중 하나는 필수
  scene_count         INT,
  output_language     VARCHAR(10) NOT NULL DEFAULT 'ko',
  tone                VARCHAR(50),
  keywords            JSON,                        -- ["보호장갑","배터리"]
  narration_cpm       INT NOT NULL DEFAULT 300,    -- 분당 글자 수 기본값(설계서 4절). 호롱불 규칙을 받으면 바꾼다
  scene_default_sec   INT NOT NULL DEFAULT 30,     -- 장면당 기본 시간(설계서 4절)
  subtitle_max_chars  INT NOT NULL DEFAULT 16,     -- 자막 한 줄 최대 글자 수(설계서 4절)
  created_at          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CHECK (target_duration_sec IS NOT NULL OR scene_count IS NOT NULL),
  FOREIGN KEY (project_id) REFERENCES project(id) ON DELETE CASCADE
);

-- ---------- 실행과 이력 ----------
CREATE TABLE prompt_template (
  id            BIGINT AUTO_INCREMENT PRIMARY KEY,
  stage         ENUM('outline','scene_detail','narration','manual','quiz') NOT NULL,
  version       INT  NOT NULL,
  system_prompt TEXT NOT NULL,
  user_template TEXT NOT NULL,
  output_schema JSON NOT NULL,
  is_active     BOOLEAN NOT NULL DEFAULT FALSE,
  created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_stage_version (stage, version)
);

CREATE TABLE generation_run (
  id            BIGINT AUTO_INCREMENT PRIMARY KEY,
  project_id    BIGINT NOT NULL,
  setting_id    BIGINT NOT NULL,
  source_id     BIGINT NOT NULL,
  status        ENUM('queued','running','done','failed') NOT NULL DEFAULT 'queued',
  current_stage VARCHAR(30),
  llm_model     VARCHAR(80) NOT NULL,
  started_at    DATETIME,
  finished_at   DATETIME,
  error_message TEXT,
  FOREIGN KEY (project_id) REFERENCES project(id) ON DELETE CASCADE,
  FOREIGN KEY (setting_id) REFERENCES generation_setting(id),
  FOREIGN KEY (source_id)  REFERENCES source_document(id)
);

CREATE TABLE agent_step_log (
  id                 BIGINT AUTO_INCREMENT PRIMARY KEY,
  run_id             BIGINT NOT NULL,
  stage              VARCHAR(30) NOT NULL,
  prompt_template_id BIGINT NULL,          -- 코드 단계는 NULL
  attempt            TINYINT NOT NULL DEFAULT 1,
  input_json         JSON,
  output_json        JSON,
  status             ENUM('ok','retry','failed') NOT NULL,
  tokens_in          INT,                  -- Ollama 응답의 prompt_eval_count
  tokens_out         INT,                  -- Ollama 응답의 eval_count
  latency_ms         INT,
  created_at         DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (run_id) REFERENCES generation_run(id) ON DELETE CASCADE,
  FOREIGN KEY (prompt_template_id) REFERENCES prompt_template(id)
);

-- ---------- 영상형 결과 ----------
CREATE TABLE outline (
  id                  BIGINT AUTO_INCREMENT PRIMARY KEY,
  run_id              BIGINT NOT NULL,
  project_id          BIGINT NOT NULL,
  title               VARCHAR(200) NOT NULL,
  summary             TEXT NOT NULL,
  learning_objectives JSON NOT NULL,
  is_current          BOOLEAN NOT NULL DEFAULT TRUE,
  created_at          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (run_id)     REFERENCES generation_run(id) ON DELETE CASCADE,
  FOREIGN KEY (project_id) REFERENCES project(id) ON DELETE CASCADE
);

CREATE TABLE scene (
  id                 BIGINT AUTO_INCREMENT PRIMARY KEY,
  outline_id         BIGINT NOT NULL,
  seq                INT NOT NULL,
  title              VARCHAR(200) NOT NULL,
  key_point          VARCHAR(500) NOT NULL,
  source_paragraphs  JSON NOT NULL,        -- ["p3","p4"] 분할 근거
  screen_description TEXT,
  visual_suggestion  TEXT,
  on_screen_text     VARCHAR(300),
  duration_sec       INT NOT NULL,
  char_budget        INT NOT NULL,
  edited_fields      JSON,                 -- 사용자가 고친 필드 이름 목록, 재생성 때 보호
  updated_at         DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  KEY idx_scene_seq (outline_id, seq),     -- 순서 변경 중 충돌을 피하려고 UNIQUE로 두지 않는다
  FOREIGN KEY (outline_id) REFERENCES outline(id) ON DELETE CASCADE
);

CREATE TABLE narration (
  id               BIGINT AUTO_INCREMENT PRIMARY KEY,
  scene_id         BIGINT NOT NULL UNIQUE,
  body             TEXT NOT NULL,
  char_count       INT NOT NULL,
  est_duration_sec DECIMAL(5,1) NOT NULL,
  is_edited        BOOLEAN NOT NULL DEFAULT FALSE,
  updated_at       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  FOREIGN KEY (scene_id) REFERENCES scene(id) ON DELETE CASCADE
);

CREATE TABLE subtitle_cue (
  id           BIGINT AUTO_INCREMENT PRIMARY KEY,
  narration_id BIGINT NOT NULL,
  seq          INT NOT NULL,
  start_ms     INT NOT NULL,               -- 장면 시작 기준, SRT로 내보낼 때 누적한다
  end_ms       INT NOT NULL,
  body         VARCHAR(100) NOT NULL,      -- 줄바꿈 포함 최대 2줄
  CHECK (end_ms > start_ms),
  FOREIGN KEY (narration_id) REFERENCES narration(id) ON DELETE CASCADE
);

CREATE TABLE quiz_item (
  id           BIGINT AUTO_INCREMENT PRIMARY KEY,
  outline_id   BIGINT NOT NULL,
  scene_id     BIGINT NULL,
  question     VARCHAR(500) NOT NULL,
  choices      JSON NOT NULL,
  answer_index TINYINT NOT NULL,
  explanation  TEXT,
  FOREIGN KEY (outline_id) REFERENCES outline(id) ON DELETE CASCADE,
  FOREIGN KEY (scene_id)   REFERENCES scene(id) ON DELETE SET NULL
);

-- ---------- 매뉴얼형 결과 ----------
CREATE TABLE manual (
  id          BIGINT AUTO_INCREMENT PRIMARY KEY,
  run_id      BIGINT NOT NULL,
  project_id  BIGINT NOT NULL,
  audience    VARCHAR(100) NOT NULL,
  difficulty  ENUM('beginner','intermediate','advanced') NOT NULL,
  title       VARCHAR(200) NOT NULL,
  intro       TEXT,
  is_current  BOOLEAN NOT NULL DEFAULT TRUE,
  created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (run_id)     REFERENCES generation_run(id) ON DELETE CASCADE,
  FOREIGN KEY (project_id) REFERENCES project(id) ON DELETE CASCADE
);

CREATE TABLE manual_step (
  id                BIGINT AUTO_INCREMENT PRIMARY KEY,
  manual_id         BIGINT NOT NULL,
  seq               INT NOT NULL,
  title             VARCHAR(200) NOT NULL,
  instruction       TEXT NOT NULL,
  tip               TEXT,
  source_paragraphs JSON NOT NULL,         -- 근거 문단, 검수 C08의 수치 대조에 쓴다
  edited_fields     JSON,
  FOREIGN KEY (manual_id) REFERENCES manual(id) ON DELETE CASCADE
);

CREATE TABLE caution (
  id         BIGINT AUTO_INCREMENT PRIMARY KEY,
  manual_id  BIGINT NULL,
  scene_id   BIGINT NULL,
  severity   ENUM('info','warning','danger') NOT NULL,
  body       VARCHAR(500) NOT NULL,
  source     ENUM('ai','rule','user') NOT NULL,   -- rule: 원고의 경고 문장에서 자동 추가(검수 C10)
  FOREIGN KEY (manual_id) REFERENCES manual(id) ON DELETE CASCADE,
  FOREIGN KEY (scene_id)  REFERENCES scene(id)  ON DELETE CASCADE
);

CREATE TABLE schedule_item (
  id               BIGINT AUTO_INCREMENT PRIMARY KEY,
  manual_id        BIGINT NOT NULL,
  manual_step_id   BIGINT NULL,             -- 이 일정이 수행하는 매뉴얼 단계
  seq              INT NOT NULL,
  title            VARCHAR(200) NOT NULL,
  start_offset_day INT NOT NULL DEFAULT 0,  -- 시작일 기준 며칠째에 시작하는지, 코드가 계산한다
  duration_days    INT NOT NULL DEFAULT 1,  -- LLM이 원고에서 뽑은 소요 기간
  interval_days    INT,                     -- 반복 작업이면 주기, 한 번만 하면 NULL
  note             VARCHAR(500),
  source           ENUM('ai','user') NOT NULL,
  CHECK (duration_days >= 1),
  FOREIGN KEY (manual_id)      REFERENCES manual(id) ON DELETE CASCADE,
  FOREIGN KEY (manual_step_id) REFERENCES manual_step(id) ON DELETE SET NULL
);

-- ---------- 검수와 수정 이력 ----------
CREATE TABLE review_check (
  id          BIGINT AUTO_INCREMENT PRIMARY KEY,
  run_id      BIGINT NOT NULL,
  check_code  VARCHAR(10) NOT NULL,         -- C01~C12, H01~H03
  target_type VARCHAR(30),                  -- scene, narration, manual 등
  target_id   BIGINT,
  result      ENUM('pass','warn','fail','unchecked') NOT NULL,
  message     VARCHAR(500),
  checked_by  BIGINT NULL,                  -- 사람 확인 항목의 확인자
  checked_at  DATETIME,
  FOREIGN KEY (run_id)     REFERENCES generation_run(id) ON DELETE CASCADE,
  FOREIGN KEY (checked_by) REFERENCES app_user(id)
);

CREATE TABLE revision (
  id           BIGINT AUTO_INCREMENT PRIMARY KEY,
  entity_type  VARCHAR(30) NOT NULL,        -- scene, narration, manual_step, schedule_item 등
  entity_id    BIGINT NOT NULL,
  field_name   VARCHAR(50) NOT NULL,
  before_value MEDIUMTEXT,
  after_value  MEDIUMTEXT,
  user_id      BIGINT NOT NULL,
  created_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY idx_entity (entity_type, entity_id),
  FOREIGN KEY (user_id) REFERENCES app_user(id)
);

-- ---------- 수정 요청 에이전트(설계서 13절) ----------
CREATE TABLE edit_request (
  id           BIGINT AUTO_INCREMENT PRIMARY KEY,
  project_id   BIGINT NOT NULL,
  user_id      BIGINT NOT NULL,
  request_text VARCHAR(1000) NOT NULL,      -- 사용자가 입력한 수정 요청 원문
  status       ENUM('running','proposed','refused','limit','failed','done') NOT NULL DEFAULT 'running',
  tool_calls   TINYINT NOT NULL DEFAULT 0,  -- 도구 호출 수, 최대 8회
  summary      TEXT,                        -- 에이전트가 끝에 남긴 작업 요약
  llm_model    VARCHAR(80) NOT NULL,
  created_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  finished_at  DATETIME,
  FOREIGN KEY (project_id) REFERENCES project(id) ON DELETE CASCADE,
  FOREIGN KEY (user_id)    REFERENCES app_user(id)
);

CREATE TABLE agent_action (
  id              BIGINT AUTO_INCREMENT PRIMARY KEY,
  edit_request_id BIGINT NOT NULL,
  seq             TINYINT NOT NULL,          -- 몇 번째 도구 호출인지
  tool_name       VARCHAR(50) NOT NULL,
  arguments       JSON NOT NULL,             -- LLM이 넘긴 도구 인자
  result_summary  TEXT,                      -- LLM에게 돌려준 결과의 앞부분
  status          ENUM('ok','error','blocked') NOT NULL,  -- blocked: 가드레일이 막은 호출
  latency_ms      INT,
  created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (edit_request_id) REFERENCES edit_request(id) ON DELETE CASCADE
);

CREATE TABLE change_proposal (
  id              BIGINT AUTO_INCREMENT PRIMARY KEY,
  edit_request_id BIGINT NOT NULL,
  target_type     ENUM('scene','narration','manual_step') NOT NULL,
  target_id       BIGINT NOT NULL,
  field_name      VARCHAR(50) NOT NULL,
  before_value    MEDIUMTEXT,
  after_value     MEDIUMTEXT NOT NULL,
  reason          VARCHAR(500),              -- 에이전트가 제시한 수정 이유
  user_edited     BOOLEAN NOT NULL DEFAULT FALSE,  -- 사용자가 직접 고친 필드인지(경고 표시용)
  status          ENUM('pending','accepted','rejected') NOT NULL DEFAULT 'pending',
  decided_by      BIGINT NULL,
  decided_at      DATETIME,
  FOREIGN KEY (edit_request_id) REFERENCES edit_request(id) ON DELETE CASCADE,
  FOREIGN KEY (decided_by)      REFERENCES app_user(id)
);
