# S06 — Prosody Bank Schema와 기존 이력 수집

## 권장 모델

- GPT-5.6 Sol
- Reasoning: High

## 이번 세션의 유일한 목표

기존 take JSON, report, `pins.json`, prosody target을 수정하지 않고 읽어 SQLite Prosody Bank로 idempotent ingest하는 기능을 만든다.

## 구현 범위

```text
scripts/luna_quality/prosody_bank/schema.py
scripts/luna_quality/prosody_bank/sqlite_store.py
scripts/luna_quality/prosody_bank/ingest.py
scripts/luna_quality/prosody_bank/queries.py
```

## 필수 의미 구분

- `selected`: 사람이 명시적으로 pin한 take
- `not_selected`: 후보였으나 선택되지 않음
- `rejected`: 명시적 반려 근거가 존재
- `unknown`: 선택 의미를 판단할 근거 없음

비선택을 자동 반려로 바꾸지 않는다.

## 필수 provenance

- source path
- source SHA256
- source modified time은 참고값
- parser version
- schema version
- project/block/phrase/take ID
- ingest run ID
- source format

## SQLite 요구사항

- migration table
- foreign key 활성화
- transaction
- bulk insert
- 동일 source hash 재실행 idempotent
- source가 바뀌면 revision 추가
- audio binary 저장 금지
- repo-relative path 우선
- query index

## 기존 데이터 파서

S00에서 실제 확인한 포맷만 지원한다. 필드가 없으면 null/unknown으로 저장한다. 일반 지식으로 임의 보완하지 않는다.

## 테스트

- 신규 DB 생성
- 동일 ingest 두 번
- source 수정 후 revision
- malformed JSON 격리
- pins 선택 이벤트
- 비선택/반려 구분
- transaction rollback
- schema migration dry run

## 금지 사항

- 기존 `pins.json` 수정 금지
- `LUNA_PROSODY_TARGET.json` 수정 금지
- WAV 복사 금지
- ranker 학습 금지
- production 연결 금지

## 완료 기준

- fixture dataset ingest 성공
- idempotency 입증
- provenance query 가능
- 선택 이력과 take feature join 가능
- DB schema 문서화

## 종료

```bash
python tools/stage_gate.py request-completion \
  --stage S06 \
  --report .codex/reports/S06_REPORT.md \
  --test "<prosody bank tests>=PASS"
```

```text
STAGE_COMPLETE_AWAITING_USER_APPROVAL
```
