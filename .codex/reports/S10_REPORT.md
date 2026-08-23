# S10 Production Integration Report

## 결과

S08의 검증된 shadow orchestrator와 conditionals cache를 production entry
point에 기본 비활성 feature flag로 연결했다. 모든 flag가 `off`인 기존
실행은 integration module을 import하지 않으며 Candidate B, 생성 파라미터,
take cache, pin, beam, pause, 출력 파일명과 production report schema를
그대로 유지한다.

`shadow`는 production `OUTDIR`을 읽기 전용으로 평가하고 별도의 sibling
report directory에만 기록한다. `select`는 실제 ranker·speaker calibration·
사용자 승인 manifest의 정확한 hash와 validator pass/coverage/confidence를
모두 충족할 때만 제안하며, production 측에서 pin·기존 take gate·block
median·phrase reset을 다시 검사한다. 조건 하나라도 실패하면 블록 전체가
기존 selector로 복귀한다.

S05/S07에는 실제 production calibration/ranker 근거가 없으므로 production
승인 manifest를 만들거나 select를 활성화하지 않았다. S09에도 실제 생성
오디오가 없으므로 hybrid는 `experiment` 요청을 진단에 기록할 뿐 production
경로로 승격하지 않는다.

## 구현 내용

### Production entry point

- `quality off|shadow|select`
- `cache off|on`
- `asr off|on`
- `speaker off|on`
- `mos off|on`
- `ranker off|shadow|select`
- `hybrid off|experiment`
- 모든 flag 기본값 `off`; 모두 기본값이면 integration import와 report write 없음
- integration 설정 오류, session 생성 오류, validator/model 오류는 기존 selector
  유지 및 별도 fallback report
- completed block report가 있으면 기존 checkpoint skip 동작 유지
- Candidate B conditionals cache hit일 때만 `audio_prompt_path=None`; cache miss,
  손상, fingerprint mismatch, deserialize 오류는 기존 Candidate B prompt 경로 사용
- shadow/selection 평가는 take 생성과 기존 re-gate 뒤, beam assembly 전에 수행
- production 선택 직전 pin, take `ok`, metrics, block median, reset gate 재검사
- 기존 production block/pipeline report 필드 및 `_luna.wav` 이름 유지

### Select fail-closed 계약

- `quality=select`와 `ranker=select` 동시 요구
- MOS/hybrid production select 금지
- ranker schema/config와 calibration artifact 검증
- calibration은 `calibrated_candidate`, finite cosine threshold `[-1, 1]` 요구
- approval schema `luna-production-select-approval/1`
- `approved_by=USER`, production select boolean, ranker/calibration/config SHA-256 일치
- audio sanity와 existing prosody gate를 최소 승인 validator로 요구
- 활성화한 ASR/speaker validator도 approval scope와 실제 `pass` 요구
- `unknown`/`not_run`은 hard fail을 보상하지 않으며 select survivor가 될 수 없음
- phrase별 최소 2 eligible survivor, 승인 feature coverage/confidence 요구
- 모든 unpinned phrase가 동시에 조건을 충족하지 않으면 블록 전체 fallback
- 기존 pin은 항상 우선

### Cache와 optional dependency

- Candidate B 고정 hash와 V3 source/T3/S3Gen/VE/tokenizer fingerprint를 manifest에 기록
- manifest 없이 신뢰할 수 없는 artifact가 있으면 overwrite하지 않고 fallback
- exact manifest hit만 conditionals 재사용
- WhisperX ASR/alignment model은 explicit use에서 process당 한 번 lazy load
- speaker similarity는 calibrated threshold 이상 `pass`, 미만 `fail`, calibration
  부족은 `unknown`
- MOS adapter는 검증 범위에 없으므로 `on`이어도 `not_run` 진단이며 select 불가

### 보고와 운영 문서

- session/block quality report atomic write
- 한글 block ID는 filesystem-safe prefix와 SHA-256 suffix로 충돌 방지
- report path가 production `OUTDIR` 내부이면 거부하고 안전한 sibling fallback 사용
- PowerShell flag 예시, select 조건, cache invalidation, rollback 절차 문서화

## 검증

### Canonical Luna runtime unit regression

```text
engine\chatterbox-v3\venv\Scripts\python.exe -X utf8 -m unittest discover -s tests\luna_quality\unit -p test_*.py
Ran 96 tests — PASS
```

검증 matrix에는 default off, invalid flag, shadow read-only, restart/atomic report,
UTF-8 경로, missing/bad ranker, missing approval, exact hash approval, hard validator
failure, empty eligible set, MOS/hybrid select 차단, pin 우선, bad take, block median,
phrase reset, conditionals cache create/hit/bad manifest, startup failure report,
block filter, 기존 S02-S09 regression이 포함된다.

### Optional integration tests

```text
engine\chatterbox-v3\venv\Scripts\python.exe -X utf8 -m unittest discover -s tests\luna_quality\integration -p test_*.py
Ran 2 tests — PASS (skipped=2)
```

두 검사는 명시적 실제-model integration opt-in이 없어 skip됐다. 이 단계에서
실제 narration audio 생성이나 외부 model download는 수행하지 않았다.

### Compile, immutable contract, scope

```text
engine\chatterbox-v3\venv\Scripts\python.exe -X utf8 -m py_compile scripts\luna_narration_pipeline_v1.py scripts\luna_quality\production_integration.py
PASS

python -X utf8 tools\stage_gate.py verify
PASS — active_stage=S10, model=GPT-5.6 Sol, reasoning=High

python -X utf8 tools\stage_gate.py check-scope
PASS

git diff --check
PASS
```

## 불변사항과 제한

- Candidate B reference path/hash 변경 없음
- Chatterbox Multilingual V3와 고정 generation parameters 변경 없음
- assets, engine, model pins, 기존 `_luna.wav`, pin, cache/output 변경 없음
- 기존 production audio 생성 또는 재선택 수행 없음
- 실제 ranker/calibration/user approval artifact 없음; select 기본 및 현재 상태 비활성
- S09 hybrid production promotion 없음
- 다음 단계 파일/TODO 선행 구현 없음
