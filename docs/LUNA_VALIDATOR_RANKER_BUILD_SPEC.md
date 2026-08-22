# Luna Validator + Preference Ranker 구축 사양

- 문서 목적: Codex가 기존 Luna production 파이프라인을 깨지 않고 검수·선호학습·실험 기능을 단계적으로 구현하기 위한 공식 개발 기준
- 기준일: 2026-08-22
- 구현 방식: 단계별 수동 승인, 한 단계당 한 Codex 세션, 다음 단계 자동 진행 금지
- production 기본 원칙: 기존 결과 완전 보존, 신규 기능 기본 OFF 또는 shadow

---

## 1. 배경과 문제 정의

현재 Luna는 다음 조합으로 고정되어 있다.

- Chatterbox Multilingual V3
- Candidate B 고정 레퍼런스
- 고정 generation parameter
- 구절별 best-of-N 생성
- 속도·피치·종결·tail·끝맺음 컬·절대 피치·구절 연결 게이트
- 사람이 최종 승인한 take를 `pins.json`으로 고정

현 파이프라인은 음색과 일부 억양을 수치로 통제하지만, 다음 문제는 여전히 남아 있다.

1. 특정 음절만 갑자기 뜨거나 꺼지는 문제
2. 내용은 맞지만 Luna답지 않은 발화
3. 구절 단위 생성 때문에 문장 전체 억양이 끊기는 문제
4. 생성 후보가 많을 때 사람 청취 비용이 큰 문제
5. 사람이 고른 `pins.json` 선택 이력이 다음 생성에 체계적으로 재사용되지 않는 문제
6. 원문 누락·반복·비정상 무음·화자 drift를 현재 prosody 지표만으로 충분히 잡지 못하는 문제

본 프로젝트는 TTS 엔진을 교체하는 프로젝트가 아니다. 기존 Luna를 중심으로 아래 기능을 추가한다.

- Candidate B 조건값 고정 캐시
- 오디오 건전성 검사
- 원문/ASR/한국어 강제정렬 검사
- 화자 동일성 검사
- 승인·반려 이력 기반 Prosody Bank
- 사람이 고른 take를 학습하는 Preference Ranker
- 기존 선택을 바꾸지 않는 shadow orchestration
- 문장 전체/의미절/기존 구절 방식의 실험
- 충분한 근거가 확보된 뒤에만 production feature flag 통합

---

## 2. 비목표

다음은 이 프로젝트의 목표가 아니다.

- GPT-SoVITS, CosyVoice, Fish, Qwen, XTTS, RVC 등으로 Luna 엔진 교체
- 외부 인물 음성 복제 또는 음원 재사용
- 공개 Chatterbox fine-tuning 코드를 검증 없이 V3에 적용
- deep learning 기반 거대 선호모델을 처음부터 학습
- SpeechMOS만으로 자연스러움 확정
- 장문 전체를 무조건 한 번에 합성
- 기존 동결 오디오 일괄 재생성
- 기존 캐시 포맷을 한 번에 폐기
- 기존 entry point 변경

---

## 3. 검증된 기술 사실과 설계 반영

### 3.1 Candidate B 조건값 캐시

Chatterbox Multilingual 구현의 `Conditionals`는 T3 조건과 S3Gen 조건을 저장하고 로드할 수 있다. Candidate B 레퍼런스에서 계산되는 화자 임베딩·prompt speech token·S3Gen reference feature를 캐시할 수 있다.

설계 반영:

- 레퍼런스 WAV를 매번 다시 분석하는 대신 검증된 조건 캐시를 선택적으로 로드한다.
- 캐시 키에는 모델 버전, T3 checkpoint hash, VE/S3Gen hash, tokenizer hash, reference WAV hash, exaggeration을 포함한다.
- 캐시가 하나라도 불일치하면 사용하지 않는다.
- 캐시 미사용 시 기존 레퍼런스 분석 경로로 폴백한다.
- 이 기능만으로 prosody가 결정적으로 고정된다고 주장하지 않는다. T3 음성 토큰 생성은 계속 확률적이다.

### 3.2 WhisperX 한국어 정렬

WhisperX는 ASR과 word-level forced alignment를 제공하며 한국어 기본 alignment model 경로가 존재한다.

설계 반영:

- 원문 누락·삽입·반복·오독 검사의 보조 수단으로 사용한다.
- 숫자, 단위, 영문 약어, 혼합 표기는 TTS 기대 발음 문자열로 정규화한 뒤 비교한다.
- WhisperX가 억양 또는 자연스러움을 판정한다고 가정하지 않는다.
- optional dependency로 유지한다.

### 3.3 SpeechBrain 화자 검증

SpeechBrain은 cosine similarity 기반 speaker verification 인터페이스를 제공한다.

설계 반영:

- Chatterbox 자체 Voice Encoder 점수를 1차 화자 점수로 사용한다.
- SpeechBrain ECAPA 계열 점수는 독립 보조 점수로 사용한다.
- 일반 기본 threshold를 Luna 기준으로 쓰지 않는다.
- 승인 Luna, 반려 Luna, Candidate B로 별도 calibration을 수행한다.

### 3.4 SpeechMOS/UTMOS

SpeechMOS는 UTMOS 기반 예측 MOS를 제공한다.

설계 반영:

- 심한 합성음·깨짐·소음·전체적 저품질을 제거하는 보조 신호로만 사용한다.
- Luna 취향, 의미 강조, 질문 종결, 특정 조사 억양의 최종 판정기로 쓰지 않는다.
- 하드 게이트 위반을 MOS가 보상할 수 없다.

### 3.5 Chatterbox Multilingual V3 fine-tuning

공개 `chatterbox-finetuning` 프로젝트는 확인된 코드 기준 일반 Chatterbox/Turbo 중심이며 Luna production의 Multilingual V3와 직접 호환된다고 입증되지 않았다.

설계 반영:

- fine-tuning은 현 단계의 production 로드맵에서 제외한다.
- 향후 별도 challenger 연구로만 다룬다.
- 이 프로젝트의 성공을 fine-tuning에 의존시키지 않는다.

---

## 4. 핵심 아키텍처

```text
JOBS.json
   │
   ▼
기존 Luna 텍스트 전처리/구절 분할
   │
   ▼
기존 Chatterbox V3 후보 생성
   │
   ├────────────── 기존 production 경로 ──────────────┐
   │                                                   │
   ▼                                                   │
Luna Quality Orchestrator (초기 shadow)                 │
   │                                                   │
   ├─ Audio Sanity Validator                           │
   ├─ Content/ASR Validator                            │
   ├─ Speaker Identity Validator                       │
   ├─ Existing Prosody Gate Adapter                    │
   ├─ Optional MOS Adapter                             │
   └─ Preference Ranker                                │
   │                                                   │
   ▼                                                   │
Shadow report / 추천 take                              │
   │                                                   │
   └──────── 실제 선택 변경 없음 ───────────────────────┘

충분한 검증 후:

feature flag select mode에서만
Hard-gate 생존 후보 → Preference Ranker → 최종 take
```

---

## 5. 모듈 경계

권장 신규 패키지 경로:

```text
scripts/luna_quality/
├── __init__.py
├── contracts.py
├── config.py
├── hashing.py
├── capability.py
├── conditionals/
│   ├── cache.py
│   └── manifest.py
├── validators/
│   ├── audio_sanity.py
│   ├── content_asr.py
│   ├── speaker_identity.py
│   ├── prosody_adapter.py
│   └── mos_adapter.py
├── adapters/
│   ├── whisperx_adapter.py
│   ├── speechbrain_adapter.py
│   └── chatterbox_ve_adapter.py
├── prosody_bank/
│   ├── schema.py
│   ├── sqlite_store.py
│   ├── ingest.py
│   └── queries.py
├── ranking/
│   ├── features.py
│   ├── pairwise.py
│   ├── train.py
│   ├── evaluate.py
│   └── artifact.py
├── orchestrator/
│   ├── engine.py
│   ├── policy.py
│   └── report.py
├── experiments/
│   └── hybrid_synthesis/
│       ├── planner.py
│       ├── runner.py
│       └── evaluator.py
└── cli.py

tests/luna_quality/
├── unit/
├── integration/
├── fixtures/
└── regression/
```

실제 저장소 구조가 다르면 S00 보고서에서 매핑을 제안한다. 사용자 승인 없이 기존 production 파일을 이동하지 않는다.

---

## 6. 공통 데이터 계약

최소 공통 타입:

### 6.1 `TakeIdentity`

```text
block_id
phrase_id
take_id
seed
text
text_hash
source_wav_path
source_json_path
```

### 6.2 `ValidationResult`

```text
validator_name
validator_version
status: pass | fail | unknown | not_run
hard_gate: bool
score: optional float
threshold: optional float
reasons: list[str]
metrics: dict[str, scalar]
artifacts: dict[str, path]
source_hashes: dict[str, sha256]
started_at
finished_at
```

### 6.3 `TakeEvaluation`

```text
identity
validations[]
existing_prosody_metrics
ranking_features
hard_gate_pass
rank_score
rank_model_version
recommended
```

### 6.4 `ProsodyBankRecord`

```text
record_schema_version
project_id
block_id
phrase_id
take_id
text
sentence_class
syllable_count
duration
syllables_per_second
pitch_median_hz
pitch_range_st
tail_delta_st
relative_tail
final_glide_st_per_s
final_rebound_st
speaker_similarity_chatterbox
speaker_similarity_speechbrain
asr_text
content_error_rate
utmos_score
selected
rejected_reason
source_hashes
created_at
```

모든 record는 schema version과 provenance hash를 가져야 한다.

---

## 7. 판정 정책

### 7.1 하드 게이트

다음 위반은 다른 점수로 보상할 수 없다.

- WAV 손상, NaN/Inf, 0 길이
- 심한 clipping 또는 비정상 무음
- 원문 핵심 단어 누락 또는 원문 외 반복
- 화자 유사도 calibration 기준 미달
- 기존 Luna prosody 필수 게이트 위반
- validation 실행 오류를 성공으로 위장한 경우

### 7.2 보조 점수

아래는 생존 후보 사이의 순위에만 사용한다.

- SpeechMOS/UTMOS
- 승인 Luna와의 feature distance
- 앞뒤 구절 연결 자연스러움
- 선호 ranker 점수
- 처리 시간

### 7.3 unknown 처리

optional dependency가 없거나 측정 불가할 때는 `unknown` 또는 `not_run`이다. 임의로 `pass`로 바꾸지 않는다.

production mode 정책은 단계 S10에서 명시적 feature flag와 함께 결정한다.

---

## 8. Prosody Bank 설계

초기 구현은 SQLite를 권장한다.

이유:

- 로컬 단일 사용자 환경에 충분함
- 외부 DB 설치가 필요 없음
- provenance와 schema migration을 관리하기 쉬움
- query와 pairwise training dataset 생성이 간단함

권장 테이블:

```text
projects
blocks
phrases
takes
validation_results
prosody_features
selection_events
rank_models
schema_migrations
```

오디오 binary는 DB에 넣지 않는다. 경로와 SHA256만 저장한다.

필수 특성:

- 동일 입력 재수집 시 idempotent
- source hash가 달라지면 새 revision
- 기존 `pins.json`의 선택을 selection event로 저장
- 선택되지 않은 후보는 자동으로 반려로 단정하지 않음
- 명시적 반려 사유와 단순 비선택을 구분
- 동결 프로젝트는 read-only provenance로 관리

---

## 9. Preference Ranker 설계

초기 모델은 작고 설명 가능한 pairwise ranker로 시작한다.

권장 1차 구현:

- pairwise logistic regression
- 표준화된 수치 feature
- block/script 단위 group split
- 고정 seed
- feature schema hash
- model artifact와 training manifest 저장

학습쌍 예시:

```text
pins.json에서 take 5 선택
→ take 5 > take 1
→ take 5 > take 2
→ take 5 > take 3
...
```

주의:

- 선택되지 않았다는 이유만으로 심각한 반려라고 간주하지 않는다.
- 동일 문장 후보가 train/test에 동시에 들어가면 leakage다.
- 모든 데이터가 한두 문장 유형에 몰리면 자동 선택을 비활성화한다.
- 모델 score는 하드 게이트를 우회하지 못한다.
- 충분한 데이터가 없으면 `insufficient_data` 상태를 반환한다.

필수 평가:

- top-1 pin 일치율
- top-3 pin 포함률
- pairwise accuracy
- grouped cross-validation
- 문장 종류별 성능
- 모델 미사용 baseline 대비 개선
- 사람 청취 후보 수 감소율

---

## 10. Hybrid Synthesis 실험

세 가지 모드를 비교한다.

### A. Existing phrase mode

현행 약 10음절 구절별 독립 합성.

### B. Sentence mode

문장 전체 합성 후 강제 정렬로 구절 시각만 추출.

### C. Hybrid mode

- 짧은 문장: 문장 전체
- 긴 문장: 의미 절/연결어미 단위
- 안정성 한도 초과: 기존 phrase mode 폴백

실험 원칙:

- 기존 production 캐시와 다른 output root 사용
- 동일 대본, 동일 후보 수, 동일 seed policy
- 동결 프로젝트 제외
- 기존 오디오 덮어쓰기 금지
- hallucination, 내용 정확도, speaker drift, prosody, 블라인드 선호를 함께 평가
- 실험 결과만으로 자동 promotion 금지

도입 후보 기준은 사용자가 승인한다. 기본 제안은 블라인드 선호 65% 이상, 원문 오류 증가 없음, 화자 유사도 저하 없음, 기존 반려 유형 증가 없음이다. 이 수치는 기술 사실이 아니라 의사결정 기준 제안이다.

---

## 11. Feature Flag

S10 이전에는 production code에 flag를 추가하지 않는다.

S10 권장 flag:

```text
LUNA_QUALITY_MODE=off|shadow|select
LUNA_CONDITIONALS_CACHE=off|on
LUNA_ASR_VALIDATOR=off|on
LUNA_SPEAKER_VALIDATOR=off|on
LUNA_MOS_VALIDATOR=off|on
LUNA_PREFERENCE_RANKER=off|shadow|select
LUNA_HYBRID_SYNTHESIS=off|experiment
```

기본값:

```text
LUNA_QUALITY_MODE=off
나머지 기능도 off
```

최초 배포는 `shadow`만 허용하고, selection 변경은 별도 사용자 승인 후 활성화한다.

---

## 12. 실패와 폴백

- 신규 validator import 실패: 기존 pipeline은 계속 동작하되 shadow report에 오류 기록
- conditionals cache 무효: 기존 WAV condition 생성 경로 사용
- ASR 모델 없음: content validation `not_run`, 기존 production 선택 유지
- speaker model 없음: secondary score `not_run`, primary Chatterbox VE만 사용 가능
- ranker artifact 불일치: ranker 비활성화
- DB schema mismatch: migration 없이 자동 수정 금지
- hybrid experiment 실패: existing phrase mode로 experiment 종료, production 영향 없음
- output report 실패: production selection을 변경하지 않음

select mode에서는 fail-open/fail-closed 정책을 별도로 명시해야 하며, 사용자 승인 전 기본 동작은 fail-open + 기존 선택 유지다.

---

## 13. 성능 원칙

- 모델은 한 stage/run에서 가능한 한 한 번만 로드한다.
- Candidate B conditionals는 hash 검증 후 재사용한다.
- 동일 WAV의 feature와 embedding을 content hash 기준으로 캐시한다.
- CPU 환경을 기본 가정한다.
- optional validator를 순차적으로 로드·해제해 메모리 충돌을 피한다.
- 실제 오디오 후보 생성과 validator 실행을 분리한다.
- 동일 take를 여러 validator가 각각 다시 resample하지 않도록 공통 audio view를 사용한다.
- SQLite transaction과 bulk insert를 사용한다.
- ranker는 작은 모델로 유지한다.
- 전체 repo를 매 단계 다시 분석하지 않도록 S00 manifest와 stage report를 후속 단계 입력으로 사용한다.

---

## 14. 보안·라이선스·개인정보

- Candidate B 및 private voice source는 public repo에 올리지 않는다.
- 오디오 경로와 hash만 기록하며 실제 private WAV 복사본을 신규 artifact에 포함하지 않는다.
- Git LFS 또는 private storage 정책은 기존 저장소 정책을 따른다.
- WhisperX, SpeechBrain, SpeechMOS 및 model weight의 라이선스는 S11에서 별도로 감사한다.
- 외부 음성 서비스로 private audio를 전송하지 않는다.
- 테스트 fixture는 합성/승인된 내부 샘플 또는 공개 사용 허가 샘플만 쓴다.

---

## 15. 완료 정의

프로젝트 완료는 단순 코드 작성이 아니다.

필수 조건:

1. 기존 production baseline이 유지된다.
2. 모든 신규 모듈은 독립적으로 비활성화 가능하다.
3. 각 validator가 구조화된 결과를 낸다.
4. Prosody Bank ingest가 idempotent하다.
5. ranker가 grouped evaluation을 통과한다.
6. shadow mode에서 실제 pin과 비교 보고가 생성된다.
7. hybrid experiment가 production과 완전히 격리된다.
8. select mode는 명시적 사용자 승인 전 비활성이다.
9. rollback 문서와 명령이 존재한다.
10. Luna narration skill 변경안은 증거와 함께 별도 제안되며 자동 반영하지 않는다.

---

## 16. 단계 종료 원칙

각 단계가 끝나면 다음 단계 코드를 선행 작성하지 않는다. Codex는 완료 보고서와 완료요청만 만든 뒤 종료한다. 다음 단계는 사용자가 모델을 바꾸고 `stage_gate.py advance`를 실행한 새 세션에서만 시작한다.
