# S00 단계 완료 보고서

## 1. 단계 목표

기존 Luna production 파이프라인을 수정하지 않고 저장소의 실제 진입점, 모델 load, checkpoint, Candidate B, 고정 파라미터, 처리·cache·output 계약, dependency, 테스트 상태, 동결 자산과 최소 침습 통합 경계를 baseline으로 동결한다.

- 감사 기준 commit SHA: `417774ab6b7177f723b8bd75f5fb56fd25b5a0b0`
- 단계 시작 기준 commit SHA: `d5d2a3c669af223cbe798f48a90efa34cc88b67d`
- S00 산출물 commit: 이 보고서와 두 baseline 파일을 포함하는 단일 commit. Git commit은 내용 주소이므로 self SHA는 파일 내부가 아니라 완료 요청 및 단계 종료 응답에 기록한다.

## 2. 실제 변경 파일

- `docs/luna_quality/baseline/S00_REPO_AUDIT.md`
- `docs/luna_quality/baseline/BASELINE_MANIFEST.json`
- `.codex/reports/S00_REPORT.md`

사용자가 별도로 둔 `references/LUNA_VIMAX_BOOTSTRAP_V1_2026-08-23.zip` 및 같은 이름의 압축 해제 폴더는 변경하지 않았으며 정확한 두 경로만 `.git/info/exclude`에 로컬 제외했다. `.git/info/exclude`는 commit 대상 worktree 파일이 아니다.

## 3. 구현 내용

- production entry point와 SHA-256, 모델 loader 호출, CPU/offline runtime 및 실제 Hugging Face snapshot을 기록했다.
- 6개 checkpoint의 이름, bytes, SHA-256과 snapshot root를 기록했다.
- Candidate B의 기대/실제 hash 및 WAV 형식, 현재 Luna skill과 prosody target의 hash를 기록했다.
- phrase split → take generation → metrics/gate → pins → beam assembly → final output 흐름을 정리했다.
- fixed generation·prosody·pause·output 파라미터를 machine-readable manifest에 동결했다.
- 기존 project 산출물의 schema/WAV inventory와 cache invalidation 조건을 기록했다.
- 확정 final WAV 17개와 SUBSEA timing 2개의 실제 경로 및 SHA-256을 동결했다.
- 후속 통합 경계를 독립 `scripts/luna_quality/` shadow 모듈과 S10의 default-off selection hook 두 곳으로 제한했다.

## 4. 유지한 불변 조건

- production code, test code, dependency, 모델/cache, audio, rules를 변경하지 않았다.
- audio를 생성·재생성·삭제하지 않았다.
- 확정 SPIDER-001/SUBSEA-001 산출물을 수정하지 않았다.
- 후속 단계 module/test scaffold를 만들지 않았다.
- 다음 단계 S01을 시작하지 않았다.

## 5. 테스트

| 명령 | 결과 | 비고 |
|---|---|---|
| `python -m json.tool docs/luna_quality/baseline/BASELINE_MANIFEST.json` | PASS | JSON parse 확인 |
| production entry point `compile(...)` | PASS | 파일 수정 없이 syntax compile |
| manifest path/hash 대조 | PASS | entry/skill/reference/target, checkpoint 6개, final WAV 17개, timing 2개 |
| Chatterbox V3 CPU model load smoke | PASS | audio 생성 없음, sample rate 24 kHz |
| 기존 JSON/WAV inventory 검사 | PASS | JSON 1,071개 parse, WAV 1,052개 header 계약 확인 |
| `python -X utf8 tools/stage_gate.py verify` | PASS | local HMAC key 부재로 signature verification만 생략, CI는 `--require-signature` 필요 |
| `python -X utf8 tools/stage_gate.py check-scope` | PASS | baseline 두 파일과 S00 report가 허용 범위임을 최종 확인 |
| `git diff --check` | PASS | whitespace 오류 없음 |

## 6. baseline 영향

새 baseline은 현재 production 동작을 설명하고 후속 validator/ranker 구현의 비교 기준을 제공한다. runtime 동작이나 기존 output에는 영향이 없다.

## 7. 확인된 사실

- entry point는 `scripts/luna_narration_pipeline_v1.py` 단일 파일이다.
- `v3`는 `t3_mtl23ls_v3.safetensors`로 해석되고 CPU/offline load가 성공한다.
- Candidate B hash는 기대값과 일치하지만 production entry point 자체는 runtime hash 검증을 하지 않는다.
- current operational source는 production 상수와 `.agents` Luna skill이다. prosody target JSON은 역사적 근거이며 runtime 입력이 아니다.
- block report 존재만으로 block 전체 cache가 재사용되고 text/hash/final WAV는 검증하지 않는다.
- 확정 project output에는 schema evolution과 현재 band 밖의 역사적 결과가 있으나 동결 대상이다.
- Windows CP949에서는 `stage_gate.py status`가 em dash 출력 때문에 실패하며 `-X utf8`에서는 성공한다.

## 8. 미확인 가설

없음. source에서 확인할 수 없는 항목은 manifest의 `unresolved_items`에 `missing` 또는 관찰된 위험으로만 기록했다.

## 9. 남은 위험

- 자동 test/fixture와 reproducible dependency lock이 없다.
- block/take cache invalidation 및 output provenance가 불완전하다.
- `.agents`와 `.claude` Luna skill 사본이 다르다.
- ignored runtime 및 확정 WAV 변경은 Git scope 검사만으로 검출되지 않는다.
- 옛 prosody measurement와 project JOBS/pins가 보존되어 있지 않다.

## 10. 다음 단계 입력으로 전달할 자료

- `docs/luna_quality/baseline/S00_REPO_AUDIT.md`
- `docs/luna_quality/baseline/BASELINE_MANIFEST.json`
- 현재 pipeline의 output/cache 계약과 확정 asset hash
- S01–S09 독립 shadow 모듈 경계

## 11. 완료 판정

- [x] 현재 단계 acceptance criteria 충족
- [x] 금지 경로 미수정
- [x] `stage_gate.py check-scope` 통과
- [x] 모든 변경 커밋 — 이 보고서를 포함한 S00 단일 commit으로 처리
- [x] worktree clean — commit 후 확인
