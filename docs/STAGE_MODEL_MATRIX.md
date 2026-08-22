# Codex 단계별 모델·추론 강도 배정표

기준일: 2026-08-22

## 1. 배정 원칙

- **GPT-5.6 Sol**: 아키텍처 판단, 통계 설계, production 통합, 최종 감사처럼 오류 비용이 큰 단계
- **GPT-5.6 Terra**: 명확한 사양을 코드로 구현하고 테스트하는 대부분의 단계
- **GPT-5.6 Luna**: 문서 정리·단순 반복 수정 등 매우 기계적인 보조 작업에만 사용. 단계 책임 모델로는 사용하지 않음
- **GPT-5.3-Codex**: GPT-5.6 계열을 선택할 수 없을 때의 coding fallback
- **GPT-5.3-Codex-Spark**: 연구 미리보기 성격이며 단계 책임 모델로 사용하지 않음

GPT-5.6을 Codex에서 사용하려면 지원되는 최신 Codex 앱 또는 CLI가 필요하다. 모델 선택기에서 GPT-5.6을 볼 수 없으면 아래 fallback 열을 사용한다. Terra의 `Standard`는 별도 슬라이더가 보이지 않을 때 기본 reasoning 설정을 뜻한다. Pro 옵션은 Codex 선택기에 실제로 표시될 때만 S11의 선택적 대안이며 이 계획은 Pro를 필수로 가정하지 않는다.

---

## 2. 단계별 모델

| 단계 | 책임 모델 | 추론 강도 | fallback | 이유 |
|---|---|---:|---|---|
| S00 저장소 감사·baseline 동결 | GPT-5.6 Sol | High | GPT-5.3-Codex High | 기존 파이프라인 구조·캐시·동결 자산을 잘못 해석하면 이후 모든 단계가 틀어짐 |
| S01 계약·테스트 하네스 | GPT-5.6 Terra | Standard | GPT-5.3-Codex Medium | 요구사항이 명확하고 production 동작을 바꾸지 않는 구조화 구현 |
| S02 Candidate B conditionals cache | GPT-5.6 Terra | Standard | GPT-5.3-Codex Medium | 공식 Conditionals save/load를 안전하게 감싸는 제한된 구현 |
| S03 오디오 건전성 validator | GPT-5.6 Terra | Standard | GPT-5.3-Codex Medium | 결정적 DSP·threshold·테스트 중심 작업 |
| S04 ASR·WhisperX 내용 정렬 | GPT-5.6 Terra | High | GPT-5.3-Codex High | 한국어 정규화, optional dependency, 숫자·단위 예외가 있어 추론 필요 |
| S05 화자 동일성 validator | GPT-5.6 Terra | High | GPT-5.3-Codex High | Chatterbox VE와 SpeechBrain의 역할 분리 및 calibration 설계 필요 |
| S06 Prosody Bank·이력 수집 | GPT-5.6 Sol | High | GPT-5.3-Codex High | schema, provenance, idempotency, 기존 pins 의미 구분이 핵심 |
| S07 Preference Ranker | GPT-5.6 Sol | Extra High | GPT-5.3-Codex High | pairwise 학습, leakage 방지, grouped evaluation 판단이 가장 어려움 |
| S08 Shadow Orchestrator | GPT-5.6 Terra | High | GPT-5.3-Codex High | 여러 validator 연결과 production 무영향 보장이 핵심 |
| S09 Hybrid Synthesis 실험 | GPT-5.6 Sol | Extra High | GPT-5.3-Codex High | 실험 설계, 캐시 격리, 공정 비교, 장문 안정성 판단 필요 |
| S10 Production feature-flag 통합 | GPT-5.6 Sol | High | GPT-5.3-Codex High | 기존 entry point·출력·rollback을 보존해야 하는 고위험 변경 |
| S11 최종 회귀·라이선스·release 감사 | GPT-5.6 Sol | Extra High | GPT-5.3-Codex High | 전체 증거를 종합해 배포 여부를 판단하는 마지막 방어선 |

---

## 3. 효율적인 모델 사용 규칙

1. 한 단계 안에서 모델을 바꾸지 않는다.
2. 단계마다 새 Codex 세션을 연다.
3. 이전 단계 전체 대화를 붙이지 않는다. 아래 파일만 읽게 한다.
   - `AGENTS.md`
   - 현재 stage prompt
   - 바로 이전 단계 report
   - S00 baseline manifest
   - 구현에 필요한 코드
4. Sol은 판단·설계 단계에 집중하고, 명확한 구현은 Terra에 맡긴다.
5. Extra High는 S07, S09, S11에만 사용하고 S10은 High를 기본으로 한다.
6. Fast mode는 출력량이 많고 복잡한 단계에서는 사용하지 않는다.
7. Luna 또는 Spark를 사용해 핵심 코드·threshold·통계 판단을 확정하지 않는다.
8. 동일 단계 재시도는 같은 모델을 유지하고, 실패 원인만 추가 컨텍스트로 준다.
9. 다음 단계 모델은 사용자가 직접 선택한 뒤 새 세션에서 시작한다.

---

## 4. 모델 선택기에서 옵션이 다를 때

- Sol High가 없고 Medium만 있으면 S00~S06은 Medium으로 진행 가능하다.
- S07·S09·S11에서 Extra High가 없으면 Sol High를 사용한다.
- Terra가 없으면 GPT-5.3-Codex를 사용한다.
- GPT-5.4 계열은 2026-08-31 Codex retirement 예정이므로 신규 단계 계획에 넣지 않는다.
- 모델 이름이 달라졌으면 현재 Codex의 최신 공식 모델 목록을 확인하고 다음 원칙으로 치환한다.
  - 최고 추론 모델 → Sol 역할
  - 균형형 coding 모델 → Terra 역할
  - 최저비용 모델 → Luna 역할
