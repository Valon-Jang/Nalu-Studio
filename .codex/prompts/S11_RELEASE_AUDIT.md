# S11 — 최종 회귀·라이선스·Release 감사

## 권장 모델

- GPT-5.6 Sol
- Reasoning: Extra High
- Codex 선택기에 Pro가 실제로 노출된 환경에서는 사용자 판단으로 Pro를 선택할 수 있으나 필수 조건이 아니다.

## 이번 세션의 유일한 목표

전체 구현이 Luna의 불변 규칙과 stage evidence를 지키는지 감사하고 release candidate 여부를 판정한다. 새로운 기능 범위를 추가하지 않는다.

## 감사 항목

### 코드와 아키텍처

- production entry point 유지
- engine/Candidate B/parameter 불변
- 신규 모듈 경계
- optional dependency isolation
- feature flag 기본값
- rollback
- error handling
- no silent pass

### 데이터

- private audio 비노출
- Prosody Bank provenance
- DB migration
- ranker artifact/data hash
- calibration provenance
- 동결 프로젝트 보호

### 평가

- 전체 unit test
- integration test 상태
- baseline regression
- shadow 선택 무영향
- ranker grouped evaluation
- hybrid isolation
- Windows CPU 경로
- checkpoint/resume
- 성능 및 모델 로드 횟수

### 라이선스

- Chatterbox
- WhisperX 및 alignment model
- SpeechBrain 및 speaker model
- SpeechMOS/UTMOS
- scikit-learn 등 신규 dependency
- 배포 artifact에 포함되는 model weight의 별도 조건

### 문서

- 설치
- feature flag
- 운영
- 실패/폴백
- 캐시 삭제가 필요한 조건
- DB backup/restore
- ranker retrain
- 사용자 승인 절차

## 산출물

```text
docs/luna_quality/release/S11_RELEASE_AUDIT.md
docs/luna_quality/release/RELEASE_CHECKLIST.md
docs/luna_quality/release/ROLLBACK.md
docs/luna_quality/release/LUNA_SKILL_CHANGE_PROPOSAL.md
```

`LUNA_SKILL_CHANGE_PROPOSAL.md`는 제안서일 뿐 실제 project skill인 `.agents/skills/luna-narration/SKILL.md`를 수정하지 않는다.

## 판정

다음 중 하나만 선택한다.

- `RELEASE_CANDIDATE_APPROVED`
- `SHADOW_ONLY_APPROVED`
- `NOT_APPROVED`

판정 근거와 미해결 위험을 명시한다.

## 금지 사항

- 신규 기능 추가 금지
- threshold를 결과에 맞춰 임의 조정 금지
- 실패 테스트 삭제/skip 처리 금지
- skill 직접 수정 금지
- 다음 단계 생성 금지

## 완료 기준

- 모든 감사 항목에 evidence path 존재
- 미실행 테스트를 실행된 것처럼 쓰지 않음
- release/rollback 절차가 재현 가능
- 최종 판정 명확
- worktree clean

## 종료

```bash
python tools/stage_gate.py request-completion \
  --stage S11 \
  --report .codex/reports/S11_REPORT.md \
  --test "<full regression suite>=PASS_OR_EXPLICITLY_BLOCKED" \
  --test "<license audit>=PASS_OR_DOCUMENTED_RISK"
```

사용자가 검토 후 `python tools/stage_gate.py close`를 실행한다. Codex는 close를 실행하지 않는다.

```text
STAGE_COMPLETE_AWAITING_USER_APPROVAL
```
