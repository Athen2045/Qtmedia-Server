use std::path::Path;

use qtmedia_app::{
    protocol::StableError,
    sidecar::{bundled_binary_sibling, request_can_recover, ActivityTracker, LifecycleTracker},
};

#[test]
fn bundled_tools_are_resolved_beside_the_tauri_executable() {
    let executable = Path::new("bundle").join("MacOS").join("Qtmedia");
    assert_eq!(
        bundled_binary_sibling(&executable, "ffmpeg").unwrap(),
        Path::new("bundle").join("MacOS").join("ffmpeg")
    );
}

#[test]
fn intentional_shutdown_is_distinct_from_an_engine_crash() {
    let lifecycle = LifecycleTracker::default();
    assert!(!lifecycle.is_shutting_down());
    lifecycle.begin_shutdown();
    assert!(lifecycle.is_shutting_down());
}

#[test]
fn activity_tracker_stays_busy_until_the_last_job_finishes() {
    let tracker = ActivityTracker::default();
    tracker.started("job-1", "download-1");
    tracker.started("job-2", "download-2");
    assert!(tracker.is_busy());

    tracker.finished("job-1", "cancel-request");
    assert!(tracker.is_busy());
    tracker.finished("job-1", "download-1");
    assert!(tracker.is_busy());
    tracker.finished("job-2", "download-2");
    assert!(!tracker.is_busy());
}

#[test]
fn only_repeatable_idle_requests_recover_from_engine_loss() {
    assert!(request_can_recover(
        "inspect",
        StableError::SidecarUnavailable
    ));
    assert!(request_can_recover(
        "library_list",
        StableError::ProcessExited
    ));
    assert!(!request_can_recover(
        "download",
        StableError::SidecarUnavailable
    ));
    assert!(!request_can_recover("cancel", StableError::ProcessExited));
    assert!(!request_can_recover("inspect", StableError::InvalidRequest));
}

#[test]
fn activity_tracker_releases_jobs_after_engine_loss() {
    let tracker = ActivityTracker::default();
    tracker.started("job-lost", "download-lost");

    tracker.clear();

    assert!(!tracker.is_busy());
}
