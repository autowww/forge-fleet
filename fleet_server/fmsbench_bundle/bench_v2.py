#!/usr/bin/env python3
"""FMSBench 0.2.0: repeatable isolated PostgreSQL / SQLite / DuckDB + CPU benchmark.

NO production connection. Run via Docker Compose (recommended), or locally with explicitly
configured FMSBENCH_PG_DSN pointing to an isolated disposable benchmark database only.
"""
import argparse
import concurrent.futures
import csv
import datetime
import hashlib
import json
import math
import multiprocessing as mp
import os
from pathlib import Path
import platform
import re
import socket
import sqlite3
import statistics
import sys
import threading
import time

SUITE_VERSION = '0.2.0'
DATA_REV = 'fms-market-sec-2026-10-24-r2'
PROFILES = {
    'micro': (4_000, 800, 40),      # development and CI, NOT comparable for capacity decisions
    'smoke': (30_000, 6_000, 100),  # install / SQL correctness smoke
    'standard': (1_000_000, 200_000, 500),
    'large': (5_000_000, 1_000_000, 500),
}
ENGINES = ('postgres', 'duckdb', 'sqlite')
SQL_WEIGHT = {'market_rollup': .12, 'rolling_features': .18, 'pit_join': .20,
              'sec_signals': .15, 'numeric_features': .10, 'point_lookup': .05,
              'concurrent_jobs': .20}
ENGINE_WEIGHT = {'postgres': .45, 'duckdb': .25, 'sqlite': .10, 'compute': .20}
JOB = ('market_rollup', 'pit_join', 'numeric_features')
BARS_FIELDS = 'bar_id,ticker_id,day_id,open_price,close_price,volume,sector_id'
FACT_FIELDS = 'fact_id,ticker_id,day_id,known_day,metric_id,kind,accession_id,sentiment,impact'

# Same SQL structure across all database engines, no ticker- or company-specific logic.
QUERIES = {
    'market_rollup': '''SELECT COUNT(*), ROUND(CAST(SUM(vwap) AS DECIMAL(28, 6)), 3), ROUND(CAST(SUM(vol) AS DECIMAL(28, 6)), 1) FROM (
      SELECT ticker_id, SUM(close_price * volume) / SUM(volume) AS vwap,
             SUM(volume) AS vol FROM bars WHERE day_id % 7 <> 0 GROUP BY ticker_id) q''',
    'rolling_features': '''SELECT COUNT(*), ROUND(CAST(SUM(ABS(close_price - ma20)) AS DECIMAL(28, 6)), 3) FROM (
      SELECT close_price, AVG(close_price) OVER (
        PARTITION BY ticker_id ORDER BY day_id ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) ma20
      FROM bars) q''',
    'pit_join': '''SELECT COUNT(*), ROUND(CAST(SUM(s) AS DECIMAL(28, 6)), 3) FROM (
      SELECT b.ticker_id, SUM(f.sentiment * f.impact * b.close_price) s
      FROM bars b JOIN filings f ON b.ticker_id = f.ticker_id AND b.day_id = f.day_id
      WHERE f.known_day <= b.day_id AND f.kind IN (0, 1, 2)
      GROUP BY b.ticker_id) q''',
    'sec_signals': '''WITH scored AS (
      SELECT ticker_id, metric_id, kind,
        SUM(CASE WHEN known_day <= day_id THEN sentiment * impact ELSE 0 END) signal,
        COUNT(DISTINCT accession_id) filings_count
      FROM filings GROUP BY ticker_id, metric_id, kind), ranked AS (
      SELECT signal, filings_count,
        ROW_NUMBER() OVER (PARTITION BY metric_id ORDER BY ABS(signal) DESC, ticker_id, kind) pos
      FROM scored)
      SELECT COUNT(*), ROUND(CAST(SUM(signal) AS DECIMAL(28, 6)), 3), SUM(filings_count) FROM ranked WHERE pos <= 40''',
    'numeric_features': '''SELECT COUNT(*), ROUND(CAST(SUM(feature) AS DECIMAL(28, 6)), 3) FROM (
      SELECT ticker_id, SUM(
        ((close_price-open_price)*(close_price-open_price))/(ABS(open_price)+1.0)
        + (volume % 997)*0.013 + close_price*close_price/(volume+1.0)) feature
      FROM bars GROUP BY ticker_id) q''',
    'point_lookup': '''SELECT COUNT(*), ROUND(CAST(SUM(close_price) AS DECIMAL(28, 6)), 3) FROM bars
      WHERE ticker_id = 17 AND day_id BETWEEN 50 AND 150''',
}


def checksum():
    payload = json.dumps({'sql': QUERIES, 'job': JOB, 'data': DATA_REV,
                          'weights': SQL_WEIGHT, 'engines': ENGINE_WEIGHT}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def canonical(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return float(value)
    return float(value) if hasattr(value, '__float__') else str(value)


def values_equal(a, b):
    if len(a) != len(b):
        return False
    for ra, rb in zip(a, b):
        if len(ra) != len(rb):
            return False
        for va, vb in zip(ra, rb):
            if va is None or vb is None:
                if va is not None or vb is not None:
                    return False
            elif isinstance(va, (float, int)) and isinstance(vb, (float, int)):
                if not math.isclose(va, vb, rel_tol=1e-7, abs_tol=.15):
                    return False
            elif va != vb:
                return False
    return True


def fixture_schema():
    return '''CREATE TABLE bars (
        bar_id BIGINT PRIMARY KEY, ticker_id INTEGER NOT NULL, day_id INTEGER NOT NULL,
        open_price DOUBLE PRECISION NOT NULL, close_price DOUBLE PRECISION NOT NULL,
        volume BIGINT NOT NULL, sector_id INTEGER NOT NULL);
        CREATE TABLE filings (
        fact_id BIGINT PRIMARY KEY, ticker_id INTEGER NOT NULL, day_id INTEGER NOT NULL,
        known_day INTEGER NOT NULL, metric_id INTEGER NOT NULL, kind INTEGER NOT NULL,
        accession_id BIGINT NOT NULL, sentiment DOUBLE PRECISION NOT NULL,
        impact DOUBLE PRECISION NOT NULL);'''


def fixture_id(profile):
    return hashlib.sha256(json.dumps({'profile': profile, 'dims': PROFILES[profile], 'revision': DATA_REV},
                                      sort_keys=True).encode()).hexdigest()[:16]


def make_fixture(path, profile):
    bar_n, fact_n, tickers = PROFILES[profile]
    path.mkdir(parents=True, exist_ok=True)
    manifest_file = path / 'fixture-manifest.json'
    if manifest_file.exists():
        meta = json.loads(manifest_file.read_text())
        if meta.get('fixture_id') != fixture_id(profile):
            raise RuntimeError('Fixture revision changed. Select a fresh work directory.')
        for name in ('bars.csv', 'filings.csv'):
            fpath = path / name
            if not fpath.is_file() or _sha(fpath) != meta['sha256'][name]:
                raise RuntimeError('Fixture file altered or incomplete. Refusing to reuse.')
        return meta
    if any((path / f).exists() for f in ('bars.csv', 'filings.csv')):
        raise RuntimeError('Unmanifested input CSV exists; refusing to overwrite')
    started = time.perf_counter()
    with (path / 'bars.csv').open('w', newline='') as handle:
        writer = csv.writer(handle)
        writer.writerow(BARS_FIELDS.split(','))
        for i in range(bar_n):
            p = 100.0 + 3.0 * math.sin(i / 53.0) + (i % 211) / 31.0
            op = 100.0 + 3.0 * math.sin(i / 53.0) + (i % 181) / 41.0
            writer.writerow((i, i % tickers, i // tickers, f'{op:.8f}', f'{p:.8f}',
                             1000 + (i * 73) % 100000, i % 11))
    days = (bar_n + tickers - 1) // tickers
    with (path / 'filings.csv').open('w', newline='') as handle:
        writer = csv.writer(handle)
        writer.writerow(FACT_FIELDS.split(','))
        for i in range(fact_n):
            day = ((i * 17) // tickers) % days
            writer.writerow((i, i % tickers, day, day + (i % 7) - 3,
                             i % 23, i % 5, i % 80000,
                             f'{(((i * 19) % 21) - 10) / 10:.8f}',
                             f'{(1 + (i * 31) % 400) / 25:.8f}'))
    meta = {'fixture_id': fixture_id(profile), 'profile': profile,
            'dimensions': {'bars': bar_n, 'filings': fact_n, 'tickers': tickers},
            'revision': DATA_REV, 'sha256': {n: _sha(path / n) for n in ('bars.csv', 'filings.csv')},
            'generation_seconds': round(time.perf_counter() - started, 3)}
    manifest_file.write_text(json.dumps(meta, indent=2) + '\n')
    return meta


def _sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def pg_dsn():
    dsn = os.getenv('FMSBENCH_PG_DSN', '')
    if not dsn:
        raise RuntimeError('FMSBENCH_PG_DSN required (run with ./run.sh for isolated Docker)')
    # Defend against accidentally pointing benchmark at a production database.
    from urllib.parse import urlsplit
    url = urlsplit(dsn)
    host = url.hostname
    if host not in ('postgres', '127.0.0.1', 'localhost'):
        raise RuntimeError('Refusing PostgreSQL host outside dedicated local benchmark stack')
    if (url.path or '').lstrip('/') != 'fmsbench' or (url.username or '') != 'fmsbench':
        raise RuntimeError('Refusing PostgreSQL database/user other than fmsbench')
    return dsn


class Engine:
    def __init__(self, name, folder, schema, pg_parallel=0, duck_threads=1):
        self.name, self.folder, self.schema = name, folder, schema
        self.pg_parallel, self.duck_threads = pg_parallel, duck_threads
        self.conn = None

    def __enter__(self):
        if self.name == 'sqlite':
            # Create a separate connection per parallel reader; no SQLite SQL intra-query parallelism.
            uri = f'file:{(self.folder / "market.sqlite").resolve()}?mode=ro'
            self.conn = sqlite3.connect(uri, uri=True, timeout=15)
            self.conn.execute('PRAGMA query_only=ON')
            self.conn.execute('PRAGMA temp_store=MEMORY')
        elif self.name == 'duckdb':
            import duckdb
            self.conn = duckdb.connect(str(self.folder / 'market.duckdb'), read_only=True)
            self.conn.execute(f'SET threads = {int(self.duck_threads)}')
        elif self.name == 'postgres':
            import psycopg
            self.conn = psycopg.connect(pg_dsn(), autocommit=True)
            with self.conn.cursor() as cur:
                cur.execute(f'SET search_path TO {self.schema}')
                cur.execute('SET default_transaction_read_only = on')
                cur.execute("SELECT set_config('max_parallel_workers_per_gather', %s, false)",
                            (str(int(self.pg_parallel)),))
                cur.execute("SET work_mem = '32MB'")
        return self

    def __exit__(self, *_):
        if self.conn:
            self.conn.close()

    def query(self, sql):
        if self.name == 'postgres':
            with self.conn.cursor() as cur:
                cur.execute(sql)
                return [tuple(canonical(v) for v in row) for row in cur.fetchall()]
        return [tuple(canonical(v) for v in row) for row in self.conn.execute(sql).fetchall()]


def prepare_sqlite(folder, rows):
    path = folder / 'market.sqlite'
    if path.exists():
        with sqlite3.connect(path) as con:
            counts = [con.execute(f'SELECT COUNT(*) FROM {tbl}').fetchone()[0]
                      for tbl in ('bars', 'filings')]
        if counts != list(rows):
            raise RuntimeError('Existing SQLite database with wrong row count; select a fresh fixture')
        return
    con = sqlite3.connect(path)
    try:
        con.executescript(fixture_schema())
        for table in ('bars', 'filings'):
            with (folder / f'{table}.csv').open(newline='') as stream:
                rdr = csv.reader(stream)
                names = next(rdr)
                holder = ','.join('?' * len(names))
                sql = f'INSERT INTO {table} VALUES ({holder})'
                while batch := list(__import__('itertools').islice(rdr, 5000)):
                    con.executemany(sql, batch)
                con.commit()
        con.execute('CREATE INDEX idx_bars_ticker_day ON bars(ticker_id, day_id)')
        con.execute('CREATE INDEX idx_filings_ticker_day ON filings(ticker_id, day_id)')
        con.execute('ANALYZE')
        con.commit()
    finally:
        con.close()


def prepare_duckdb(folder, rows):
    import duckdb
    path = folder / 'market.duckdb'
    if path.exists():
        con = duckdb.connect(str(path), read_only=True)
        try:
            counts = [con.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
                      for table in ('bars', 'filings')]
        finally:
            con.close()
        if counts != list(rows):
            raise RuntimeError('Existing DuckDB database with wrong row count; select a fresh fixture')
        return
    con = duckdb.connect(str(path))
    try:
        con.execute('SET threads = 4')
        for statement in fixture_schema().split(';'):
            if statement.strip():
                con.execute(statement)
        for name in ('bars', 'filings'):
            p = str((folder / (name + '.csv')).resolve()).replace("'", "''")
            con.execute(f"COPY {name} FROM '{p}' (HEADER TRUE, DELIMITER ',')")
        con.execute('CREATE INDEX idx_bars_ticker_day ON bars(ticker_id, day_id)')
        con.execute('CREATE INDEX idx_filings_ticker_day ON filings(ticker_id, day_id)')
        con.execute('ANALYZE')
        con.execute('CHECKPOINT')
    finally:
        con.close()


def prepare_postgres(folder, schema, rows):
    import psycopg
    from psycopg import sql
    with psycopg.connect(pg_dsn(), autocommit=True) as con:
        with con.cursor() as cur:
            cur.execute(sql.SQL('CREATE SCHEMA IF NOT EXISTS {}').format(sql.Identifier(schema)))
            cur.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(schema)))
            cur.execute("SELECT to_regclass('bars') IS NOT NULL")
            exists = cur.fetchone()[0]
            if exists:
                counts = []
                for table in ('bars', 'filings'):
                    cur.execute(f'SELECT COUNT(*) FROM {table}')
                    counts.append(cur.fetchone()[0])
                if counts != list(rows):
                    raise RuntimeError('Existing PostgreSQL fixture with incorrect size')
                return
            for statement in fixture_schema().split(';'):
                if statement.strip():
                    cur.execute(statement)
            for table in ('bars', 'filings'):
                # Psycopg COPY sends streaming data in batches: no giant in-memory list.
                with cur.copy(f'COPY {table} FROM STDIN WITH (FORMAT CSV, HEADER TRUE)') as copy:
                    with (folder / f'{table}.csv').open('rb') as reader:
                        for data in iter(lambda: reader.read(1024 * 1024), b''):
                            copy.write(data)
            cur.execute('CREATE INDEX idx_bars_ticker_day ON bars(ticker_id, day_id)')
            cur.execute('CREATE INDEX idx_filings_ticker_day ON filings(ticker_id, day_id)')
            cur.execute('ANALYZE bars')
            cur.execute('ANALYZE filings')



def measure_pg_ingest(schema, repeats, rows=5000):
    '''Isolated PostgreSQL WAL-on, primary-key INSERT + UPDATE benchmark.'''
    import psycopg
    with psycopg.connect(pg_dsn(), autocommit=True) as con:
        cur = con.cursor()
        cur.execute(f'SET search_path TO {schema}')
        cur.execute('CREATE TABLE IF NOT EXISTS ingest_stage AS '
                    f'SELECT bar_id,close_price,volume FROM bars ORDER BY bar_id LIMIT {rows}')
        cur.execute('CREATE TABLE IF NOT EXISTS ingest_target ('
                    'bar_id BIGINT PRIMARY KEY, close_price DOUBLE PRECISION, volume BIGINT)')
        cur.execute('SELECT COUNT(*) FROM ingest_stage')
        if cur.fetchone()[0] != rows:
            raise RuntimeError(f'Wrong ingest_stage size: expected {rows} rows')
        statement = '''INSERT INTO ingest_target(bar_id,close_price,volume)
            SELECT bar_id,close_price,volume FROM ingest_stage WHERE TRUE
            ON CONFLICT (bar_id) DO UPDATE SET
            close_price = EXCLUDED.close_price, volume = EXCLUDED.volume'''
        durations = []
        # Warmup excluded. Each cycle inserts, then updates all rows, and commits.
        for iteration in range(repeats + 1):
            cur.execute('TRUNCATE ingest_target')
            t0 = time.perf_counter()
            with con.transaction():
                cur.execute(statement)
                cur.execute(statement)
            elapsed = time.perf_counter() - t0
            if iteration > 0:
                durations.append(elapsed)
        cur.execute('SELECT COUNT(*) FROM ingest_target')
        if cur.fetchone()[0] != rows:
            raise RuntimeError('PostgreSQL UPSERT failed correctness check')
    return {'rows_per_second': (rows * 2) / statistics.median(durations),
            'median_sec': statistics.median(durations),
            'rows_per_cycle': rows * 2, 'durability': 'fsync=on, synchronous_commit=on'}


def engine_version(engine):
    if engine == 'sqlite':
        return sqlite3.sqlite_version
    if engine == 'duckdb':
        import duckdb
        return duckdb.__version__
    import psycopg
    with psycopg.connect(pg_dsn()) as con:
        return con.execute('SHOW server_version').fetchone()[0]


def measure_queries(name, folder, schema, threads, repeats):
    all_times = {}
    outputs = {}
    # SQLite has no general intra-query threads setting. 'parallel' here repeats 1T latency.
    configs = {'single': 1, 'configured': threads if name != 'sqlite' else 1}
    for mode, t in configs.items():
        with Engine(name, folder, schema, pg_parallel=(0 if mode == 'single' else t),
                    duck_threads=t) as conn:
            for key, sql in QUERIES.items():
                first = conn.query(sql)
                measured = []
                for _ in range(repeats):
                    t0 = time.perf_counter()
                    result = conn.query(sql)
                    measured.append(time.perf_counter() - t0)
                    if not values_equal(first, result):
                        raise RuntimeError(f'Non-deterministic query result: {name}/{key}')
                if key in outputs and not values_equal(outputs[key], first):
                    raise RuntimeError(f'Mode result mismatch: {name}/{key}')
                outputs[key] = first
                all_times.setdefault(key, {})[mode + '_median_sec'] = statistics.median(measured)
    for key in all_times:
        all_times[key]['result'] = outputs[key]
        all_times[key]['speedup'] = (all_times[key]['single_median_sec'] /
                                     all_times[key]['configured_median_sec'])
    return all_times


def concurrency_round(name, folder, schema, workers, duration, expected):
    timing = {}
    def synchronize():
        timing['start'] = time.perf_counter()
        timing['deadline'] = timing['start'] + duration
    barrier = threading.Barrier(workers, action=synchronize)
    def work(_):
        n = 0
        with Engine(name, folder, schema, pg_parallel=0, duck_threads=1) as db:
            # Warmup excluded from timed section.
            db.query(QUERIES['point_lookup'])
            barrier.wait(timeout=60)
            while True:
                for key in JOB:
                    result = db.query(QUERIES[key])
                    if n == 0 and not values_equal(result, expected[key]):
                        raise RuntimeError(f'Concurrent result mismatch: {name}/{key}')
                n += 1
                if time.perf_counter() >= timing['deadline']:
                    return n
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        out = list(pool.map(work, range(workers)))
    elapsed = time.perf_counter() - timing['start']
    return {'completed_jobs': sum(out), 'elapsed_seconds': elapsed,
            'jobs_per_second': sum(out) / elapsed}


def measure_concurrent(name, folder, schema, max_workers, duration, repeats, expected):
    levels = {1, max_workers}
    n = 2
    while n < max_workers:
        levels.add(n)
        n *= 2
    result = {}
    for count in sorted(levels):
        samples = [concurrency_round(name, folder, schema, count, duration, expected)
                   for _ in range(repeats)]
        result[str(count)] = {
            'median_jobs_per_second': statistics.median(s['jobs_per_second'] for s in samples),
            'trials': samples,
        }
    best = max(result, key=lambda k: result[k]['median_jobs_per_second'])
    return {'scales': result, 'best_workers': int(best),
            'best_jobs_per_second': result[best]['median_jobs_per_second']}


def _compute_batch(loops, size):
    import numpy as np
    i = np.arange(size, dtype=np.float64)
    base = ((i * 17.) % 1009) / 1009.
    total = 0.
    for _ in range(loops):
        # Vectorized, CPU + memory bandwidth, no BLAS dependency.
        signal = np.tanh(base * 1.2 - .8) * np.log1p(base * 30.)
        total += float(np.sum(signal * (base + 1.) / np.sqrt(base + .25)))
    return total


def measure_compute(max_workers, repeats, size=200_000, loops=4):
    import numpy
    from concurrent.futures import ProcessPoolExecutor
    stages = {1, max_workers}
    s = 2
    while s < max_workers:
        stages.add(s)
        s *= 2
    results = {}
    # Fresh pool per level, process startup and imports EXCLUDED from timing.
    for workers in sorted(stages):
        with ProcessPoolExecutor(max_workers=workers, mp_context=mp.get_context('spawn')) as pool:
            warmed = list(pool.map(_compute_batch, [1] * workers, [128] * workers))
            if any(not math.isfinite(x) for x in warmed):
                raise RuntimeError('Compute warmup invalid')
            times = []
            results_signature = None
            for _ in range(repeats):
                tasks = workers * 3
                t0 = time.perf_counter()
                calculated = list(pool.map(_compute_batch, [loops] * tasks, [size] * tasks))
                elapsed = time.perf_counter() - t0
                if not all(math.isclose(calculated[0], x, rel_tol=1e-12) for x in calculated):
                    raise RuntimeError('Compute kernel mismatch')
                results_signature = round(calculated[0], 6)
                times.append(tasks * loops * size / elapsed)
            results[str(workers)] = {'median_rows_per_second': statistics.median(times),
                                     'checksum': results_signature}
    best = max(results, key=lambda k: results[k]['median_rows_per_second'])
    return {'scales': results, 'best_workers': int(best),
            'best_rows_per_second': results[best]['median_rows_per_second'],
            'numpy_version': numpy.__version__, 'size': size, 'loops': loops}


def hardware():
    def read(p):
        try:
            return Path(p).read_text().strip()
        except OSError:
            return None
    meminfo = read('/proc/meminfo') or ''
    memmatch = re.search(r'^MemTotal:\s+(\d+)', meminfo, re.M)
    cpuinfo = read('/proc/cpuinfo') or ''
    cpumatch = re.search(r'^model name\s*:\s*(.+)', cpuinfo, re.M)
    return {'hostname_visible_in_container': socket.gethostname(),
            'cpu_model': cpumatch.group(1) if cpumatch else platform.processor(),
            'host_logical_cpus': os.cpu_count(),
            'affinity_cpus': len(os.sched_getaffinity(0)) if hasattr(os, 'sched_getaffinity') else None,
            'mem_total_gib': round(int(memmatch.group(1)) / 1024**2, 2) if memmatch else None,
            'cgroup_cpu_max': read('/sys/fs/cgroup/cpu.max'),
            'cgroup_memory_max': read('/sys/fs/cgroup/memory.max'),
            'platform': platform.platform(), 'python': platform.python_version()}


def run(args):
    started_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    folder = args.work / (args.profile + '-' + fixture_id(args.profile))
    folder.mkdir(parents=True, exist_ok=True)
    dataset = make_fixture(folder, args.profile)
    schema = 'fms_' + fixture_id(args.profile)
    rows = (dataset['dimensions']['bars'], dataset['dimensions']['filings'])
    print(f"Prepared fixture {args.profile}: {rows[0]:,} OHLCV bars; {rows[1]:,} SEC facts", flush=True)
    timings = {}
    for eng in ENGINES:
        t0 = time.perf_counter()
        print(f'[prepare] {eng}', flush=True)
        if eng == 'postgres':
            prepare_postgres(folder, schema, rows)
        elif eng == 'duckdb':
            prepare_duckdb(folder, rows)
        else:
            prepare_sqlite(folder, rows)
        timings[eng] = round(time.perf_counter() - t0, 3)
    engines = {}
    canonical_results = None
    for eng in ENGINES:
        print(f'[benchmark] {eng} SQL + concurrency', flush=True)
        queries = measure_queries(eng, folder, schema, args.threads, args.repeats)
        # Cross-engine numeric correctness checking: very important for fair scores.
        outputs = {k: v['result'] for k, v in queries.items()}
        if canonical_results is None:
            canonical_results = outputs
        else:
            for key in QUERIES:
                if not values_equal(canonical_results[key], outputs[key]):
                    raise RuntimeError(f'Cross-engine SQL correctness mismatch for {eng}/{key}: '
                                       f'{canonical_results[key]} vs {outputs[key]}')
        concurrency = measure_concurrent(eng, folder, schema, args.workers,
                                         args.duration, args.trials, outputs)
        engines[eng] = {'version': engine_version(eng), 'queries': queries,
                        'concurrency': concurrency, 'prep_seconds': timings[eng]}
        if eng == 'postgres':
            print('[benchmark] PostgreSQL WAL-on INSERT + UPSERT', flush=True)
            engines[eng]['ingest'] = measure_pg_ingest(schema, args.repeats, rows=min(5000, rows[0]))
        print(f"  {eng}: {concurrency['best_jobs_per_second']:.3f} completed bundles/s ", flush=True)
    print('[benchmark] NumPy numerical compute', flush=True)
    compute = measure_compute(args.workers, args.trials, size=args.compute_size, loops=args.compute_loops)
    result = {'suite': 'FMSBench', 'suite_version': SUITE_VERSION, 'data_revision': DATA_REV,
              'workload_checksum': checksum(), 'node': args.node or socket.gethostname(),
              'start_utc': started_at, 'end_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'hardware': hardware(), 'fixture': dataset,
              'config': {'profile': args.profile, 'threads': args.threads, 'workers': args.workers,
                         'repeats': args.repeats, 'trials': args.trials, 'duration': args.duration,
                         'compute_size': args.compute_size, 'compute_loops': args.compute_loops},
              'engines': engines, 'compute': compute,
              'sql_weights': SQL_WEIGHT, 'engine_weights': ENGINE_WEIGHT,
              'status': 'passed'}
    args.results.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    node = re.sub(r'[^A-Za-z0-9_-]', '-', result['node'])[:48]
    final_path = args.results / f'fmsbench-{node}-{stamp}.json'
    if final_path.exists():
        raise RuntimeError(f'Refusing to overwrite result: {final_path}')
    temp_path = final_path.with_suffix('.json.tmp')
    temp_path.write_text(json.dumps(result, indent=2, allow_nan=False) + '\n')
    temp_path.replace(final_path)
    print(f'PASSED, JSON: {final_path}', flush=True)
    baseline = args.baseline
    if baseline is None and (Path('/baselines/granite.json')).is_file():
        baseline = Path('/baselines/granite.json')
    if baseline:
        from rank_v2 import render
        try:
            render(baseline, [final_path])
        except (ValueError, KeyError) as exc:
            print(f'Baseline incompatible: {exc} (results still saved)', file=sys.stderr)
    else:
        print('NO GRANITE BASELINE: copy Granite run JSON to baselines/granite.json '
              'and rerun rank_v2.py. No speedup claimed.', flush=True)
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=('run',))
    p.add_argument('--node', default=None)
    p.add_argument('--profile', choices=PROFILES, default='smoke')
    p.add_argument('--threads', type=int, default=8)
    p.add_argument('--workers', type=int, default=4)
    p.add_argument('--repeats', type=int, default=2)
    p.add_argument('--trials', type=int, default=2)
    p.add_argument('--duration', type=float, default=2.0)
    p.add_argument('--compute-size', type=int, default=200_000)
    p.add_argument('--compute-loops', type=int, default=4)
    p.add_argument('--work', type=Path, default=Path('/benchwork'))
    p.add_argument('--results', type=Path, default=Path('/results'))
    p.add_argument('--baseline', type=Path)
    args = p.parse_args()
    if not (1 <= args.workers <= 32 and 1 <= args.threads <= 16 and
            1 <= args.repeats <= 20 and 1 <= args.trials <= 10 and
            .25 <= args.duration <= 120 and 100 <= args.compute_size <= 10_000_000 and
            1 <= args.compute_loops <= 100):
        p.error('Unsafe test parameters (workers<=32, threads<=16, duration .25–120s)')
    run(args)


if __name__ == '__main__':
    main()
