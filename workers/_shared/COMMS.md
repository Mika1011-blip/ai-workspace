To contact another worker, use list_sessions and send_to_session only.

When your task is done, call report_result(status, summary, tags) once —
status is success, failed, skipped or needs_input — so your run is on
record before you stop.
