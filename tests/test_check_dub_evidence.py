from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from check_dub_evidence import check


PASSABLE = {
    'artifact_sha256': 'a' * 64,
    'duration_ms': 5200,
    'expected_cue_ids': ['line-1', 'line-2'],
    'cues': [
        {'id': 'line-1', 'expected_ms': [180, 2900], 'observed_ms': [200, 2850], 'render_speed': 1},
        {'id': 'line-2', 'expected_ms': [3180, 5160], 'observed_ms': [3190, 5130], 'render_speed': 1.06},
    ],
    'shots': [{'id': 'close-up', 'range_ms': [0, 5200], 'visible_speech': True,
               'sync_review': 'pass', 'av_offset_ms': 39, 'mouth_review': 'pass'}],
    'mix': dict.fromkeys(('wording', 'voice', 'background', 'peaks'), 'pass'),
}


class DubbingEvidenceTests(unittest.TestCase):
    def test_recognizable_words_do_not_clear_early_clause_and_warping(self):
        evidence = deepcopy(PASSABLE)
        evidence['cues'][1]['observed_ms'] = [1740, 3980]
        evidence['shots'][0]['mouth_review'] = 'warping'
        evidence['shots'][0]['sync_review'] = 'unverified'
        result = check(evidence, artifact_verified=True)
        self.assertEqual(result['status'], 'repair_required')
        problems = {item['code']: item for item in result['findings']}
        self.assertEqual(problems['CLAUSE_BEAT_MISMATCH']['cue_id'], 'line-2')
        self.assertEqual(problems['CLAUSE_BEAT_MISMATCH']['start_delta_ms'], -1440)
        self.assertEqual(problems['CLAUSE_BEAT_MISMATCH']['end_delta_ms'], -1180)
        self.assertEqual(problems['MOUTH_ARTIFACT']['shot_id'], 'close-up')
        self.assertEqual(problems['AV_SYNC_UNVERIFIED']['severity'], 'review')

    def test_missing_timeline_and_output_evidence_keep_preview_in_review(self):
        evidence = deepcopy(PASSABLE)
        del evidence['shots'][0]['mouth_review']
        evidence['shots'][0]['range_ms'] = [0, 4500]
        evidence['cues'].pop()
        result = check(evidence)
        self.assertEqual(result['status'], 'review_required')
        self.assertEqual({row['code'] for row in result['findings']},
                         {'ARTIFACT_UNVERIFIED', 'CLAUSE_COVERAGE_UNVERIFIED',
                          'SHOT_COVERAGE_UNVERIFIED', 'MOUTH_QUALITY_UNVERIFIED'})

    def test_measured_sync_drift_and_excessive_speed_have_distinct_repairs(self):
        evidence = deepcopy(PASSABLE)
        evidence['shots'][0]['av_offset_ms'] = -120
        evidence['cues'][0]['render_speed'] = 1.14
        result = check(evidence, artifact_verified=True)
        self.assertEqual(result['status'], 'repair_required')
        self.assertEqual([row['code'] for row in result['findings']], ['CLAUSE_TOO_FAST', 'AV_SYNC_MISMATCH'])
        self.assertEqual(result['findings'][1]['offset_ms'], -120)

    def test_verified_revision_passes_and_offscreen_needs_no_lip_evidence(self):
        evidence = deepcopy(PASSABLE)
        result = check(evidence, artifact_verified=True)
        self.assertEqual(result, {'status': 'checks_passed', 'artifact_sha256': 'a' * 64, 'findings': []})
        evidence['shots'] = [{'id': 'narrated', 'range_ms': [0, 5200], 'visible_speech': False}]
        self.assertEqual(check(evidence, artifact_verified=True)['status'], 'checks_passed')
