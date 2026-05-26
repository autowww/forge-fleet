"""SQLite job store — see README.md."""

import time as time

from fleet_server.store.core import connect, get_fleet_version_row, insert_job, update_job, get_job, authenticate_workspace_worker_bridge, merge_job_meta, merge_worker_progress, set_worker_result, sum_accounted_core_seconds, count_jobs_by_status, count_running_jobs_by_container_class, workload_title_for_job, count_jobs, list_jobs_summary
from fleet_server.store.telemetry import telemetry_time_bounds, get_energy_ledger, apply_energy_ledger_delta, maybe_record_telemetry_sample, list_telemetry_samples, insert_cooldown_event, cooldown_time_bounds, cooldown_aggregate_s, cooldown_summary_payload, cooldown_summary_presets

__all__ = [
    "connect",
    "get_fleet_version_row",
    "insert_job",
    "update_job",
    "get_job",
    "authenticate_workspace_worker_bridge",
    "merge_job_meta",
    "merge_worker_progress",
    "set_worker_result",
    "sum_accounted_core_seconds",
    "count_jobs_by_status",
    "count_running_jobs_by_container_class",
    "workload_title_for_job",
    "count_jobs",
    "list_jobs_summary",
    "telemetry_time_bounds",
    "get_energy_ledger",
    "apply_energy_ledger_delta",
    "maybe_record_telemetry_sample",
    "list_telemetry_samples",
    "insert_cooldown_event",
    "cooldown_time_bounds",
    "cooldown_aggregate_s",
    "cooldown_summary_payload",
    "cooldown_summary_presets",
]
