# Luna Validator + Preference Ranker — Codex 단계 실행팩

이 실행팩은 `C:\Users\tequi\Nalu-Studio`의 현재 구조에 맞춰 조정되어 있다. 이 폴더의 **내용물**을 Nalu 저장소 루트에 복사하되, 기존 파일과 충돌하면 덮어쓰지 말고 먼저 비교한다. 실행 경로는 이동에 강하도록 모두 저장소 기준 상대경로를 사용한다.

단계 표기는 `S00~S11`로 총 12개다. `S00`은 저장소 감사와 baseline 동결을 위한 준비 단계이고, 실제 구축은 `S01~S11`의 11단계다.

## 1. 이 실행팩이 보장하는 작업 흐름

- Codex 한 세션당 한 단계만 수행
- 단계별 권장 모델과 추론 강도 고정
- 현재 단계 외 경로 수정 시 scope 검사 실패
- Codex는 완료요청까지만 생성 가능
- 다음 단계 전환은 `LUNA_STAGE_GATE_KEY`를 가진 사용자만 가능
- GitHub Actions와 branch protection을 설정하면 stage state 변조도 merge 차단 가능

## 2. 선행 조건

- 작업 루트: `C:\Users\tequi\Nalu-Studio`
- Git 저장소. 현재 폴더에 `.git`이 없으면 실행팩을 복사하기 전에 루트에서 `git init`을 먼저 실행한다.
- Python 3.11 이상 권장
- GPT-5.6을 사용할 경우 Codex CLI 0.144.0 이상 또는 해당 버전을 지원하는 최신 Codex 앱
- 기존 진입점: `scripts/luna_narration_pipeline_v1.py`
- Luna 런타임 Python: `engine/chatterbox-v3/venv/Scripts/python.exe`
- Candidate B: `assets/voice_ref/B_voiced_spectral_micro_smooth.wav`
- Prosody 기준: `assets/voice_ref/LUNA_PROSODY_TARGET.json`

### PowerShell 사전 점검

Nalu 루트에서 실행한다.

```powershell
$required = @(
  '.\scripts\luna_narration_pipeline_v1.py',
  '.\engine\chatterbox-v3\venv\Scripts\python.exe',
  '.\engine\chatterbox-v3\chatterbox\src',
  '.\engine\chatterbox-v3\hf-cache',
  '.\assets\voice_ref\B_voiced_spectral_micro_smooth.wav',
  '.\assets\voice_ref\LUNA_PROSODY_TARGET.json'
)
$missing = $required | Where-Object { -not (Test-Path -LiteralPath $_) }
if ($missing) { throw "Missing Luna prerequisite: $($missing -join ', ')" }
Get-FileHash '.\assets\voice_ref\B_voiced_spectral_micro_smooth.wav' -Algorithm SHA256
```

Candidate B의 SHA256은 `30C6D3405F46684AF467C7D26FF40A2FB57DD48CC84CD24CF7403D9AA00A2BB9`여야 한다.

Codex가 Luna 내레이션 요청에 이 규칙을 자동 연결하려면 스킬 파일이 반드시 `.agents/skills/luna-narration/SKILL.md`에 있어야 한다. 실행팩은 이 구조를 이미 포함한다.

## 3. 최초 1회 초기화

먼저 실행팩 파일을 저장소에 추가하고 `.gitignore.append` 내용을 기존 `.gitignore`에 합친 뒤, **실행팩만 먼저 커밋**한다. 이 커밋이 S00의 stage-start 기준점이 된다.

```bash
git add AGENTS.md README_START_HERE.md LUNA_CODEX_MASTER_SPEC.md .agents docs .codex tools .github .gitignore
# 기존 프로젝트 정책에 맞는 방식으로 커밋
```

그 다음 signed state를 만든다.

### PowerShell

```powershell
$env:LUNA_STAGE_GATE_KEY = python -c "import secrets; print(secrets.token_urlsafe(48))"
python tools/stage_gate.py init --stage S00
python tools/stage_gate.py status
```

키를 터미널 세션이 끝난 뒤에도 유지하려면 본인이 사용하는 비밀 관리 방식에 저장한다. 저장소 파일, 문서, 커밋, 채팅 프롬프트에 키를 넣지 않는다.

### bash

```bash
export LUNA_STAGE_GATE_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
python tools/stage_gate.py init --stage S00
python tools/stage_gate.py status
```

초기화 후 `.codex/stage_state.json`만 별도 커밋한다. 이 control commit은 scope 검사에서 무시되지만 HMAC과 protected-file hash로 검증된다.

**중요:** key가 설정된 approval terminal과 Codex terminal을 분리한다. 같은 터미널을 사용할 때는 Codex를 시작하기 전에 key를 제거한다.

PowerShell:

```powershell
Remove-Item Env:LUNA_STAGE_GATE_KEY
python tools/stage_gate.py codex-safe
```

bash:

```bash
unset LUNA_STAGE_GATE_KEY
python tools/stage_gate.py codex-safe
```

Codex 세션에서 `codex-safe`가 실패하면 작업을 시작하지 않는다.

## 4. S00 시작

1. Codex에서 **GPT-5.6 Sol / High**를 선택한다.
2. 새 세션을 연다.
3. `.codex/prompts/S00_REPO_AUDIT.md` 내용을 작업 지시로 사용한다.
4. Codex가 마지막에 `STAGE_COMPLETE_AWAITING_USER_APPROVAL`을 출력하면 작업을 중지한다.

## 5. 다음 단계로 수동 전환

Codex가 아니라 사용자가 직접 검토 후 실행한다.

```bash
python tools/stage_gate.py verify --require-signature
python tools/stage_gate.py status
python tools/stage_gate.py advance --to S01
```

`stage_state.json`을 커밋한 뒤, Codex를 열기 전 approval key를 제거하거나 key가 없는 별도 터미널/앱 세션을 사용한다.

그 다음 모델을 `docs/STAGE_MODEL_MATRIX.md`에 맞게 바꾸고 **새 Codex 세션**을 열어 S01 prompt를 사용한다.

이 과정을 S11까지 반복한다.

## 6. GitHub에서 강제 차단하기

저장소 Settings에서 다음을 설정한다.

1. Actions secret `LUNA_STAGE_GATE_KEY`에 로컬과 동일한 키 등록
2. `.github/workflows/luna-stage-gate.yml` 활성화
3. 기본 브랜치 branch protection에서 `luna-stage-gate` check를 required로 설정
4. required check를 관리자도 우회하지 않도록 설정
5. 가능하면 workflow와 `AGENTS.md`, `.codex`, `tools/stage_gate.py`에 CODEOWNERS 승인을 요구

저장소 지침만으로는 쓰기 권한을 가진 에이전트가 파일 자체를 바꾸는 것을 물리적으로 막을 수 없다. **외부 secret을 사용하는 required CI check와 branch protection까지 적용해야 merge 수준에서 강제된다.**

## 7. 단계가 막혔을 때

Codex가 `STAGE_BLOCKED_AWAITING_USER_DECISION` 또는 `STAGE_FAILED_AWAITING_USER_ACTION`으로 끝냈으면 `advance`를 실행하지 않는다. 보고서와 실패 명령을 확인한 뒤 같은 단계·같은 모델의 새 세션에서 보완한다.

## 8. 비용 효율 원칙

- S00, S06, S07, S09, S10, S11만 Sol 사용
- 일반 구현은 Terra 사용
- Luna는 formatting처럼 결과 판단이 필요 없는 별도 보조 세션에만 사용
- 이전 대화 전체를 넘기지 말고 stage report와 필요한 파일만 읽게 함
- S07/S09 외 Extra High 사용 금지
- Pro는 Codex 모델 선택기에 실제로 표시될 때만 S11에서 선택적으로 사용하며 필수로 가정하지 않음

## 9. 주요 파일

```text
AGENTS.md                                  Codex 절대 규칙
.agents/skills/luna-narration/SKILL.md   자동 발견되는 Luna 불변 규칙
docs/LUNA_VALIDATOR_RANKER_BUILD_SPEC.md  전체 구축 사양
docs/STAGE_MODEL_MATRIX.md                단계별 모델 선택
.codex/stage_plan.json                    단계·허용 경로·다음 단계
.codex/stage_state.json                   현재 단계와 서명
tools/stage_gate.py                       검증·완료요청·사용자 전환
.codex/prompts/                            단계별 시작 프롬프트
```
