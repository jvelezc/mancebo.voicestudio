"""Qwen Base cloning and VoiceDesign through the pinned native audio.cpp runtime.

No Python Qwen/transformers dependency and no automatic model download. Models
must be installed explicitly. Only one package is resident in the owned server;
switching between design and cloning reaps that server before loading the other.
"""
from __future__ import annotations

import os
import socket

from engines.audiocpp import AudioCPPBackend, bootstrap
from services.tts_backend import TTSInputError


CLONE = bootstrap.ModelPackage(
    family="qwen3_tts",
    model_id="qwen3-tts-native-base",
    package_dir="Qwen3-TTS-12Hz-0.6B-Base-GGUF",
    default_package="qwen3-tts-12hz-0.6b-base-q8_0.gguf",
    label="Qwen3 TTS Base",
    default_port=17870,
    package_env="VOICESTUDIO_QWEN_NATIVE_CLONE_PACKAGE",
    port_env="VOICESTUDIO_QWEN_NATIVE_PORT",
    model_env="VOICESTUDIO_QWEN_NATIVE_CLONE_MODEL",
    workdir="qwen-native-clone",
)
DESIGN = bootstrap.ModelPackage(
    family="qwen3_tts",
    model_id="qwen3-tts-native-design",
    package_dir="Qwen3-TTS-12Hz-1.7B-VoiceDesign-GGUF",
    default_package="qwen3-tts-12hz-1.7b-voicedesign-q8_0.gguf",
    label="Qwen3 TTS VoiceDesign",
    default_port=17870,
    package_env="VOICESTUDIO_QWEN_NATIVE_DESIGN_PACKAGE",
    port_env="VOICESTUDIO_QWEN_NATIVE_PORT",
    model_env="VOICESTUDIO_QWEN_NATIVE_DESIGN_MODEL",
    workdir="qwen-native-design",
)


def cpu_threads() -> int:
    """Keep the default suitable for a bounded CPU worker, on every OS."""
    value = os.environ.get("VOICESTUDIO_QWEN_NATIVE_THREADS", "2")
    try:
        threads = int(value)
    except ValueError:
        raise RuntimeError("VOICESTUDIO_QWEN_NATIVE_THREADS must be an integer from 1 to 16") from None
    if not 1 <= threads <= 16:
        raise RuntimeError("VOICESTUDIO_QWEN_NATIVE_THREADS must be an integer from 1 to 16")
    return threads


class QwenNativeBackend(AudioCPPBackend):
    id = "qwen3-native"
    display_name = "Qwen3 TTS native (CPU, multilingual cloning and voice design)"
    supports_voice_design = True
    supports_num_step = False
    supports_guidance_scale = False
    instruct_directs_delivery = False

    def __init__(self) -> None:
        super().__init__()
        self._selected_package = CLONE
        self._language: str | None = None

    @classmethod
    def is_available(cls) -> tuple[bool, str]:
        try:
            cpu_threads()
            bootstrap.resolve_server_binary()
            for package in (CLONE, DESIGN):
                bootstrap.resolve_model_file(package)
        except (RuntimeError, OSError) as error:
            return False, str(error)
        return True, "ready"

    @property
    def supported_languages(self) -> list[str]:
        return ["en", "zh", "ja", "ko", "de", "fr", "ru", "pt", "es", "it"]

    def _package(self):
        return self._selected_package

    def _select_server_port(self, package) -> int:
        if os.environ.get("VOICESTUDIO_QWEN_NATIVE_DYNAMIC_PORT") != "1":
            return super()._select_server_port(package)
        # Different model instances can coexist during a model-manager handoff.
        # Never terminate a listener merely because it holds the configured port.
        # The inherited per-launch identity challenge still checks ownership if
        # another process wins the small bind-to-spawn race.
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            return listener.getsockname()[1]

    def _runtime_directory(self, package):
        directory = super()._runtime_directory(package)
        if os.environ.get("VOICESTUDIO_QWEN_NATIVE_DYNAMIC_PORT") == "1":
            return directory / "launches" / self._server_model_id
        return directory

    def _server_configuration(self, **kwargs) -> dict:
        config = super()._server_configuration(**kwargs)
        config["threads"] = cpu_threads()
        return config

    def _request_options(self, kw: dict, ref_audio):
        # Base cloning follows its reference. It does not implement a graded
        # emotion knob or instruction-based delivery for a cloned speaker.
        description = (kw.get("instruct") or kw.get("description")) if not ref_audio else None
        return description, None

    def _post_json(self, path: str, payload: dict, timeout: float):
        if path == "/v1/audio/speech":
            payload = dict(payload)
            payload.pop("guidance_scale", None)
            if self._language:
                payload["language"] = self._language
            # The native runtime splits longer scripts and combines their audio.
            # The token budget applies per text chunk, not to the whole script.
            payload["text_chunk_size"] = 240
            payload["max_tokens"] = 2048
        return super()._post_json(path, payload, timeout)

    def generate(self, text: str, **kw):
        self._check_language(kw.get("language"))
        reference = kw.get("ref_audio")
        if reference and not str(kw.get("ref_text") or "").strip():
            raise TTSInputError("Qwen voice cloning needs the reference recording’s transcript. Add or transcribe it before generating.")
        package = CLONE if reference else DESIGN
        language = self._normalize_language_code(kw.get("language"))
        with self._lock:
            if package != self._selected_package:
                self._terminate_server()
                self._port = None
                self._selected_package = package
            self._language = None if language in (None, "auto", "multi") else language
            return super().generate(text, **kw)
