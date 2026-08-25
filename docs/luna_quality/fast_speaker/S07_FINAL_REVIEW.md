# Luna FAST Speaker v1 S07 최종 검토

## 최종 판정

FAST Speaker v1의 기능·회귀·실제 발화 검증을 완료했다. S07 감사 중 발견한 v1 결함은 모두 수정한 뒤 재검증했으며, 현재 확인된 출시 차단 항목은 없다.

실제 음성 검사는 Chatterbox Multilingual V3 + Candidate B로 한국어 두 구절을 생성해 WAV 저장 없이 Windows 기본 스피커의 `waveOut` 메모리 PCM 경로로 끝까지 재생했다. 다만 현재 CPU 실행 성능은 실시간 수준이 아니며, 자연스러움과 취향은 사용자의 청취 판정이 최종 기준이다.

## 요구사항별 판정표

| 영역 | 요구사항 | 판정 | 검증 근거 |
|---|---|---:|---|
| 실행 | Tkinter 앱 직접 실행 | PASS | `scripts/luna_fast_speaker.py` 직접 실행과 실제 창 표시 확인 |
| 실행 | 별도 resident worker 자동 로드 | PASS | 실제 창 로딩 상태 및 실제 worker READY 확인 |
| 실행 | 모델 로딩 중 UI 반응 | PASS | 로딩 중 실제 창 활성화·화면 캡처·정상 종료 확인 |
| UI | 핵심 버튼 전체 표시 | PASS | 버튼을 3개 행으로 재배치한 뒤 실제 창에서 잘림 없음 확인 |
| UI | 한글 중심 조작 문구 | PASS | 수동/배치/발화/중지/문제/재검증/규칙/재시작 문구 확인 |
| 입력 | 여러 문장·새 입력 대기열 | PASS | controller queue 및 최근 3개 제한 테스트 |
| 입력 | `Ctrl+Enter`와 발화 버튼 | PASS | UI binding과 활성화 상태 검사 |
| 스트리밍 | 첫 구절 완료 즉시 재생, 다음 구절 prefetch | PASS | controller 테스트와 실제 2구절 재생 |
| 오디오 | Windows 기본 출력, 메모리 PCM | PASS | 실제 `WinmmAudioSink` 24 kHz PCM16LE 재생 완료 |
| 오디오 | 정상 발화 WAV 미저장 | PASS | 실제 검사 전후 `fast_speaker/**/*.wav` 집합 동일 |
| 오디오 | 마지막 구절·현재 문장 캐시 재생 | PASS | 재합성 요청 수가 늘지 않는 인간형 E2E 테스트 |
| 제어 | Stop 즉시 정지·stale 결과 차단 | PASS | 늦은 결과 미재생 및 Stop 직후 새 발화 정상 진행 테스트 |
| 제어 | Pause는 현재 구절 종료 후 정지 | PASS | pause/continue 경계 테스트와 인간형 E2E |
| 배치 | 붙여넣기와 TXT/MD 불러오기 | PASS | UI 경로 및 source path 저장 |
| 배치 | 줄바꿈 우선·문장부호 추가 분할 | PASS | parser 회귀 테스트 |
| 배치 | 정상 종료 자동 PASS | PASS | batch 상태 테스트와 인간형 E2E |
| 배치 | 문제 문장 ISSUE·해결 후 문장 처음부터 재개 | PASS | `resume_from_sentence` 및 RESOLVED 연결 테스트 |
| 세션 | 전환 시 원자 저장 | PASS | 임시 파일 + `os.replace` 구현·테스트 |
| 세션 | 비정상 종료 후 진행 문장 처음부터 복구 | PASS | `PLAYING -> PENDING`, 최신 세션 자동 복원 테스트 |
| 세션 | 원문·경로·상태·문제 링크·코드 버전 저장 | PASS | session schema v2 round-trip 테스트 |
| 문제 | 최근 3개 구절 ID·문맥 선택 | PASS | bounded recent history와 실제 UI 선택 문자열 검사 |
| 문제 | 발음/억양/분할/속도·호흡/기타 분류 | PASS | 한글 UI 분류와 enum 저장 |
| 문제 | 발음 문제 필수 3개 필드 | PASS | 누락 거부 및 정상 저장 테스트 |
| 문제 | 문제일 때만 WAV/JSON/MD 생성 | PASS | issue 전용 저장 테스트와 실제 정상 발화 무WAV 검사 |
| 문제 | 완전한 Codex 재현 요청 | PASS | 문장·문맥·seed·설정·해시·증거·재현·회귀·금지·종료 지시 검사 |
| 재검증 | 동일 issue ID revision 유지 | PASS | r001/r002 저장·복원 테스트 |
| 재검증 | 이전 음성/최신 재검증 음성 별도 재생 | PASS | 현재 revision 기준 별도 경로 선택 검사 |
| 규칙 | FAST-test overlay 초기 무변경 | PASS | 빈 replacement 초기 파일 |
| 규칙 | transactional reload·실패 rollback | PASS | 잘못된 JSON/금지 key에서 이전 snapshot 유지 테스트 |
| 규칙 | reload 시 model/reference 미재로드 | PASS | rule 모듈 경계와 실제 worker 비접근 검사 |
| 재시작 | worker만 재시작, UI/session/issue 유지 | PASS | fake 및 실제 worker restart, session byte-equivalent 검사 |
| 측정 | cold READY·warm TTFA·합성·길이·RTF | PASS | 실제 V3/Candidate B 수치 기록 |
| 연속성 | 구절 간 gap/underrun 기록 | PASS | 실제 2구절 gap과 controller rolling metrics 기록 |
| 회귀 | 현재 FAST 분할·설정·출력 계약 유지 | PASS | FAST baseline 및 adapter 회귀 테스트 |
| 회귀 | production entrypoint/동작 유지 | PASS | production 회귀 10개 및 pipeline 해시 확인 |
| 불변 | V3/Candidate B/고정 파라미터 유지 | PASS | 해시·설정 fixture·실제 metadata 확인 |
| E2E | 인간형 전체 흐름 | PASS | 배치→일시정지/캐시재생→문제→reload rollback→retest→resolved→문맥 재개→worker 교체→crash 복구 단일 테스트 |

## 실제 발화 성능

측정 문장:

- `루나 실제 발화 검사입니다.`
- `두 번째 구절도 재생합니다.`

| 항목 | 측정값 |
|---|---:|
| Cold READY | 89.759초 |
| Warm TTFA | 44.798초 |
| 구절 1 합성 / 음성 / RTF | 44.191초 / 2.160초 / 20.459 |
| 구절 2 합성 / 음성 / RTF | 39.890초 / 2.040초 / 19.554 |
| 평균 RTF | 20.006 |
| 구절 간 공백 | 39.942초 |
| underrun | 1회 |
| Worker restart READY | 31.503초 |
| 출력 형식 | 24 kHz, mono, PCM16LE, Windows 기본 스피커 |
| 정상 WAV 생성 | 없음 |

수치상 기능은 정상이나 CPU에서 합성이 음성 길이보다 약 20배 느려 다음 구절이 재생보다 앞서지 못했다. v1에는 사전 합의된 성능 합격 숫자가 없으므로 측정 항목은 PASS지만, true-real-time 성능은 달성하지 못했다.

## 검증 이력

1. 1차 전체 자동 검증: 124개 단위 테스트 통과. 코드 감사에서 Stop 이후 새 발화, 앱 자동 복구, 문제 보고서 완전성 결함 발견.
2. 수정 후 FAST 집중 검증: 25개 통과.
3. 실제 발화 및 실제 worker restart: 1개 통과, 207.655초.
4. 실제 UI 검증 1차: 직접 실행 import 오류와 오른쪽 버튼 잘림 발견.
5. launcher와 UI 배치 수정 후 실제 UI 검증 2차: 창 실행, 한글 핵심 버튼 전체 표시, 로딩 중 반응 확인.
6. 인간형 통합 흐름: 1개 통과.
7. 최종 전체 검증: 단위 130개 통과, production/FAST 회귀 10개 통과(별도 opt-in real repeatability 1개는 기본 실행에서 skip, S01에서 이미 실제 통과 기록).

## 보호 항목

- Candidate B SHA-256: `30C6D3405F46684AF467C7D26FF40A2FB57DD48CC84CD24CF7403D9AA00A2BB9`
- Luna prosody target SHA-256: `267E79EC088933C9C43B6584E90BD04B2B4E77EABA3134A669D151C464458BAE`
- Production pipeline SHA-256: `781FD5D74B7B8F427D1EE229E8E9D9D43EC0C145EEF8F1ABDDF296FCC93BC5BF`
- production pipeline, voice reference, engine 디렉터리 변경 없음.

## 알려진 한계

- 현재 CPU 측정에서 warm TTFA와 RTF가 커서 연속 실시간 발화가 아니다.
- 실제 오디오 장치 callback 완료는 확인했지만 Luna다운 자연스러움·발음 취향의 최종 합격은 사람의 청취 판정이 필요하다.
- v1은 Windows 기본 출력만 지원하며 장치 선택 UI는 없다.
- 문제 규칙은 FAST-test overlay에만 적용되며 production 승격은 별도 사용자 승인이 필요하다.

## 이후 권고사항 — 구현하지 않음

- 동일 품질·동일 V3/Candidate B 조건을 유지한 채 warm TTFA와 RTF의 병목을 별도 계측한다.
- 충분한 실제 문제/승인 corpus가 쌓인 후 single-take 성공률과 true-real-time 전략을 별도 v2 범위로 검토한다.
- production 규칙 승격은 반복 재현 증거와 사용자 청취 승인 후 독립 단계로 수행한다.

## 차단 항목

없음.
