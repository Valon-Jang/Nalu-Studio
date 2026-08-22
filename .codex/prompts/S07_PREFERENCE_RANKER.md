# S07 — Preference Ranker 학습과 Offline 평가

## 권장 모델

- GPT-5.6 Sol
- Reasoning: Extra High

## 이번 세션의 유일한 목표

Prosody Bank의 사람 선택 이력으로 작은 pairwise ranker를 학습하고, 데이터 leakage 없이 offline 평가하는 기능을 만든다. production 선택에는 연결하지 않는다.

## 시작 전 데이터 충분성 확인

먼저 다음을 보고한다.

- pin이 있는 phrase 수
- pair 수
- block/project 수
- 문장 종류 분포
- feature missing rate
- 한 프로젝트 집중도

데이터가 부족하면 모델을 억지로 만들지 말고 `insufficient_data` artifact와 필요한 최소 데이터 기준을 제안한다.

## 1차 모델

- pairwise logistic regression 권장
- 복잡한 neural ranker 금지
- feature standardization
- fixed seed
- model artifact + metadata
- feature schema hash
- training dataset hash

## 데이터 분할

- 동일 block 또는 동일 문장의 take가 train/test에 동시에 들어가지 않음
- group split 사용
- 가능하면 project-level holdout도 별도 평가
- random row split 금지

## feature

기존 검증된 Luna 지표와 S03~S05 보조 지표를 사용한다.

- 속도
- pitch median/range
- tail delta/relative tail
- final glide/rebound
- level deviation
- phrase reset 관련 값
- speaker similarities
- ASR/content score
- MOS는 낮은 가중치 후보

text embedding이나 거대 모델 feature는 1차 범위에서 제외한다.

## 평가

필수:

- pairwise accuracy
- pin top-1 accuracy
- pin top-3 recall
- MRR 또는 NDCG
- 문장 class별 결과
- simple existing quality-score baseline과 비교
- ablation
- calibration/uncertainty

## 안전 정책

- 하드 게이트 실패 후보는 rank 대상 제외
- ranker artifact/schema mismatch 시 비활성
- confidence가 낮으면 후보 수를 줄이지 않음
- 모델이 선택하지 못해도 기존 pipeline 결과 유지

## 테스트

- synthetic ranking dataset
- leakage detection
- deterministic training
- artifact round-trip
- feature schema mismatch
- insufficient data
- grouped evaluation

## 금지 사항

- production pipeline 연결 금지
- deep model 도입 금지
- 한 번의 높은 정확도로 자동 promotion 금지
- 미선택을 모두 강한 negative로 취급 금지

## 완료 기준

- 재현 가능한 training command
- artifact와 evaluation report 생성
- baseline 대비 결과 명시
- 데이터 부족 여부 정직 기록
- S08이 호출할 read-only inference interface 확정

## 종료

```bash
python tools/stage_gate.py request-completion \
  --stage S07 \
  --report .codex/reports/S07_REPORT.md \
  --test "<ranker unit tests>=PASS" \
  --test "<offline grouped evaluation command>=PASS_OR_INSUFFICIENT_DATA_DOCUMENTED"
```

```text
STAGE_COMPLETE_AWAITING_USER_APPROVAL
```
