import json
import socket
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from core import config
from engines import audiocpp
from engines.qwen_native import QwenNativeBackend


@pytest.fixture
def launches(monkeypatch, tmp_path):
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    occupied = listener.getsockname()[1]
    seen, reserved = [], [listener]
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(audiocpp.bootstrap, "resolve_server_binary", lambda: tmp_path / "native-server")
    monkeypatch.setattr(audiocpp.bootstrap, "resolve_model_file", lambda package: tmp_path / "model.gguf")
    monkeypatch.setattr(audiocpp.bootstrap, "server_port", lambda package: occupied)
    monkeypatch.setattr(audiocpp.bootstrap, "resolve_compute_selection", lambda: SimpleNamespace(device=SimpleNamespace(backend="cpu", index=0, target="cpu")))
    monkeypatch.setattr(QwenNativeBackend, "_wait_for_health", lambda self: None)

    def spawn(args, **kwargs):
        path = args[args.index("--config") + 1]
        with open(path, encoding="utf-8") as source:
            value = json.load(source)
        seen.append((path, value))
        if value["port"] != occupied:
            bound = socket.socket()
            bound.bind(("127.0.0.1", value["port"]))
            reserved.append(bound)
        process = Mock()
        process.poll.return_value = None
        def stopped(*args, **kwargs):
            process.poll.return_value = 0
            return 0
        process.wait.side_effect = stopped
        return process

    monkeypatch.setattr(audiocpp, "spawn_owned", spawn)
    yield occupied, seen
    for listener in reserved:
        listener.close()


def test_managed_model_instances_avoid_the_busy_default_port_and_separate_launch_files(monkeypatch, launches):
    occupied, seen = launches
    monkeypatch.setenv("VOICESTUDIO_QWEN_NATIVE_DYNAMIC_PORT", "1")
    first, second = QwenNativeBackend(), QwenNativeBackend()
    first._ensure_loaded()
    second._ensure_loaded()
    assert len(seen) == 2
    assert all(value["host"] == "127.0.0.1" and value["port"] != occupied for _, value in seen)
    assert seen[0][1]["port"] != seen[1][1]["port"]
    assert seen[0][0] != seen[1][0]
    assert seen[0][1]["models"][0]["id"] != seen[1][1]["models"][0]["id"]


def test_standalone_model_still_uses_its_operator_configured_port(monkeypatch, launches):
    occupied, seen = launches
    monkeypatch.delenv("VOICESTUDIO_QWEN_NATIVE_DYNAMIC_PORT", raising=False)
    QwenNativeBackend()._ensure_loaded()
    assert len(seen) == 1
    assert seen[0][1]["port"] == occupied


def test_managed_handoff_reaps_previous_owned_model_before_loading_another(monkeypatch, launches):
    monkeypatch.setenv("VOICESTUDIO_QWEN_NATIVE_DYNAMIC_PORT", "1")
    first, second = QwenNativeBackend(), QwenNativeBackend()
    first._ensure_loaded()
    owned = first._proc
    second._ensure_loaded()
    owned.terminate.assert_called_once()
    owned.wait.assert_called_once()
    assert first._proc is None
    assert second._proc is not None


def test_managed_handoff_refuses_to_load_when_owned_model_cannot_be_stopped(monkeypatch, launches):
    _, seen = launches
    monkeypatch.setenv("VOICESTUDIO_QWEN_NATIVE_DYNAMIC_PORT", "1")
    first, second = QwenNativeBackend(), QwenNativeBackend()
    first._ensure_loaded()
    owned = first._proc
    with monkeypatch.context() as patch:
        patch.setattr(first, "_terminate_server", lambda: None)
        with pytest.raises(RuntimeError, match="did not stop"):
            second._ensure_loaded()
        assert len(seen) == 1
        assert first._proc is owned
        assert second._proc is None
    first._terminate_server()


def test_managed_handoff_waits_for_active_generation(monkeypatch):
    monkeypatch.setenv("VOICESTUDIO_QWEN_NATIVE_DYNAMIC_PORT", "1")
    first, second = QwenNativeBackend(), QwenNativeBackend()
    active, second_started, release = threading.Event(), threading.Event(), threading.Event()
    order = []

    def language_check(language):
        second_started.set()

    monkeypatch.setattr(second, "_check_language", language_check)

    def generate(instance, text, **kwargs):
        order.append(text)
        if instance is first:
            active.set()
            assert release.wait(5)
        return text

    monkeypatch.setattr(audiocpp.AudioCPPBackend, "generate", generate)
    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(first.generate, "first")
        assert active.wait(5)
        b = pool.submit(second.generate, "second")
        try:
            assert second_started.wait(5)
            with pytest.raises(FutureTimeout):
                b.result(timeout=0.1)
            assert order == ["first"]
        finally:
            release.set()
        assert a.result(timeout=5) == "first"
        assert b.result(timeout=5) == "second"
    assert order == ["first", "second"]
