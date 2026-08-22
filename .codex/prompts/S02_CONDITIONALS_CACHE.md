# S02 — Candidate B Conditionals Cache

## 권장 모델

- GPT-5.6 Terra
- Reasoning: Standard

## 이번 세션의 유일한 목표

공식 Chatterbox Multilingual V3의 conditionals 저장·로드 기능을 안전하게 감싸는 독립 캐시 모듈을 만든다. production pipeline에는 아직 연결하지 않는다.

## 구현 요구사항

권장 파일:

```text
scripts/luna_quality/conditionals/cache.py
scripts/luna_quality/conditionals/manifest.py
```

캐시 manifest 필수 항목:

- schema version
- Chatterbox package/source version
- T3 checkpoint filename + SHA256
- S3Gen file + SHA256
- Voice Encoder file + SHA256
- tokenizer file + SHA256
- Candidate B WAV repo-relative path + SHA256
- language_id
- exaggeration
- conditionals artifact SHA256
- created_at

동작:

1. 모든 source hash가 일치할 때만 cache hit
2. 불일치·파일 손상·deserialization 오류는 명시적 cache miss
3. 원본 reference WAV를 변경하거나 복사하지 않음
4. cache artifact는 private/local cache 경로에 저장
5. atomic write 사용
6. Windows 파일 잠금·중단 시 부분 파일을 남기지 않음
7. actual model load는 integration test로 분리
8. unit test는 fake Conditionals 객체로 수행

## 검증해야 할 사실

- 공식 `Conditionals.save/load` 호출 형식
- 현재 V3 loader가 사용하는 실제 class와 file format
- exaggeration이 conditionals에 포함되는 방식

## 금지 사항

- production pipeline 연결 금지
- prosody 고정 효과를 주장하지 않음
- Candidate B WAV를 Git에 복사하지 않음
- model checkpoint를 신규 저장소 경로로 이동하지 않음
- 캐시가 없을 때 실패시키는 production 정책 구현 금지

## 완료 기준

- deterministic cache key
- invalidation 이유가 구조화되어 반환됨
- corrupt cache test 통과
- atomic write test 통과
- private source가 artifact에 포함되지 않음

## 종료

```bash
python tools/stage_gate.py request-completion \
  --stage S02 \
  --report .codex/reports/S02_REPORT.md \
  --test "<conditionals unit tests>=PASS"
```

```text
STAGE_COMPLETE_AWAITING_USER_APPROVAL
```
