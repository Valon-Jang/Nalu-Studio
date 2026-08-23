# S08 단계 완료 보고서

## 1. 목표와 완료 판정

기존 Luna output directory를 읽기만 하여 take별 validator 결과, hard-gate
survivor, shadow ranking, 실제 선택 비교를 JSON report로 내는 독립 Shadow
Quality Orchestrator를 구현했다.

- 단계 시작 commit: `34c2432c35acd7e2336958b540cc79fecba6de13`
- production entry point 수정: 없음
- 기존 WAV/take JSON/block report/pins 변경: 없음
- select mode 구현: 없음
- S08 fixture shadow run: PASS

## 2. 구현 내용

### 읽기 전용 입출력 경계

- `P##_t#.json`과 sibling WAV, `phrases.json`, `*_report.json`, `*_pins.json`을
  discovery만 한다.
- `*_pins.json`이 있으면 block report보다 우선해 actual selection으로 기록한다.
- report 출력 경로가 입력 `--outdir` 내부이면 명시적으로 거부한다.
- input directory 전체 SHA-256 manifest를 실행 전후로 비교해
  `read_only_verified`를 기록한다.
- 모든 report에 `production_selection_changed: false`를 기록한다.

### validator와 gate 정책

처리 순서는 audio sanity → content/ASR → speaker → persisted existing prosody
gate → optional MOS → survivor → ranker/fallback → actual selection comparison이다.

- 기존 take JSON의 `ok`/`why`를 `existing_prosody_gate` 구조화 결과로 import하며
  재측정·재게이트하지 않는다.
- hard-gate `fail`만 후보를 survivor set에서 제외한다.
- `unknown`/`not_run`은 report에 그대로 보존하며 `pass`로 바꾸지 않는다.
- validator 예외는 `unknown`과 `validator_exception:<type>`로 기록하고 다른
  take/validator 실행을 중단시키지 않는다.
- ASR/speaker/MOS가 설정되지 않은 기본 CLI는 각각 `not_run`이다. `--enable-asr`
  때만 WhisperX를 명시적으로 호출한다.

### ranking과 실제 선택 비교

- 유효한 S07 artifact가 있으면 hard-gate survivor에 preference ranker를 적용한다.
- artifact/schema/model mismatch 또는 artifact 미지정이면 disabled reason을 기록하고
  persisted duration·syllable count·slope·pitch level·final curl 기반의 투명한
  shadow baseline score로만 순위를 낸다.
- shadow top-1/top-3, actual selected take, agreement, 그리고 불일치 시
  hard-gate/feature/rank-score delta를 모두 report한다.
- S07의 실제 ranker artifact는 `insufficient_data`이므로 이 단계에서 자동 모델
  활성화나 production selection 변경은 발생하지 않는다.

### provenance와 CLI

- report는 input source-manifest hash, take JSON hash, validator config hash,
  ranker artifact hash/model id를 기록한다.
- CLI:

```powershell
python -X utf8 -m scripts.luna_quality.cli shadow-evaluate `
  --outdir <EXISTING_OUTDIR> `
  --report <NEW_REPORT_OUTSIDE_OUTDIR>
```

세부 계약은 `docs/luna_quality/orchestrator/S08_SHADOW_ORCHESTRATOR.md`에
기록했다.

## 3. fixture shadow 결과

결정적 fixture는 두 take와 persisted block selection을 사용했다.

- 기본 ASR/speaker/MOS `not_run` 상태에서도 해당 상태를 숨기지 않고 baseline
  report를 생성했다.
- valid ranker artifact, missing ranker, artifact schema mismatch를 각각 검증했다.
- hard audio failure 한 건은 해당 take만 survivor set에서 제외했고 실행 전체는
  계속됐다.
- content validator 예외는 `unknown`으로 보고됐고 shadow top-1 report는 생성됐다.
- pin이 존재하면 block report보다 우선하며 agreement/disagreement가 계산됐다.
- take 순서는 filename/take number 기준 결정적이며 input file byte snapshot은 실행
  전후 동일했다.

이 fixture는 오케스트레이션 계약 검증용이며 실제 Luna 후보 선호 성능이나
production promotion 근거가 아니다.

## 4. 변경 파일

- `scripts/luna_quality/orchestrator/__init__.py`
- `scripts/luna_quality/orchestrator/engine.py`
- `scripts/luna_quality/orchestrator/policy.py`
- `scripts/luna_quality/orchestrator/report.py`
- `scripts/luna_quality/cli.py`
- `tests/luna_quality/unit/test_shadow_orchestrator.py`
- `docs/luna_quality/orchestrator/S08_SHADOW_ORCHESTRATOR.md`
- `.codex/reports/S08_REPORT.md`

## 5. 테스트

| 명령 | 결과 |
|---|---|
| `engine\chatterbox-v3\venv\Scripts\python.exe -X utf8 -m unittest tests.luna_quality.unit.test_shadow_orchestrator -v` | PASS, 10 tests |
| `python -X utf8 -m scripts.luna_quality.cli shadow-evaluate --help` | PASS |
| `engine\chatterbox-v3\venv\Scripts\python.exe -X utf8 -m unittest discover -s tests\luna_quality\unit -p test_*.py -v` | PASS, 69 tests |
| `python -X utf8 -m compileall -q scripts\luna_quality\orchestrator scripts\luna_quality\cli.py tests\luna_quality\unit\test_shadow_orchestrator.py` | PASS |
| `python -X utf8 tools\stage_gate.py check-scope` | PASS |
| `git diff --check` | PASS |

## 6. 제한과 안전성

- CLI default는 optional model을 로드하지 않으므로 ASR/speaker/MOS는 `not_run`이다.
  이 상태가 성공을 뜻하지 않는다는 사실이 report에 보존된다.
- 실제 historical pin과 ranker training data가 부족한 상태는 S07의
  `insufficient_data` artifact로 계속 표현된다.
- S08은 기존 selection을 비교 대상으로만 읽으며, pin write/take regeneration/
  candidate deletion/production pipeline 변경을 수행하지 않는다.

## 7. 완료 판정

- [x] 기존 output directory read-only
- [x] 새 shadow report만 생성
- [x] validator fail/unknown/not_run 구분 및 오류 격리
- [x] hard-gate 비보상 정책
- [x] ranker missing/mismatch fallback
- [x] actual selection agreement/disagreement 비교
- [x] deterministic ordering 및 input immutability 검증
- [x] S08 범위 검사와 전체 unit regression 통과
