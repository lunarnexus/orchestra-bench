"""Read-only reporting helpers for benchmark results."""

from .debug import DebugReport, build_debug_report, format_debug_report
from .session_debug import SessionTranscript, classify_session, discover_session_transcripts, format_session_debug, format_session_raw, render_session_transcript
from .formatters import format_dashboard, format_run_detail, format_runs, format_timing, format_tokens
from .management import (
    compare_results,
    delete_all_result_dirs,
    delete_results,
    describe_filters,
    format_compare_results,
    format_delete_preview,
    format_rescore_report,
    rescore_results,
    select_results,
)
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
    "compare_results",
    "delete_all_result_dirs",
    "delete_results",
    "describe_filters",
    "format_compare_results",
    "format_delete_preview",
    "format_rescore_report",
    "rescore_results",
    "select_results",
    "DebugReport",
    "build_debug_report",
    "format_debug_report",
    "SessionTranscript",
    "classify_session",
    "discover_session_transcripts",
    "format_session_debug",
    "format_session_raw",
    "render_session_transcript",
]
