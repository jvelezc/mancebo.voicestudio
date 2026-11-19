"""Classify measured dubbing defects and propose bounded repair actions."""

import argparse
import hashlib
import json
import math
from pathlib import Path
import subprocess


def ms(value):
    if type(value) not in (float, int) or not math.isfinite(value):
        raise ValueError('Timing observations must be finite numbers in milliseconds')
    return value


def check(evidence, artifact_verified=False):
    findings = []

    def report(code, severity, action, **scope):
        findings.append({'code': code, 'severity': severity, 'action': action, **scope})

    if not artifact_verified:
        report('ARTIFACT_UNVERIFIED', 'review', 'Hash, probe and fully decode the actual output revision.')

    cues = evidence.get('cues', [])
    if not cues:
        report('CLAUSE_MEASUREMENTS_MISSING', 'review', 'Measure starts and ends against source scene beats.')
    duration = evidence.get('duration_ms')
    if duration is not None and ms(duration) <= 0:
        raise ValueError('Invalid artifact duration')
    clause_tolerance = ms(evidence.get('clause_tolerance_ms', 200))
    sync_tolerance = ms(evidence.get('av_tolerance_ms', 80))
    speed_limit = ms(evidence.get('maximum_speedup', 1.10))
    if clause_tolerance <= 0 or sync_tolerance <= 0 or not 1 <= speed_limit <= 2:
        raise ValueError('Invalid timing limits')
    cue_ids = set()
    for cue in cues:
        cue_id = cue['id']
        if not isinstance(cue_id, str) or not cue_id or cue_id in cue_ids:
            raise ValueError('Cue IDs must be nonempty and unique')
        cue_ids.add(cue_id)
        expected_start, expected_end = map(ms, cue['expected_ms'])
        if not 0 <= expected_start < expected_end or (duration is not None and expected_end > duration):
            raise ValueError('Invalid expected interval')
        scope = {'cue_id': cue_id, 'start_ms': expected_start, 'end_ms': expected_end}
        if cue.get('observed_ms') is None:
            report('CLAUSE_UNVERIFIED', 'review', 'Align the clause on the final dialogue track.', **scope)
        else:
            actual_start, actual_end = map(ms, cue['observed_ms'])
            if not 0 <= actual_start < actual_end or (duration is not None and actual_end > duration):
                raise ValueError('Invalid observed interval')
            start_delta = actual_start - expected_start
            end_delta = actual_end - expected_end
            if max(abs(start_delta), abs(end_delta)) > clause_tolerance:
                report('CLAUSE_BEAT_MISMATCH', 'repair',
                       'Refit this clause and its adjacent pauses, then regenerate and align only the affected span.',
                       start_delta_ms=start_delta, end_delta_ms=end_delta, **scope)
        speed = cue.get('render_speed')
        if speed is None:
            report('CLAUSE_SPEED_UNVERIFIED', 'review', 'Read the applied speed from the render evidence.', **scope)
        elif ms(speed) <= 0:
            raise ValueError('Invalid render speed')
        elif speed > speed_limit:
            report('CLAUSE_TOO_FAST', 'repair', 'Adapt the wording or approved timing before applying more speed.', **scope)
    expected_ids = evidence.get('expected_cue_ids')
    if (not isinstance(expected_ids, list) or not expected_ids
            or any(not isinstance(key, str) or not key for key in expected_ids)
            or len(expected_ids) != len(cue_ids) or set(expected_ids) != cue_ids):
        report('CLAUSE_COVERAGE_UNVERIFIED', 'review', 'Match all measured cue IDs to the approved translation plan.')

    shots = evidence.get('shots', [])
    covered = 0
    incomplete_coverage = duration is None or not shots
    for shot in shots:
        start, end = map(ms, shot['range_ms'])
        if not 0 <= start < end:
            raise ValueError('Invalid shot interval')
        incomplete_coverage |= start != covered
        covered = end
        scope = {'shot_id': shot['id'], 'start_ms': start, 'end_ms': end}
        visible = shot.get('visible_speech')
        if visible is False:
            continue
        if visible is not True:
            report('VISIBLE_SPEECH_UNVERIFIED', 'review', 'Identify the visible active speaker.', **scope)
            continue
        offset = shot.get('av_offset_ms')
        sync_review = shot.get('sync_review')
        if sync_review == 'fail' or (offset is not None and abs(ms(offset)) > sync_tolerance):
            report('AV_SYNC_MISMATCH', 'repair',
                   'Check the audio and frame origins. Re-render this shot from the timed dialogue and verify playback.',
                   offset_ms=offset, **scope)
        elif sync_review != 'pass':
            report('AV_SYNC_UNVERIFIED', 'review', 'Check mouth timing on consecutive playback.', **scope)
        artifact = shot.get('mouth_review')
        if artifact in ('warping', 'temporal_flicker', 'double_edge', 'seam'):
            report('MOUTH_ARTIFACT', 'repair',
                   'Stabilize the face track and limit the feathered region. Compare a targeted retake in motion.',
                   artifact=artifact, **scope)
        elif artifact != 'pass':
            report('MOUTH_QUALITY_UNVERIFIED', 'review', 'Inspect mouth shape and frame-to-frame stability in motion.', **scope)
    if incomplete_coverage or covered != duration:
        report('SHOT_COVERAGE_UNVERIFIED', 'review', 'Record shot ranges across the entire output and identify visible speakers.')

    mix = evidence.get('mix', {})
    mix_checks = {
        'wording': 'Verify the finished mix against the reviewed translation and repair wrong or missing words.',
        'voice': 'Listen for pronunciation, speaker likeness and expression. Regenerate only affected dialogue.',
        'background': 'Check the music and effects bed for continuity and original speech bleed. Repair the affected mix.',
        'peaks': 'Measure the encoded output peaks and correct the mix gain or limiter.',
    }
    for key, action in mix_checks.items():
        result = mix.get(key)
        if result != 'pass':
            report(f'MIX_{key.upper()}_{"FAILED" if result == "fail" else "UNVERIFIED"}',
                   'repair' if result == 'fail' else 'review', action)

    status = 'checks_passed'
    if findings:
        status = 'repair_required' if any(row['severity'] == 'repair' for row in findings) else 'review_required'
    return {'status': status, 'artifact_sha256': evidence.get('artifact_sha256'), 'findings': findings}


def verify_artifact(path, expected_hash, duration_ms):
    if path.suffix.lower() not in {'.mp4', '.mkv', '.mov', '.webm'}:
        raise ValueError('Expected a local render video')
    with path.open('rb') as source:
        if hashlib.file_digest(source, 'sha256').hexdigest() != expected_hash:
            raise ValueError('Evidence belongs to a different artifact revision')
    input_path = str(path.resolve())
    media_options = ['-protocol_whitelist', 'file,pipe']
    probe = subprocess.run(['ffprobe', '-v', 'error', *media_options, '-show_entries', 'format=duration',
                            '-of', 'json', input_path], check=True, capture_output=True, timeout=30)
    measured_duration = ms(float(json.loads(probe.stdout)['format']['duration']) * 1000)
    if abs(measured_duration - ms(duration_ms)) > 80:
        raise ValueError('Artifact timing and the evidence timeline disagree')
    command = ['ffmpeg', '-v', 'error', '-nostdin', '-xerror', *media_options, '-i', input_path,
               '-map', '0:v:0', '-map', '0:a:0', '-f', 'null', '-']
    subprocess.run(command, check=True, capture_output=True, timeout=900)
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('evidence', type=Path)
    parser.add_argument('--artifact', type=Path)
    args = parser.parse_args()
    try:
        raw = args.evidence.read_text(encoding='utf-8')
        evidence = json.loads(raw)
        if not isinstance(evidence, dict):
            raise ValueError('Evidence must be a JSON object')
        verified = bool(args.artifact and verify_artifact(args.artifact, evidence.get('artifact_sha256'),
                                                          evidence.get('duration_ms')))
        result = check(evidence, artifact_verified=verified)
    except (TypeError, ValueError, KeyError, OSError, subprocess.SubprocessError):
        result = {'status': 'review_required', 'findings': [{'code': 'EVIDENCE_OR_MEDIA_INVALID', 'severity': 'review',
                  'action': 'Check the evidence schema, artifact digest, FFmpeg and full decode before delivery.'}]}
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return {'checks_passed': 0, 'review_required': 2, 'repair_required': 3}[result['status']]


if __name__ == '__main__':
    raise SystemExit(main())
