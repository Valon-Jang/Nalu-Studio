# Luna Validator + Preference Ranker — Codex Operating Contract

이 저장소에서 Codex가 수행하는 Luna 음성 품질 개선 작업은 이 문서와 `.codex/stage_plan.json`을 최우선으로 따른다.

## 0. 작업 시작 전 필수 읽기

작업을 시작하기 전에 반드시 아래 파일을 순서대로 전부 읽는다.

1. `.agents/skills/luna-narration/SKILL.md`
2. `docs/LUNA_VALIDATOR_RANKER_BUILD_SPEC.md`
3. `docs/STAGE_MODEL_MATRIX.md`
4. `.codex/stage_plan.json`
5. `.codex/stage_state.json`
6. 현재 단계 프롬프트 `.codex/prompts/<ACTIVE_STAGE>_*.md`

그 다음 반드시 아래 명령을 실행한다.

```bash
python tools/stage_gate.py codex-safe
python tools/stage_gate.py verify
python tools/stage_gate.py status
python tools/stage_gate.py check-scope
```

`active_stage`가 현재 사용자가 요청한 단계와 다르면 즉시 중단한다.

## 1. 절대 불변 규칙

- Luna의 production 음성 엔진은 **Chatterbox Multilingual V3 + Candidate B**다.
- 공대루나 런타임은 `engine/chatterbox-v3`, Python은 `engine/chatterbox-v3/venv/Scripts/python.exe`를 사용한다.
- Candidate B는 `assets/voice_ref/B_voiced_spectral_micro_smooth.wav`, prosody 기준은 `assets/voice_ref/LUNA_PROSODY_TARGET.json`을 사용한다.
- Candidate B 경로·해시·고정 파라미터를 임의로 바꾸지 않는다.
- 다른 TTS, RVC, VC, 음성 엔진을 production 경로에 혼합하지 않는다.
- 확인되지 않은 Chatterbox fine-tuning 또는 LoRA를 Luna V3에 적용하지 않는다.
- `scripts/luna_narration_pipeline_v1.py`는 S10 이전 단계에서 수정하지 않는다.
- S09까지는 기존 production 선택 결과와 오디오를 바꾸지 않는 **독립 모듈 또는 shadow/experiment 경로**만 만든다.
- 기존 캐시·확정 오디오·동결 프로젝트를 무효화하지 않는다.
- 현재 Luna 분할·속도·피치·tail·끝맺음 컬 규칙을 임의로 삭제하거나 약화하지 않는다.
- 외부 점수는 기존 하드 게이트 위반을 보상할 수 없다.
- SpeechMOS 점수 하나로 최종 후보를 선택하지 않는다.
- SpeechBrain 기본 threshold를 Luna threshold로 그대로 사용하지 않는다.
- WhisperX가 자연스러움 또는 억양을 판정한다고 가정하지 않는다.
- 프로젝트 문서가 지원하지 않는 사실은 추측으로 확정하지 않는다.

## 2. 단계 잠금 규칙

- 한 Codex 세션은 **정확히 한 단계만** 수행한다.
- 다음 단계의 설계, 파일, 테스트, TODO를 선행 구현하지 않는다.
- 현재 단계의 `next_stage` 파일을 만들거나 수정하지 않는다.
- `.codex/stage_state.json`을 직접 수정하지 않는다.
- `.codex/stage_plan.json`, `AGENTS.md`, `tools/stage_gate.py`, workflow, 핵심 사양서를 수정하지 않는다.
- `python tools/stage_gate.py advance ...` 또는 `close`를 실행하지 않는다.
- 단계 전환은 사용자만 비밀키를 사용해 실행한다. Codex 프로세스에는 `LUNA_STAGE_GATE_KEY`를 절대 노출하지 않는다.
- 현재 단계 완료 후에는 완료요청만 만들고 **반드시 정지**한다.

## 3. 변경 범위

- 현재 단계의 `allowed_paths`와 `always_allowed_paths`에 해당하는 파일만 수정한다.
- 경로가 애매하면 구현하지 말고 단계 보고서에 차단 사유를 기록한다.
- 다른 단계 파일을 건드려야 할 것 같으면 현재 단계에서 중단하고 `BLOCKED_NEEDS_USER_DECISION`으로 보고한다.
- 범위를 넓히기 위해 stage plan 또는 guard를 수정하지 않는다.

## 4. 구현 원칙

- 기존 entry point와 출력 파일 이름을 유지한다.
- 새 기능은 작은 모듈과 명시적 인터페이스로 분리한다.
- optional dependency는 lazy import하고, 미설치 시 기존 파이프라인이 깨지지 않게 한다.
- 결정적 단위 테스트는 실제 대형 모델을 로드하지 않고 fixture/mock으로 실행 가능하게 한다.
- 실제 모델·GPU·외부 다운로드가 필요한 검증은 별도 integration test로 분리한다.
- threshold, model ID, schema version, source hash, feature version을 결과에 기록한다.
- 모든 판정은 `pass/fail/unknown/not_run`을 구분한다.
- 실패를 침묵시키거나 빈 오디오를 성공 결과로 대체하지 않는다.
- production 기본값은 기존 동작 유지다.

## 5. 단계 완료 절차

1. 현재 단계 요구사항과 금지사항을 다시 확인한다.
2. 관련 테스트를 모두 실행한다.
3. `python tools/stage_gate.py check-scope`가 통과해야 한다.
4. `.codex/reports/<STAGE>_REPORT.md`를 작성한다.
5. 변경사항을 현재 단계 단일 커밋으로 정리하고 worktree를 깨끗하게 만든다.
6. 아래 명령으로 완료요청을 만든다.

```bash
python tools/stage_gate.py request-completion \
  --stage <STAGE> \
  --report .codex/reports/<STAGE>_REPORT.md \
  --test "<실행한 테스트 명령>=PASS"
```

7. 최종 응답 마지막 줄을 정확히 다음과 같이 쓴다.

```text
STAGE_COMPLETE_AWAITING_USER_APPROVAL
```

8. 그 이후 다음 단계에 관한 코드를 작성하거나 실행하지 않는다.

## 6. 차단 또는 실패 시

완료 기준을 충족하지 못하면 억지로 통과시키지 않는다. 보고서에 아래를 기록하고 중단한다.

- 실패한 테스트
- 재현 명령
- 원인으로 확인된 사실
- 아직 확인되지 않은 가설
- 현재 단계 안에서 가능한 다음 조치
- 사용자 결정이 필요한 항목

최종 응답 마지막 줄은 다음 중 하나다.

```text
STAGE_BLOCKED_AWAITING_USER_DECISION
```

또는

```text
STAGE_FAILED_AWAITING_USER_ACTION
```
