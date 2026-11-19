"""Hosted music must not switch between mixed and separated audio at each cue."""
import asyncio
import numpy as np
import pytest
import soundfile as sf

from services.dub_background import surgical_background


def test_continuous_music_keeps_the_same_separated_samples_across_every_cue(tmp_path):
    rate = 48000
    times = np.arange(rate * 3) / rate
    # Separation changes both level and phase. Switching to the original mix
    # between cues would modulate the bed even when both inputs are non-silent.
    bed = np.column_stack((.08*np.sin(2*np.pi*220*times), .04*np.sin(2*np.pi*330*times)))
    original = bed * 2 + .1
    source, separated = [tmp_path/name for name in ('source.wav', 'bed.wav')]
    sf.write(source, original, rate, subtype='FLOAT')
    sf.write(separated, bed, rate, subtype='FLOAT')
    actual = asyncio.run(surgical_background(str(source), str(separated), str(tmp_path),
        [{'start': .4, 'end': 1}, {'start': 1.7, 'end': 2.4}], [], 3, continuous=True))
    samples, sample_rate = sf.read(actual, dtype='float32', always_2d=True)
    assert sample_rate == rate
    np.testing.assert_allclose(samples, bed, atol=1e-6)
    assert sf.info(actual).duration == pytest.approx(3, abs=1/rate)


def test_continuous_music_rejects_incomplete_separation_instead_of_filling_silence(tmp_path):
    source, separated = [tmp_path/name for name in ('source.wav', 'bed.wav')]
    sf.write(source, np.zeros((96000, 2)), 48000)
    sf.write(separated, np.zeros((48000, 2)), 48000)
    with pytest.raises(ValueError, match='incomplete'):
        asyncio.run(surgical_background(str(source), str(separated), str(tmp_path),
            [{'start': .2, 'end': .5}], [], 2, continuous=True))


def test_continuous_music_does_not_reuse_the_sentence_switching_cache(tmp_path):
    source, separated = [tmp_path/name for name in ('source.wav', 'bed.wav')]
    sf.write(source, np.full((48000,2), .1), 48000, subtype='FLOAT')
    sf.write(separated, np.full((48000,2), .02), 48000, subtype='FLOAT')
    args = (str(source), str(separated), str(tmp_path), [{'start': .2, 'end': .7}], [], 1)
    legacy = asyncio.run(surgical_background(*args))
    continuous = asyncio.run(surgical_background(*args, continuous=True))
    assert legacy != continuous
    assert sf.read(legacy)[0][0,0] == pytest.approx(.1)
    assert sf.read(continuous)[0][0,0] == pytest.approx(.02)


def test_music_time_map_retains_video_landmarks_and_unchanged_pauses():
    from services.dub_background import music_time_map
    from services.video_retime import expand_retime_chunks
    chunks = expand_retime_chunks([{'orig_start': 1, 'orig_end': 2, 'stretch_ratio': 1.5}], 3)
    mapping, duration = music_time_map(chunks, 48000)
    assert mapping == '0 0\n48000 48000\n96000 120000\n144000 168000\n'
    assert duration == 3.5


@pytest.mark.parametrize('chunks', [[], [(1,2,1)], [(0,1,float('nan'))], [(0,1,1),(0.9,2,1)]])
def test_music_time_map_rejects_missing_or_ambiguous_timeline(chunks):
    from services.dub_background import music_time_map
    with pytest.raises(ValueError): music_time_map(chunks, 48000)


def test_continuous_retiming_does_not_fall_back_to_chopped_music_without_its_tool(tmp_path, monkeypatch):
    monkeypatch.delenv('VOICESTUDIO_RUBBERBAND_BIN', raising=False)
    source, separated = [tmp_path/name for name in ('source.wav', 'bed.wav')]
    sf.write(source, np.zeros((48000,2)), 48000)
    sf.write(separated, np.zeros((48000,2)), 48000)
    with pytest.raises(ValueError, match='configured Rubber Band'):
        asyncio.run(surgical_background(str(source), str(separated), str(tmp_path),
            [{'start':0,'end':1}], [{'orig_start':0,'orig_end':1,'stretch_ratio':1.1}], 1, continuous=True))


def test_zero_length_cue_does_not_require_a_music_retimer(tmp_path, monkeypatch):
    monkeypatch.delenv('VOICESTUDIO_RUBBERBAND_BIN', raising=False)
    source, separated = [tmp_path/name for name in ('source.wav', 'bed.wav')]
    sf.write(source, np.zeros((48000,2)), 48000)
    sf.write(separated, np.full((48000,2), .02), 48000, subtype='FLOAT')
    out = asyncio.run(surgical_background(str(source), str(separated), str(tmp_path),
        [{'start':0,'end':1}], [{'orig_start':.5,'orig_end':.5,'stretch_ratio':0}], 1, continuous=True))
    assert sf.info(out).duration == pytest.approx(1)
    np.testing.assert_allclose(sf.read(out)[0], .02, atol=1e-6)


def test_cancelled_music_render_kills_and_reaps_its_own_process(tmp_path, monkeypatch):
    from services import dub_background as background
    from pathlib import Path
    killed = []
    class Process:
        returncode = None
        async def wait(self):
            if self.returncode is None: raise asyncio.CancelledError()
            return self.returncode
        def kill(self):
            killed.append(True); self.returncode = -9
    process = Process()
    async def spawn(*args, **kwargs): return process
    monkeypatch.setattr(background, 'spawn_subprocess', spawn)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(background._retime_music(Path('/configured/rubberband'), 'in.wav', 'out.wav', tmp_path/'map.txt', 3))
    assert killed == [True] and process.returncode == -9
