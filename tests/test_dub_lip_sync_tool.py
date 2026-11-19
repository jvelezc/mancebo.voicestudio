from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from dub_lip_sync import audio_contract, frame_timing, video_contract


def test_same_duration_does_not_hide_a_dropped_presentation_beat():
    original = [{'best_effort_timestamp_time': value} for value in ('0.0', '0.04', '0.08')]
    frame_timing(original, 3)
    original[1]['best_effort_timestamp_time'] = '0.02'
    with pytest.raises(ValueError, match='constant 25 fps'):
        frame_timing(original, 3)


def test_equal_length_audio_with_nonzero_origin_is_refused():
    audio = {'codec_type': 'audio', 'start_time': '0.0', 'duration': '5.20'}
    audio_contract([audio], 130)
    with pytest.raises(ValueError, match='zero-based timeline'):
        audio_contract([{**audio, 'start_time': '0.04'}], 130)


def test_prepared_video_contract_requires_the_full_shot():
    video = {'codec_type': 'video', 'width': 1280, 'height': 720, 'nb_frames': '130',
             'r_frame_rate': '25/1', 'start_time': '0.0', 'duration': '5.20'}
    assert video_contract([video]) == (1280, 720, 130)
    with pytest.raises(ValueError, match='zero-based 25 fps'):
        video_contract([{**video, 'nb_frames': '129'}])
