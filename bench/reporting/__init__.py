"""Read-only reporting helpers for benchmark results."""

from .debug import DebugReport, build_debug_report, format_debug_report
from .formatters import format_dashboard, format_run_detail, format_runs, format_timing, format_tokens
from .queries import ReportEntry, collect_results, filter_results, sort_results

__all__ = [
    "ReportEntry",
    "collect_results",
    "filter_results",
    "sort_results",
    "format_dashboard",
    "format_runs",
    "format_run_detail",
    "format_tokens",
    "format_timing",
    "DebugReport",
    "build_debug_report",
    "format_debug_report",
]
