# Nalu (Nalu) — Luna 목소리 + 제작 지식 전용 프로젝트

> **Root 호환 주석 (2026-09-01):** 아래의 “음성 엔진 + 스킬 지식 전용” 범위는 2026-08-08 분리 당시 상태를 설명하는 역사 기록이다. 사용자의 현재 방향은 Luna 음성을 유지하면서 영상 제작까지 포함한다. 현재 방향과 문서 권위는 `.root/CURRENT.md`와 `.root/nodes/DOCUMENT_MAP.md`에서 확인하며, 이 주석은 `.agents/skills/luna-narration/SKILL.md`의 음성 불변 규칙을 변경하지 않는다.

2026-08-08, 무거워진 `Personal-AI-Venture-Orchestrator`에서 분리해 새로 시작.
**범위는 Luna 목소리 엔진 + 스킬 MD(지식)만.** 영상 제작 자산(Blender 스크립트, 렌더,
기획서, 조립 파이프라인, 브랜드 영상/텍스처 소스)은 의도적으로 가져오지 않았다 —
CEO 결정(2026-08-08): 영상 파이프라인은 아직 버그(A/V 드리프트)와 무게 문제가 있어서
그대로 옮기지 않고, 이 프로젝트에서 스킬 MD에 적힌 규칙/교훈을 참고해 새로 구축한다.
옛 프로젝트는 계속 존재하며 영상 원본 자산(스크립트·렌더 프레임)은 전부 그쪽에 있다.

## 로드해야 할 스킬 (작업 시작 시 항상 확인)

- `.claude/skills/luna-narration/SKILL.md` — Luna 목소리 생성. 어떤 나레이션 작업이든 이거 먼저.
- `.claude/skills/nalu-video/SKILL.md` — 영상 기획 문법(지식만, 코드 없음) — 새 영상 파이프라인 설계 시 참고.
- `.claude/skills/nalu-video-production/SKILL.md` — Blender 제작 레시피/함정 목록(지식만, 코드 없음) — 새로 구현할 때 참고.

## 이 프로젝트에 있는 것

| 자산 | 경로 |
|---|---|
| Luna TTS 엔진(venv+chatterbox+HF캐시) | `engine/chatterbox-v3/` (2026-08-08 Windows Temp에서 영구 이전) |
| Luna 목소리 기준음(Candidate B) + 프로소디 타겟 수치 | `assets/voice_ref/` |
| 나레이션 파이프라인 (유일 진입점) | `scripts/luna_narration_pipeline_v1.py` |
| SUBSEA-001 확정 내레이션 wav + 0.1초 타이밍 | `projects/SUBSEA-001/audio/`, `NARRATION_TIMING_v3_0p1s.{md,csv}` |
| SPIDER-001 확정 내레이션 wav | `projects/SPIDER-001/audio/` |
| 스킬 MD 3종 (지식·규칙 문서) | `.claude/skills/` |

## 이 프로젝트에 없는 것 (전부 옛 프로젝트에만 있음)

- 영상 제작 스크립트(Blender `scripts/visual_worlds/*.py`), 조립 스크립트(`build_subsea_v3_assembly.py` 등)
- 렌더 프레임 드래프트(`experiments/`, 14GB)
- 정본 영상 기획서(`VIDEO_PLAN_v3_STORY.md`), 완성 mp4
- 브랜드 영상 자산(엔드카드/아웃트로/배너), CC0 텍스처, 자막 폰트
- 거버넌스 문서(AGENTS.md, Lane C 등)

새 영상 작업을 다시 시작할 때는 `nalu-video`/`nalu-video-production` 스킬의
규칙(3-world 문법, 품질 최소선 T1 motion v2, 함정 목록, 조립 시 갭-홀드 프레임 필요성 등)을
참고해서 여기서 새로 코드를 짠다. 옛 프로젝트의 스크립트를 그대로 재사용하려면 그쪽에서
파일을 가져와야 한다(자동으로 없음).
