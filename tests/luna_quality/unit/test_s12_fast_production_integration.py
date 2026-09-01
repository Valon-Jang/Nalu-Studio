from __future__ import annotations

import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from scripts.luna_quality.voice_runtime.contract import REQUEST_SCHEMA_VERSION, VoiceMode, VoiceRequest
from scripts.luna_quality.voice_runtime.runtime import LunaVoiceRuntime, SYNTHESIS_PARAMETERS
from scripts.luna_quality.voice_runtime.transport import DEFAULT_HOST, LocalVoiceServer, send_request


class FakeWave:
    pass


class FakeModel:
    def __init__(self) -> None:
        self.sr = 24000
        self.device = "cpu"
        self.conds = object()
        self.generate_calls: list[dict] = []

    def generate(self, text, **kwargs):
        self.generate_calls.append({"text": text, **kwargs})
        return FakeWave()


class FakeConditioner:
    def __init__(self) -> None:
        self.prepare_count = 0

    def prepare(self, model, conditionals_cls):
        self.prepare_count += 1
        model.conds = object()
        return {"status": "hit", "condition_prepare_count": self.prepare_count}


class S12FastProductionIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.model = FakeModel()
        self.conditioner = FakeConditioner()
        self.writes: list[tuple[Path, object, int]] = []
        self.seeds: list[int] = []
        self.runtime = LunaVoiceRuntime(
            self.root,
            model_factory=lambda: self.model,
            conditioner=self.conditioner,
            audio_writer=lambda path, wav, sr: (path.parent.mkdir(parents=True, exist_ok=True), path.write_bytes(b"RIFFfake"), self.writes.append((path, wav, sr))),
            seed_setter=self.seeds.append,
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_contract_defaults_to_fast_and_rejects_invalid_input(self) -> None:
        request = VoiceRequest.from_mapping({"text": "안녕하세요.", "output_wav": "out.wav"})
        self.assertIs(request.mode, VoiceMode.FAST)
        self.assertEqual(request.schema_version, REQUEST_SCHEMA_VERSION)
        with self.assertRaisesRegex(ValueError, "text is required"):
            VoiceRequest.from_mapping({"output_wav": "out.wav"})
        with self.assertRaisesRegex(ValueError, "mode"):
            VoiceRequest.from_mapping({"text": "대사", "output_wav": "out.wav", "mode": "other"})

    def test_repeated_fast_requests_load_model_and_condition_once(self) -> None:
        first = self.runtime.handle({"request_id": "one", "text": "첫 번째 대사입니다.", "output_wav": "one.wav"})
        second = self.runtime.handle({"request_id": "two", "text": "두 번째 대사입니다.", "output_wav": "two.wav", "seed": 7})
        self.assertEqual(first["status"], "ok")
        self.assertEqual(second["status"], "ok")
        self.assertEqual(first["mode"], "fast")
        self.assertEqual(first["take_count"], 1)
        self.assertEqual(self.runtime.model_load_count, 1)
        self.assertEqual(self.conditioner.prepare_count, 1)
        self.assertEqual(len(self.model.generate_calls), 2)
        self.assertEqual(self.model.generate_calls[0]["audio_prompt_path"], None)
        for name, expected in SYNTHESIS_PARAMETERS.items():
            self.assertEqual(self.model.generate_calls[0][name], expected)
        self.assertEqual(self.seeds, [20260823, 7])
        self.assertTrue((self.root / "one.wav").is_file())
        self.assertTrue((self.root / "two.wav").is_file())

    def test_fast_writes_common_json_response(self) -> None:
        result = self.runtime.handle({
            "request_id": "json",
            "text": "JSON 응답 테스트입니다.",
            "output_wav": "take.wav",
            "output_json": "take.json",
        })
        saved = json.loads((self.root / "take.json").read_text(encoding="utf-8"))
        self.assertEqual(saved, result)
        self.assertEqual(saved["quality"]["mode"], "not_run")
        self.assertTrue(saved["local_only"])

    def test_production_dispatch_uses_same_resident_model(self) -> None:
        calls = []

        def production(request, model):
            calls.append((request, model))
            return {"status": "ok", "mode": "production", "quality": {"mode": "shadow"}}

        runtime = LunaVoiceRuntime(
            self.root,
            model_factory=lambda: self.model,
            conditioner=self.conditioner,
            audio_writer=lambda *_: None,
            production_runner=production,
        )
        result = runtime.handle({"text": "정밀 생성입니다.", "output_wav": "production.wav", "mode": "production"})
        self.assertEqual(result["quality"]["mode"], "shadow")
        self.assertIs(calls[0][1], self.model)
        self.assertEqual(runtime.model_load_count, 1)
        self.assertEqual(self.conditioner.prepare_count, 1)

    def test_default_production_route_calls_existing_pipeline_in_safe_shadow_mode(self) -> None:
        import scripts.luna_narration_pipeline_v1 as pipeline
        import scripts.luna_quality.production_integration as integration

        observed = {}

        class FakeSession:
            def __init__(self, repo_root, outdir, model, flags):
                observed["model"] = model
                observed["quality_mode"] = flags.quality_mode
                observed["conditionals_cache"] = flags.conditionals_cache
                self.report_root = Path(outdir).parent / "quality-reports"
                self.conditionals_status = {"status": "hit"}

        def synthesize(model, sr, block, outdir, np, torch, ta, quality_session):
            observed["block"] = block
            observed["quality_session"] = quality_session
            Path(outdir).mkdir(parents=True, exist_ok=True)
            (Path(outdir) / f"{block['id']}_luna.wav").write_bytes(b"RIFFproduction")
            return {"id": block["id"], "picks": [0], "n_phrases": 1}

        output = self.root / "final.wav"
        with patch.object(integration, "ProductionQualitySession", FakeSession), patch.object(pipeline, "synthesize_block", side_effect=synthesize):
            result = self.runtime.handle({
                "request_id": "production-default",
                "text": "프로덕션 통합입니다.",
                "output_wav": str(output),
                "mode": "production",
            })
        self.assertEqual(observed["quality_mode"], "shadow")
        self.assertEqual(observed["conditionals_cache"], "on")
        self.assertIs(observed["model"], self.model)
        self.assertEqual(observed["block"]["text"], "프로덕션 통합입니다.")
        self.assertFalse(result["quality"]["production_selection_default_on"])
        self.assertEqual(result["production"]["block_report"]["picks"], [0])
        self.assertEqual(output.read_bytes(), b"RIFFproduction")

    def test_local_json_transport(self) -> None:
        server = LocalVoiceServer((DEFAULT_HOST, 0), self.runtime)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            port = server.server_address[1]
            health = send_request({"action": "health"}, port=port, timeout=5)
            self.assertEqual(health["status"], "starting")
            response = send_request({"text": "로컬 전송입니다.", "output_wav": "transport.wav"}, port=port, timeout=5)
            self.assertEqual(response["status"], "ok")
            self.assertTrue((self.root / "transport.wav").is_file())
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_short_cli_form_is_text_only_and_defaults_to_fast(self) -> None:
        from scripts import luna_voice

        captured = {}

        def dispatch(payload, port, *, auto_start):
            captured.update(payload)
            return {"status": "ok", "mode": payload["mode"], "output_wav": payload["output_wav"]}

        output = self.root / "cli.wav"
        response = self.root / "cli.json"
        with patch.object(luna_voice, "_dispatch", side_effect=dispatch):
            exit_code = luna_voice.main(["대사만 입력합니다.", "--output", str(output), "--response", str(response)])
        self.assertEqual(exit_code, 0)
        self.assertEqual(captured["text"], "대사만 입력합니다.")
        self.assertEqual(captured["mode"], "fast")


if __name__ == "__main__":
    unittest.main()
