#!/usr/bin/env python3
"""Compute version-strict Granite=100 FMSBench leaderboard; never invent baseline metrics."""
import argparse
import csv
import json
import math
from pathlib import Path
from bench_v2 import ENGINE_WEIGHT, SQL_WEIGHT, QUERIES, values_equal


def read(path):
    with open(path) as f:
        value = json.load(f)
    if value.get('suite') != 'FMSBench' or value.get('status') != 'passed':
        raise ValueError(f'{path}: incomplete/invalid run')
    return value


def comparable(a, b):
    # Different code, profiles, runtime versions, concurrency levels: invalid comparison.
    keys = ('suite_version', 'data_revision', 'workload_checksum', 'config')
    for key in keys:
        if a[key] != b[key]:
            raise ValueError(f'Mismatch in {key} (run both nodes with same command/image)')
    if a['fixture']['sha256'] != b['fixture']['sha256'] or a['fixture']['dimensions'] != b['fixture']['dimensions']:
        raise ValueError('Fixture hash/size mismatch')
    for eng in ('postgres', 'duckdb', 'sqlite'):
        if a['engines'][eng]['version'] != b['engines'][eng]['version']:
            raise ValueError(f'{eng} engine version mismatch')
        for key in QUERIES:
            if not values_equal(a['engines'][eng]['queries'][key]['result'],
                                b['engines'][eng]['queries'][key]['result']):
                raise ValueError(f'{eng}: wrong analytical query output for {key}')
    if a['compute']['numpy_version'] != b['compute']['numpy_version']:
        raise ValueError('NumPy version mismatch')
    ca = a['compute']['scales']['1']['checksum']
    cb = b['compute']['scales']['1']['checksum']
    if not math.isclose(ca, cb, rel_tol=1e-6, abs_tol=.01):
        raise ValueError('Compute output checksum mismatch')
    # sanity-check score weights in both records, even with same checksum.
    for r in (a, b):
        if r['engine_weights'] != ENGINE_WEIGHT or r['sql_weights'] != SQL_WEIGHT:
            raise ValueError('Scoring weights mismatch')


def _ratio(a, b, label):
    a = float(a)
    b = float(b)
    if not (math.isfinite(a) and math.isfinite(b) and a > 0 and b > 0):
        raise ValueError(f'Invalid metric for {label}')
    return a / b


def _weighted_geometric(speeds, weights):
    return math.exp(sum(weights[k] * math.log(speeds[k]) for k in weights))


def score(candidate, granite):
    comparable(candidate, granite)
    engine_scores = {}
    detail = {}
    for eng in ('postgres', 'duckdb', 'sqlite'):
        rates = {}
        for q in QUERIES:
            # Faster single SQL duration => higher throughput.
            c = candidate['engines'][eng]['queries'][q]['configured_median_sec']
            g = granite['engines'][eng]['queries'][q]['configured_median_sec']
            rates[q] = _ratio(g, c, eng + '/' + q)
        rates['concurrent_jobs'] = _ratio(
            candidate['engines'][eng]['concurrency']['best_jobs_per_second'],
            granite['engines'][eng]['concurrency']['best_jobs_per_second'], eng + '/concurrent')
        sql_score = _weighted_geometric(rates, SQL_WEIGHT)
        if eng == 'postgres':
            ingest = _ratio(candidate['engines'][eng]['ingest']['rows_per_second'],
                            granite['engines'][eng]['ingest']['rows_per_second'], 'postgres/ingest')
            rates['pg_ingest'] = ingest
            engine_scores[eng] = math.exp(.90 * math.log(sql_score) + .10 * math.log(ingest))
        else:
            engine_scores[eng] = sql_score
        detail[eng] = {k: round(v, 4) for k, v in rates.items()}
    engine_scores['compute'] = _ratio(candidate['compute']['best_rows_per_second'],
                                      granite['compute']['best_rows_per_second'], 'compute')
    overall = 100 * _weighted_geometric(engine_scores, ENGINE_WEIGHT)
    return {'node': candidate['node'], 'score': round(overall, 2),
            'speedup_vs_granite': round(overall / 100, 4),
            'subscores': {k: round(100 * v, 2) for k, v in engine_scores.items()},
            'workload_speedups': detail,
            'single_query_performance': {
                eng: {k: round(granite['engines'][eng]['queries'][k]['single_median_sec'] /
                               candidate['engines'][eng]['queries'][k]['single_median_sec'], 3)
                      for k in QUERIES}
                for eng in ('postgres', 'duckdb', 'sqlite')},
            'granite_node': granite['node'],
            'absolute_rates': {
                'postgres_jobs_per_second': candidate['engines']['postgres']['concurrency']['best_jobs_per_second'],
                'postgres_ingest_rows_per_second': candidate['engines']['postgres']['ingest']['rows_per_second'],
                'duckdb_jobs_per_second': candidate['engines']['duckdb']['concurrency']['best_jobs_per_second'],
                'sqlite_jobs_per_second': candidate['engines']['sqlite']['concurrency']['best_jobs_per_second'],
                'compute_rows_per_second': candidate['compute']['best_rows_per_second']}}


def render(baseline, results, csv_output=None, json_output=None):
    granite = read(baseline)
    measured = [score(read(p), granite) for p in results]
    measured.sort(key=lambda x: x['score'], reverse=True)
    print(f'Granite baseline: {granite["node"]} = 100.00 | profile={granite["config"]["profile"]}')
    print(f'{"Node":23} {"Total":>8} {"PG":>8} {"DuckDB":>8} {"SQLite":>8} {"Compute":>8} {"Speedup":>9}')
    print('-' * 80)
    for row in measured:
        parts = row['subscores']
        print(f'{row["node"][:23]:23} {row["score"]:8.2f} {parts["postgres"]:8.1f} '
              f'{parts["duckdb"]:8.1f} {parts["sqlite"]:8.1f} {parts["compute"]:8.1f} '
              f'{row["speedup_vs_granite"]:8.2f}x')
    if csv_output:
        with open(csv_output, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['node', 'score', 'vs_granite_x', 'postgres_score',
                             'duckdb_score', 'sqlite_score', 'compute_score',
                             'postgres_jobs_per_sec', 'postgres_ingest_rows_per_sec',
                             'duckdb_jobs_per_sec', 'sqlite_jobs_per_sec', 'compute_rows_per_sec'])
            for row in measured:
                writer.writerow([row['node'], row['score'], row['speedup_vs_granite'],
                                *[row['subscores'][k] for k in ENGINE_WEIGHT],
                                 *[row['absolute_rates'][k] for k in (
                                     'postgres_jobs_per_second', 'postgres_ingest_rows_per_second',
                                     'duckdb_jobs_per_second', 'sqlite_jobs_per_second',
                                     'compute_rows_per_second')]])
    if json_output:
        Path(json_output).write_text(json.dumps({'baseline': granite['node'], 'ranking': measured}, indent=2) + '\n')
    return measured


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--baseline', type=Path, required=True)
    p.add_argument('--csv', type=Path)
    p.add_argument('--json', type=Path)
    p.add_argument('results', nargs='+', type=Path)
    a = p.parse_args()
    render(a.baseline, a.results, a.csv, a.json)


if __name__ == '__main__':
    main()
