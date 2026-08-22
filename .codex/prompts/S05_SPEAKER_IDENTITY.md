# S05 — 화자 동일성 Validator와 Calibration

## 권장 모델

- GPT-5.6 Terra
- Reasoning: High

## 이번 세션의 유일한 목표

Candidate B 및 승인 Luna와 생성 후보의 화자 일치도를 측정하는 독립 validator를 만든다. Chatterbox Voice Encoder를 1차, SpeechBrain을 2차 보조로 사용한다.

## 구현 범위

```text
scripts/luna_quality/adapters/chatterbox_ve_adapter.py
scripts/luna_quality/adapters/speechbrain_adapter.py
scripts/luna_quality/validators/speaker_identity.py
```

## 필수 동작

### Chatterbox VE

- 현재 production Chatterbox와 동일한 Voice Encoder 사용
- 16kHz mono normalization
- embedding cache by audio SHA256
- Candidate B embedding cache
- cosine similarity 반환

### SpeechBrain

- lazy import
- model ID와 revision 기록
- 기본 threshold를 사용하더라도 calibration 전에는 판정 기준으로 쓰지 않음
- 별도 embedding cache

### Calibration

입력 그룹:

- Candidate B
- 승인 Luna
- 화자 drift로 반려된 후보
- 음질 문제는 있지만 같은 화자인 후보

출력:

- score distribution
- recommended threshold 후보
- false accept/false reject tradeoff
- sample count
- calibration dataset manifest/hash

데이터가 부족하면 threshold를 확정하지 않고 `insufficient_data`를 반환한다.

## 테스트

- 동일 waveform
- amplitude scaling
- resampling
- 다른 synthetic tone/fixture
- missing dependency
- missing calibration
- cache hit/invalidation

실제 화자 threshold 정확도는 integration dataset에서만 평가한다.

## 금지 사항

- SpeechBrain `0.25`를 Luna threshold로 고정 금지
- speaker score가 content/prosody hard failure를 보상하게 하지 않음
- production pipeline 연결 금지
- private Candidate B embedding을 public artifact에 직접 노출 금지

## 완료 기준

- primary/secondary score를 분리해 반환
- calibration 없이는 hard pass/fail 비활성
- provenance와 model revision 기록
- optional dependency 미설치 시 정상 import

## 종료

```bash
python tools/stage_gate.py request-completion \
  --stage S05 \
  --report .codex/reports/S05_REPORT.md \
  --test "<speaker validator unit tests>=PASS"
```

```text
STAGE_COMPLETE_AWAITING_USER_APPROVAL
```
