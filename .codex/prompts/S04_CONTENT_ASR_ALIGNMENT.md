# S04 — 원문/ASR/WhisperX 한국어 정렬 Validator

## 권장 모델

- GPT-5.6 Terra
- Reasoning: High

## 이번 세션의 유일한 목표

생성된 음성이 원문을 누락·삽입·반복·오독했는지 검사하고, 한국어 단어/구절 타이밍을 얻는 optional content validator를 만든다. 억양 판정은 하지 않는다.

## 구현 범위

```text
scripts/luna_quality/text_normalization.py
scripts/luna_quality/adapters/whisperx_adapter.py
scripts/luna_quality/validators/content_asr.py
```

## 필수 설계

### 기대 발음 정규화

별도 함수로 분리한다.

- 숫자
- 연도
- 소수
- 퍼센트
- 단위
- 영문 약어
- 한글/영문 혼합 용어
- punctuation

S00의 기존 respell/normalization이 있으면 중복 구현하지 말고 adapter로 사용한다. 근거가 없는 읽기 규칙을 임의 확정하지 않는다.

### ASR 비교

최소 지표:

- normalized edit distance
- deletion/insertion/substitution count
- critical term match
- repetition detection
- unexpected continuation

### WhisperX

- lazy import
- 한국어 language code 고정 가능
- alignment model availability를 capability로 확인
- word timestamp와 confidence 반환
- 숫자·기호가 align되지 않는 경우 unknown을 명시
- model download가 unit test에서 발생하지 않음

## 하드 게이트 정책

threshold는 아직 production에 적용하지 않는다. offline config와 report만 만든다.

critical term 누락은 별도 flag로 반환한다. 전체 edit score가 낮더라도 critical term 오류를 숨기지 않는다.

## 테스트

- 동일 문장
- 한 단어 누락
- 한 단어 삽입
- 반복
- 숫자 표기만 다른 동등 발음
- 영문 약어
- alignment not available
- ASR exception

ASR/WhisperX 실제 모델 테스트는 integration marker로 격리한다.

## 금지 사항

- 자연스러움 점수 생성 금지
- prosody 판단 금지
- WhisperX failure를 pass로 처리 금지
- production pipeline 연결 금지
- 외부 API로 private audio 전송 금지

## 완료 기준

- deterministic text comparison unit test
- optional dependency 미설치 상태에서도 package import 성공
- 한국어 alignment adapter interface 확정
- content error와 timing extraction 결과 분리

## 종료

```bash
python tools/stage_gate.py request-completion \
  --stage S04 \
  --report .codex/reports/S04_REPORT.md \
  --test "<content/asr unit tests>=PASS" \
  --test "<optional integration tests>=PASS_OR_DOCUMENTED_NOT_RUN"
```

```text
STAGE_COMPLETE_AWAITING_USER_APPROVAL
```
