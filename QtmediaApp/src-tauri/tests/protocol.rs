use qtmedia_app::protocol::{parse_sidecar_line, RequestTracker, StableError};
use serde_json::json;

#[test]
fn parses_known_events_and_converts_public_fields_to_camel_case() {
    let event = parse_sidecar_line(
        r#"{"id":"request-4","event":"download_progress","job_id":"job-x","downloaded_bytes":8,"total_bytes":16,"percent":50}"#,
    )
    .unwrap();
    assert_eq!(event.request_id, "request-4");
    assert_eq!(event.frontend_payload["event"], "download_progress");
    assert_eq!(event.frontend_payload["jobId"], "job-x");
    assert_eq!(event.frontend_payload["downloadedBytes"], 8);
    assert!(event.frontend_payload.get("url").is_none());
}

#[test]
fn rejects_malformed_unknown_and_url_bearing_output() {
    assert_eq!(
        parse_sidecar_line("not-json").unwrap_err(),
        StableError::MalformedOutput
    );
    assert_eq!(
        parse_sidecar_line(r#"{"id":"1","event":"invented"}"#).unwrap_err(),
        StableError::MalformedOutput
    );
    assert_eq!(
        parse_sidecar_line(
            r#"{"id":"1","event":"error","code":"x","url":"https://example.test/private"}"#
        )
        .unwrap_err(),
        StableError::UnsafeOutput
    );
}

#[test]
fn correlates_only_terminal_responses_for_each_action() {
    let mut tracker = RequestTracker::default();
    tracker.insert("request-1", "inspect").unwrap();
    assert!(!tracker.is_terminal("request-1", "inspection_started"));
    assert!(tracker.is_terminal("request-1", "inspection_ready"));
    assert!(tracker.take("request-1").is_some());
    assert!(tracker.take("request-1").is_none());

    tracker.insert("request-2", "library_list").unwrap();
    assert!(tracker.is_terminal("request-2", "error"));

    tracker.insert("request-3", "cancel").unwrap();
    assert!(tracker.is_terminal("request-3", "cancellation_requested"));
    assert!(!tracker.is_terminal("request-3", "download_cancelled"));
}

#[test]
fn parses_cancellation_acknowledgement_without_marking_the_job_finished() {
    let event = parse_sidecar_line(
        r#"{"id":"cancel-1","event":"cancellation_requested","job_id":"job-x"}"#,
    )
    .unwrap();
    assert_eq!(event.frontend_payload["event"], "cancellation_requested");
    assert_eq!(event.frontend_payload["jobId"], "job-x");
}

#[test]
fn stable_errors_never_include_raw_sidecar_details() {
    let value = serde_json::to_value(StableError::ProcessExited).unwrap();
    assert_eq!(value, json!("sidecar_exited"));
}
