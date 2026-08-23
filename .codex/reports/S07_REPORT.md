# S07 단계 완료 보고서

## 1. 단계 목표와 판정

Prosody Bank의 명시적 사람 선택 이력으로 작은 pairwise logistic ranker를
학습하고 block/동일 문장 누수 없이 offline 평가하는 shadow-only 경로를
구현했다. Production 선택 경로는 수정하거나 연결하지 않았다.

- 단계 시작 commit: `d091c0071326e20299bbec1959d3e2b19a5792f1`
- 실제 데이터 판정: `insufficient_data`
- 실제 ranker 모델 생성: 안 함
- 합성 계약 평가: PASS

## 2. 시작 전 실제 데이터 충분성

S00에서 확인된 대로 이 checkout에는 옛 prosody measurement와 project
JOBS/pins가 보존되어 있지 않다. 따라서 현재 사용 가능한 실데이터의
충분성은 다음과 같다.

| 항목 | 관찰값 |
|---|---:|
| pin이 있는 phrase | 0 |
| 명시적 selected-vs-alternative pair | 0 |
| block | 0 |
| project | 0 |
| 문장 종류 분포 | 없음 |
| feature missing rate | 측정 불가(eligible candidate 0) |
| 한 프로젝트 집중도 | 측정 불가(pin 0) |

이를 `docs/luna_quality/ranking/S07_INSUFFICIENT_DATA.json`에 dataset/feature
schema hash와 함께 기록했다. 실제 모델과 baseline 비교는 `not_run`이며,
합성 결과를 실데이터 성능으로 승격하지 않았다.

제안한 최소 수집 기준은 명시적 pin phrase 50개, pair 150개, 독립 block
5개, pair 양쪽의 명시적 hard-gate pass 증거다. Project holdout을 위해
2개 project를 권장하되 blocking 조건과 별도의 경고로 구분한다.

## 3. 구현 내용

### 데이터와 누수 방지

- 정확히 하나의 명시적 `selected`가 있는 phrase에서만 같은 phrase의
  `not_selected` 대안과 pair를 만든다.
- `unknown`, `rejected`, 복수 pin, hard-gate 미통과/미확인 후보를 제외한다.
- `(project, block)`과 정규화 문장 hash를 union한 연결요소로 train/test를
  분리한다. Random row split 경로는 제공하지 않는다.
- 2개 이상 project가 있으면 별도 project holdout을 평가한다.
- Prosody Bank export는 S06에 hard-gate 증거가 없으면 `unknown`으로
  내보내고 학습에서 fail closed 한다.

### 모델과 feature

- Pure-Python standardized pairwise logistic regression, fixed seed `407`
- Winner/loser 대칭 표본으로 all-positive intercept의 자명한 해 방지
- 속도, pitch median/range, tail/relative tail, final glide/rebound, level
  deviation, phrase reset, 두 speaker similarity, content score/error rate,
  MOS를 고정된 순서로 사용
- Text embedding/deep model 없음
- MOS는 다른 feature보다 8배 강한 L2 regularization 적용
- Missing feature는 training mean으로 대체하고 schema/standardization을
  artifact metadata에 기록

### 평가와 artifact

- Pairwise accuracy, pin top-1, top-3 recall, MRR, NDCG
- 문장 class별 결과, 기존 quality score baseline 비교
- 단일 feature ablation, Brier score, ECE, low-confidence fraction
- Model/version, ordered feature schema/hash, dataset/source hashes, seed,
  standardization, coefficient, sufficiency, grouped evaluation을 JSON에 기록
- Artifact/schema/model mismatch 또는 `insufficient_data`는 read-only loader가
  `disabled`로 반환

### Read-only inference 안전 경계

- 명시적 hard-gate pass가 없는 후보는 rank하지 않는다.
- Confidence가 낮으면 `candidate_reduction_allowed=false`다.
- 모든 결과에 `production_selection_changed=false`를 기록한다.
- Production entry point, 기존 선택, cache, 확정 audio는 변경하지 않았다.

## 4. 합성 offline 평가

결정적 합성 fixture는 50 pinned phrase, 150 pair, 10 block, 2 project,
3 sentence class로 구성했다. 쉽게 분리되는 중복 신호는 통계 계약 검증용일
뿐 실제 Luna 품질 증거가 아니다.

| 항목 | 결과 |
|---|---:|
| connected-group train/test pair | 120 / 30 |
| connected-group train/test group | 8 / 2 |
| pairwise accuracy | 1.000 |
| pin top-1 / top-3 | 1.000 / 1.000 |
| MRR / NDCG | 1.000 / 1.000 |
| Brier / ECE | 0.0000123 / 0.00277 |
| synthetic baseline pairwise accuracy | 0.000 |
| project-holdout train/test pair | 75 / 75 |

세 문장 class 모두 1.000이며 단일 feature ablation delta는 중복 합성
신호 때문에 모두 0이다. 이 값들로 자동 promotion하지 않는다.

## 5. 변경 파일

- `scripts/luna_quality/ranking/__init__.py`
- `scripts/luna_quality/ranking/features.py`
- `scripts/luna_quality/ranking/data.py`
- `scripts/luna_quality/ranking/pairwise.py`
- `scripts/luna_quality/ranking/evaluate.py`
- `scripts/luna_quality/ranking/artifact.py`
- `scripts/luna_quality/ranking/train.py`
- `scripts/luna_quality/prosody_bank/queries.py`
- `tests/luna_quality/unit/test_preference_ranker.py`
- `docs/luna_quality/ranking/S07_INSUFFICIENT_DATA.json`
- `docs/luna_quality/ranking/S07_OFFLINE_EVALUATION.md`
- `.codex/reports/S07_REPORT.md`

## 6. 테스트

| 명령 | 결과 |
|---|---|
| `engine\chatterbox-v3\venv\Scripts\python.exe -X utf8 -m unittest tests.luna_quality.unit.test_preference_ranker -v` | PASS, 12 tests |
| `engine\chatterbox-v3\venv\Scripts\python.exe -X utf8 -m unittest tests.luna_quality.unit.test_preference_ranker.PreferenceRankerTest.test_grouped_and_project_evaluation -v` | PASS, grouped/project evaluation |
| `engine\chatterbox-v3\venv\Scripts\python.exe -X utf8 -m unittest discover -s tests\luna_quality\unit -p test_*.py -v` | PASS, 59 tests |
| `python -X utf8 -m json.tool docs\luna_quality\ranking\S07_INSUFFICIENT_DATA.json` | PASS |
| `python -X utf8 -m scripts.luna_quality.ranking.train --help` | PASS, warning 없음 |
| `python -X utf8 tools\stage_gate.py check-scope` | PASS |
| `git diff --check` | PASS |

참고로 system Python의 전체 회귀는 기존 S05 adapter가 요구하는 NumPy가
그 환경에 없어 3건이 실행되지 않았다. 저장소 계약이 지정한 Chatterbox
V3 venv에서 같은 전체 59건이 모두 통과했다. S07 코드는 외부 dependency를
추가하지 않는다.

## 7. 재현 명령

실데이터 export가 생기면 다음 명령이 충분성을 먼저 판정하고, 부족하면
모델 대신 `insufficient_data` artifact/evaluation을 쓴다.

```powershell
python -X utf8 -m scripts.luna_quality.ranking.train `
  --input <candidates.json> `
  --artifact <ranker.json> `
  --evaluation <evaluation.json> `
  --seed 407
```

## 8. 확인된 제한과 위험

- 현재 실데이터가 없어 실데이터 정확도, baseline delta, calibration,
  ablation은 확인할 수 없다.
- S06 저장 행에는 명시적 hard-gate pass bit가 없어 기존 행은 안전하게
  `unknown` 처리된다. 실제 학습에는 pass 증거가 포함된 새 export가 필요하다.
- 합성 fixture의 완전 분리는 코드 계약만 입증하며 사람 선호 일반화 성능을
  입증하지 않는다.
- Ranker는 shadow-only이며 production 기본 동작은 그대로다.

## 9. 완료 판정

- [x] 데이터 부족 여부와 최소 기준을 정직하게 기록
- [x] 재현 가능한 training command
- [x] 결정적 pairwise 모델과 versioned artifact 계약
- [x] leakage-free group/project 평가
- [x] baseline/class/ablation/calibration 지표
- [x] artifact/schema mismatch fail-closed
- [x] hard-gate 및 low-confidence 안전 정책
- [x] S07 범위 검사와 전체 단위 회귀 통과
- [x] Production pipeline 미변경
