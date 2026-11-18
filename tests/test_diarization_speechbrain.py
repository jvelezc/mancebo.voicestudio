"""Full-recording SpeechBrain analysis, including silence, tail and recovery."""

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import soundfile as sf
import torch

from services import diarization_speechbrain as subject


@pytest.fixture
def installed(tmp_path, monkeypatch):
    root = tmp_path / "model"
    root.mkdir()
    weights = b"fixture checkpoint bytes"
    (root / "embedding_model.ckpt").write_bytes(weights)
    manifest = {
        "repo": subject.MODEL_ID,
        "license": "apache-2.0",
        "revision": "a" * 40,
        "files": {
            "embedding_model.ckpt": {
                "sha256": hashlib.sha256(weights).hexdigest(),
                "bytes": len(weights),
            }
        },
    }
    (root / "model-manifest.json").write_text(json.dumps(manifest))
    monkeypatch.setenv(subject.MODEL_ENV, str(root))
    return root


def test_missing_or_wrong_license_model_is_not_loaded(tmp_path, monkeypatch, installed):
    data = json.loads((installed / "model-manifest.json").read_text())
    data["license"] = "cc-by-nc-4.0"
    (installed / "model-manifest.json").write_text(json.dumps(data))
    with pytest.raises(ValueError, match="provenance"):
        subject.SpeechBrainDiarization()
    monkeypatch.delenv(subject.MODEL_ENV)
    with pytest.raises(FileNotFoundError):
        subject.SpeechBrainDiarization()
    assert subject.status()["model_installed"] is False


def test_checkpoint_hash_is_verified_before_constructing_speechbrain(installed):
    path = installed / "embedding_model.ckpt"
    path.write_bytes(b"x" * path.stat().st_size)
    with pytest.raises(ValueError, match="checksum"):
        subject.SpeechBrainDiarization()


def test_speech_scan_keeps_middle_and_tail_after_multiple_empty_windows(
    tmp_path, monkeypatch
):
    source = tmp_path / "long-silences.wav"
    samples = np.zeros(182 * subject.RATE, dtype=np.float32)
    for begin, end in [(1, 4), (120, 124), (178, 182)]:
        samples[begin * subject.RATE : end * subject.RATE] = 0.5
    sf.write(source, samples, subject.RATE)
    calls = []

    def vad(chunk, options, **kwargs):
        calls.append(len(chunk))
        speech = np.flatnonzero(chunk > 0.1)
        return (
            [{"start": int(speech[0]), "end": int(speech[-1]) + 1}]
            if len(speech)
            else []
        )

    monkeypatch.setattr("faster_whisper.vad.get_speech_timestamps", vad)
    regions = subject.speech_regions(source, lambda: None)
    assert regions == [
        (subject.RATE, 4 * subject.RATE),
        (120 * subject.RATE, 124 * subject.RATE),
        (178 * subject.RATE, 182 * subject.RATE),
    ]
    assert len(calls) == 7
    windows = subject.embedding_windows(regions)
    assert windows[0][0] == subject.RATE and windows[-1][1] == 182 * subject.RATE


def test_global_clustering_preserves_same_voice_before_and_after_long_silence(
    installed, tmp_path, monkeypatch
):
    source = tmp_path / "source.wav"
    sf.write(source, np.zeros(182 * subject.RATE, dtype=np.float32), subject.RATE)
    regions = [
        (0, 4 * subject.RATE),
        (80 * subject.RATE, 84 * subject.RATE),
        (178 * subject.RATE, 182 * subject.RATE),
    ]
    monkeypatch.setattr(subject, "speech_regions", lambda source, check: regions)
    pipeline = subject.SpeechBrainDiarization()

    def embedding(recording, start, end, cache):
        vector = np.zeros(192, dtype=np.float32)
        vector[1 if 80 * subject.RATE <= start < 84 * subject.RATE else 0] = 1
        return vector

    monkeypatch.setattr(pipeline, "_embedding", embedding)
    turns = list(pipeline(source, num_speakers=2).itertracks(yield_label=True))
    assert turns[0][0].start == 0 and turns[-1][0].end == 182
    assert turns[0][2] == turns[-1][2] == "SPEAKER_00"
    assert {speaker for segment, _, speaker in turns if 80 <= segment.start < 84} == {
        "SPEAKER_01"
    }
    for group in [(0, 4), (80, 84), (178, 182)]:
        selected = [
            segment
            for segment, _, speaker in turns
            if group[0] <= segment.start < group[1]
        ]
        assert selected[0].start == group[0] and selected[-1].end == group[1]
        assert all(
            first.end == second.start for first, second in zip(selected, selected[1:])
        )


def test_embedding_checkpoint_reuses_verified_vector_and_recomputes_corruption(
    installed, tmp_path, monkeypatch
):
    source = tmp_path / "source.wav"
    sf.write(source, np.ones(subject.RATE, dtype=np.float32) * 0.1, subject.RATE)
    cache = tmp_path / "checkpoints"
    cache.mkdir()
    calls = []
    encoder = SimpleNamespace(
        encode_batch=lambda signal: (
            calls.append(signal.shape)
            or torch.arange(1, 193, dtype=torch.float32).reshape(1, 1, 192)
        )
    )
    pipeline = subject.SpeechBrainDiarization()
    monkeypatch.setattr(pipeline, "_encoder", lambda: encoder)
    with sf.SoundFile(source) as recording:
        first = pipeline._embedding(recording, 0, subject.RATE, cache)
    restarted = subject.SpeechBrainDiarization()
    monkeypatch.setattr(restarted, "_encoder", lambda: encoder)
    with sf.SoundFile(source) as recording:
        again = restarted._embedding(recording, 0, subject.RATE, cache)
    assert np.array_equal(first, again) and calls == [torch.Size([1, subject.RATE])]
    next(cache.glob("*.npy")).write_bytes(b"corrupted checkpoint")
    with sf.SoundFile(source) as recording:
        repaired = restarted._embedding(recording, 0, subject.RATE, cache)
    assert np.array_equal(first, repaired) and len(calls) == 2


@pytest.mark.parametrize("count", [0, 21, True, "2"])
def test_invalid_count_refused_before_reading_source(installed, count):
    with pytest.raises(ValueError, match="twenty"):
        subject.SpeechBrainDiarization()("not-read.wav", num_speakers=count)


def test_silence_has_no_invented_speakers_and_cancellation_prevents_analysis(
    installed, tmp_path, monkeypatch
):
    source = tmp_path / "silent.wav"
    sf.write(source, np.zeros(subject.RATE, dtype=np.float32), subject.RATE)
    monkeypatch.setattr(subject, "speech_regions", lambda source, check: [])
    pipeline = subject.SpeechBrainDiarization()
    assert list(pipeline(source).itertracks(yield_label=True)) == []
    with pytest.raises(RuntimeError, match="cancelled"):
        pipeline(source, cancel_check=lambda: True)


def test_default_is_unchanged_and_speechbrain_inventory_names_actual_model(
    installed, monkeypatch
):
    from services import diarization_runtime

    monkeypatch.setattr(
        diarization_runtime.prefs, "resolve", lambda *args, **kwargs: kwargs["default"]
    )
    assert diarization_runtime.selected_backend() == diarization_runtime.PYANNOTE
    monkeypatch.setattr(
        diarization_runtime.prefs, "resolve", lambda *args, **kwargs: subject.BACKEND_ID
    )
    assert diarization_runtime.selected_backend() == subject.BACKEND_ID
    assert diarization_runtime.selected_model_id() == subject.MODEL_ID
    assert diarization_runtime.selected_model_repos() == []


def test_missing_default_bundle_is_reported_before_optional_runtime_imports(
    fresh_model_manager, monkeypatch
):
    from contextlib import contextmanager

    manager = fresh_model_manager(force=True)
    monkeypatch.setattr(manager, "_diar_pipeline", None)
    monkeypatch.setattr("services.token_resolver.resolve", lambda **kwargs: None)

    @contextmanager
    def missing():
        raise FileNotFoundError("The installed-only bundle is absent")
        yield

    monkeypatch.setattr("services.diarization_local.local_pipeline_config", missing)
    monkeypatch.setattr(
        "core.windows_rocm.pipelines.pipeline_error",
        lambda: (_ for _ in ()).throw(
            AssertionError("optional runtime must not be loaded")
        ),
    )
    pipeline, error = manager.get_diarization_pipeline(return_error=True)
    assert pipeline is None and error == manager.DIARIZATION_ERR_NO_TOKEN
