"""Monitor one Linux command without treating cgroup file cache as process RSS.

Example: python -m nt_reference_experiment.measure --output resources.json \
    --rss-limit-mib 1400 -- python -m nt_reference_experiment.run ...

The child inherits stdout, stderr and the caller's environment. The guard watches
only that child's RSS/HWM; cgroup measurements describe the entire shared cgroup.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import resource
import signal
import subprocess
import sys
import time


MIB = 1024 ** 2
POLL_SECONDS = 1.0
TERM_GRACE_SECONDS = 5.0


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def read_text(path):
    try:
        return Path(path).read_text().strip()
    except (OSError, UnicodeError):
        return None


def key_values(path):
    values = {}
    for line in (read_text(path) or '').splitlines():
        fields = line.split()
        if len(fields) == 2:
            try:
                values[fields[0]] = int(fields[1])
            except ValueError:
                continue
    return values


def read_process_memory(pid):
    """Return kernel measurements in bytes, or null after the process exits."""
    status = read_text(Path('/proc') / str(pid) / 'status')
    values = {'rss_bytes': None, 'hwm_bytes': None}
    for line in (status or '').splitlines():
        fields = line.split()
        if fields and fields[0] in ('VmRSS:', 'VmHWM:') and len(fields) >= 2:
            key = 'rss_bytes' if fields[0] == 'VmRSS:' else 'hwm_bytes'
            try:
                values[key] = int(fields[1]) * 1024
            except ValueError:
                continue
    return values


def _unescape_mount(value):
    return re.sub(r'\\([0-7]{3})', lambda match: chr(int(match[1], 8)), value)


def find_cgroup_v2(pid=None):
    """Resolve the process cgroup inside the current mount namespace."""
    proc = Path('/proc') / (str(pid) if pid is not None else 'self')
    group = None
    for line in (read_text(proc / 'cgroup') or '').splitlines():
        fields = line.split(':', 2)
        if len(fields) == 3 and fields[0] == '0' and fields[1] == '':
            group = fields[2]
            break
    if group is None:
        return None
    candidates = []
    for line in (read_text('/proc/self/mountinfo') or '').splitlines():
        left, separator, right = line.partition(' - ')
        fields = left.split()
        if not separator or right.split()[0] != 'cgroup2' or len(fields) < 5:
            continue
        root, mount = _unescape_mount(fields[3]), Path(_unescape_mount(fields[4]))
        if group == root:
            candidates.append(mount)
        elif root == '/':
            candidates.append(mount / group.lstrip('/'))
        elif group.startswith(root.rstrip('/') + '/'):
            candidates.append(mount / group[len(root):].lstrip('/'))
        # A cgroup namespace can report '/' while the mount keeps its host root.
        if group == '/':
            candidates.append(mount)
    for candidate in candidates:
        if (candidate / 'memory.current').is_file():
            return candidate.resolve()
    return None


def _number_or_max(value):
    if value in (None, 'max'):
        return value
    try:
        return int(value)
    except ValueError:
        return None


def read_cgroup(path):
    if path is None:
        return None
    stat = key_values(path / 'memory.stat')
    cpu_max = read_text(path / 'cpu.max')
    cpu_fields = (cpu_max or '').split()
    quota = _number_or_max(cpu_fields[0]) if len(cpu_fields) == 2 else None
    period = _number_or_max(cpu_fields[1]) if len(cpu_fields) == 2 else None
    return {
        'memory_max_bytes': _number_or_max(read_text(path / 'memory.max')),
        'memory_current_bytes': _number_or_max(read_text(path / 'memory.current')),
        'memory_anon_bytes': stat.get('anon'),
        'memory_file_bytes': stat.get('file'),
        'memory_events': key_values(path / 'memory.events'),
        'cpu_max': cpu_max,
        'cpu_quota_us': quota,
        'cpu_period_us': period,
        'cpu_limit_cores': quota / period if isinstance(quota, int) and isinstance(period, int) and period > 0 else None,
    }


def _maximum(previous, current):
    if current is None:
        return previous
    return current if previous is None else max(previous, current)


def _terminate_group(process, sig):
    try:
        os.killpg(process.pid, sig)
    except ProcessLookupError:
        pass


def _stop_and_wait(process):
    if process.poll() is None:
        _terminate_group(process, signal.SIGTERM)
        try:
            process.wait(timeout=TERM_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            _terminate_group(process, signal.SIGKILL)
            process.wait()


def _write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f'.tmp.{os.getpid()}')
    try:
        temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def measure(command, output, rss_limit_mib):
    start = time.monotonic()
    process = None
    cgroup_path = find_cgroup_v2()
    initial_cgroup = read_cgroup(cgroup_path)
    stop_signal = None
    previous_handlers = {}
    result = {
        'schema_version': 1,
        'command': list(command),
        'started_at_utc': utc_now(),
        'ended_at_utc': None,
        'wall_seconds': None,
        'child_pid': None,
        'exit_code': None,
        'wrapper_exit_code': None,
        'resource_guard_triggered': False,
        'rss_limit_mib': rss_limit_mib,
        'rss_limit_bytes': int(rss_limit_mib * MIB),
        'poll_interval_seconds': POLL_SECONDS,
        'term_grace_seconds': TERM_GRACE_SECONDS,
        'peak_process_rss_bytes': None,
        'peak_process_hwm_bytes': None,
        'peak_process_memory_bytes': None,
        'child_rusage_maxrss_bytes': None,
        'peak_cgroup_current_bytes': None,
        'peak_cgroup_anon_bytes': None,
        'peak_cgroup_file_bytes': None,
        'cgroup_v2_path': str(cgroup_path) if cgroup_path else None,
        'cgroup_initial': initial_cgroup,
        'cgroup_final': None,
        'cgroup_events_delta': None,
        'sample_count': 0,
        'samples': [],
        'status': 'starting',
        'limitations': [
            'Process RSS/HWM covers the single child, not additional descendants.',
            'Cgroup statistics and event deltas cover all processes in the shared cgroup.',
            'Polling may miss short-lived allocations; VmHWM improves the peak estimate.',
            'After reaping the only child, Linux RUSAGE_CHILDREN.ru_maxrss supplies its final peak RSS.',
            'File cache does not trigger the RSS guard; no RLIMIT_AS is applied.',
        ],
    }

    def receive_signal(signum, _frame):
        nonlocal stop_signal
        stop_signal = signum

    def sample():
        memory = read_process_memory(process.pid) if process is not None else {'rss_bytes': None, 'hwm_bytes': None}
        cgroup = read_cgroup(cgroup_path)
        result['sample_count'] += 1
        result['peak_process_rss_bytes'] = _maximum(result['peak_process_rss_bytes'], memory['rss_bytes'])
        result['peak_process_hwm_bytes'] = _maximum(result['peak_process_hwm_bytes'], memory['hwm_bytes'])
        result['peak_process_memory_bytes'] = _maximum(result['peak_process_rss_bytes'], result['peak_process_hwm_bytes'])
        if cgroup:
            for output_key, input_key in (
                ('peak_cgroup_current_bytes', 'memory_current_bytes'),
                ('peak_cgroup_anon_bytes', 'memory_anon_bytes'),
                ('peak_cgroup_file_bytes', 'memory_file_bytes'),
            ):
                result[output_key] = _maximum(result[output_key], cgroup[input_key])
        record = {'elapsed_seconds': round(time.monotonic() - start, 3), **memory, 'cgroup': cgroup}
        result['samples'].append(record)
        return memory, cgroup

    wrapper_code = 1
    try:
        if not Path('/proc/self/status').is_file():
            raise RuntimeError('This resource monitor requires Linux /proc; no command was started.')
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous_handlers[signum] = signal.signal(signum, receive_signal)
        process = subprocess.Popen(command, start_new_session=True)
        result['child_pid'] = process.pid
        result['status'] = 'running'
        process_cgroup_path = find_cgroup_v2(process.pid)
        if process_cgroup_path is not None and process_cgroup_path != cgroup_path:
            cgroup_path = process_cgroup_path
            result['cgroup_v2_path'] = str(cgroup_path)
            result['cgroup_initial'] = read_cgroup(cgroup_path)
        while True:
            memory, _ = sample()
            measured_peak = _maximum(memory['rss_bytes'], memory['hwm_bytes'])
            if measured_peak is not None and measured_peak > result['rss_limit_bytes']:
                result['resource_guard_triggered'] = True
                result['guard_triggered_at_seconds'] = time.monotonic() - start
                result['guard_trigger_rss_bytes'] = memory['rss_bytes']
                result['guard_trigger_hwm_bytes'] = memory['hwm_bytes']
                result['status'] = 'resource_guard_triggered'
                _stop_and_wait(process)
                wrapper_code = 125
                break
            if stop_signal is not None:
                result['interrupted_by_signal'] = stop_signal
                result['status'] = 'interrupted'
                _stop_and_wait(process)
                wrapper_code = 128 + stop_signal
                break
            child_code = process.poll()
            if child_code is not None:
                result['status'] = 'completed' if child_code == 0 else 'command_failed'
                wrapper_code = child_code if child_code >= 0 else 128 - child_code
                break
            time.sleep(POLL_SECONDS)
    except Exception as error:
        result['status'] = 'monitor_failed'
        result['error'] = f'{type(error).__name__}: {error}'
        print(result['error'], file=sys.stderr, flush=True)
        wrapper_code = 1
    finally:
        final_cgroup = None
        try:
            if process is not None:
                _stop_and_wait(process)
                result['exit_code'] = process.returncode
                result['child_rusage_maxrss_bytes'] = int(resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss * 1024)
                _, final_cgroup = sample()
                result['peak_process_memory_bytes'] = _maximum(result['peak_process_memory_bytes'], result['child_rusage_maxrss_bytes'])
            else:
                final_cgroup = read_cgroup(cgroup_path)
        except Exception as error:
            result['cleanup_error'] = f'{type(error).__name__}: {error}'
            if wrapper_code == 0:
                wrapper_code = 1
                result['status'] = 'monitor_failed'
        result['cgroup_final'] = final_cgroup
        before, after = result['cgroup_initial'], final_cgroup
        if before is not None and after is not None:
            event_keys = set(before['memory_events']) | set(after['memory_events']) | {'oom', 'oom_kill'}
            result['cgroup_events_delta'] = {
                key: after['memory_events'][key] - before['memory_events'][key]
                if key in before['memory_events'] and key in after['memory_events'] else None
                for key in sorted(event_keys)
            }
        result['ended_at_utc'] = utc_now()
        result['wall_seconds'] = time.monotonic() - start
        result['wrapper_exit_code'] = wrapper_code
        for signum, previous in previous_handlers.items():
            signal.signal(signum, previous)
        _write_json(output, result)
    return wrapper_code


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--rss-limit-mib', required=True, type=float)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    if not command:
        parser.error('A command is required after --.')
    if not 0 < args.rss_limit_mib < float('inf'):
        parser.error('--rss-limit-mib must be finite and positive.')
    return measure(command, args.output, args.rss_limit_mib)


if __name__ == '__main__':
    raise SystemExit(main())
