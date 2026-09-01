---
name: luna-narration
description: Nalu YouTube 내레이션(나레이션) 생성 규칙. 새 영상 대본의 음성 합성, Luna 목소리 작업, 내레이션 재생성, 억양 수정 요청 시 반드시 이 스킬을 로드한다. Use when creating or fixing any Nalu narration audio, Luna voice synthesis, or when a script needs TTS narration.
---

# Luna 내레이션 생성 규칙 (Nalu)

## 목소리 — 절대 불변

- **Luna = Chatterbox Multilingual V3 + Candidate B 레퍼런스만 사용.**
  - venv: `<repo>\engine\chatterbox-v3\venv\Scripts\python.exe` (CPU, 모델 로드 ~60초) — 2026-08-08 이전엔 Windows Temp에 있었으나 삭제 위험 때문에 프로젝트 내부(`engine/chatterbox-v3/`)로 영구 이전함. venv/hf-cache/chatterbox 소스 전부 이 아래에 있음.
  - 레퍼런스 wav: `assets/voice_ref/B_voiced_spectral_micro_smooth.wav` (sha256 30C6D34...)
  - 파라미터: exaggeration 0.5 / cfg 0.5 / temperature 0.72 / repetition_penalty 1.2 / min_p 0.05 / top_p 1.0 / language_id "ko"
- heami·xtts·qwen·neural 등 다른 엔진으로 절대 대체 금지 (과거 세션들이 이걸로 이탈해 CEO 불만).
- 신비한건축사전 내레이터의 **음성 복제·오디오 재사용 금지** — 억양 통계만 사용.

## 유일한 진입점

```
venv_python -X utf8 scripts/luna_narration_pipeline_v1.py JOBS.json OUTDIR
```

- `JOBS.json` = `{"blocks":[{"id":"B01","text":"대본 문장들...","seed":정수}, ...]}`
- 출력: `OUTDIR/<id>_luna.wav` + `<id>_report.json`(구절 타임라인 — 자막 생성에 사용) + `pipeline_report.json`
- 블록별 수동 튜닝 금지. 대본이 바뀌어도 이 파이프라인 하나로 처리한다.
- 목표 수치의 원본: `assets/voice_ref/LUNA_PROSODY_TARGET.json` (신비한건축사전 6편 측정치 + CEO 검증 이력)

## Luna Quality System — 모든 내레이션 생성에 필수

기존 TTS만 단독 실행하지 않는다. 모든 Luna 생성 작업은 기존 production
파이프라인에 Luna Quality System을 함께 연결한다. Luna의 생성 엔진과
정체성은 계속 Chatterbox Multilingual V3 + Candidate B이며, 다른 TTS나
VC/RVC를 섞지 않는다.

현재 검증된 릴리스 경계는 `SHADOW_ONLY_APPROVED`다. 따라서 Quality System은
반드시 실행하되 production 선택을 자동으로 바꾸는 `select`는 승인된 실제
ranker·speaker calibration·USER approval manifest가 모두 준비되기 전까지
사용하지 않는다.

### 기본 실행 설정

```powershell
$env:LUNA_QUALITY_MODE = 'shadow'
$env:LUNA_CONDITIONALS_CACHE = 'on'
$env:LUNA_ASR_VALIDATOR = 'on'
$env:LUNA_SPEAKER_VALIDATOR = 'on'
$env:LUNA_MOS_VALIDATOR = 'on'
$env:LUNA_PREFERENCE_RANKER = 'shadow'
$env:LUNA_HYBRID_SYNTHESIS = 'off'
```

- `LUNA_QUALITY_MODE=off`로 생성하지 않는다.
- 구현되어 정상 작동 가능한 validator와 ranker는 임의로 끄지 않는다.
- flag가 `on`이어도 dependency·model·calibration·artifact가 없으면 결과는
  `unknown` 또는 `not_run`이다. 이를 `pass`로 표현하지 않는다.
- WhisperX, SpeechBrain, MOS 또는 model revision을 검증 없이 다운로드하거나
  설치해 빈 칸을 억지로 채우지 않는다.
- unavailable 항목이 있으면 기존 gate만으로 최종 취향을 확정하지 않는다.
  후보와 별도 quality report를 보존하고 사용자 비교 청취로 전환한다.
- conditionals cache는 Candidate B와 V3 source/checkpoint/reference hash가
  정확히 맞을 때만 사용한다. 불일치하면 기존 Candidate B 분석 경로로
  폴백하되 Quality System 자체를 끄지는 않는다.

### 필수 평가 순서

1. 생성 전에 기존 `pins.json`, Prosody Bank, ranker artifact, speaker
   calibration, 승인 manifest와 optional validator 가용성을 확인한다.
2. Chatterbox V3 + Candidate B와 고정 synthesis parameter로 여러 take를
   생성한다.
3. Audio Sanity와 ASR/원문 일치 검사로 손상, clipping, 비정상 무음, 오독,
   누락, 삽입, 반복, hallucination을 먼저 분리한다.
4. 승인된 calibration이 있으면 Luna speaker identity를 검사한다. calibration이
   없으면 `unknown`이며 화자 통과로 간주하지 않는다.
5. 기존 pitch/speed/tail/curl/rebound와 문장 연결 수치를 측정하되, 아래의
   취향 지표를 단독 hard reject로 사용하지 않는다.
6. 동일 문장 유형의 Prosody Bank 기록, 과거 사용자 승인 take, 기존 pin과
   Preference Ranker 결과를 함께 비교한다.
7. legacy gate와 사용자 이력/ranker 판단이 충돌하면 양쪽 결과와 이유를
   quality report에 남긴다.
8. 기술적 오류가 없는 상위 후보는 gate 결과와 무관하게 보존하여 사용자가
   직접 비교 청취할 수 있게 한다.

### Hard Reject와 Preference를 분리

다음은 다른 점수가 보상할 수 없는 기술적 hard reject다.

- 손상되거나 비어 있는 WAV, NaN/Inf
- 심한 clipping, noise 또는 비정상 무음
- 원문 핵심어 오독·누락·삽입·반복·hallucination
- 심각한 자음 왜곡
- 승인된 calibration 기준에서 Luna와 명백히 다른 화자

다음은 취향과 문장 기능에 따라 달라지는 preference/ranking feature다.
단독으로 최종 탈락을 결정하지 않는다.

- 절대 pitch level
- tail 절대·상대 낙폭
- final glide와 rebound
- 종결 기울기
- 허용 범위 안 속도의 미세한 차이
- 기존 quality score와 block median 선호값

현재 production JSON의 `ok=false`가 위 preference feature만으로 발생했다면
파일을 삭제하거나 명백한 불량으로 부르지 않는다. `legacy_gate_fail`과
`user_reviewable`을 함께 기록하고 비교 청취 후보로 유지한다.

### 문장 유형별 평가

최소한 다음 유형을 분리한다. 특정 `-요`/`-죠` 문제에서 얻은 종결 규칙을
모든 평서문에 그대로 적용하지 않는다.

- 일반 설명 평서문
- 단정적 기술 설명(`-입니다`, `-됩니다`)
- `-요` 종결
- `-죠` 종결
- 의문문
- 이어지는 구절과 강제분할 조각
- 숫자 포함 구절
- 강조 문장

sentence class를 Prosody Bank record와 preference pair에 함께 기록하고,
동일 유형의 승인 사례를 우선 비교한다. 유형 근거가 부족하면 threshold를
임의 조정하지 말고 사용자에게 후보를 들려준다.

### 사용자 선호는 최상위 학습 신호

사용자가 “좋다”, “더 자연스럽다”, “Luna 같다”, “어둡다”, “별로다”,
“1번이 더 좋다”처럼 평가하면 코멘트로만 소비하지 않는다.

- preferred take와 comparison take의 정확한 project/block/phrase/take ID,
  WAV·JSON SHA-256, 문장 유형, metrics, validator 상태와 사용자 표현을
  selection event로 기록한다.
- 예: `P00_t0 > P00_t10`.
- 사용자가 승인한 take는 legacy gate에서 탈락했어도 positive preference
  example로 보존하고 `legacy_gate_false_negative` 충돌을 기록한다.
- 단순히 선택되지 않은 후보를 명시적 반려로 바꾸지 않는다.
- 기존 `pins.json` 선택 이력을 Prosody Bank에 수집하고, 충분한 실제 pair가
  모였을 때만 grouped evaluation을 거쳐 ranker를 다시 학습한다.
- ranker가 `insufficient_data`, schema mismatch, low coverage 또는 low
  confidence이면 점수를 꾸미지 않는다. 상위 후보를 사용자에게 들려주어
  preference data를 추가 확보한다.

사용자가 좋은 후보를 이미 찾았으면 새 take 생성을 즉시 멈추고 기존 후보
비교와 preference 기록을 먼저 끝낸다. 사용자가 중단을 요청하면 현재 생성을
즉시 중단하며, 이미 완성된 후보와 측정 JSON은 삭제하지 않는다.

### 최종 선택 전 체크리스트

- Quality System이 실제로 `shadow` 또는 승인된 `select`로 실행됐는가
- 요청한 validator가 `pass/fail/unknown/not_run` 중 무엇을 반환했는가
- Preference Ranker가 실제 artifact를 로드했는가, 아니면
  `insufficient_data/not_run`인가
- Prosody Bank와 기존 pins/사용자 승인 이력을 조회했는가
- legacy gate와 ranker/사용자 선호 충돌을 기록했는가
- 기술적 hard reject가 아닌 상위 후보를 사용자 청취용으로 보존했는가

하나라도 확인할 수 없으면 기존 gate만으로 최종 취향을 확정하지 않는다.
목표는 기존 threshold에 가장 가까운 음성이 아니라, 같은 Luna 정체성을
유지하면서 실제 사용자가 가장 자연스럽다고 느끼는 take를 안정적으로
선택하는 것이다.

## 파이프라인이 하는 일 (전부 CEO 검증 완료 2026-08-05)

1. **구절 분할**: 문장→쉼표/연결어미 경계→~10음절(4~22) 구절. 한도 초과 시 연결형(-어/-아/-고/-서/-과/-와/-처럼…) 어미 단어 우선으로 강제 분할(조사에서 자르면 문장 끝처럼 읽혀서 CEO 반려됨). **수식어(-한/-된/-진/-인) 뒤 절단 금지** ("…유연한 | 부분이…" 반려). **-에서(처격) 뒤 절단 금지 + 연결어미 '서'로 오인 금지** — 동사구에 붙음 ("손목에서 | 거미줄을" 반려: "쉬지말고 이어버리자"). 리스펠 사전에 끊어진→끄너진 포함. 강제분할 조각 뒤 쉼은 0.05~0.10초(0이면 "순간 음소거"처럼 들림 — "부분과" 반려). 분할 규칙 변경 시 **동결된 프로젝트는 작업 목록에서 제외**할 것(분할이 바뀌면 캐시·확정 오디오 무효화).
2. **구절별 best-of-N** (기본 6, 의문문/강제분할 10; 전원 탈락 시 에스컬레이션 0.85→0.87→0.87 — 시드가 k에서 파생되므로 같은 풀 재실행은 같은 테이크만 나옴, 새 오디오가 필요하면 풀 확장뿐). **온도 0.9 금지: 자음 왜곡 사례** (긴 구간→"킨 구간", CEO 적발 — 발음 의심 구절은 재생성하고 저온 테이크 우선) + 게이트:
   - 말속도 5.6~7.2 음절/초 (숫자 구절 4.4~, **의문문 5.2~** — 의문문은 끝을 자연히 늘임)
   - 종결 기울기(st/s): 평서 [−35,+8]·프라이어 −12 (문장 끝 평서는 상한 −2) / **강제분할 조각 [−8,+4]·프라이어 −2** (수평 유지 — "돕지만" 검증)
   - **의문문(-까요/-나요/-가요) 끝은 직전 대비 tail 밴드가 주 게이트**: tail ∈ [−4.0,−1.5], 상대낙폭 ∈ [−0.40,−0.25] (합격 중심 "건널까요" −2.1/−0.30; 급하강 −4.8/−0.42 반려; 덜 떨어짐 −0.95/−0.11 반려; 올라감 "가능할까요" +0.45 반려). 창 기울기 [−10,−5]·프라이어 −6.5는 tail 측정 불가 시 폴백 전용 — 창 기울기는 마지막 음절을 뭉개므로 주 게이트로 쓰지 말 것 (CEO 감사에서 적발된 구멍)
   - 피치 폭 4~15 st
   - **절대 피치 레벨: 구절 중앙값 235Hz ±2st** — 연도처럼 높게 치고 들어가는 구절이 내내 떠 있으면 기울기가 정상이어도 이상함 ("육십오 년" 237Hz 좋음 vs "육십육 년" 307Hz 반려). 캐시된 테이크도 로드 시 현재 규칙으로 재판정됨(재생성 불필요)
   - **문장 끝 = 스텝 + 끝맺음 컬** (CEO 3차 라운드 실측 발견): "확실히 떨어짐"으로 들리는 형태는 단조 하강이 아니라 **직전 대비 한 계단 하강(스텝) 후 마지막 0.2초가 작게 되올라가는 끝맺음 컬**(활강 +9~+13 st/s, 되튐 ~3st). 반려 형태 두 가지: 끝에서 급락(−15~−18, 삼켜짐)·밋밋 유지(되튐 ≤1, 떠 있음). 게이트: 활강 ≥ +4 AND 되튐 ≥ 2.5st. **요/죠/까요 마침이 반복적으로 문제되는 근본 원인이 이것** — 창 기울기·중앙값 비교로는 못 잡음
   - **[설계 원리] 끝 낙폭의 기준은 항상 '직전 대비'** (CEO 2026-08-06): 사람 음높이는 상황에 따라 전체적으로 낮아질 수 있으므로, 기준음역·구절최고점 같은 고정 앵커로 끝음을 판정하면 오판이 생긴다. 낙폭은 직전 0.35초 대비로 잰다. (실측도 일치: 앵커 기반 M2/M3는 합·불 분리 실패, 직전 대비 기반만 성공. 단, 구절 **전체**가 떠 있는 문제는 별개로 절대 레벨 게이트 235Hz±2st가 담당 — 끝 판정과 역할 분리)
   - **문장 끝 이중 tail 게이트** (CEO: "그냥 떨어지고 안떨어지고보다 **상대 낙폭**이 필요해"): ① 절대 하강 tail_delta(끝 0.25초 vs 직전 0.35초) ≤ −1.5st ② **상대 낙폭 tail_delta÷구절피치폭 ≤ −0.28** — 반려 5개는 전부 ≥ −0.26, 합격 3개는 전부 ≤ −0.30. "넘어서죠"는 낮게 착지(−3.7st)했는데도 반려됨: 착지점이 아니라 **구절 스스로의 움직임 대비 낙폭**이 기준. 이어짐 구절은 면제("돕지만" −0.85가 정상). 문장 끝 평서 구절은 창 기울기 상한도 −2로 강화. 0.55초 창 기울기만으론 마지막 음절 들림을 뭉개서 못 잡음("낮아요" 창기울기 +5.5인데 통과했던 사고)
   - 품질 점수의 레벨 가중치는 6.0 — 레벨 이탈(확 들림)이 2% 느린 속도보다 훨씬 치명적 (B06 우선순위 역전 사고)
   - **자동 게이트의 한계 (정직 기록)**: 구절 중간 특정 음절의 취향 문제(스파이더'맨' 꺼짐, 아미노산'이' 들림, 몸속'에서' 떠 있음)는 일반화된 음절 통계로 합/불이 안 갈림(좋은 예시가 더 큰 꺼짐을 가짐). 이런 건 게이트 통과 테이크 여러 개를 CEO가 청취 선택 → `OUTDIR/<블록>_pins.json {"P02": 5}` 로 고정하는 픽커 방식으로 처리
3. **빔서치 조립**: 구절 간 피치 리셋 [−4,+13] st (목표 +4.65), 블록 종결 중앙값 [−20,−5].
4. **쉼 삽입**: 문장 중간 **0~0.02초(사실상 바로 연결 — CEO "B4가 너무 좋다")**, 문장 끝 0.38~0.60초.
5. 구절당 트림+30ms 패드, 12ms 페이드, RMS −20dBFS 정렬, 피크 0.89 가드.

## 운영 방법

- 체크포인트 방식: 죽어도 같은 명령 재실행이면 이어서 진행. 특정 구절만 재생성하려면 그 구절의 `P##_t*.{wav,json}`과 블록 `_report.json`/`_luna.wav`만 삭제 후 재실행.
- 장시간 작업은 `nohup ... &`로 분리 실행 + 로그 `tail -f` Monitor (완료/Traceback만 필터).
- 동시에 두 인스턴스 돌릴 땐 **jobs 파일을 블록별로 분리**(같은 블록 동시 접근 금지) + 나중 인스턴스에 `OMP_NUM_THREADS=4`.
- Windows 콘솔에 한글 출력 금지(cp949 깨짐) — 파일로 쓰고 Read로 읽는다.

## 억양 불만이 나오면 (규칙 진화 프로토콜)

1. 해당 구절의 `P##_t*.json` 테이크 지표를 좋은 예시와 **수치로 비교**한다 (귀로 추측 금지).
2. 테이크가 아니라 **규칙을 고친다** — 새 구절 클래스(게이트 밴드+프라이어)를 추가하거나 분할 규칙을 수정.
3. 근거를 `LUNA_PROSODY_TARGET.json`과 이 파일에 기록(CEO 발언 인용 포함).
4. 해당 구절 체크포인트만 삭제하고 재생성 — 좋다고 판정된 구절은 절대 다시 안 뽑는다.

## 후반 작업 연결

- 자막: `<id>_report.json`의 timeline(구절 텍스트+시각)에서 생성. ASS는 Name 필드 필수, WrapStyle 0, MarginV 540, 폰트는 로컬 `_fonts/`.
- 최종 블록은 태그 없이 합성하고 브랜드 아웃트로 `assets/youtube/nalu/brand_audio/NALU_BRAND_OUTRO_BRIGHT_48k.wav`를 뒤에 붙인다.
- 영상 규격: 1080x1920, 24fps, 최종 믹스 −14 LUFS.
