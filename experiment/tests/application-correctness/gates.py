"""Prospective application eligibility; every original fidelity predicate stays unchanged.

No new numerical tolerance: finite timing/rate deviations are OUT_OF_SPEC. Delivery,
actuation, paths, resource/clock and record validity remain mandatory. This module
never certifies the later application or replaces the independent raw audit.
"""
import collections
import json
import math
import statistics

AGGREGATES = {'calibration passes without threshold changes',
              'application network calibration unchanged criteria'}
FIDELITY = {
    'RTT restoration within frozen tolerance',
    'delay RTT increment within frozen bounds',
    'access-segment control unaffected',
    'baseline above requested cap',
    'rate-only throughput within frozen bounds',
    'throughput restores',
}
PATHS = [('edge', '10.123.0.3'), ('cloud', '10.123.0.10'),
         ('edge', '10.123.0.12')]


def require(value, message):
    if not value:
        raise ValueError(message)


def number(value):
    require(type(value) in (int, float) and math.isfinite(value) and value >= 0,
            'Finite nonnegative measurement required')
    return value


def assess(measurements, checks, aggregate, *, finished=False):
    """Recompute six original phases and bind every numerical check, before traffic.

    The optional seventh phase is the original restored path after the cut. Its
    complete structural/raw validation is mandatory in the offline audit.
    """
    require(aggregate in AGGREGATES, 'Unknown aggregate')
    prefix = 'calibration' if aggregate.startswith('calibration') else 'application-qualification'
    names = [f'{prefix}-{kind}-00-{phase}' for kind in ('delay', 'rate')
             for phase in ('baseline', 'impaired', 'restored')]
    expected = names + (['path-cut-restored'] if finished else [])
    require([m['phase'] for m in measurements] == expected, 'Complete ordered qualification required')
    for m in measurements:
        require(len(m['pings']) == 3, 'Three ordinary paths required')
        for row, (source, destination) in zip(m['pings'], PATHS):
            require(row['source'] == source and row['destination'] == destination,
                    'Ordinary path changed')
            require(type(row['exit_code']) is int and row['exit_code'] == 0
                    and type(row['received']) is int and row['received'] == 20
                    and type(row['transmitted']) is int and row['transmitted'] == 20,
                    'Ordinary delivery must succeed, not merely a numeric deviation')
            require(len(row['rtt_ms']) == 20, 'Complete RTT sample required')
            values = [number(v) for v in row['rtt_ms']]
            require(number(row['median_ms']) == statistics.median(values), 'Median/raw disagreement')
        if '-rate-' in m['phase'] or m['phase'] == 'path-cut-restored':
            transfer = m['iperf']
            require(type(transfer['raw']['exit_code']) is int and transfer['raw']['exit_code'] == 0
                    and 'error' not in transfer['json'] and number(transfer['receive_bytes']) > 0,
                    'Ordinary TCP must succeed')
            number(m['receive_mbps'])
            require(m['receive_mbps'] == transfer['receive_mbps'], 'TCP rate disagreement')
    expected_rows = []
    def check(description, passed, **details):
        expected_rows.append(dict(description=description, passed=bool(passed), **details))
    for index, kind in enumerate(('delay', 'rate')):
        rows = measurements[index*3:index*3+3]
        for direction in (0, 1):
            a, b, c = [r['pings'][direction]['median_ms'] for r in rows]
            check('RTT restoration within frozen tolerance', abs(c-a) <= 2,
                  kind=kind, baseline_ms=a, restored_ms=c)
            if kind == 'delay':
                check('delay RTT increment within frozen bounds', 15 <= b-a <= 25,
                      direction=direction, increment_ms=b-a, bounds_ms=[15, 25])
        control = [r['pings'][2]['median_ms'] for r in rows]
        check('access-segment control unaffected', max(control)-min(control) <= 2,
              values_ms=control)
        if kind == 'rate':
            a, b, c = [r['receive_mbps'] for r in rows]
            check('baseline above requested cap', a >= 20, mbps=a)
            check('rate-only throughput within frozen bounds', 7 <= b <= 11, mbps=b)
            check('throughput restores', c >= 20 and c >= a*.75,
                  baseline_mbps=a, restored_mbps=c)
    require(all(type(c.get('passed')) is bool for c in checks), 'Nonboolean predicate')
    encode = lambda row: json.dumps(row, sort_keys=True, allow_nan=False)
    numerical = [c for c in checks if c['description'] in FIDELITY]
    require(collections.Counter(map(encode, numerical)) == collections.Counter(map(encode, expected_rows)),
            'Original numerical checks missing, duplicated, changed or inconsistent')
    aggregates = [c for c in checks if c['description'] in AGGREGATES]
    require(len(aggregates) == 1 and aggregates[0]['description'] == aggregate,
            'Exactly one declared aggregate required')
    ordinary = [c for c in checks if c['description'] not in AGGREGATES]
    require(aggregates[0]['passed'] is all(c['passed'] for c in ordinary),
            'Original aggregate disagreement')
    failed = [c for c in ordinary if not c['passed']]
    require(all(c['description'] in FIDELITY for c in failed),
            'Failure is not a supported numerical fidelity deviation')
    return dict(rule='application-correctness-split-v1', application_eligible=True,
                original_aggregate=aggregate,
                original_qualification_passed=not failed,
                network_fidelity='OUT_OF_SPEC' if failed else 'IN_SPEC',
                failed_numerical_checks=failed, measurement_phases=len(measurements),
                check_count=len(checks))


def install(experiment_class):
    """Patch only the two declared aggregate stop decisions, retaining False events."""
    original = experiment_class.require
    def split(self, description, passed, **details):
        if description not in AGGREGATES:
            return original(self, description, passed, **details)
        self.check(description, passed, **details)
        receipt = assess(self.measurements, self.checks, description)
        self.ev.event('application_correctness_gate', **receipt)
    experiment_class.require = split
    return original
