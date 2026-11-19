"""Mancebo's natural pacing policy must not consume pauses or cut speech."""
import pytest

from services.fit_planner import FitParams, plan_fit


def natural_policy():
    return FitParams(
        max_audio_only_rate=1.1, audio_rate_cap=1.1, video_slow_cap=1.0,
        gap_guard_s=0.0, allow_video_retime=False, min_audio_rate=1.0,
        preserve_pauses=True, audio_only_rate_cap=1.1,
    )


def test_natural_policy_preserves_the_full_middle_pause_and_trailing_bed():
    plan = plan_fit(
        [{"id": "a", "start": 1, "end": 3}, {"id": "b", "start": 11, "end": 13}],
        [2, 2], 20, natural_policy(),
    )
    assert [(s.new_start, s.effective_end, s.new_end) for s in plan.segments] == [(1, 3, 3), (11, 13, 13)]
    assert plan.total_duration == 20
    assert not plan.needs_video_retime


@pytest.mark.parametrize("natural,overflow", [(2.2, 0), (2.2002, 0.0002), (4.0, 1.6364)])
def test_natural_policy_reports_overrun_at_ten_percent_instead_of_legacy_compression(natural, overflow):
    segment = plan_fit([{"id": "line", "start": 0, "end": 2}], [natural], 10, natural_policy()).segments[0]
    assert segment.audio_rate <= 1.1
    assert segment.video_ratio == 1
    assert segment.effective_end == 2
    assert segment.overflow_s == pytest.approx(overflow, abs=0.0001)
    assert (segment.status == "overflow_trimmed") == (overflow > 0)


def test_natural_policy_keeps_shorter_delivery_at_its_natural_speed():
    segment = plan_fit([{"id": "line", "start": 1, "end": 5}], [1], 10, natural_policy()).segments[0]
    assert segment.audio_rate == 1
    assert segment.status == "fits"
    assert segment.orig_start == segment.new_start == 1


def test_managed_request_binds_the_policy_before_generation_without_mutating_standalone(monkeypatch):
    from api.routers.dub_generate import _managed_pacing_request
    from schemas.requests import DubRequest
    request = DubRequest(
        segments=[{"start": 0, "end": 2, "text": "Hello"}],
        speed=1.8, timing_strategy="strict_slot",
    )
    monkeypatch.delenv("VOICESTUDIO_DUB_NATURAL_PACING", raising=False)
    assert _managed_pacing_request(request) is request
    monkeypatch.setenv("VOICESTUDIO_DUB_NATURAL_PACING", "1")
    managed = _managed_pacing_request(request)
    assert managed is not request
    assert request.speed == 1.8 and request.timing_strategy == "strict_slot"
    assert managed.speed == 1 and managed.timing_strategy == "smart_fit"
    assert managed.fit_options.preserve_pauses is True
    assert managed.fit_options.allow_video_retime is False
    assert managed.fit_options.audio_only_rate_cap == 1.1
    assert managed.fit_options.min_audio_rate == 1


def test_pause_and_rate_policy_invalidate_fit_cache_without_invalidating_default_tracks():
    from services.incremental import fit_fingerprint
    original = fit_fingerprint({})
    assert fit_fingerprint({"preserve_pauses": False, "audio_only_rate_cap": 1.8}) == original
    assert fit_fingerprint({"preserve_pauses": True}) != original
    assert fit_fingerprint({"audio_only_rate_cap": 1.1}) != original
