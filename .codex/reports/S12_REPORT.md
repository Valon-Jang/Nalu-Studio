# S12 FAST Production Integration Report

## 최종 판정

`S12_FAST_PRODUCTION_INTEGRATION`의 승인 범위를 구현하고 검증했다.

- 기본 사용자 인터페이스는 `대사 → Luna WAV + JSON`이다.
- FAST는 기본 모드이며 요청마다 정확히 1 take를 생성한다.
- 상주 워커는 Chatterbox Multilingual V3 모델과 검증된 Candidate B condition을 프로세스 수명 동안 재사용한다.
- PRODUCTION은 동일한 상주 모델로 기존 `synthesize_block` best-of-N 경로와 `ProductionQualitySession`을 호출한다.
- 사용자 청취 승인 전 Quality System은 `shadow`이며 새 selector는 production default가 아니다.
- S11 보고서·릴리스 문서·테스트와 `CLOSED` 이력은 수정하지 않았다.
- 다음 Stage는 개설하거나 시작하지 않았다.

## 구현 결과

### 사용자 인터페이스

새 entry point는 `scripts/luna_voice.py`다.

```text
python scripts/luna_voice.py "대사"
python scripts/luna_voice.py "대사" --mode production
python scripts/luna_voice.py request --input request.json --response response.json
python scripts/luna_voice.py start|status|stop
```

첫 합성 명령은 필요하면 canonical production Python으로 백그라운드 워커를 자동 시작한다. 워커는 `127.0.0.1:18765`에만 bind하며 모든 text/audio 처리는 로컬이다.

### FAST

- `mode`를 생략하면 `fast`다.
- 1 request = 1 `model.generate` 호출 = 1 take다.
- `audio_prompt_path=None`이며 startup에 이미 검증·로드된 Candidate B condition을 사용한다.
- 기존 고정 pronunciation respell을 적용하고 24 kHz PCM16 WAV를 기록한다.
- 빈 text, 잘못된 mode/schema/seed/path 계약은 명시적 error다. 빈 WAV를 성공으로 만들지 않는다.

### Resident model / Candidate B

- canonical Python: `engine/chatterbox-v3/venv/Scripts/python.exe`
- model: `ChatterboxMultilingualTTS.from_pretrained(device="cpu", t3_model="v3")`
- offline Hugging Face cache만 사용한다.
- Candidate B SHA-256을 startup마다 검증한다.
- official `Conditionals.load/save`와 기존 S02 hash manifest를 사용한다.
- 실제 cache key: `191eba963b0e2451046a157c314e8c672b84b484ccbea9401224b070cef6c097`
- 실제 daemon smoke의 model load count: `1`
- 실제 daemon smoke의 Candidate B condition load/prepare count: `1`

### PRODUCTION

- 기존 `scripts/luna_narration_pipeline_v1.py`는 수정하지 않았다.
- 같은 resident model을 기존 `synthesize_block`에 전달한다.
- 기존 phrase splitting, best-of-N, resume cache, pins, take gates, beam assembly, pause, final WAV/report naming을 그대로 쓴다.
- `ProductionQualitySession`은 `quality_mode="shadow"`, `conditionals_cache="on"`으로 연결된다.
- 따라서 quality evidence는 생성하지만 새로운 quality proposal이 production 선택을 바꾸지 않는다.

### 공통 계약

- request schema: `luna-voice-request/1`
- response schema: `luna-voice-response/1`
- 공통 필드: request id, mode, text, WAV path, optional JSON path, seed, block id
- response provenance: engine, Candidate B hash, 고정 synthesis parameters, sample rate, take count, generation time, model/condition reuse counters, quality mode, local-only 표시

## 음성 불변성

다음 고정값을 코드와 실제 응답에서 확인했다.

- engine: Chatterbox Multilingual V3
- voice reference: Candidate B
- Candidate B SHA-256: `30c6d3405f46684af467c7d26ff40a2fb57dd48cc84cd24cf7403d9aa00a2bb9`
- language: `ko`
- exaggeration: `0.5`
- cfg weight: `0.5`
- temperature: `0.72`
- repetition penalty: `1.2`
- min-p: `0.05`
- top-p: `1.0`

보존 SHA-256:

- `assets/voice_ref/B_voiced_spectral_micro_smooth.wav`: `30c6d3405f46684af467c7d26ff40a2fb57dd48cc84cd24cf7403d9aa00a2bb9`
- `assets/voice_ref/LUNA_PROSODY_TARGET.json`: `267e79ec088933c9c43b6584e90bd04b2b4e77eaba3134a669d151c464458bae`
- `scripts/luna_narration_pipeline_v1.py`: `781fd5d74b7b8f427d1ee229e8e9d9d43ec0c145eef8f1abddf296fcc93bc5bf`
- `engine/chatterbox-v3/chatterbox/src/chatterbox/mtl_tts.py`: `96fd2dfbd947d3b617fdada8721264bc6597799e81ebf8e43603f083f72fe433`

## 실제 한국어 결과와 시간

### Real integration

Canonical production venv에서 실제 V3 모델로 다음 두 요청을 한 runtime에서 연속 생성했다.

- `안녕하세요. 공대루나입니다.`
- `기술 이야기를 시작합니다.`

검증 결과:

- 두 WAV 모두 24 kHz이며 44-byte WAV header보다 크고 frame count가 0보다 큼
- 두 JSON 모두 `status=ok`, `take_count=1`
- 두 번째 응답까지 `model_load_count=1`
- 두 번째 응답까지 `condition_prepare_count=1`
- test wall time: `162.243 s` (model startup + 두 실제 CPU 합성 포함)

### Daemon operational smoke

백그라운드 시작 → status → 실제 합성 → WAV/JSON 확인 → stop을 실행했다.

- startup: `26.966 s`
- text: `상주 워커 검증입니다.`
- generation: `33.742 s`
- WAV: `C:\Users\tequi\AppData\Local\Temp\luna_s12_daemon_smoke.wav`
- WAV bytes: `84,524`
- JSON: `C:\Users\tequi\AppData\Local\Temp\luna_s12_daemon_smoke.json`
- sample rate: `24,000`
- `model_load_count=1`, `condition_prepare_count=1`
- 종료 후 status: `not_running`

해석: 저장된 문장을 즉시 재생하는 방식이 아니다. resident/precompute가 반복 setup 비용을 제거하지만 새 문장의 CPU neural synthesis 시간은 남는다.

## 검증

### S12 unit / integration contract

```text
engine\chatterbox-v3\venv\Scripts\python.exe -m unittest tests.luna_quality.unit.test_s12_fast_production_integration -v
PASS — 7 tests
```

검증 항목: FAST default, invalid contract, one-take, fixed parameters, repeated resident reuse, WAV/JSON response, localhost JSON transport, text-only CLI, PRODUCTION dispatch, existing pipeline 호출, shadow-only default.

### 전체 unit

```text
engine\chatterbox-v3\venv\Scripts\python.exe -m unittest discover -s tests/luna_quality/unit -p "test_*.py"
PASS — 103 tests
```

### release regression

```text
engine\chatterbox-v3\venv\Scripts\python.exe -m unittest discover -s tests/luna_quality/regression -p "test_*.py"
PASS — 6 tests
```

### 실제 한국어 FAST

```text
RUN_LUNA_S12_REAL_FAST=1 engine\chatterbox-v3\venv\Scripts\python.exe -m unittest tests.luna_quality.integration.test_s12_resident_korean_fast -v
PASS — 1 test / 2 real WAV requests / 162.243 s
```

### compile

```text
engine\chatterbox-v3\venv\Scripts\python.exe -m compileall -q scripts/luna_quality/voice_runtime scripts/luna_voice.py tests/luna_quality/unit/test_s12_fast_production_integration.py tests/luna_quality/integration/test_s12_resident_korean_fast.py
PASS
```

### Production environment unchanged

작업 전후 read-only 검사:

- `torch==2.6.0+cpu` — PASS
- `torchaudio==2.6.0+cpu` — PASS
- `numpy==1.26.4` — PASS
- `engine/chatterbox-v3/**` git diff 없음 — PASS

비canonical system Python에는 NumPy가 없어 기존 speaker unit 3개가 import error였으며, 이는 지원 런타임이 아니다. 요구된 canonical production venv에서 같은 전체 suite는 PASS했다.

## 변경 파일

- `.codex/stage_plan.json`
- `.codex/stage_state.json`
- `.codex/prompts/S12_FAST_PRODUCTION_INTEGRATION.md`
- `scripts/luna_voice.py`
- `scripts/luna_quality/voice_runtime/__init__.py`
- `scripts/luna_quality/voice_runtime/contract.py`
- `scripts/luna_quality/voice_runtime/conditioner.py`
- `scripts/luna_quality/voice_runtime/runtime.py`
- `scripts/luna_quality/voice_runtime/transport.py`
- `tests/luna_quality/unit/test_s12_fast_production_integration.py`
- `tests/luna_quality/integration/test_s12_resident_korean_fast.py`
- `docs/luna_quality/integration/S12_FAST_PRODUCTION_INTEGRATION.md`
- `.codex/reports/S12_REPORT.md`
- `.codex/completion_requests/S12.json`

## 보존한 사용자 작업

작업 시작 전 존재하던 stage-gate removal 및 기타 사용자 미커밋 변경은 되돌리거나 덮어쓰지 않았다. 이 때문에 사용자 소유 변경까지 임의로 commit하거나 worktree를 강제로 clean하지 않았다. S12 파일과 명시 승인된 plan/state 변경만 추가했다.

## 남은 위험과 default-ON 권고

- FAST를 사용자 인터페이스 기본값으로 사용하는 것은 이번 명시 승인 범위이며 권고한다.
- Quality System의 production selector default-ON은 아직 권고하지 않는다. 현재 PRODUCTION은 shadow만 사용한다.
- 실제 CPU FAST는 짧은 대사도 이번 측정에서 약 34초였다. resident는 startup을 줄이지만 synthesis 자체를 즉시 재생 수준으로 만들지는 않는다.
- worker는 OS 재시작 후 필요 시 다시 시작되며 첫 호출은 startup 비용이 추가된다.
- 매우 긴 단일 FAST text는 한 take model limit와 생성 지연 위험이 있다. 정밀 장문은 PRODUCTION을 사용해야 한다.
- 실제 음색 승인 전에는 생성된 smoke WAV를 사용자가 청취해야 한다.

## Stage 상태

S11은 `CLOSED` 이력으로 보존했다. S12만 `COMPLETE_AWAITING_USER_APPROVAL`로 전환하고 다음 Stage는 시작하지 않는다.
