"""Native engine contracts; transport audio is synthetic, not a model-quality test."""
from __future__ import annotations

import base64
import io
import wave
from unittest.mock import Mock

import pytest

from engines import audiocpp
from engines.qwen_native import CLONE, DESIGN, QwenNativeBackend, cpu_threads
from services.tts_backend import TTSInputError


@pytest.fixture(autouse=True)
def clean_native_thread_override(monkeypatch):
    monkeypatch.delenv("VOICESTUDIO_QWEN_NATIVE_THREADS", raising=False)


@pytest.fixture
def transport(monkeypatch):
    backend = QwenNativeBackend()
    selected = audiocpp.bootstrap.select_device(audiocpp.bootstrap.parse_device_list('CPU:0 "Test CPU" [CPU]'))
    seen = []
    def load():
        backend._server_model_id = "synthetic-native-model"
        backend._selection = selected
    monkeypatch.setattr(backend, "_ensure_loaded", load)
    audio = io.BytesIO()
    with wave.open(audio, "wb") as target:
        target.setnchannels(1); target.setsampwidth(2); target.setframerate(24000)
        target.writeframes(b"\0\0" * 2400)
    reply = {"audio": base64.b64encode(audio.getvalue()).decode()}
    def post(self, path, payload, timeout):
        seen.append((self._package(), path, payload, timeout))
        return reply
    monkeypatch.setattr(audiocpp.AudioCPPBackend, "_post_json", post)
    return backend, seen


def test_design_selects_design_weights_and_forwards_description_language_and_seed(transport):
    backend, seen = transport
    result = backend.generate("A synthetic preview.", description="A clear narrator", language="pt-BR", seed=42)
    package, path, payload, timeout = seen[0]
    assert package == DESIGN
    assert path == "/v1/audio/speech"
    assert payload == {"model": "synthetic-native-model", "input": "A synthetic preview.", "response_format": "json", "instructions": "A clear narrator", "seed": 42, "language": "pt", "text_chunk_size": 240, "max_tokens": 2048}
    assert timeout > 0
    assert result.shape == (1, 2400)
    assert backend.sample_rate == 24000


def test_clone_uses_reference_and_transcript_without_fake_delivery_controls(transport):
    backend, seen = transport
    backend.generate("Different words.", ref_audio="reference.wav", ref_text="Reference words.", instruct="Make the voice excited", guidance_scale=2.0, language="es", seed=7)
    package, _, payload, _ = seen[0]
    assert package == CLONE
    assert payload["voice_ref"] == {"type": "path", "path": "reference.wav"}
    assert payload["reference_text"] == "Reference words."
    assert payload["language"] == "es" and payload["seed"] == 7
    assert "instructions" not in payload and "guidance_scale" not in payload
    assert not backend.instruct_directs_delivery
    assert not backend.supports_num_step and not backend.supports_guidance_scale


def test_missing_reference_transcript_is_rejected_before_loading_or_transport(transport, monkeypatch):
    backend, seen = transport
    load = Mock(); monkeypatch.setattr(backend, "_ensure_loaded", load)
    for value in [None, "", "  "]:
        with pytest.raises(TTSInputError, match="reference recording.*transcript"):
            backend.generate("A script.", ref_audio="private-reference.wav", ref_text=value)
    load.assert_not_called()
    assert seen == []


def test_unsupported_language_fails_before_native_io(transport, monkeypatch):
    backend, seen = transport
    load = Mock(); monkeypatch.setattr(backend, "_ensure_loaded", load)
    with pytest.raises(ValueError):
        backend.generate("A script.", language="pl")
    load.assert_not_called()
    assert seen == []


def test_auto_language_does_not_send_a_false_language_hint(transport):
    backend, seen = transport
    backend.generate("A script.", language="Auto")
    assert "language" not in seen[0][2]


def test_mode_switch_reaps_owned_server_and_same_mode_reuses_it(transport):
    backend, _ = transport
    process = Mock(); backend._proc = process
    backend.generate("Design.", description="A calm narrator")
    process.terminate.assert_called_once()
    process.wait.assert_called_once()
    assert backend._package() == DESIGN
    next_process = Mock(); backend._proc = next_process
    backend.generate("Clone.", ref_audio="reference.wav", ref_text="Reference.")
    assert backend._package() == CLONE
    next_process.terminate.assert_called_once()
    backend.generate("Clone again.", ref_audio="reference.wav", ref_text="Reference.")
    next_process.terminate.assert_called_once()


def test_instances_do_not_share_mode_language_or_reference_state(transport):
    first, _ = transport
    second = QwenNativeBackend()
    first.generate("Design.", description="A calm narrator", language="fr")
    assert first._package() == DESIGN and first._language == "fr"
    assert second._package() == CLONE and second._language is None


def test_availability_requires_both_packages_without_starting_a_server(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(audiocpp.bootstrap, "resolve_server_binary", lambda: tmp_path / "server")
    monkeypatch.setattr(audiocpp.bootstrap, "resolve_model_file", lambda package: calls.append(package) or tmp_path / package.default_package)
    spawn = Mock(); monkeypatch.setattr(audiocpp, "spawn_owned", spawn)
    assert QwenNativeBackend.is_available() == (True, "ready")
    assert calls == [CLONE, DESIGN]
    spawn.assert_not_called()
    def missing(package):
        if package == DESIGN: raise RuntimeError("Qwen VoiceDesign is not installed")
        return tmp_path / package.default_package
    monkeypatch.setattr(audiocpp.bootstrap, "resolve_model_file", missing)
    assert QwenNativeBackend.is_available() == (False, "Qwen VoiceDesign is not installed")
    spawn.assert_not_called()


@pytest.mark.parametrize("threads", [1, 2, 16], ids=["Lower", "Default", "Upper"])
def test_cpu_thread_boundaries_reach_only_this_engine_configuration(monkeypatch, threads):
    monkeypatch.setenv("VOICESTUDIO_QWEN_NATIVE_THREADS", str(threads))
    config = QwenNativeBackend()._server_configuration(model_id="test", family="qwen3_tts", model_path="model.gguf", port=17870)
    assert config["threads"] == threads
    assert config["max_loaded_models"] == 1
    assert config["host"] == "127.0.0.1"
    assert config["models"] == [{"id": "test", "family": "qwen3_tts", "path": "model.gguf", "task": "tts", "mode": "offline"}]


@pytest.mark.parametrize("value", ["0", "17", "invalid"], ids=["Below", "Above", "Malformed"])
def test_invalid_thread_budget_fails_before_runtime_probe(monkeypatch, value):
    monkeypatch.setenv("VOICESTUDIO_QWEN_NATIVE_THREADS", value)
    probe = Mock(); monkeypatch.setattr(audiocpp.bootstrap, "resolve_server_binary", probe)
    assert QwenNativeBackend.is_available()[0] is False
    with pytest.raises(RuntimeError, match="integer from 1 to 16"): cpu_threads()
    probe.assert_not_called()


def test_cpu_default_and_package_names_do_not_change_other_engines():
    assert cpu_threads() == 2
    assert QwenNativeBackend().supported_languages == ["en", "zh", "ja", "ko", "de", "fr", "ru", "pt", "es", "it"]
    assert CLONE.default_package != DESIGN.default_package
    assert CLONE.model_env != DESIGN.model_env
    assert audiocpp.bootstrap.BREEZE.default_port == 17860
    assert audiocpp.bootstrap.DOTS.default_port == 17861


def test_native_engine_help_opens_the_fork_that_contains_its_guide():
    from services.tts_backend import _engine_docs_url

    assert _engine_docs_url("qwen3-native") == "https://github.com/jvelezc/mancebo.voicestudio/blob/main/docs/engines/qwen-native.md"


@pytest.mark.parametrize("package,directory,filename", [
    (CLONE, "Qwen3-TTS-12Hz-0.6B-Base-GGUF", "qwen3-tts-12hz-0.6b-base-q8_0.gguf"),
    (DESIGN, "Qwen3-TTS-12Hz-1.7B-VoiceDesign-GGUF", "qwen3-tts-12hz-1.7b-voicedesign-q8_0.gguf"),
], ids=["Base", "VoiceDesign"])
def test_each_package_resolves_only_its_pinned_local_cache(monkeypatch, tmp_path, package, directory, filename):
    import huggingface_hub

    monkeypatch.delenv(package.model_env, raising=False)
    monkeypatch.delenv(package.package_env, raising=False)
    model = tmp_path / directory / filename
    model.parent.mkdir()
    model.write_bytes(b"synthetic test model; never executed")
    snapshot = Mock(return_value=str(tmp_path))
    monkeypatch.setattr(huggingface_hub, "snapshot_download", snapshot)
    assert audiocpp.bootstrap.resolve_model_file(package) == model
    snapshot.assert_called_once_with(
        repo_id="audio-cpp/audio.cpp-gguf",
        revision="dc6fecccc2b0c6bdda0a8b2f38fa61394fee0b9c",
        allow_patterns=[f"{directory}/{filename}"],
        local_files_only=True,
    )
