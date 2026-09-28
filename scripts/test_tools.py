"""Offline regression tests: no network, EtherCAT device, or motor commands."""
import hashlib
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from analyze_dc import analyze, classify_faults, read_csv
from collect_dc import collect


def row(t, **kw):
    r = dict(time_s=t, all_op=True, wkc=6, wkc_expected=6, dc_ns=50,
             dc_valid=True, dc_fresh=True, ready=False, phase='run',
             al_code=0, drive_error=0, cycle=None, cycle_time_ns=None)
    r.update(kw)
    return r


def report(rows, **kw):
    return analyze(rows, 1000, .2, .15, **kw)


class AnalysisTests(unittest.TestCase):
    def test_nonfinite_threshold_rejected(self):
        with self.assertRaises(ValueError):
            analyze([row(0)], float('nan'), .2, .15)

    def test_missing_snapshot_command_recorded_without_retry_or_sudo(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'test.log'
            path.write_text('offline test')
            with patch('collect_dc.platform.system', return_value='Linux'), patch('collect_dc.subprocess.run', side_effect=FileNotFoundError('test missing CLI')) as run:
                result = collect([path], Path(temp) / 'bundle', {}, 1)
            self.assertEqual(len(result['snapshots']), 5)
            self.assertEqual(run.call_count, 5)
            for call in run.call_args_list:
                self.assertNotIn('sudo', call.args[0])
                self.assertFalse(call.kwargs.get('shell', False))
                self.assertEqual(call.kwargs['timeout'], 5)

    def test_low_dc_without_all_op_never_qualifies(self):
        r = report([row(i / 10, all_op=False) for i in range(10)])
        self.assertIsNone(r['first_joint_stable_observed_s'])

    def test_ready_and_joint_stability_are_separate(self):
        r = report([row(i / 10, ready=i >= 5) for i in range(10)])
        self.assertAlmostEqual(r['first_joint_stable_observed_s'], .2)
        self.assertEqual(r['ready_reported_s'], .5)

    def test_invalid_and_stale_samples_reset_window(self):
        rows = [row(0), row(.1), row(.2, dc_valid=False), row(.3), row(.4, dc_fresh=False), row(.5), row(.6)]
        self.assertIsNone(report(rows)['first_joint_stable_observed_s'])

    def test_unknown_freshness_is_not_success(self):
        self.assertIsNone(report([row(i / 10, dc_fresh=None) for i in range(10)])['first_joint_stable_observed_s'])

    def test_wkc_mismatch_resets_window(self):
        r = report([row(0), row(.1, wkc=3), row(.2), row(.3)])
        self.assertIsNone(r['first_joint_stable_observed_s'])
        self.assertEqual(r['run']['wkc_mismatch_observations'], 1)

    def test_missing_wkc_not_zero_or_success(self):
        r = report([row(i / 10, wkc=None) for i in range(5)])
        self.assertEqual(r['run']['wkc_unknown_observations'], 5)
        self.assertEqual(r['run']['wkc_mismatch_observations'], 0)

    def test_gap_breaks_window_and_decimation_not_cycle_loss(self):
        r = report([row(0, cycle=0), row(.1, cycle=100), row(1, cycle=1000), row(1.1, cycle=1100)])
        self.assertIsNone(r['first_joint_stable_observed_s'])
        self.assertEqual(len(r['observation_gaps']), 1)
        self.assertFalse(r['cycle_records']['available'])

    def test_later_loss_preserved_stopping_excluded(self):
        r = report([row(0, ready=True), row(.1, ready=True), row(.2, ready=True),
                    row(.3, ready=False, all_op=False, dc_ns=5000),
                    row(.4, phase='stopping', dc_ns=9000)])
        self.assertEqual(r['post_joint_stable']['dc_peak_abs_ns'], 5000)
        self.assertEqual(r['ready_lost_observations'], 1)

    def test_full_cycle_gap_count_is_record_gap(self):
        r = report([row(0, cycle=1, cycle_time_ns=1000000), row(.001, cycle=2, cycle_time_ns=2000000),
                    row(.004, cycle=5, cycle_time_ns=5000000)], every_cycle=True, period_ns=1000000)
        self.assertEqual(r['cycle_records']['missing_record_count'], 2)
        self.assertEqual(r['cycle_records']['max_abs_period_error_ns'], 0)

    def test_clock_reset_and_duplicate_rejected(self):
        for rows in ([row(1), row(0)], [row(0), row(0)]):
            with self.assertRaises(ValueError):
                report(rows)

    def test_fault_domains_and_release_phase(self):
        text = 'CHECK_FAULT err=0xa000\nAL status message 0x001A: Synchronization error\nSDO upload timed out\nReleasing master...\nEtherCAT ERROR: Failed to receive AL state datagram'
        faults = classify_faults(text)
        self.assertEqual([f['category'] for f in faults], ['drive_error', 'ethercat_al', 'mailbox_sdo', 'other_diagnostic'])
        self.assertEqual(faults[-1]['phase'], 'release_or_after')

    def test_csv_missing_headers_and_nan_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / 'data.csv'
            p.write_text('time_s,dc_ns\n0,0\n', encoding='utf-8')
            with self.assertRaises(ValueError):
                read_csv(p)
            p.write_text('time_s,all_op,wkc,wkc_expected,dc_ns,dc_valid,dc_fresh,ready\n0,1,6,6,nan,1,1,0\n', encoding='utf-8')
            with self.assertRaises(ValueError):
                read_csv(p)

    def test_collector_preserves_bytes_hash_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / 'source.log'
            data = b'original\x00bytes\n'
            p.write_bytes(data)
            out = Path(temp) / 'bundle'
            m = collect([p], out, {'run': 'synthetic'})
            self.assertEqual(m['files'][0]['sha256'], hashlib.sha256(data).hexdigest())
            self.assertEqual((out / m['files'][0]['name']).read_bytes(), data)
            self.assertEqual(m['snapshots'], [])
            with self.assertRaises(FileExistsError):
                collect([p], out, {})


if __name__ == '__main__':
    unittest.main()
