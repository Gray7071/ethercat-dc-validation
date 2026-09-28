#!/usr/bin/env python3
"""Offline DC observations; standard library only. Never controls hardware."""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import re
import statistics


def number(value):
    if value is None or str(value).strip() == '':
        return None
    result = float(value)
    if not math.isfinite(result):
        raise ValueError('Non-finite number')
    return result


def flag(value):
    if value is None or str(value).strip() == '':
        return None
    if str(value).lower() in ('1', 'true'):
        return True
    if str(value).lower() in ('0', 'false'):
        return False
    raise ValueError('Boolean must be 0/1 or true/false: ' + str(value))


def code(value):
    if value is None or str(value).strip() == '':
        return None
    s = str(value).strip()
    return int(s, 16) if s.lower().startswith('0x') else int(s)


def read_csv(path):
    with path.open(encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        required = {'time_s', 'all_op', 'wkc', 'wkc_expected', 'dc_ns',
                    'dc_valid', 'dc_fresh', 'ready'}
        if not required <= set(reader.fieldnames or []):
            raise ValueError('Missing columns: ' + ', '.join(sorted(required - set(reader.fieldnames or []))))
        rows = []
        for i, raw in enumerate(reader, 2):
            try:
                row = {k: number(raw.get(k)) for k in ('time_s', 'wkc', 'wkc_expected', 'dc_ns')}
                row.update({k: code(raw.get(k)) for k in ('cycle', 'cycle_time_ns', 'al_code', 'drive_error')})
                row.update({k: flag(raw.get(k)) for k in ('all_op', 'dc_valid', 'dc_fresh', 'ready')})
                row['phase'] = raw.get('phase') or 'unknown'
                rows.append(row)
            except ValueError as exc:
                raise ValueError(f'{path}:{i}: {exc}') from exc
    return rows


def read_r13(folder, motor_wkc, sensor_wkc):
    """Specific adapter for 193 r13 session.jsonl, not an arbitrary log parser.

    TELEM lacks a DC sample ID. Freshness is deliberately unknown.
    Sensor state is merged only when a prior observation is <=150 ms old.
    """
    rows, sensor = [], None
    with (folder / 'session.jsonl').open(encoding='utf-8') as f:
        last_t = -1.0
        for index, line in enumerate(f, 1):
            obj = json.loads(line)
            t = number(obj['t'])
            if t is None or t < last_t:
                raise ValueError(f'Non-monotonic observation at JSONL line {index}')
            last_t = t
            message = obj['line']
            if message.startswith('{'):
                s = json.loads(message)
                if s.get('type') == 'telemetry':
                    sensor = (t, s)
            if not message.startswith('TELEM '):
                continue
            v = dict(re.findall(r'(\w+)=([^ ]+)', message))
            known = sensor is not None and t - sensor[0] <= .15
            s = sensor[1] if known else {}
            motor_op = v['op'] == '1'
            all_op = motor_op and s.get('actual_state') == 'OP' if known else None
            wc = int(v['wc']) + int(s['wkc']) if known else None
            valid = v['dc'].isdigit() and int(v['dc']) != 0xffffffff
            life = v['life']
            rows.append(dict(time_s=t, all_op=all_op, wkc=wc,
                             wkc_expected=motor_wkc + sensor_wkc,
                             dc_ns=int(v['dc']) if valid else None, dc_valid=valid,
                             dc_fresh=None, ready=life == 'READY',
                             phase='stopping' if life in ('STOPPING', 'CLOSED') else 'run',
                             al_code=None, drive_error=code(v.get('err')),
                             cycle=int(v['cycle']), cycle_time_ns=None))
    return rows


def classify_faults(text):
    """Keep protocol domains separate. Kernel clock is not mapped to app time."""
    result = []
    phase = 'unknown_before_release'
    for line in text.splitlines():
        if 'Requesting master' in line:
            phase = 'initialization_or_run'
        if 'Releasing master' in line or 'Released.' in line:
            phase = 'release_or_after'
        category = None
        if re.search(r'AL status (?:message|code)\s+0x[0-9a-f]+', line, re.I):
            category = 'ethercat_al'
        elif re.search(r'(?:SDO|mailbox|CoE)', line, re.I) and re.search(r'(?:timed? ?out|timeout|failed|error|no response)', line, re.I):
            category = 'mailbox_sdo'
        elif re.search(r'(?:err|error_code|drive_error)=0x(?!0+\b)[0-9a-f]+', line, re.I):
            category = 'drive_error'
        elif 'ERROR' in line or 'WARNING' in line or 'did not sync' in line:
            category = 'other_diagnostic'
        if category:
            result.append({'category': category, 'phase': phase, 'line': line})
    return result


def analyze(rows, dc_limit, stable_seconds, max_gap, every_cycle=False, period_ns=None):
    if not rows:
        raise ValueError('No observations')
    if not all(math.isfinite(v) for v in (dc_limit, stable_seconds, max_gap)) or dc_limit < 0 or stable_seconds < 0 or max_gap <= 0:
        raise ValueError('Invalid thresholds')
    if period_ns is not None and period_ns <= 0:
        raise ValueError('period_ns must be positive')
    previous = None
    for r in rows:
        t = r['time_s']
        if t is None or t < 0 or (previous is not None and t <= previous):
            raise ValueError('time_s must be nonnegative and strictly increasing within one run')
        previous = t
        for field in ('wkc', 'wkc_expected'):
            if r.get(field) is not None and (r[field] < 0 or int(r[field]) != r[field]):
                raise ValueError(field + ' must be a nonnegative integer')

    active = [r for r in rows if r['phase'] not in ('stopping', 'released', 'after_release')]
    first_op = next((r['time_s'] for r in active if r['all_op'] is True), None)
    ready = next((r['time_s'] for r in active if r['ready'] is True), None)
    first_stable = None
    good_start, prev_t = None, None
    gaps = []
    for r in active:
        gap = prev_t is not None and r['time_s'] - prev_t > max_gap
        if gap:
            gaps.append({'after_s': prev_t, 'gap_s': r['time_s'] - prev_t})
        good = (r['all_op'] is True and r['wkc'] is not None
                and r['wkc_expected'] is not None and r['wkc_expected'] > 0
                and r['wkc'] == r['wkc_expected'] and r['dc_valid'] is True
                and r['dc_fresh'] is True and r['dc_ns'] is not None
                and abs(r['dc_ns']) <= dc_limit
                and r.get('drive_error') in (None, 0) and r.get('al_code') in (None, 0))
        if not good:
            good_start = None
        else:
            if good_start is None or gap:
                good_start = r['time_s']
            if first_stable is None and r['time_s'] - good_start + 1e-12 >= stable_seconds:
                first_stable = r['time_s']
        prev_t = r['time_s']

    def metrics(subset):
        valid = [abs(r['dc_ns']) for r in subset if r['dc_valid'] is True and r['dc_ns'] is not None]
        return {'observations': len(subset), 'dc_peak_abs_ns': max(valid, default=None),
                'dc_invalid_or_missing': sum(r['dc_valid'] is not True or r['dc_ns'] is None for r in subset),
                'dc_freshness_unknown': sum(r['dc_fresh'] is None for r in subset),
                'wkc_mismatch_observations': sum(r['wkc'] is not None and r['wkc_expected'] is not None and r['wkc'] != r['wkc_expected'] for r in subset),
                'wkc_unknown_observations': sum(r['wkc'] is None or r['wkc_expected'] is None for r in subset),
                'not_all_op_observations': sum(r['all_op'] is False for r in subset),
                'all_op_unknown_observations': sum(r['all_op'] is None for r in subset),
                'dc_over_limit_observations': sum(v > dc_limit for v in valid)}

    faults = [{'time_s': r['time_s'], 'phase': r['phase'], 'category': category, 'code': hex(r[field])}
              for r in rows for field, category in [('al_code', 'ethercat_al'), ('drive_error', 'drive_error')]
              if r.get(field) not in (None, 0)]
    post = [r for r in active if ready is not None and r['time_s'] >= ready]
    stable = [r for r in active if first_stable is not None and r['time_s'] >= first_stable]
    cycle_report = {'available': False, 'reason': 'Requires explicit --every-cycle and cycle/cycle_time_ns on every row'}
    if every_cycle:
        if not all(r.get('cycle') is not None and r.get('cycle_time_ns') is not None for r in rows):
            raise ValueError('--every-cycle requires cycle and cycle_time_ns on every row')
        steps = [b['cycle'] - a['cycle'] for a, b in zip(rows, rows[1:])]
        intervals = [b['cycle_time_ns'] - a['cycle_time_ns'] for a, b in zip(rows, rows[1:])]
        if any(s <= 0 for s in steps) or any(i <= 0 for i in intervals):
            raise ValueError('Cycle or timestamp resets/duplicates: split runs before analysis')
        cycle_report = {'available': True, 'gap_events': sum(s > 1 for s in steps),
                        'missing_record_count': sum(s - 1 for s in steps),
                        'interval_min_ns': min(intervals, default=None),
                        'interval_max_ns': max(intervals, default=None),
                        'interval_mean_ns': statistics.mean(intervals) if intervals else None,
                        'max_abs_period_error_ns': max((abs(i - period_ns) for i, s in zip(intervals, steps) if s == 1), default=None) if period_ns else None,
                        'meaning': 'Software sample records; gaps do not prove missing EtherCAT frames'}
    return {'schema_version': 1, 'duration_observed_s': rows[-1]['time_s'] - rows[0]['time_s'],
            'first_all_op_observed_s': first_op, 'ready_reported_s': ready,
            'first_joint_stable_observed_s': first_stable,
            'criteria': {'dc_limit_ns': dc_limit, 'stable_seconds': stable_seconds, 'max_observation_gap_s': max_gap},
            'run': metrics(active), 'post_ready': metrics(post), 'post_joint_stable': metrics(stable),
            'ready_lost_observations': sum(r['ready'] is False for r in post),
            'observation_gaps': gaps, 'cycle_records': cycle_report, 'fault_observations': faults,
            'missing_fault_fields': {k: sum(r.get(k) is None for r in active) for k in ('al_code', 'drive_error')},
            'verdict': 'observations_only_not_automatic_acceptance',
            'limits': ['Times use the input time origin; no extrapolation before the first observation.',
                       'READY is reported by the application, not independently certified.',
                       'Stable detection requires fresh DC, all OP and complete WKC; missing data is not a pass.',
                       'Post-stable metrics include later loss; a peak is not proof of sustained success.',
                       'Software DC and sample timestamps do not measure physical SYNC0 or NIC transmit jitter.']}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('input', type=Path, help='Normalized CSV or r13 evidence folder')
    p.add_argument('--format', choices=['csv', 'sophon-r13'], default='csv')
    p.add_argument('--dc-limit-ns', required=True, type=float)
    p.add_argument('--stable-seconds', required=True, type=float)
    p.add_argument('--max-observation-gap-s', required=True, type=float)
    p.add_argument('--every-cycle', action='store_true')
    p.add_argument('--period-ns', type=int)
    p.add_argument('--motor-wkc', type=int)
    p.add_argument('--sensor-wkc', type=int)
    p.add_argument('--kernel-log', type=Path, help='Already isolated per-run log; never a full historical dmesg')
    p.add_argument('--out', required=True, type=Path)
    args = p.parse_args()
    try:
        source = args.input
        if args.format == 'sophon-r13':
            if args.motor_wkc is None or args.sensor_wkc is None:
                p.error('r13 requires explicit --motor-wkc and --sensor-wkc')
            if args.motor_wkc <= 0 or args.sensor_wkc <= 0:
                p.error('r13 expected WKC values must be positive')
            rows = read_r13(source, args.motor_wkc, args.sensor_wkc)
            source = source / 'session.jsonl'
        else:
            rows = read_csv(source)
        report = analyze(rows, args.dc_limit_ns, args.stable_seconds,
                         args.max_observation_gap_s, args.every_cycle, args.period_ns)
        report['input'] = {'name': source.name, 'sha256': hashlib.sha256(source.read_bytes()).hexdigest(), 'format': args.format}
        if args.format == 'sophon-r13':
            report['limits'].append('r13: DC sample freshness unavailable; no independent stable-time claim. Sensor state carried forward at most 150 ms. OP uses combined telemetry, not CLI poll timing.')
        if args.kernel_log:
            report['kernel_faults'] = classify_faults(args.kernel_log.read_text(encoding='utf-8', errors='replace'))
            report['kernel_sha256'] = hashlib.sha256(args.kernel_log.read_bytes()).hexdigest()
        # Exclusive create: don't silently overwrite a previous run/report.
        with args.out.open('x', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2, allow_nan=False)
            f.write('\n')
        print(json.dumps({k: report[k] for k in ('first_all_op_observed_s', 'ready_reported_s', 'first_joint_stable_observed_s', 'post_ready')}, ensure_ascii=False))
    except (ValueError, KeyError, OSError) as exc:
        p.exit(2, str(exc) + '\n')


if __name__ == '__main__':
    main()
