# Removal targets

| Target | Action |
| --- | --- |
| `tools/stage_gate.py` | Move to timestamped backup and remove live copy |
| `.github/workflows/luna-stage-gate.yml` | Move to timestamped backup and remove live copy |
| `.codex/stage_state.json` | Preserve stage identity/status; remove key, signature, approval, lock, and unlock properties |
| `.codex/stage_plan.json` | Preserve Stage definitions; remove gate/security properties |
| `AGENTS.md` | Replace known Stage-Gate security wording with a manual-stop rule |
| `.github/CODEOWNERS` | Remove only Stage-Gate-specific ownership lines |
| `.env.example` | Replace a `LUNA_STAGE_GATE_KEY` placeholder with `LUNA_STAGE_GATE_KEY=REMOVE` |

GitHub rulesets and branch-protection required checks are external repository settings. Remove the `luna-stage-gate` required check manually after applying this patch.
