import json
import socket
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
