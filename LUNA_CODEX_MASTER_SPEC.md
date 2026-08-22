# Luna Validator + Preference Ranker — Codex Master Spec

## 목적

기존 Luna production 엔진을 유지하면서 다음 기능을 단계적으로 추가한다.

- Candidate B conditionals cache
- 오디오 건전성 검사
- ASR/WhisperX 원문·타이밍 검사
- Chatterbox VE + SpeechBrain 화자 동일성 검사
- Prosody Bank
- pins 기반 Preference Ranker
- shadow orchestrator
- phrase/sentence/hybrid 합성 비교 실험
- evidence가 확보된 기능만 feature flag로 production 통합

Luna의 불변 기준은 `.agents/skills/luna-narration/SKILL.md`다. 이 위치는 Codex가 저장소 스킬을 자동 발견하는 경로이므로 Luna 내레이션 요청과 설명이 일치하면 암묵적으로 로드할 수 있다.

## 절대 금지

- Chatterbox Multilingual V3 + Candidate B 교체
- 다른 TTS/VC/RVC production 혼합
- 확인되지 않은 V3 fine-tuning/LoRA 적용
- 기존 `pins.json`, 확정 WAV, 동결 프로젝트 자동 수정
- S10 이전 production entry point 수정
- 다음 단계 선행 구현

## 단계와 모델

| 단계 | 내용 | 모델 | 추론 |
|---|---|---|---|
| S00 | 저장소 감사·baseline 동결 | GPT-5.6 Sol | High |
| S01 | 공통 계약·테스트 하네스 | GPT-5.6 Terra | Standard |
| S02 | Candidate B conditionals cache | GPT-5.6 Terra | Standard |
| S03 | Audio sanity validator | GPT-5.6 Terra | Standard |
| S04 | ASR·WhisperX 내용 정렬 | GPT-5.6 Terra | High |
| S05 | 화자 동일성·calibration | GPT-5.6 Terra | High |
| S06 | Prosody Bank | GPT-5.6 Sol | High |
| S07 | Preference Ranker | GPT-5.6 Sol | Extra High |
| S08 | Shadow Orchestrator | GPT-5.6 Terra | High |
| S09 | Hybrid Synthesis 실험 | GPT-5.6 Sol | Extra High |
| S10 | Production feature-flag 통합 | GPT-5.6 Sol | High |
| S11 | 최종 회귀·라이선스 감사 | GPT-5.6 Sol | Extra High |

## 수동 단계 전환

Codex는 현재 단계 작업과 완료요청만 수행한다.

```bash
python tools/stage_gate.py request-completion \
  --stage S00 \
  --report .codex/reports/S00_REPORT.md \
  --test "<test>=PASS"
```

사용자는 보고서를 검토하고 비밀키가 있는 터미널에서만 다음 단계를 연다.

```bash
python tools/stage_gate.py advance --to S01
```

그 후 `LUNA_STAGE_GATE_KEY`를 Codex 프로세스에서 제거하고 `python tools/stage_gate.py codex-safe`를 통과시킨다. 모델을 바꾼 새 Codex 세션에서 S01 prompt를 사용한다. Codex는 `advance`를 실행하거나 `.codex/stage_state.json`을 수정할 수 없다.

## 하드 게이트 구조

1. `AGENTS.md`: 한 세션·한 단계 규칙
2. `.codex/stage_plan.json`: 단계별 허용 경로
3. `tools/stage_gate.py check-scope`: stage-start commit 이후 변경 경로 검사
4. `request-completion`: 완료요청만 생성, stage 불변
5. `advance`: 사용자 key 필수
6. signed state + protected-file hash
7. GitHub Actions required check
8. CODEOWNERS/ruleset으로 guard 파일 변경 시 사용자 승인

## 시작 순서

1. 실행팩을 대상 저장소 루트에 복사
2. `.gitignore.append` 내용을 기존 `.gitignore`에 병합
3. 실행팩 파일만 먼저 커밋
4. `LUNA_STAGE_GATE_KEY` 설정
5. `python tools/stage_gate.py init --stage S00`
6. `.codex/stage_state.json` 커밋
7. GPT-5.6 Sol High로 새 Codex 세션
8. `.codex/prompts/S00_REPO_AUDIT.md` 사용

## 상세 문서

- 전체 설계: `docs/LUNA_VALIDATOR_RANKER_BUILD_SPEC.md`
- 모델 배정: `docs/STAGE_MODEL_MATRIX.md`
- 강제 수준: `docs/STAGE_GATE_SECURITY.md`
- 단계별 지시: `.codex/prompts/`
- 시작 방법: `README_START_HERE.md`
