# S10 — Feature Flag 기반 Production 통합

## 권장 모델

- GPT-5.6 Sol
- Reasoning: High

## 이번 세션의 유일한 목표

S08 shadow orchestrator의 검증된 부분만 기존 `scripts/luna_narration_pipeline_v1.py`에 최소 침습으로 연결한다. 기본값에서는 기존 동작과 출력이 완전히 동일해야 한다.

## 시작 전 필수 증거

- S00 baseline manifest
- S03~S08 report 모두 승인됨
- S09 결과는 hybrid 기능을 넣을 경우에만 필수
- 사용자 승인된 통합 범위가 report 또는 stage 시작 지시에 명시됨

승인 범위가 불명확하면 코드를 바꾸지 않고 차단 보고한다.

## 필수 Feature Flag

```text
LUNA_QUALITY_MODE=off|shadow|select
LUNA_CONDITIONALS_CACHE=off|on
LUNA_ASR_VALIDATOR=off|on
LUNA_SPEAKER_VALIDATOR=off|on
LUNA_MOS_VALIDATOR=off|on
LUNA_PREFERENCE_RANKER=off|shadow|select
LUNA_HYBRID_SYNTHESIS=off|experiment
```

기본값은 전부 기존 동작 유지 방향이다.

## 통합 원칙

1. 기존 CLI entry point 그대로 유지
2. 기존 JOBS.json format 그대로 유지
3. 기존 output filename 그대로 유지
4. flag OFF에서 baseline output/report contract 유지
5. shadow mode는 선택을 변경하지 않음
6. select mode는 사용자 승인된 validator/ranker만 사용
7. hard gate failure와 unknown 정책을 명시
8. 신규 모듈 오류 시 기존 production 경로 폴백 + 오류 report
9. rollback은 환경변수 OFF로 즉시 가능
10. 기존 cache를 자동 삭제하지 않음

## select mode 조건

- ranker artifact/schema/config hash 확인
- calibration artifact 확인
- hard-gate survivor 존재
- confidence/coverage 기준 충족
- 기준 미달 시 기존 selector 사용
- pin이 있으면 pin 우선 정책을 보존

## 테스트

필수 regression matrix:

- 모든 flag OFF
- quality shadow
- 각 optional dependency 없음
- invalid cache
- invalid ranker artifact
- explicit pin 존재
- validator fail
- validator unknown
- empty survivor set
- Windows UTF-8 path/text
- restart/checkpoint resume

가능하면 baseline fixture에 대해 OFF mode report와 output hash를 비교한다. 확률적 재생성을 유발하지 않는 방식으로 검증한다.

## 금지 사항

- fixed Luna engine/parameter 변경 금지
- 다른 TTS/VC 연결 금지
- private asset 이동 금지
- 기존 오디오 일괄 재생성 금지
- skill 자동 수정 금지
- S09 hybrid를 evidence 없이 production select mode로 활성화 금지

## 완료 기준

- flag OFF regression 통과
- shadow mode 선택 무영향 입증
- select mode fallback/rollback 테스트 통과
- entry point와 output contract 유지
- 변경 diff가 최소 침습
- 운영 문서와 장애 복구 명령 존재

## 종료

```bash
python tools/stage_gate.py request-completion \
  --stage S10 \
  --report .codex/reports/S10_REPORT.md \
  --test "<full unit test suite>=PASS" \
  --test "<baseline regression>=PASS" \
  --test "<shadow no-selection-change test>=PASS"
```

```text
STAGE_COMPLETE_AWAITING_USER_APPROVAL
```
