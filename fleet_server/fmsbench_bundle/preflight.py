#!/usr/bin/env python3
"""Host preflight for a local FMSBench run.

Checks Docker, free disk, memory, and power. Takes no install action and does
not start services. Parallel runs are rejected by the flock in ./run.sh.
"""
import argparse
import hashlib
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
from pathlib import Path

from bench_v2 import PROFILES

PREFLIGHT_REVISION = '0.2.0-preflight-1'
DISK_MIN_GIB = {'micro': 1.0, 'smoke': 2.0, 'standard': 8.0, 'large': 20.0}
RAM_MIN_GIB = {'micro': 1.0, 'smoke': 1.5, 'standard': 4.0, 'large': 8.0}
HEAVY_PROFILES = ('standard', 'large')
COMPOSE_GUIDANCE = (
    'Docker Compose v2 plugin is not available (docker compose version failed). '
    'Install guidance: on Ubuntu, the package is docker-compose-v2; '
    "Docker's package is docker-compose-plugin. "
    'See https://docs.docker.com/compose/install/linux/ . '
    'This benchmark will not install packages or change system services.'
)
ENGINE_GUIDANCE = (
    'Docker Engine is not on PATH. Install Docker Engine and the Compose v2 plugin '
    '(Ubuntu package docker-compose-v2, or docker-compose-plugin). '
    'See https://docs.docker.com/engine/install/ . '
    'This benchmark will not install packages or change system services.'
)
DAEMON_GUIDANCE = (
    'Docker Engine is installed but the daemon did not return a server version. '
    'Start the local Docker service, then re-run ./run.sh. '
    'This benchmark will not start or change system services.'
)


def project_name(root):
    digest = hashlib.sha256(str(Path(root).resolve()).encode()).hexdigest()[:8]
    return 'fmsbench-' + digest


def _capture(argv, runner, timeout=10):
    try:
        completed = runner(argv, capture_output=True, text=True, timeout=timeout, check=False)
    except FileNotFoundError:
        return {'ok': False, 'code': 127, 'stdout': '', 'stderr': 'not found'}
    except subprocess.TimeoutExpired:
        return {'ok': False, 'code': 124, 'stdout': '', 'stderr': 'timeout'}
    stdout = completed.stdout or ''
    stderr = completed.stderr or ''
    return {'ok': completed.returncode == 0, 'code': completed.returncode,
            'stdout': stdout.strip(), 'stderr': stderr.strip()}


def _clip(text, limit=240):
    text = (text or '').replace('\n', ' ').strip()
    return text[:limit]


def probe_docker(runner=None, binary=None):
    runner = runner or subprocess.run
    if binary is None:
        binary = shutil.which('docker') is not None
    report = {'binary': binary, 'engine_version': None, 'daemon': False,
              'daemon_version': None, 'compose': False, 'compose_version': None,
              'compose_error': None}
    if not binary:
        return report
    engine = _capture(['docker', '--version'], runner)
    report['engine_version'] = _clip(engine['stdout'] or engine['stderr']) or None
    info = _capture(['docker', 'info', '--format', '{{.ServerVersion}}'], runner)
    if info['ok'] and info['stdout']:
        report['daemon'] = True
        report['daemon_version'] = _clip(info['stdout'], 80)
    if report['daemon']:
        compose = _capture(['docker', 'compose', 'version'], runner)
        report['compose'] = compose['ok']
        if compose['ok']:
            report['compose_version'] = _clip(compose['stdout'] or compose['stderr'])
        else:
            report['compose_error'] = _clip(compose['stderr'] or compose['stdout'])
    return report


def probe_containers(project, runner=None):
    runner = runner or subprocess.run
    listed = _capture(['docker', 'ps', '-a', '--filter', 'name=' + project,
                       '--format', '{{.Names}}\t{{.Status}}'], runner)
    if not listed['ok']:
        return {'state': 'unavailable', 'containers': []}
    rows = []
    for line in listed['stdout'].splitlines():
        if not line.strip():
            continue
        name, _, status = line.partition('\t')
        rows.append({'name': name[:80], 'status': status[:80]})
        if len(rows) >= 20:
            break
    return {'state': 'ok', 'containers': rows}


def parse_meminfo(text):
    values = {}
    for line in (text or '').splitlines():
        if ':' not in line:
            continue
        key, raw = line.split(':', 1)
        parts = raw.split()
        if parts and parts[0].isdigit():
            values[key] = int(parts[0])
    available = values.get('MemAvailable', values.get('MemFree'))
    source = None
    if 'MemAvailable' in values:
        source = 'MemAvailable'
    elif 'MemFree' in values:
        source = 'MemFree'
    return {
        'mem_total_gib': round(values['MemTotal'] / 1024**2, 2) if 'MemTotal' in values else None,
        'mem_available_gib': round(available / 1024**2, 2) if available is not None else None,
        'mem_available_kib': available,
        'mem_source': source,
        'swap_total_gib': round(values['SwapTotal'] / 1024**2, 2) if 'SwapTotal' in values else None,
        'swap_free_gib': round(values['SwapFree'] / 1024**2, 2) if 'SwapFree' in values else None,
    }


def parse_mount_fstype(mountinfo, target):
    target = str(Path(target).resolve())
    best = None
    best_len = -1
    for line in (mountinfo or '').splitlines():
        parts = line.split()
        if '-' not in parts or len(parts) < 2:
            continue
        sep = parts.index('-')
        mount_point = parts[4] if len(parts) > 4 else ''
        fstype = parts[sep + 1] if sep + 1 < len(parts) else None
        if not mount_point or fstype is None:
            continue
        if target == mount_point or target.startswith(mount_point.rstrip('/') + '/'):
            if len(mount_point) > best_len:
                best = fstype
                best_len = len(mount_point)
    return best


def probe_power(root):
    root = Path(root)
    if not root.is_dir():
        return {'state': 'unavailable', 'supplies': []}
    supplies = []
    for entry in sorted(p for p in root.iterdir() if p.is_dir()):
        supplies.append({'name': entry.name, 'type': _read(entry / 'type'),
                         'online': _read(entry / 'online'), 'status': _read(entry / 'status')})
    mains = [s for s in supplies if (s['type'] or '').lower() in ('mains', 'ups')]
    batteries = [s for s in supplies if (s['type'] or '').lower() == 'battery']
    if any(s['online'] == '1' for s in mains):
        state = 'ac'
    elif any((s['status'] or '').lower() == 'discharging' for s in batteries):
        state = 'battery'
    elif batteries and mains and all(s['online'] == '0' for s in mains):
        state = 'battery'
    else:
        state = 'unavailable'
    return {'state': state, 'supplies': supplies}


def probe_thermal(root):
    root = Path(root)
    if not root.is_dir():
        return None
    readings = []
    for zone in sorted(p for p in root.iterdir() if p.name.startswith('thermal_zone')):
        raw = _read(zone / 'temp')
        if raw and raw.lstrip('-').isdigit():
            readings.append(int(raw) / 1000.0)
    if not readings:
        return None
    return round(max(readings), 1)


def _read(path):
    try:
        return Path(path).read_text().strip()
    except OSError:
        return None


def probe_resources(work, meminfo_text=None, mountinfo_text=None, power_root=None, thermal_root=None):
    work = Path(work)
    if meminfo_text is None:
        meminfo_text = _read('/proc/meminfo') or ''
    memory = parse_meminfo(meminfo_text)
    if mountinfo_text is None:
        mountinfo_text = _read('/proc/self/mountinfo') or ''
    try:
        usage = shutil.disk_usage(work if work.exists() else work.parent)
        free_bytes = usage.free
        total_bytes = usage.total
    except OSError:
        free_bytes = None
        total_bytes = None
    cpuinfo = _read('/proc/cpuinfo') or ''
    model = None
    for line in cpuinfo.splitlines():
        if line.startswith('model name'):
            model = line.split(':', 1)[1].strip()
            break
    numa_root = Path('/sys/devices/system/node')
    if numa_root.is_dir():
        numa = len([p for p in numa_root.iterdir() if p.name.startswith('node') and p.name[4:].isdigit()])
    else:
        numa = None
    power = probe_power(power_root or '/sys/class/power_supply')
    thermal = probe_thermal(thermal_root or '/sys/class/thermal')
    return {
        'free_bytes': free_bytes,
        'free_gib': round(free_bytes / 1024**3, 2) if free_bytes is not None else None,
        'disk_total_gib': round(total_bytes / 1024**3, 2) if total_bytes is not None else None,
        'fstype': parse_mount_fstype(mountinfo_text, work if work.exists() else work.parent) or 'unavailable',
        'mem_total_gib': memory['mem_total_gib'],
        'mem_available_gib': memory['mem_available_gib'],
        'mem_available_kib': memory['mem_available_kib'],
        'mem_source': memory['mem_source'],
        'swap_total_gib': memory['swap_total_gib'] if memory['swap_total_gib'] is not None else 'unavailable',
        'swap_free_gib': memory['swap_free_gib'] if memory['swap_free_gib'] is not None else 'unavailable',
        'logical_cpus': os.cpu_count(),
        'affinity_cpus': len(os.sched_getaffinity(0)) if hasattr(os, 'sched_getaffinity') else None,
        'cpu_model': model or 'unavailable',
        'arch': platform.machine() or 'unavailable',
        'numa_nodes': numa if numa else 'unavailable',
        'cgroup_cpu_max': _read('/sys/fs/cgroup/cpu.max') or 'unavailable',
        'cgroup_memory_max': _read('/sys/fs/cgroup/memory.max') or 'unavailable',
        'power_state': power['state'],
        'power': power,
        'thermal_c': thermal if thermal is not None else 'unavailable',
    }


def blocking_errors(report):
    errors = []
    profile = report['profile']
    docker = report.get('docker') or {}
    resources = report.get('resources') or {}
    if not docker.get('binary'):
        errors.append(ENGINE_GUIDANCE)
    elif not docker.get('daemon'):
        errors.append(DAEMON_GUIDANCE)
    elif not docker.get('compose'):
        errors.append(COMPOSE_GUIDANCE)
    minimum_disk = DISK_MIN_GIB[profile]
    free_bytes = resources.get('free_bytes')
    if free_bytes is None:
        errors.append('Could not read free disk space for the work directory.')
    elif free_bytes < int(minimum_disk * 1024**3):
        errors.append(
            'Not enough free disk for profile %s: %.2f GiB free, %.1f GiB required under the work directory.'
            % (profile, resources.get('free_gib') or 0, minimum_disk))
    available_kib = resources.get('mem_available_kib')
    minimum_ram = RAM_MIN_GIB[profile]
    if available_kib is None:
        errors.append('Could not read available memory from /proc/meminfo.')
    elif available_kib < int(minimum_ram * 1024**2):
        errors.append(
            'Not enough available memory for profile %s: %.2f GiB available, %.1f GiB required.'
            % (profile, resources.get('mem_available_gib') or 0, minimum_ram))
    if profile in HEAVY_PROFILES and resources.get('power_state') == 'battery':
        errors.append(
            'Refusing profile %s while the host is on battery. Connect AC power, or use --profile smoke for a correctness check.'
            % profile)
    return errors


def warnings_for(report):
    warnings = []
    resources = report.get('resources') or {}
    profile = report['profile']
    if profile not in HEAVY_PROFILES and resources.get('power_state') == 'battery':
        warnings.append('Host appears to be on battery. smoke and micro results are not capacity evidence.')
    if resources.get('fstype') == 'tmpfs':
        warnings.append('Work directory is on tmpfs. PostgreSQL durability numbers will not represent a physical disk.')
    thermal = resources.get('thermal_c')
    if isinstance(thermal, (int, float)) and thermal >= 90:
        warnings.append('A thermal zone reports %.1fC. Throughput may be throttled.' % thermal)
    containers = (report.get('containers') or {}).get('containers') or []
    if containers:
        names = ', '.join(row['name'] for row in containers[:5])
        warnings.append('This project already has containers (%s). ./run.sh reuses the benchmark stack.' % names)
    if resources.get('arch') not in (None, 'x86_64', 'aarch64', 'arm64'):
        warnings.append('CPU architecture %s is outside the x86_64/arm64 images exercised by this package.' % resources.get('arch'))
    return warnings


def _work_error(work):
    cwd = Path('.').resolve()
    resolved = Path(work).resolve()
    if resolved == Path('/'):
        return 'Refusing work directory /.'
    if resolved != cwd and cwd not in resolved.parents:
        return 'Work directory must stay inside the benchmark checkout (%s).' % cwd
    return None


def build_report(work, profile, runner=None):
    root = Path('.').resolve()
    project = project_name(root)
    docker = probe_docker(runner)
    containers = {'state': 'unavailable', 'containers': []}
    if docker.get('daemon'):
        containers = probe_containers(project, runner)
    resources = probe_resources(work)
    report = {'preflight_revision': PREFLIGHT_REVISION, 'profile': profile,
              'project': project, 'checkout': str(root), 'hostname': socket.gethostname(),
              'docker': docker, 'containers': containers, 'resources': resources}
    report['blocking'] = blocking_errors(report)
    report['warnings'] = warnings_for(report)
    return report


def write_report(path, report):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    temp.replace(path)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work', type=Path, default=Path('work'))
    parser.add_argument('--profile', default='smoke')
    parser.add_argument('--report', type=Path)
    args = parser.parse_args(argv)
    if args.profile not in PROFILES:
        report = {'preflight_revision': PREFLIGHT_REVISION, 'profile': args.profile,
                  'blocking': ['Unknown profile %r. Expected one of: %s.'
                               % (args.profile, ', '.join(PROFILES))],
                  'warnings': [], 'docker': None, 'resources': None}
        if args.report:
            write_report(args.report, report)
        print('ERROR: ' + report['blocking'][0], file=sys.stderr)
        return 2
    path_error = _work_error(args.work)
    if path_error:
        print('ERROR: ' + path_error, file=sys.stderr)
        return 2
    work = Path(args.work)
    if not work.exists():
        work.mkdir(parents=True)
    report = build_report(work, args.profile)
    if args.report:
        write_report(args.report, report)
    for line in report['warnings']:
        print('WARNING: ' + line)
    if report['blocking']:
        for line in report['blocking']:
            print('ERROR: ' + line, file=sys.stderr)
        return 2
    print('PREFLIGHT OK profile=%s project=%s free_gib=%s mem_available_gib=%s'
          % (args.profile, report['project'], report['resources']['free_gib'],
             report['resources']['mem_available_gib']))
    return 0


if __name__ == '__main__':
    sys.exit(main())
