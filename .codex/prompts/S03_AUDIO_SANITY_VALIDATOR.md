# S03 — Audio Sanity Validator

## 권장 모델

- GPT-5.6 Terra
- Reasoning: Standard

## 이번 세션의 유일한 목표

대형 AI 모델 없이 결정적으로 실행되는 오디오 건전성 validator를 구현한다. production selection에는 연결하지 않는다.

## 검사 항목

- 파일 존재·decode 가능 여부
- sample count와 duration
- NaN/Inf
- zero waveform
- peak, RMS, crest factor
- clipping ratio
- DC offset
- leading/trailing silence
- 비정상적으로 긴 내부 silence
- abrupt end 또는 과도한 tail
- peak guard 초과
- expected sample rate 정보

threshold는 코드에 흩어놓지 말고 versioned config로 관리한다. 기존 Luna RMS −20dBFS, peak 0.89 guard 등과 충돌하지 않게 S00 근거를 사용한다.

## 출력

`ValidationResult`로 반환하며:

- hard gate 여부
- status
- reasons
- 측정값
- threshold
- validator version
- source hash

을 포함한다.

## 테스트

합성 fixture로 다음을 만든다.

- 정상 sine/voice-like envelope
- all-zero
- NaN
- clipping
- 긴 앞/뒤 무음
- 내부 무음
- 짧은 파일
- abrupt cut

실제 Luna WAV는 unit test에 복사하지 않는다.

## 금지 사항

- SpeechMOS 구현 금지
- ASR 구현 금지
- speaker validator 구현 금지
- production pipeline 수정 금지
- 실패 시 빈 tensor를 정상 결과로 반환 금지

## 완료 기준

- 모든 fixture의 기대 status가 명시적
- threshold 변경 시 validator version 또는 config hash가 바뀜
- CPU에서 빠르게 실행
- 기존 오디오 파일을 수정하지 않음

## 종료

```bash
python tools/stage_gate.py request-completion \
  --stage S03 \
  --report .codex/reports/S03_REPORT.md \
  --test "<audio sanity tests>=PASS"
```

```text
STAGE_COMPLETE_AWAITING_USER_APPROVAL
```
