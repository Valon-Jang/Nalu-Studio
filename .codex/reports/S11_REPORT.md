# S11 Release Audit Report

## 결과

최종 판정은 `SHADOW_ONLY_APPROVED`다.

기존 Luna production selector와 모든 품질 기능이 기본 `off`인 실행은
릴리스 회귀 검사를 통과했다. 별도 경로에 읽기 전용 진단 결과만 기록하는
`shadow` 운용도 승인한다. 다만 실제 Luna 선호 데이터, ranker, speaker
calibration, 고정된 optional model 설치, 전체 third-party notice와 Candidate B
재배포 권한이 없으므로 production `select` 및 공개 배포는 승인하지 않는다.

## 산출물

- `docs/luna_quality/release/S11_RELEASE_AUDIT.md`
- `docs/luna_quality/release/RELEASE_CHECKLIST.md`
- `docs/luna_quality/release/ROLLBACK.md`
- `docs/luna_quality/release/LUNA_SKILL_CHANGE_PROPOSAL.md`
- `tests/luna_quality/regression/test_release_baseline.py`
- `tests/luna_quality/integration/test_chatterbox_model_load.py`

실제 `.agents/skills/luna-narration/SKILL.md`는 수정하지 않았다. 제안서는
별도 사용자 승인 후 검토할 문서일 뿐이다.

## 감사 결론

### 코드와 아키텍처

- production entry point는 `scripts/luna_narration_pipeline_v1.py` 하나로 유지된다.
- Chatterbox Multilingual V3, Candidate B, 고정 생성 파라미터, take/pin 우선순위,
  pause, output name과 checkpoint/resume 계약은 바뀌지 않았다.
- 일곱 integration flag는 모두 기본 `off`다.
- optional dependency는 lazy 경계 안에 있고 미설치/예외/`unknown`/`not_run`은
  성공으로 승격되지 않는다.
- hard gate 실패는 ranker/MOS 점수로 보상되지 않는다.
- 실제 hybrid runner의 deterministic test는 multi-mode 실행에서 generator를
  한 번만 생성하는 계약을 확인한다.

### 데이터와 평가

- Candidate B, 6개 model checkpoint, 동결된 최종 WAV 17개, timing JSON 2개의
  크기/해시가 S00 baseline과 일치한다.
- completed block 재시작은 기존 block report를 byte-for-byte 보존하고 새
  block audio나 quality report를 만들지 않는다.
- S07 실제 상태는 `insufficient_data`; production ranker/select approval은 없다.
- S05 real speaker calibration, S09 real hybrid/blind-listening evidence도 없다.
- 새 narration audio, pin, Prosody Bank, ranker/calibration artifact를 만들지 않았다.

### 실제 모델 검사

- Windows CPU에서 고정 V3 모델이 24 kHz로 로드됐다. 관측 시간은 68.130초이며
  오디오는 생성하지 않았다.
- 실제 Candidate B conditionals save/load round-trip이 통과했다. 관측 시간은
  52.053초이며 임시 conditionals artifact는 테스트가 제거했다.
- WhisperX/SpeechBrain/SpeechMOS는 현재 canonical venv에 없고 WhisperX Korean
  transcription/alignment integration은 실행하지 않았다.
- V3 smoke test 중 `spacy-pkuseg`가 Hugging Face offline 환경 변수와 별개로
  public tokenizer data를 `C:\Users\tequi\.pkuseg`에 내려받았다. Luna audio는
  아니지만 cold-start offline 재현성 위험이다. 캐시는 저장소 밖에 남아 있으며
  정확한 확인·삭제 절차를 `ROLLBACK.md`에 기록했다.

### 라이선스

- Chatterbox code/model, WhisperX/alignment, SpeechBrain/speaker model,
  SpeechMOS/UTMOS22, scikit-learn의 upstream 선언과 현재 포함 여부를 감사했다.
- 현재 로컬 core는 확인했지만 optional package/model revision이 고정되지 않았고
  배포용 LICENSE/NOTICE bundle도 없다.
- Candidate B 재배포 권한 문서가 저장소에 없으므로 private reference를 공개
  bundle에 포함하면 안 된다.
- 상세 출처와 조건은 `docs/luna_quality/release/S11_RELEASE_AUDIT.md`에 기록했다.
  이는 engineering inventory이며 법률 자문이 아니다.

## 검증

### Compile

```text
engine\chatterbox-v3\venv\Scripts\python.exe -X utf8 -m compileall -q scripts\luna_quality scripts\luna_narration_pipeline_v1.py tests\luna_quality
PASS
```

### 전체 unit regression

```text
engine\chatterbox-v3\venv\Scripts\python.exe -X utf8 -m unittest discover -s tests\luna_quality\unit -p test_*.py -v
Ran 96 tests — PASS
```

### S11 release baseline regression

```text
engine\chatterbox-v3\venv\Scripts\python.exe -X utf8 -m unittest discover -s tests\luna_quality\regression -p test_*.py -v
Ran 6 tests — PASS
```

### Optional integration discovery

```text
engine\chatterbox-v3\venv\Scripts\python.exe -X utf8 -m unittest discover -s tests\luna_quality\integration -p test_*.py -v
Ran 3 tests — PASS (skipped=3 by explicit opt-in guards)
```

기본 discovery의 skip을 실제 실행으로 표기하지 않는다. 별도 명시적 실행 결과는
다음과 같다.

```text
set RUN_LUNA_MODEL_LOAD_SMOKE=1&& engine\chatterbox-v3\venv\Scripts\python.exe -X utf8 -m unittest tests.luna_quality.integration.test_chatterbox_model_load -v
Ran 1 test — PASS

set PKUSEG_HOME=C:\Users\tequi\.pkuseg&& set RUN_LUNA_CONDITIONALS_INTEGRATION=1&& engine\chatterbox-v3\venv\Scripts\python.exe -X utf8 -m unittest tests.luna_quality.integration.test_conditionals_cache_integration -v
Ran 1 test — PASS

WhisperX Korean integration — NOT RUN
```

### Dependency, immutable contract and scope

```text
engine\chatterbox-v3\venv\Scripts\python.exe -X utf8 -m pip check
No broken requirements found — PASS

python -X utf8 tools\stage_gate.py verify
PASS

python -X utf8 tools\stage_gate.py check-scope
PASS

git diff --check
PASS
```

## 미해결 위험과 승인 경계

production `select` 전에는 다음이 모두 필요하다.

1. S07 최소 요건을 충족하는 실제 pin/preference history와 grouped ranker 평가.
2. 승인/거절 Luna 및 Candidate B로 만든 실제 speaker calibration.
3. WhisperX, Korean alignment, SpeechBrain의 exact package/model revision과
   non-private integration fixture.
4. cold-start tokenizer download 해소, 재현 가능한 dependency lock,
   third-party LICENSE/NOTICE bundle.
5. 실제 hybrid audio와 blind listening evidence.
6. 위 evidence와 exact hashes를 검토한 USER select approval manifest.

그 전까지 `LUNA_QUALITY_MODE`는 `off` 또는 `shadow`만 사용하고
`LUNA_PREFERENCE_RANKER=select`는 사용하지 않는다.

## 불변사항

- Candidate B path/hash 및 prosody target 변경 없음.
- engine, model pin, asset, 기존 production audio 변경 없음.
- threshold 조정, 실패 test 삭제/skip 전환, 신규 기능 추가 없음.
- 다음 단계 파일이나 TODO 생성 없음.
