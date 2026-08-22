# S00 — 저장소 감사 및 Baseline 동결

## 권장 모델

- GPT-5.6 Sol
- Reasoning: High

## 이번 세션의 유일한 목표

기존 Luna production 파이프라인을 수정하지 않고, 후속 단계가 추측 없이 작업할 수 있도록 실제 저장소 구조·진입점·모델 로딩·캐시·출력·테스트·동결 자산을 조사해 baseline 문서와 manifest를 만든다.

## 시작 명령

```bash
python tools/stage_gate.py verify
python tools/stage_gate.py status
python tools/stage_gate.py check-scope
```

`active_stage != S00`이면 즉시 중단한다.

## 조사 대상

1. `scripts/luna_narration_pipeline_v1.py` 전체 구조
2. Chatterbox Multilingual V3 loading 방식과 실제 checkpoint 이름
3. Candidate B reference path와 hash 검증 위치
4. generation parameter의 실제 source of truth
5. 구절 분할·take 생성·게이트·beam assembly·pins 처리 흐름
6. `P##_t*.wav/json`, `_report.json`, `_luna.wav`, `pipeline_report.json`, `_pins.json` 포맷
7. 캐시 재사용과 invalidation 조건
8. `LUNA_PROSODY_TARGET.json` 구조와 사용 위치
9. 기존 테스트와 fixture
10. Python, torch, librosa, Chatterbox dependency version
11. CPU 실행 방식과 Windows UTF-8 주의사항
12. 동결 프로젝트·확정 오디오 보호 방식
13. 새 모듈을 넣을 수 있는 최소 침습 경계

## 산출물

다음 두 파일만 만든다.

```text
docs/luna_quality/baseline/S00_REPO_AUDIT.md
docs/luna_quality/baseline/BASELINE_MANIFEST.json
```

`BASELINE_MANIFEST.json` 최소 필드:

```text
schema_version
created_at
git_head
entry_point
entry_point_sha256
skill_path
skill_sha256
model_loader
model_checkpoint_files
candidate_b_path
candidate_b_expected_sha256
prosody_target_path
prosody_target_sha256
fixed_parameters
output_contracts
cache_contracts
test_commands
dependency_versions
frozen_paths
unresolved_items
```

private 오디오 자체를 복사하지 않는다.

## 금지 사항

- production code 수정 금지
- 테스트 코드 수정 금지
- dependency 변경 금지
- 오디오 재생성 금지
- 캐시 삭제 금지
- MD 규칙 변경 금지
- 후속 단계 코드 뼈대 생성 금지

## 완료 기준

- 실제 파일과 코드 근거로 모든 경로를 기록
- 존재하지 않는 파일은 `missing`으로 기록
- 추측과 사실을 구분
- 최소 침습 통합 위치를 2개 이하로 제안
- baseline manifest가 JSON parse 가능
- `python tools/stage_gate.py check-scope` 통과

## 단계 종료

보고서와 manifest를 커밋하고 worktree를 clean으로 만든 뒤:

```bash
python tools/stage_gate.py request-completion \
  --stage S00 \
  --report .codex/reports/S00_REPORT.md \
  --test "python -m json.tool docs/luna_quality/baseline/BASELINE_MANIFEST.json=PASS"
```

`.codex/reports/S00_REPORT.md`에는 조사 결과 요약과 commit SHA를 기록한다.

다음 단계 파일을 만들지 말고 즉시 종료한다.

마지막 줄:

```text
STAGE_COMPLETE_AWAITING_USER_APPROVAL
```
