//! Engine tests: the control state machine, feeder and renderer on one thread
//! (`ManualEngine`) with `FakeOutput` and a manual clock. The fake device
//! only plays when a test advances it.

use std::collections::HashSet;
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use qtmedia_app::audio::engine::{
    Command, Event, ManualEngine, Platform, PlayState, Settings, RELEASE_AFTER,
};
use qtmedia_app::audio::format::{DeviceCaps, Negotiated, OutputMode, PcmFormat, RateMismatch};
use qtmedia_app::audio::output::fake::FakeOutput;
use qtmedia_app::audio::output::{Output, OutputError};

const BUFFER: usize = 512;

fn fixture(name: &str) -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("tests/fixtures/audio")
        .join(name)
}

fn raw(name: &str) -> Vec<u8> {
    std::fs::read(fixture(name)).unwrap()
}

struct Caps {
    exclusive: HashSet<PcmFormat>,
}

impl DeviceCaps for Caps {
    fn supports_exclusive(&self, format: &PcmFormat) -> bool {
        self.exclusive.contains(format)
    }
    fn mix_format(&self) -> PcmFormat {
        PcmFormat::float(48_000, 2)
    }
    fn is_bluetooth(&self) -> bool {
        false
    }
}

/// One opened fake device, shared with the test.
#[derive(Clone)]
struct Device {
    output: Arc<Mutex<FakeOutput>>,
    closed: Arc<AtomicBool>,
    negotiated: Negotiated,
}

impl Device {
    fn play(&self, frames: usize) {
        self.output.lock().unwrap().play(frames);
    }
    fn bytes(&self) -> Vec<u8> {
        self.output.lock().unwrap().bytes().to_vec()
    }
    fn is_closed(&self) -> bool {
        self.closed.load(Ordering::SeqCst)
    }
    fn fail_with(&self, error: OutputError) {
        self.output.lock().unwrap().fail_with(error);
    }
}

/// The `Box<dyn Output>` the engine owns; flags the device closed on drop.
struct Handle(Device);

impl Output for Handle {
    fn format(&self) -> PcmFormat {
        self.0.output.lock().unwrap().format()
    }
    fn wait(&mut self, timeout_ms: u32) -> Result<usize, OutputError> {
        self.0.output.lock().unwrap().wait(timeout_ms)
    }
    fn write(&mut self, bytes: &[u8]) -> Result<usize, OutputError> {
        self.0.output.lock().unwrap().write(bytes)
    }
    fn start(&mut self) -> Result<(), OutputError> {
        self.0.output.lock().unwrap().start()
    }
    fn pause(&mut self) -> Result<(), OutputError> {
        self.0.output.lock().unwrap().pause()
    }
    fn flush(&mut self) -> Result<(), OutputError> {
        self.0.output.lock().unwrap().flush()
    }
    fn position_frames(&mut self) -> Result<u64, OutputError> {
        self.0.output.lock().unwrap().position_frames()
    }
}

impl Drop for Handle {
    fn drop(&mut self) {
        self.0.closed.store(true, Ordering::SeqCst);
    }
}

#[derive(Default)]
struct FakePlatform {
    opened: Mutex<Vec<Device>>,
}

impl FakePlatform {
    fn devices(&self) -> Vec<Device> {
        self.opened.lock().unwrap().clone()
    }
    fn last(&self) -> Device {
        self.devices().last().cloned().expect("a device was opened")
    }
}

impl Platform for FakePlatform {
    fn caps(&self, _device: Option<&str>) -> Result<Box<dyn DeviceCaps>, OutputError> {
        let mut exclusive = HashSet::new();
        for rate in [44_100, 48_000, 88_200, 96_000, 176_400, 192_000] {
            for (container, valid) in [(16, 16), (24, 24), (32, 24)] {
                exclusive.insert(PcmFormat::int(rate, 2, container, valid));
            }
        }
        Ok(Box::new(Caps { exclusive }))
    }

    fn open(
        &self,
        _device: Option<&str>,
        negotiated: Negotiated,
        _volume: f32,
    ) -> Result<(Box<dyn Output>, Negotiated), OutputError> {
        let output = match negotiated.mode {
            OutputMode::Exclusive => FakeOutput::exclusive(negotiated.output, BUFFER),
            OutputMode::Shared => FakeOutput::shared(negotiated.output, BUFFER),
        };
        let device = Device {
            output: Arc::new(Mutex::new(output)),
            closed: Arc::new(AtomicBool::new(false)),
            negotiated,
        };
        self.opened.lock().unwrap().push(device.clone());
        Ok((Box::new(Handle(device)), negotiated))
    }
}

fn exclusive() -> Settings {
    Settings {
        device: None,
        mode: OutputMode::Exclusive,
        rate_mismatch: RateMismatch::Strict,
        exclusive_volume: false,
        levelling: true,
    }
}

struct Rig {
    platform: Arc<FakePlatform>,
    engine: ManualEngine,
    now: Instant,
    events: Vec<Event>,
}

impl Rig {
    fn new(settings: Settings) -> Self {
        let platform = Arc::new(FakePlatform::default());
        let engine = ManualEngine::new(platform.clone(), settings, 1.0);
        Self {
            platform,
            engine,
            now: Instant::now(),
            events: Vec::new(),
        }
    }

    fn send(&mut self, command: Command) {
        self.engine.handle(command, self.now);
        self.collect();
    }

    fn play(&mut self, name: &str) {
        self.send(Command::Play {
            path: fixture(name),
            start_seconds: 0.0,
        });
    }

    fn collect(&mut self) {
        self.events.extend(self.engine.take_events());
    }

    /// One period: the device plays a buffer, then the engine refills it.
    fn period(&mut self) {
        if let Some(device) = self.platform.devices().last() {
            device.play(BUFFER);
        }
        self.engine.pump(self.now);
        self.collect();
    }

    fn periods(&mut self, count: usize) {
        for _ in 0..count {
            self.period();
        }
    }

    fn until(&mut self, done: impl Fn(&[Event]) -> bool) {
        for _ in 0..10_000 {
            if done(&self.events) {
                return;
            }
            self.period();
        }
        panic!("condition never reached; events: {:?}", self.events);
    }

    fn position(&mut self) -> f64 {
        self.engine.position().expect("a position")
    }

    fn states(&self) -> Vec<PlayState> {
        self.events
            .iter()
            .filter_map(|event| match event {
                Event::State(state) => Some(*state),
                _ => None,
            })
            .collect()
    }
}

fn track_events(events: &[Event]) -> Vec<String> {
    events
        .iter()
        .filter_map(|event| match event {
            Event::TrackStarted { path, .. } => Some(format!("start {}", name(path))),
            Event::TrackEnded { path } => Some(format!("end {}", name(path))),
            Event::DeviceOpened { negotiated } => Some(format!("open {}", negotiated.output.rate)),
            Event::DeviceReleased => Some("release".to_owned()),
            Event::State(PlayState::Idle) => Some("idle".to_owned()),
            _ => None,
        })
        .collect()
}

fn name(path: &std::path::Path) -> String {
    path.file_name().unwrap().to_string_lossy().into_owned()
}

fn ended(events: &[Event]) -> bool {
    events.contains(&Event::State(PlayState::Idle))
}

#[test]
fn play_reaches_playing_bit_perfect_and_counts_played_frames() {
    let mut rig = Rig::new(exclusive());
    rig.play("sine_16_44100.flac");
    assert_eq!(rig.states(), [PlayState::Loading, PlayState::Playing]);
    let signal = rig
        .events
        .iter()
        .find_map(|event| match event {
            Event::SignalPath { negotiated, .. } => Some(*negotiated),
            _ => None,
        })
        .unwrap();
    assert!(signal.bit_perfect);
    assert_eq!(signal.output, PcmFormat::int(44_100, 2, 16, 16));

    rig.engine.pump(rig.now); // prefill + start
    assert_eq!(rig.position(), 0.0);
    rig.periods(4); // four buffers played
    let expected = 4.0 * BUFFER as f64 / 44_100.0;
    assert!((rig.position() - expected).abs() < 1e-9);
    assert!(rig
        .events
        .iter()
        .any(|event| matches!(event, Event::Position { .. })));
}

#[test]
fn exclusive_playback_writes_the_file_pcm_unchanged() {
    let mut rig = Rig::new(exclusive());
    rig.play("sine_16_44100.flac");
    rig.until(ended);
    let expected = raw("sine_16_44100.raw");
    // The device was released at the end; its bytes are the PCM then padding.
    let bytes = rig.platform.last().bytes();
    assert_eq!(&bytes[..expected.len()], expected.as_slice());
    assert!(bytes[expected.len()..].iter().all(|&byte| byte == 0));
}

#[test]
fn pause_holds_position_and_resume_continues() {
    let mut rig = Rig::new(exclusive());
    rig.play("sine_16_44100.flac");
    rig.periods(5);
    rig.send(Command::Pause);
    let held = rig.position();
    rig.periods(10);
    assert_eq!(rig.position(), held);
    assert_eq!(rig.engine.state(), PlayState::Paused);

    rig.send(Command::Resume);
    rig.periods(2);
    assert!(rig.position() > held);
    assert_eq!(
        rig.states(),
        [
            PlayState::Loading,
            PlayState::Playing,
            PlayState::Paused,
            PlayState::Playing
        ]
    );
}

#[test]
fn seek_flushes_the_ring_and_resumes_at_the_target() {
    let mut rig = Rig::new(exclusive());
    rig.play("sine_16_44100.flac");
    rig.periods(6);
    rig.send(Command::Seek(0.125));
    // Flushed: nothing of the old stream remains on the device.
    assert!(rig.platform.last().bytes().is_empty());
    assert_eq!(rig.platform.devices().len(), 1, "seek keeps the device");
    rig.engine.pump(rig.now);
    // 0.125 s is frame 5512.5; the decoder rounds to 5513.
    assert_eq!(rig.position(), 5513.0 / 44_100.0);

    rig.until(ended);
    let expected = raw("sine_16_44100.raw");
    let from = 5513 * 4;
    let bytes = rig.platform.last().bytes();
    assert_eq!(&bytes[..expected.len() - from], &expected[from..]);
}

#[test]
fn next_track_with_the_same_format_joins_gaplessly() {
    let mut rig = Rig::new(exclusive());
    rig.play("sine_16_44100.flac");
    rig.send(Command::SetNext(Some(fixture("sine_16_44100.flac"))));
    rig.until(ended);

    assert_eq!(
        track_events(&rig.events),
        [
            "open 44100",
            "start sine_16_44100.flac",
            "end sine_16_44100.flac",
            "start sine_16_44100.flac",
            "end sine_16_44100.flac",
            "release",
            "idle"
        ]
    );
    // One device, and the two tracks back to back with no silence between.
    assert_eq!(rig.platform.devices().len(), 1);
    let one = raw("sine_16_44100.raw");
    let both = [one.as_slice(), one.as_slice()].concat();
    let bytes = rig.platform.last().bytes();
    assert_eq!(&bytes[..both.len()], both.as_slice());
}

#[test]
fn next_track_with_another_format_reopens_the_device() {
    let mut rig = Rig::new(exclusive());
    rig.play("sine_16_44100.flac");
    rig.send(Command::SetNext(Some(fixture("sine_24_96000.flac"))));
    rig.until(ended);

    assert_eq!(
        track_events(&rig.events),
        [
            "open 44100",
            "start sine_16_44100.flac",
            "end sine_16_44100.flac",
            "open 96000",
            "start sine_24_96000.flac",
            "end sine_24_96000.flac",
            "release",
            "idle"
        ]
    );
    let devices = rig.platform.devices();
    assert_eq!(devices.len(), 2);
    assert!(devices[0].is_closed());
    assert_eq!(
        devices[1].negotiated.output,
        PcmFormat::int(96_000, 2, 24, 24)
    );
    let expected = raw("sine_24_96000.raw");
    assert_eq!(&devices[1].bytes()[..expected.len()], expected.as_slice());
}

#[test]
fn shared_mode_joins_different_rates_into_one_device() {
    let mut rig = Rig::new(Settings::default());
    rig.play("sine_16_44100.flac");
    rig.send(Command::SetNext(Some(fixture("sine_24_96000.flac"))));
    rig.until(ended);
    assert_eq!(rig.platform.devices().len(), 1);
    assert_eq!(
        track_events(&rig.events)
            .iter()
            .filter(|event| event.starts_with("start"))
            .count(),
        2
    );
}

#[test]
fn end_of_queue_reports_track_ended_then_idle_and_releases() {
    let mut rig = Rig::new(exclusive());
    rig.play("sine_16_44100.flac");
    rig.until(ended);
    let tail: Vec<_> = track_events(&rig.events)
        .into_iter()
        .rev()
        .take(3)
        .collect();
    assert_eq!(tail, ["idle", "release", "end sine_16_44100.flac"]);
    assert!(rig.platform.last().is_closed());
    assert_eq!(rig.engine.state(), PlayState::Idle);
}

#[test]
fn device_loss_reports_the_error_and_stops() {
    let mut rig = Rig::new(exclusive());
    rig.play("sine_16_44100.flac");
    rig.periods(3);
    rig.platform.last().fail_with(OutputError::DeviceLost);
    rig.period();
    assert!(rig.events.contains(&Event::Error {
        code: "audio_device_lost"
    }));
    assert_eq!(rig.engine.state(), PlayState::Stopped);
    assert!(rig.platform.last().is_closed());
}

#[test]
fn a_paused_shared_engine_releases_the_device_after_30_seconds() {
    let mut rig = Rig::new(Settings::default());
    rig.play("sine_16_44100.flac");
    rig.periods(5);
    rig.send(Command::Pause);
    let held = rig.position();

    rig.now += RELEASE_AFTER - Duration::from_secs(1);
    rig.period();
    assert!(!rig.platform.last().is_closed());

    rig.now += Duration::from_secs(1);
    rig.period();
    assert!(rig.platform.last().is_closed());
    assert!(rig.events.contains(&Event::DeviceReleased));
    assert_eq!(rig.engine.state(), PlayState::Paused);
    assert_eq!(rig.position(), held);

    // Resume reopens the device at the paused position.
    rig.send(Command::Resume);
    assert_eq!(rig.platform.devices().len(), 2);
    rig.engine.pump(rig.now);
    assert!((rig.position() - held).abs() < 1.0 / 44_100.0);
    assert_eq!(rig.engine.state(), PlayState::Playing);
}

#[test]
fn release_command_frees_the_device_immediately() {
    let mut rig = Rig::new(exclusive());
    rig.play("sine_16_44100.flac");
    rig.periods(2);
    rig.send(Command::Release);
    assert_eq!(rig.engine.state(), PlayState::Paused);
    assert!(rig.platform.last().is_closed());
}

#[test]
fn an_exclusive_pause_gives_the_device_back_at_once() {
    let mut rig = Rig::new(exclusive());
    rig.play("sine_16_44100.flac");
    rig.periods(5);
    rig.send(Command::Pause);
    let held = rig.position();
    // Other apps can use the device straight away.
    assert!(rig.platform.last().is_closed());
    assert!(rig.events.contains(&Event::DeviceReleased));
    assert_eq!(rig.engine.state(), PlayState::Paused);
    assert_eq!(rig.position(), held);

    // Seeking while paused does not take the device back.
    rig.send(Command::Seek(0.125));
    assert_eq!(rig.platform.devices().len(), 1);
    assert_eq!(rig.position(), 0.125);

    // Resume reopens it at the new position.
    rig.send(Command::Resume);
    assert_eq!(rig.platform.devices().len(), 2);
    rig.engine.pump(rig.now);
    assert!((rig.position() - 0.125).abs() < 1.0 / 44_100.0);
    assert_eq!(rig.engine.state(), PlayState::Playing);
}

#[test]
fn shared_volume_is_applied_at_the_device_without_reopening() {
    let mut loud = Rig::new(Settings::default());
    loud.play("sine_16_44100.flac");
    loud.until(ended);

    let mut quiet = Rig::new(Settings::default());
    quiet.play("sine_16_44100.flac");
    quiet.send(Command::SetVolume(0.5));
    quiet.until(ended);
    assert_eq!(quiet.platform.devices().len(), 1);

    let samples = |bytes: Vec<u8>| -> Vec<f32> {
        bytes
            .chunks_exact(4)
            .map(|b| f32::from_le_bytes([b[0], b[1], b[2], b[3]]))
            .collect()
    };
    let loud = samples(loud.platform.last().bytes());
    let quiet = samples(quiet.platform.last().bytes());
    assert_eq!(loud.len(), quiet.len());
    for (a, b) in loud.iter().zip(&quiet) {
        assert!((a * 0.5 - b).abs() < 1e-6);
    }
}

#[test]
fn exclusive_volume_is_ignored_unless_enabled() {
    let mut rig = Rig::new(exclusive());
    rig.play("sine_16_44100.flac");
    rig.send(Command::SetVolume(0.3));
    rig.until(ended);
    let expected = raw("sine_16_44100.raw");
    assert_eq!(
        &rig.platform.last().bytes()[..expected.len()],
        expected.as_slice()
    );
}

#[test]
fn a_missing_file_reports_an_error_and_stops() {
    let mut rig = Rig::new(exclusive());
    rig.play("missing.flac");
    assert!(rig.events.contains(&Event::Error { code: "audio_io" }));
    assert_eq!(rig.engine.state(), PlayState::Stopped);
    assert!(rig.platform.devices().is_empty());
}

#[test]
fn a_next_track_set_after_decoding_ended_plays_in_a_new_session() {
    let mut rig = Rig::new(exclusive());
    rig.play("sine_16_44100.flac");
    rig.period(); // the short track is fully decoded into the ring
    rig.send(Command::SetNext(Some(fixture("sine_16_44100.flac"))));
    rig.until(ended);
    assert_eq!(
        track_events(&rig.events),
        [
            "open 44100",
            "start sine_16_44100.flac",
            "end sine_16_44100.flac",
            "start sine_16_44100.flac",
            "end sine_16_44100.flac",
            "release",
            "idle"
        ]
    );
    // Same format: the device stays open across the new session.
    assert_eq!(rig.platform.devices().len(), 1);
    assert_eq!(
        rig.states()
            .iter()
            .filter(|state| **state == PlayState::Loading)
            .count(),
        2
    );
}

#[test]
fn a_new_windows_default_reopens_only_when_following_the_default() {
    // Following the default: reopen at the same position.
    let mut rig = Rig::new(Settings::default());
    rig.play("sine_16_44100.flac");
    rig.periods(5);
    let before = rig.position();
    rig.send(Command::DefaultDeviceChanged);
    assert_eq!(rig.platform.devices().len(), 2);
    assert!(rig.platform.devices()[0].is_closed());
    rig.engine.pump(rig.now);
    assert!((rig.position() - before).abs() < 1.0 / 44_100.0);
    assert_eq!(rig.engine.state(), PlayState::Playing);

    // A chosen device: nothing changes.
    let mut rig = Rig::new(Settings {
        device: Some("dac".into()),
        ..exclusive()
    });
    rig.play("sine_16_44100.flac");
    rig.periods(2);
    rig.send(Command::DefaultDeviceChanged);
    assert_eq!(rig.platform.devices().len(), 1);
}

#[test]
fn a_released_engine_stays_released_when_settings_change() {
    let mut rig = Rig::new(exclusive());
    rig.play("sine_16_44100.flac");
    rig.periods(3);
    rig.send(Command::Release);
    rig.send(Command::SetSettings(Settings::default()));
    assert_eq!(rig.platform.devices().len(), 1, "no reopen while released");
    rig.send(Command::Resume);
    assert_eq!(rig.platform.devices().len(), 2);
    assert_eq!(
        rig.platform.devices()[1].negotiated.mode,
        OutputMode::Shared,
        "resume uses the new settings"
    );
}

#[test]
fn seeking_does_not_announce_a_new_track() {
    let mut rig = Rig::new(exclusive());
    rig.play("sine_16_44100.flac");
    rig.periods(3);
    rig.events.clear();
    rig.send(Command::Seek(0.1));
    rig.period();
    assert!(
        rig.events
            .iter()
            .all(|event| matches!(event, Event::Position { .. })),
        "{:?}",
        rig.events
    );

    rig.send(Command::SetSettings(Settings::default()));
    assert!(rig
        .events
        .iter()
        .any(|event| matches!(event, Event::SignalPath { .. })));
    assert!(!rig
        .events
        .iter()
        .any(|event| matches!(event, Event::TrackStarted { .. })));
}

// --- Loudness levelling -------------------------------------------------------

fn signal(events: &[Event]) -> qtmedia_app::audio::format::Negotiated {
    events
        .iter()
        .find_map(|event| match event {
            Event::SignalPath { negotiated, .. } => Some(*negotiated),
            _ => None,
        })
        .unwrap()
}

fn levelled_rig(settings: Settings, gain: f32) -> Rig {
    let mut rig = Rig::new(settings);
    let engine = std::mem::replace(
        &mut rig.engine,
        ManualEngine::new(rig.platform.clone(), Settings::default(), 1.0),
    );
    rig.engine = engine.with_leveler(Arc::new(move |_| Some(gain)));
    rig
}

#[test]
fn levelling_scales_the_song_where_software_volume_is_allowed() {
    let mut rig = levelled_rig(
        Settings {
            exclusive_volume: true,
            ..exclusive()
        },
        0.5,
    );
    rig.play("sine_16_44100.flac");
    let negotiated = signal(&rig.events);
    assert!(!negotiated.bit_perfect);
    assert_eq!(
        negotiated.reason,
        Some(qtmedia_app::audio::format::Reason::VolumeLevelling)
    );
    rig.until(ended);
    let expected = raw("sine_16_44100.raw");
    let bytes = rig.platform.last().bytes();
    assert_ne!(&bytes[..expected.len()], expected.as_slice());
    // About half the amplitude: compare the loudest 16-bit sample.
    let peak = |data: &[u8]| {
        data.chunks_exact(2)
            .map(|pair| i16::from_le_bytes([pair[0], pair[1]]).unsigned_abs())
            .max()
            .unwrap()
    };
    let ratio = f64::from(peak(&bytes[..expected.len()])) / f64::from(peak(&expected));
    assert!((ratio - 0.5).abs() < 0.01, "{ratio}");
}

#[test]
fn strict_exclusive_and_levelling_off_stay_bit_perfect() {
    for settings in [
        exclusive(),
        Settings {
            exclusive_volume: true,
            levelling: false,
            ..exclusive()
        },
    ] {
        let mut rig = levelled_rig(settings, 0.5);
        rig.play("sine_16_44100.flac");
        assert!(signal(&rig.events).bit_perfect);
        rig.until(ended);
        let expected = raw("sine_16_44100.raw");
        assert_eq!(
            &rig.platform.last().bytes()[..expected.len()],
            expected.as_slice()
        );
    }
}
