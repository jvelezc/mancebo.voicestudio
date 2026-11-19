import numpy as np
import pytest
import soundfile as sf

from services.dub_quality import background_ready, measure_audio, natural_pacing_ready


def test_voice_audibility_cannot_be_satisfied_by_a_separate_music_bed(tmp_path):
    rate = 24000
    music = tmp_path / "music.wav"
    speech = tmp_path / "speech.wav"
    sf.write(music, 0.15 * np.sin(np.arange(rate) * 2 * np.pi * 220 / rate), rate)
    sf.write(speech, np.zeros(rate), rate)
    bed = measure_audio(str(music))
    voice = measure_audio(str(speech))
    assert background_ready(1, bed, "ok")
    assert bed["audible"] is True
    assert voice["audible"] is False
    assert voice["rms_dbfs"] == -160


@pytest.mark.parametrize("duration,status,expected", [(1, "ok", True), (1, "failed", False), (2, "ok", False), (0, "ok", False)])
def test_background_readiness_requires_a_complete_separated_stem(duration, status, expected):
    assert background_ready(duration, {"duration_seconds": 1}, status) is expected
    assert background_ready(duration, None, status) is False


def test_natural_pacing_checks_actual_segments_instead_of_only_policy_metadata():
    policy = {"preserve_pauses": True, "allow_video_retime": False, "audio_only_rate_cap": 1.1}
    line = {"audio_rate": 1.1, "video_ratio": 1, "overflow_s": 0,
            "start": 1, "end": 3, "source_start": 1, "source_end": 3}
    assert natural_pacing_ready(policy, [line])
    assert not natural_pacing_ready(policy, [])
    for override in ({"audio_rate": 1.3}, {"video_ratio": 1.1}, {"overflow_s": .1}, {"start": .9}, {"end": 3.2}):
        assert not natural_pacing_ready(policy, [{**line, **override}])
    assert not natural_pacing_ready({}, [line])


def test_streamed_audio_measurement_preserves_stereo_duration_and_energy(tmp_path):
    path = tmp_path / "long.wav"
    rate = 24000
    recording = np.full((rate * 6, 2), .125, dtype=np.float32)
    sf.write(path, recording, rate, subtype="FLOAT")
    result = measure_audio(str(path))
    assert result["duration_seconds"] == 6
    assert result["channels"] == 2
    assert result["peak"] == .125
    assert result["rms_dbfs"] == pytest.approx(-18.0617997)
    assert result["audible"] is True


def test_quality_endpoint_checks_real_project_artifacts_without_returning_private_paths(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from api.routers import dub_export as router

    directory = tmp_path / "quality_project"
    directory.mkdir()
    bed, speech = directory / "bed.wav", directory / "speech.wav"
    sf.write(bed, np.full(24000, .05, dtype=np.float32), 24000)
    sf.write(speech, np.full(24000, .15, dtype=np.float32), 24000)
    job = {"duration": 1, "background_separation": "ok", "no_vocals_path": str(bed),
           "dubbed_tracks": {"es": {"path": str(speech)}}, "fit_plans": {"es": {
               "params": {"preserve_pauses": True, "allow_video_retime": False, "audio_only_rate_cap": 1.1},
               "delivery_segments": [{"audio_rate": 1, "video_ratio": 1, "overflow_s": 0,
                                      "start": 0, "end": 1, "source_start": 0, "source_end": 1}],
           }}}
    monkeypatch.setattr(router, "DUB_DIR", str(tmp_path))
    monkeypatch.setattr(router, "_get_job", lambda identifier: job if identifier == "quality_project" else None)
    monkeypatch.setenv("VOICESTUDIO_DUB_NATURAL_PACING", "1")
    app = FastAPI()
    app.include_router(router.router)
    with TestClient(app) as client:
        result = client.get("/dub/quality/quality_project?lang=es")
        assert result.status_code == 200
        assert str(tmp_path) not in result.text
        assert result.json()["background_ready"] is True
        assert result.json()["speech"]["audible"] is True
        assert result.json()["pacing_ready"] is True
        assert result.json()["duration_ready"] is True
        sf.write(speech, np.zeros(12000), 24000)
        changed = client.get("/dub/quality/quality_project?lang=es").json()
        assert changed["speech"]["audible"] is False
        assert changed["duration_ready"] is False
        job["no_vocals_path"] = str(tmp_path / "outside.wav")
        sf.write(tmp_path / "outside.wav", np.ones(24000), 24000)
        assert client.get("/dub/quality/quality_project?lang=es").status_code == 400
