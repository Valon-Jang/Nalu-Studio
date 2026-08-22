# S08 — Shadow Quality Orchestrator

## 권장 모델

- GPT-5.6 Terra
- Reasoning: High

## 이번 세션의 유일한 목표

S03~S07 모듈을 연결해 기존 take를 평가하고 추천 순위를 내는 **독립 shadow orchestrator**를 만든다. 기존 production selection과 오디오는 절대 바꾸지 않는다.

## 구현 범위

```text
scripts/luna_quality/orchestrator/engine.py
scripts/luna_quality/orchestrator/policy.py
scripts/luna_quality/orchestrator/report.py
scripts/luna_quality/cli.py
```

## 처리 순서

```text
Take discovery
→ Audio sanity hard gate
→ Content/ASR result
→ Speaker result
→ Existing prosody gate import
→ Hard-gate survivor set
→ Optional MOS
→ Preference ranker
→ Shadow recommendation
→ Existing actual pin/selection과 비교 report
```

## 필수 정책

- 각 validator status를 보존
- unknown과 fail 구분
- hard gate는 다른 점수로 보상 불가
- ranker가 없거나 incompatible이면 기존 quality score 기준 report만 생성
- 기존 선택과 shadow 추천이 다르면 이유 feature를 표시
- 기존 pin을 덮어쓰지 않음
- 후보 파일을 삭제하거나 재생성하지 않음

## CLI 예시

실제 저장소 구조에 맞게 명령을 확정하되 다음 성격을 유지한다.

```text
python -m scripts.luna_quality.cli shadow-evaluate --outdir <EXISTING_OUTDIR> --report <NEW_REPORT>
```

## 출력

- block/phrase/take별 validator result
- hard-gate survivor
- rank score
- shadow top-1/top-3
- actual selected take
- agreement/disagreement
- 실행 capability
- source/model/config hash
- 실행 시간

## 테스트

- 모든 validator pass
- 한 hard failure
- optional validator unavailable
- ranker missing
- ranker schema mismatch
- existing pin agreement/disagreement
- report deterministic ordering
- 입력 파일 read-only 확인

## 금지 사항

- production pipeline 수정 금지
- `pins.json` 수정 금지
- take 재생성 금지
- 자동 후보 삭제 금지
- select mode 구현 금지

## 완료 기준

- 기존 output directory를 읽기만 함
- shadow report만 새로 생성
- validator 한 개 실패가 전체 crash로 이어지지 않되 오류를 숨기지 않음
- 추천 근거 추적 가능
- 실제 선택과 비교 가능

## 종료

```bash
python tools/stage_gate.py request-completion \
  --stage S08 \
  --report .codex/reports/S08_REPORT.md \
  --test "<orchestrator unit tests>=PASS" \
  --test "<shadow fixture run>=PASS"
```

```text
STAGE_COMPLETE_AWAITING_USER_APPROVAL
```
