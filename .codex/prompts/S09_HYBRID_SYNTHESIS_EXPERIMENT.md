# S09 — Hybrid Synthesis 격리 실험

## 권장 모델

- GPT-5.6 Sol
- Reasoning: Extra High

## 이번 세션의 유일한 목표

현행 phrase mode, 문장 전체 mode, 의미절 hybrid mode를 공정하게 비교하는 **격리된 실험 runner와 평가 도구**를 만든다. production pipeline과 기존 캐시는 수정하지 않는다.

## 실험 모드

### A. Existing phrase

현재 분할 결과를 그대로 사용.

### B. Sentence

문장 전체를 한 take로 생성하고 ASR/forced alignment로 기존 subtitle/phrase 경계를 사후 추출.

### C. Hybrid

- 짧은 문장 전체
- 긴 문장은 의미 절/연결어미 경계
- 안전 한도 초과 시 existing phrase fallback

## 공정성 조건

- 동일 script set
- 동일 Candidate B
- 동일 fixed generation parameter
- 동일 candidate budget
- 동일 seed derivation 원칙
- 별도 experiment output root
- 기존 cache/output 이름과 충돌 금지
- 동결 프로젝트 제외

## 안전 한도

S00에서 확인한 모델의 실제 text/token/audio 한도를 사용한다. 장문을 억지로 늘리지 않는다. hallucination·repetition·speaker drift가 증가하면 mode failure로 기록한다.

## 산출물

- segmentation plan JSON
- mode별 생성 job JSON
- mode별 validator result
- side-by-side timing report
- blind listening package manifest
- 분석 CSV/JSON
- promotion recommendation이 아닌 evidence report

실제 오디오 생성은 사용자가 명시적으로 integration command를 실행할 때만 수행되도록 한다. unit test와 기본 CI에서는 생성하지 않는다.

## 평가

- content accuracy
- abnormal silence/repetition
- speaker similarity
- existing prosody gates
- phrase transition metrics
- duration
- failure rate
- human blind preference import format

## 금지 사항

- production pipeline 수정 금지
- existing `_luna.wav` 덮어쓰기 금지
- existing `pins.json` 수정 금지
- 실험 결과 자동 promotion 금지
- 새로운 분할 규칙을 skill에 자동 반영 금지

## 완료 기준

- dry-run으로 모든 job/경로 충돌 검사 가능
- fixture에서 세 mode 비교 report 생성
- actual generation command는 명시적 opt-in
- 기존 cache와 output이 byte-level로 보존됨
- 평가 결과가 mode별로 분리됨

## 종료

```bash
python tools/stage_gate.py request-completion \
  --stage S09 \
  --report .codex/reports/S09_REPORT.md \
  --test "<hybrid planner/runner unit tests>=PASS" \
  --test "<dry-run isolation test>=PASS"
```

```text
STAGE_COMPLETE_AWAITING_USER_APPROVAL
```
