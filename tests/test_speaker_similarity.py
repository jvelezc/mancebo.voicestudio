from pydantic import ValidationError
import pytest

from schemas.requests import DubSegment
from services.incremental import segment_fingerprint
from services.speaker_similarity import source_voice_policy, require_source_reference


@pytest.mark.parametrize('profile', ['auto:speaker_1', 'auto-seg:line-7'])
def test_disabled_similarity_removes_source_reference(profile):
    assert source_voice_policy(profile, 'off', 'consistent') == (None, 'per_line')


def test_similarity_never_replaces_an_explicit_saved_voice():
    assert source_voice_policy('saved-voice-42', 'off') == ('saved-voice-42', 'per_line')
    assert source_voice_policy('saved-voice-42', 'consistent') == ('saved-voice-42', 'consistent')


def test_per_speaker_mode_overrides_job_default():
    assert source_voice_policy('auto:alice', 'consistent', 'per_line') == ('auto:alice', 'consistent')
    assert source_voice_policy('auto:bob', 'per_line', 'consistent') == ('auto:bob', 'per_line')


def test_omitted_similarity_preserves_legacy_mode():
    assert source_voice_policy('auto:alice', None) == ('auto:alice', 'per_line')
    assert source_voice_policy('auto:alice', None, 'consistent') == ('auto:alice', 'consistent')


def test_explicit_similarity_requires_a_real_source_reference(tmp_path):
    path = tmp_path / 'alice.wav'
    for missing in [None, str(path), str(tmp_path)]:
        with pytest.raises(ValueError, match='Re-analyze the source'):
            require_source_reference(missing)
    path.write_bytes(b'fixture')
    assert require_source_reference(str(path)) is None


@pytest.mark.parametrize('mode', ['consistent', 'per_line', 'off'])
def test_similarity_schema_accepts_supported_reference_strategies(mode):
    segment = DubSegment(start=0, end=4, text='Hola', speaker_similarity=mode)
    assert segment.model_dump()['speaker_similarity'] == mode


@pytest.mark.parametrize('mode', [85, 0.85, '', '85%', 'blend', True])
def test_similarity_rejects_unsupported_percentage_and_modes(mode):
    with pytest.raises(ValidationError):
        DubSegment(start=0, end=4, text='Hola', speaker_similarity=mode)


def test_reference_change_invalidates_only_the_changed_segment_audio():
    alice = {'text': 'Hola', 'profile_id': 'auto:alice'}
    bob = {'text': 'Buenos días', 'profile_id': 'auto:bob'}
    before_bob = segment_fingerprint(bob, track_lang='es')
    legacy = segment_fingerprint(alice, track_lang='es')
    assert legacy == segment_fingerprint({**alice, 'speaker_similarity': None}, track_lang='es')
    hashes = {segment_fingerprint({**alice, 'speaker_similarity': mode}, track_lang='es')
              for mode in ['consistent', 'per_line', 'off']}
    assert len(hashes) == 3
    assert legacy not in hashes
    assert segment_fingerprint(bob, track_lang='es') == before_bob
