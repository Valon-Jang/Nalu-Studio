# 실행팩 자체 검증 결과

검증일: 2026-08-22

Nalu 경로 재검증일: 2026-08-23

## 정적 검증

- `tools/stage_gate.py` Python compile: PASS
- `.codex/stage_plan.json` JSON parse: PASS
- ZIP integrity: PASS

## Nalu 스튜디오 경로 검증

- 저장소 기준 상대경로 사용: PASS
- `scripts/luna_narration_pipeline_v1.py` 존재: PASS
- `engine/chatterbox-v3/venv/Scripts/python.exe` 존재: PASS
- `engine/chatterbox-v3/chatterbox/src` 존재: PASS
- `engine/chatterbox-v3/hf-cache` 존재: PASS
- 내장 Python 3.12.10에서 `torch 2.6.0+cpu`, `torchaudio 2.6.0+cpu`, `ChatterboxMultilingualTTS` import: PASS
- `assets/voice_ref/B_voiced_spectral_micro_smooth.wav` 존재: PASS
- Candidate B SHA256 `30C6D340...A00A2BB9`: PASS
- `assets/voice_ref/LUNA_PROSODY_TARGET.json` 존재: PASS
- 저장소 스킬 발견 경로 `.agents/skills/luna-narration/SKILL.md`: PASS

현재 Nalu 폴더에는 아직 `.git`이 없으므로 실제 단계 게이트 설치 전 `git init`이 필요하다. 실행팩 검증 실패가 아니라 적용 선행 조건이다.

## 임시 Git 저장소 End-to-End 검증

다음 흐름을 실제 임시 저장소에서 실행했다.

1. 실행팩 커밋
2. 사용자 key로 S00 init
3. signed state 커밋
4. signature verify
5. S00 scope check
6. S00 허용 경로에 audit/report 생성 및 커밋
7. completion request 생성
8. 사용자 key로 S01 advance
9. S01 state 커밋
10. S01 scope check

결과: PASS

## 차단 검증

- S01에서 S02 전용 `conditionals/cache.py` 선행 생성: scope violation으로 BLOCK
- protected `AGENTS.md` 변조: protected hash mismatch로 BLOCK
- `LUNA_STAGE_GATE_KEY`가 없는 프로세스에서 `advance`: BLOCK
- `LUNA_STAGE_GATE_KEY`가 노출된 Codex 프로세스에서 `codex-safe`: BLOCK

## 강제 수준 주의

로컬 instruction과 HMAC은 자동 진행 실수를 막는다. 에이전트가 guard 파일 자체를 바꾸어 merge하는 것까지 외부 권한으로 차단하려면 GitHub required check와 CODEOWNERS/ruleset을 함께 설정해야 한다.
