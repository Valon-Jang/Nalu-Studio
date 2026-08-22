# S01 — 공통 계약과 결정적 테스트 하네스

## 권장 모델

- GPT-5.6 Terra
- Reasoning: Standard

## 이번 세션의 유일한 목표

production 동작을 바꾸지 않고, 이후 validator·bank·ranker가 공유할 데이터 계약, 설정, hashing, capability detection과 mock 기반 테스트 하네스를 만든다.

## 필수 입력

- `docs/luna_quality/baseline/S00_REPO_AUDIT.md`
- `docs/luna_quality/baseline/BASELINE_MANIFEST.json`
- `.codex/reports/S00_REPORT.md`

## 구현 범위

권장 파일:

```text
scripts/luna_quality/__init__.py
scripts/luna_quality/contracts.py
scripts/luna_quality/config.py
scripts/luna_quality/hashing.py
scripts/luna_quality/capability.py
tests/luna_quality/unit/
tests/luna_quality/fixtures/
docs/luna_quality/contracts/
```

필수 타입:

- `TakeIdentity`
- `ValidationStatus`
- `ValidationResult`
- `TakeEvaluation`
- `SourceHashManifest`
- `CapabilityStatus`

필수 원칙:

- JSON serialization round-trip
- schema version 포함
- path는 가능한 한 repo-relative
- pass/fail/unknown/not_run 구분
- optional dependency 미설치 시 import failure 금지
- validator 결과가 예외를 숨기지 않음
- 실제 Chatterbox·WhisperX·SpeechBrain·MOS 모델을 unit test에서 로드하지 않음

## 금지 사항

- `scripts/luna_narration_pipeline_v1.py` 수정 금지
- Candidate B 또는 prosody target 수정 금지
- validator 로직 선행 구현 금지
- DB 또는 ranker 구현 금지
- production entry point 추가 금지

## 테스트

최소:

- dataclass/schema serialization
- invalid status rejection
- hash deterministic behavior
- missing optional dependency capability result
- source path normalization
- Windows path와 UTF-8 text fixture

## 완료 기준

- S02~S10이 재사용할 안정된 계약 존재
- unit tests가 대형 모델 없이 통과
- dependency 추가가 필요하면 이유와 optional 여부 문서화
- 기존 production baseline 명령 결과에 영향 없음

## 종료

보고서 작성·커밋·clean worktree 후 완료요청을 만든다.

```bash
python tools/stage_gate.py request-completion \
  --stage S01 \
  --report .codex/reports/S01_REPORT.md \
  --test "<unit test command>=PASS"
```

다음 단계 구현 금지.

```text
STAGE_COMPLETE_AWAITING_USER_APPROVAL
```
