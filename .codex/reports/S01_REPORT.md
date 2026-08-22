# S01 단계 완료 보고서

## 목표와 결과

production이 기본 `off`인 독립 `scripts.luna_quality` 계약·설정·hashing·optional capability detection과 표준 라이브러리 기반 결정적 unit test를 만들었다. production pipeline, Candidate B, prosody target, runtime/cache 및 오디오는 변경하지 않았다.

## 변경 파일

- `scripts/luna_quality/__init__.py`
- `scripts/luna_quality/contracts.py`
- `scripts/luna_quality/config.py`
- `scripts/luna_quality/hashing.py`
- `scripts/luna_quality/capability.py`
- `tests/luna_quality/unit/test_contracts.py`
- `docs/luna_quality/contracts/S01_CONTRACTS.md`

## 계약

- `TakeIdentity`, `ValidationStatus`, `ValidationResult`, `TakeEvaluation`, `SourceHashManifest`, `CapabilityStatus`는 schema version과 JSON-compatible round-trip을 제공한다.
- path는 repository-relative POSIX 형태로 정규화한다.
- 상태는 `pass/fail/unknown/not_run`을 엄격히 구분한다.
- optional dependency 검사는 package import나 모델 load 없이 `find_spec`으로만 판정하고, 미설치는 `not_run`이다.
- SHA-256은 UTF-8 text와 streaming file helper로 결정적으로 계산한다.

## 검증

| 명령 | 결과 |
|---|---|
| `python -X utf8 -m unittest discover -s tests\\luna_quality\\unit -v` | PASS (4 tests) |
| `python -X utf8 tools\\stage_gate.py codex-safe` | PASS |
| `python -X utf8 tools\\stage_gate.py verify` | PASS (local key 없음: signature 미검증은 예상됨) |
| `python -X utf8 tools\\stage_gate.py check-scope` | PASS |
| `git diff --check` | PASS |

## 유지한 불변 조건과 다음 단계 입력

validator, DB, ranker, conditionals cache, production 연결은 구현하지 않았다. S02 이상은 이 versioned contract와 capability 결과를 재사용할 수 있다.

## 완료 판정

- [x] S01 acceptance criteria 충족
- [x] production·audio·runtime·protected asset 미수정
- [x] S01 허용 경로만 수정
- [x] unit tests가 대형 모델 없이 통과
- [x] 다음 단계 코드 미구현
