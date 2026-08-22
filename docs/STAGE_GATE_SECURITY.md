# Stage Gate 강제 수준

## Level 1 — 지침 차단

`AGENTS.md`와 단계별 prompt가 Codex에게 다음 단계 선행 구현과 `advance` 실행을 금지한다.

용도: 실수 방지.

## Level 2 — 로컬 범위 차단

`stage_gate.py check-scope`가 stage-start commit 이후 변경 경로를 현재 단계 allowlist와 비교한다. 다음 단계 파일이 섞이면 완료요청을 만들 수 없다.

용도: 자동 범위 검사.

## Level 3 — 사용자 키 차단

`init`, `advance`, `close`는 `LUNA_STAGE_GATE_KEY`가 필요하다. key는 별도 approval terminal에만 두고 Codex 프로세스에서는 `codex-safe`로 부재를 확인한다. Codex는 `request-completion`만 실행한다. stage state는 HMAC 서명과 protected-file hash를 가진다.

용도: 일반적인 자동 다음 단계 진입 방지.

## Level 4 — GitHub merge 차단

GitHub Actions secret, required check, branch protection, CODEOWNERS/ruleset을 함께 사용한다.

필수 설정:

- `LUNA_STAGE_GATE_KEY` secret
- `luna-stage-gate` required check
- protected control files 변경 시 owner review
- workflow 변경 시 owner review
- 관리자 우회 차단

이 설정까지 해야 쓰기 권한이 있는 에이전트가 guard 자체를 수정해 merge하는 것을 외부 권한 경계에서 막을 수 있다.
