# S09 — Hybrid Synthesis 격리 실험 완료 보고서

## 결과

현행 phrase 분할, 문장 전체, 의미절 hybrid를 같은 대본·Candidate B·고정 생성 파라미터·완성 대본 후보 수·seed 파생 규칙으로 비교하는 격리형 planner, runner, evaluator를 구현했다. production pipeline, 기존 cache, 확정 오디오, pin, 동결 프로젝트는 변경하지 않았다.

실제 음성 생성은 수행하지 않았다. 기본 명령은 model import/load 없이 dry-run만 하며, 실제 Chatterbox 실행은 `--execute-generation`과 `--acknowledge-isolated-experiment`를 동시에 지정해야만 열린다.

## 구현 내용

### Planner

- `existing_phrase`, `sentence`, `hybrid` 세 segmentation plan을 결정적으로 만든다.
- 모든 모드가 같은 원문을 사용하도록 existing phrase의 공백 제외 합성문과 source text의 완전 일치를 검사한다.
- candidate budget의 단위를 모드별 **완성 대본 후보**로 고정한다.
- 각 완성 후보의 segment generation job과 seed를 결정적으로 파생한다.
- sentence mode에는 ASR + forced alignment 사후 경계 추출을 필수 계획으로 기록한다.
- hybrid mode는 짧고 안전한 문장은 통째로 사용하고, 긴 문장은 의미절/연결어미 경계로 분할한다. 안전한 분할이 불가능하면 existing phrase로 fallback한다.
- `frozen_project: false`를 명시적으로 요구하고 `SPIDER-001`, `SUBSEA-001`을 ID로도 거부한다.

### 실제 runtime 한도와 provenance

- T3 model text cap: 2,048 token, framing 2 token 포함
- 실제 `generate()` speech cap: 1,000 new token
- S3 token rate: 25 token/s
- 마지막 speech token 제거 후 실제 최대 오디오: 약 39.96초
- S09 보수적 예상 segment 한도: 32초
- dry-run: UTF-8 byte 수 + framing 2의 보수적 token 상한
- opt-in integration: 실제 pinned Chatterbox tokenizer + framing 2 재검사 후 overflow 시 생성 없이 실패
- Candidate B 경로/해시와 한도 근거 runtime 파일 SHA-256을 plan에 기록

### Runner와 조립

- output root를 `experiments/luna_quality/<새 디렉터리>`로 강제한다.
- 모든 segment/candidate/metadata/result 경로의 traversal, 중복, 기존 파일 충돌을 검사한다.
- `_luna.wav`, `pins.json` 이름을 거부한다.
- 실제 실행 시 Chatterbox V3 model과 Candidate B conditionals를 stage/run당 한 번만 load한다.
- Candidate B hash와 고정 파라미터가 달라지면 실행을 거부한다.
- 여러 segment는 production의 12ms fade, -20 dBFS RMS, 0.89 peak guard, continuation/forced/final pause 범위를 격리 모듈에서 미러링해 완성 후보로 조립한다. 근거 production 파일 hash를 provenance에 기록하며 production 코드는 import하거나 수정하지 않는다.
- 생성 실패는 빈 오디오로 대체하지 않고 segment/candidate failure로 구조화한다.
- model 기반 후처리 validator는 실행되지 않았을 때 성공으로 간주하지 않고 `not_run`으로 남긴다.

### Evaluator

- 모드별 content accuracy, abnormal silence/repetition, hallucination, speaker similarity/drift, existing prosody gate, phrase transition, sentence boundary alignment, duration, generation/assembly timing, failure rate를 분리 집계한다.
- hard-gate failure 및 hallucination/repetition/speaker drift signal을 mode failure로 센다.
- 모드별 완성 후보 수 공정성 검사를 기록한다.
- mode와 원본 candidate ID를 감춘 blind listening manifest와 별도 answer key를 생성한다.
- `luna-hybrid-human-preference/1` import 필드를 명시한다.
- 분석 JSON/CSV, timing JSON, blind manifest/key, evidence report를 생성한다.
- promotion recommendation과 자동 promotion을 명시적으로 금지한다.

## Fixture 증거

- `experiments/luna_quality/s09_fixture_plan/segmentation_plan.json`
- mode별 job manifest 3개
- `dry_run_report.json`: `status=pass`, collision 0, model load false, audio generation false
- synthetic metric fixture 분석에서 세 모드가 분리되며, 의도적으로 넣은 hybrid repetition/content hard-gate failure가 hybrid mode failure로만 집계됨
- blind public manifest에는 mode 및 candidate ID가 없고 answer key는 별도 파일임
- fixture는 evaluator 검증용 synthetic metric이며 실제 음성 또는 실제 우열 증거가 아님

## 검증

### S09 planner/runner/evaluator unit test

```text
python -m unittest tests.luna_quality.unit.test_hybrid_synthesis -v
Ran 16 tests — PASS
```

검증 항목에는 동일 candidate budget/seed, 세 모드 원문 동일성, semantic split/fallback, 실제 한도 provenance, 동결 프로젝트 거부, sentence forced-alignment 계획, 경로 격리, 충돌 탐지, 기존 cache byte 보존, 기본 CLI dry-run, actual generation 이중 opt-in, 단일 generator load, 모드별 validator bundle, failure 집계, blind manifest, 분석 산출물이 포함된다.

### Canonical Luna runtime 전체 unit regression

```text
engine\chatterbox-v3\venv\Scripts\python.exe -m unittest \
  tests.luna_quality.unit.test_contracts \
  tests.luna_quality.unit.test_audio_sanity \
  tests.luna_quality.unit.test_content_asr \
  tests.luna_quality.unit.test_speaker_identity \
  tests.luna_quality.unit.test_conditionals_cache \
  tests.luna_quality.unit.test_prosody_bank \
  tests.luna_quality.unit.test_preference_ranker \
  tests.luna_quality.unit.test_shadow_orchestrator \
  tests.luna_quality.unit.test_hybrid_synthesis -v
Ran 85 tests — PASS
```

Host의 32-bit Python에는 `numpy`가 없어 기존 speaker identity 테스트 3개가 dependency error를 냈다. 저장소 계약의 canonical Chatterbox venv로 같은 전체 suite를 재실행해 85개 모두 통과했다. S09 전용 테스트는 host Python에서도 16개 모두 통과한다.

### Dry-run 및 범위

```text
python -X utf8 -m scripts.luna_quality.cli hybrid-run --plan experiments\luna_quality\s09_fixture_plan\segmentation_plan.json
PASS — collision=0, model_loaded=false, audio_generated=false

python -X utf8 tools\stage_gate.py check-scope
PASS

git diff --check
PASS
```

## 미실행 항목

- 실제 Chatterbox 오디오 생성: 사용자 명시적 integration opt-in이 필요하므로 실행하지 않음
- WhisperX/forced alignment, speaker model, 실제 prosody/transition post-validation: 실제 생성 오디오가 없으므로 `not_run`
- 실제 청취 선호 수집: manifest/import 계약만 제공

## 생산 영향 확인

- `scripts/luna_narration_pipeline_v1.py`: 변경 없음
- Candidate B 및 prosody target: 변경 없음
- 기존 `*_luna.wav`, `pins.json`, project cache/output: 변경 없음
- production 선택: 변경 없음
- 자동 promotion: 수행되지 않으며 S09에서 금지
