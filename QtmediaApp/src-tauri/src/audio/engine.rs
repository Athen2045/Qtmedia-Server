//! Playback engine: a control state machine, a decoder feeder and a renderer
//! joined by an `rtrb` byte ring (≈2 s of device-format audio).
//!
//! - **Control** ([`Engine`]) owns the state, the device capabilities and the
//!   queue. It negotiates formats, opens sessions and turns worker reports and
//!   the device clock into [`Event`]s.
//! - **Feeder** (decoder thread) decodes and converts ahead of playback and
//!   joins the next track into the same ring when its output format matches
//!   (gapless).
//! - **Renderer** (render thread) copies ring bytes to the [`Output`]. It never
//!   allocates or locks after its first prefill; position comes from the frames
//!   the device actually played.
//!
//! [`AudioEngine::spawn`] runs the three on their own threads. Tests drive the
//! same pieces on one thread through [`ManualEngine`] with a manual clock.

use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::mpsc::{self, Receiver, RecvTimeoutError, Sender, SyncSender, TryRecvError};
use std::sync::Arc;
use std::thread::JoinHandle;
use std::time::{Duration, Instant};

use rtrb::{Consumer, Producer, RingBuffer};

use super::convert::Converter;
use super::decoder::{DecodeError, Decoder, SourceFormat};
use super::format::{negotiate, DeviceCaps, Negotiated, OutputMode, Policy, RateMismatch, Reason};
use super::output::{Output, OutputError};

/// Seconds of converted audio the feeder keeps ahead of the device.
const RING_SECONDS: usize = 2;
/// A paused engine gives the device back after this long.
pub const RELEASE_AFTER: Duration = Duration::from_secs(30);
/// Control loop period while nothing is due.
const TICK: Duration = Duration::from_millis(250);
/// Control loop period while a track end or gapless join is due, so
/// boundaries are reported (and the next session opened) promptly.
const FAST_TICK: Duration = Duration::from_millis(10);
/// `Position` events are sent at most 4 times a second.
const POSITION_EVERY: Duration = Duration::from_millis(250);
/// Render wait per device period before re-checking commands.
const RENDER_WAIT_MS: u32 = 20;

/// Opens device capabilities (control thread) and outputs (render thread).
/// Outputs are not `Send`, so each is created on the thread that uses it.
pub trait Platform: Send + Sync {
    fn caps(&self, device: Option<&str>) -> Result<Box<dyn DeviceCaps>, OutputError>;
    /// Opens `negotiated`, possibly falling back to shared mode; returns the
    /// path actually used.
    fn open(
        &self,
        device: Option<&str>,
        negotiated: Negotiated,
        volume: f32,
    ) -> Result<(Box<dyn Output>, Negotiated), OutputError>;
}

#[derive(Debug, Clone, PartialEq)]
pub struct Settings {
    /// `None` follows the Windows default output.
    pub device: Option<String>,
    pub mode: OutputMode,
    pub rate_mismatch: RateMismatch,
    pub exclusive_volume: bool,
    /// Play songs at one loudness (where software volume is allowed).
    pub levelling: bool,
}

/// A song's loudness-levelling gain, if it has been measured.
pub type Leveler = Arc<dyn Fn(&Path) -> Option<f32> + Send + Sync>;

impl Default for Settings {
    fn default() -> Self {
        Self {
            device: None,
            mode: OutputMode::Shared,
            rate_mismatch: RateMismatch::Strict,
            exclusive_volume: false,
            levelling: true,
        }
    }
}

#[derive(Debug, Clone, PartialEq)]
pub enum Command {
    Play {
        path: PathBuf,
        start_seconds: f64,
    },
    Pause,
    Resume,
    Seek(f64),
    Stop,
    SetVolume(f32),
    SetNext(Option<PathBuf>),
    SetSettings(Settings),
    /// Give the device back now (the video overlay opened); stays paused.
    Release,
    /// Windows changed its default output; reopen if following the default.
    DefaultDeviceChanged,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PlayState {
    Idle,
    Loading,
    Playing,
    Paused,
    Stopped,
}

impl PlayState {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Idle => "idle",
            Self::Loading => "loading",
            Self::Playing => "playing",
            Self::Paused => "paused",
            Self::Stopped => "stopped",
        }
    }
}

#[derive(Debug, Clone, PartialEq)]
pub enum Event {
    State(PlayState),
    Position {
        seconds: f64,
    },
    TrackStarted {
        path: PathBuf,
        duration: Option<f64>,
        source: SourceFormat,
    },
    TrackEnded {
        path: PathBuf,
    },
    SignalPath {
        source: SourceFormat,
        negotiated: Negotiated,
    },
    /// A new output was opened (first play, format change or new settings).
    DeviceOpened {
        negotiated: Negotiated,
    },
    DeviceReleased,
    Error {
        code: &'static str,
    },
}

/// Worker → control messages, tagged with the session they belong to.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Report {
    /// The next track continues in the same ring at this session frame.
    Joined {
        session: u64,
        at_frame: u64,
    },
    /// The stream ends at this session frame.
    Ended {
        session: u64,
        at_frame: u64,
    },
    DecodeFailed {
        session: u64,
        error: DecodeError,
    },
    DeviceFailed(OutputError),
}

// ---------------------------------------------------------------------------
// Feeder (decoder thread)

/// A next track whose output matches the current one.
pub struct NextTrack {
    decoder: Decoder,
    converter: Converter,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Fill {
    /// The ring is full; try again later.
    Full,
    Joined(u64),
    Ended(u64),
    /// Everything was pushed and the producer dropped.
    Done,
}

pub struct Feeder {
    session: u64,
    decoder: Decoder,
    converter: Converter,
    ring: Option<Producer<u8>>,
    frame: u64,
    pending: Vec<u8>,
    sent: usize,
    pushed: u64,
    next: Option<NextTrack>,
    finished: bool,
}

impl Feeder {
    fn new(session: u64, decoder: Decoder, converter: Converter, ring: Producer<u8>) -> Self {
        let frame = converter.output().bytes_per_frame() as u64;
        Self {
            session,
            decoder,
            converter,
            ring: Some(ring),
            frame,
            pending: Vec::new(),
            sent: 0,
            pushed: 0,
            next: None,
            finished: false,
        }
    }

    fn set_next(&mut self, next: Option<NextTrack>) {
        if !self.finished {
            self.next = next;
        }
    }

    fn set_gain(&mut self, gain: f32) {
        self.converter.set_gain(gain);
        if let Some(next) = self.next.as_mut() {
            next.converter.set_gain(gain);
        }
    }

    fn frame_after_pending(&self) -> u64 {
        (self.pushed + (self.pending.len() - self.sent) as u64) / self.frame
    }

    fn fill(&mut self) -> Result<Fill, DecodeError> {
        loop {
            if self.sent < self.pending.len() {
                let Some(ring) = self.ring.as_mut() else {
                    return Ok(Fill::Done);
                };
                let (pushed, _) = ring.push_partial_slice(&self.pending[self.sent..]);
                self.sent += pushed.len();
                self.pushed += pushed.len() as u64;
                if self.sent < self.pending.len() {
                    return Ok(Fill::Full);
                }
            }
            self.pending.clear();
            self.sent = 0;
            if self.finished {
                // Dropping the producer tells the renderer the stream ended.
                self.ring = None;
                return Ok(Fill::Done);
            }
            match self.decoder.next_block()? {
                Some(block) => self.converter.convert(&block, &mut self.pending),
                None => match self.next.take() {
                    Some(next) => {
                        if !same_source(self.decoder.format(), next.decoder.format()) {
                            self.converter.finish(&mut self.pending);
                            self.converter = next.converter;
                        }
                        self.decoder = next.decoder;
                        return Ok(Fill::Joined(self.frame_after_pending()));
                    }
                    None => {
                        self.converter.finish(&mut self.pending);
                        self.finished = true;
                        return Ok(Fill::Ended(self.frame_after_pending()));
                    }
                },
            }
        }
    }

    /// Fills until the ring is full or the stream is done.
    fn pump(&mut self, report: &mut dyn FnMut(Report)) -> Fill {
        loop {
            match self.fill() {
                Ok(Fill::Joined(at_frame)) => report(Report::Joined {
                    session: self.session,
                    at_frame,
                }),
                Ok(Fill::Ended(at_frame)) => report(Report::Ended {
                    session: self.session,
                    at_frame,
                }),
                Ok(state) => return state,
                Err(error) => {
                    report(Report::DecodeFailed {
                        session: self.session,
                        error,
                    });
                    self.ring = None;
                    self.finished = true;
                    return Fill::Done;
                }
            }
        }
    }
}

/// Same decoded layout, so one converter (and resampler state) continues.
fn same_source(a: &SourceFormat, b: &SourceFormat) -> bool {
    (a.codec, a.sample_rate, a.channels, a.bits_per_sample)
        == (b.codec, b.sample_rate, b.channels, b.bits_per_sample)
}

// ---------------------------------------------------------------------------
// Renderer (render thread)

pub struct Renderer {
    output: Box<dyn Output>,
    exclusive: bool,
    float: bool,
    frame: usize,
    ring: Option<Consumer<u8>>,
    running: bool,
    primed: bool,
    gain: f32,
    scratch: Vec<u8>,
}

impl Renderer {
    fn new(output: Box<dyn Output>, negotiated: &Negotiated) -> Self {
        let format = output.format();
        Self {
            exclusive: negotiated.mode == OutputMode::Exclusive,
            float: format.float,
            frame: format.bytes_per_frame(),
            output,
            ring: None,
            running: false,
            primed: false,
            gain: 1.0,
            scratch: Vec::new(),
        }
    }

    fn begin(&mut self, ring: Consumer<u8>, running: bool, gain: f32) -> Result<(), OutputError> {
        self.output.flush()?;
        self.ring = Some(ring);
        self.running = running;
        self.primed = false;
        self.gain = gain;
        Ok(())
    }

    fn end(&mut self) -> Result<(), OutputError> {
        self.ring = None;
        self.primed = false;
        self.running = false;
        self.output.flush()
    }

    fn pause(&mut self) -> Result<(), OutputError> {
        if self.running {
            self.running = false;
            if self.primed {
                self.output.pause()?;
            }
        }
        Ok(())
    }

    fn resume(&mut self) -> Result<(), OutputError> {
        if !self.running {
            self.running = true;
            if self.primed {
                self.output.start()?;
            }
        }
        Ok(())
    }

    fn played(&mut self) -> Result<u64, OutputError> {
        self.output.position_frames()
    }

    /// Whether the renderer is waiting on the device clock (rather than on
    /// the feeder or a command).
    fn is_active(&self) -> bool {
        self.ring.is_some() && self.running && self.primed
    }

    /// One device period: wait for space, copy what the ring has. Before the
    /// stream starts it prefills a whole buffer (or the whole short track).
    /// Returns whether anything was written.
    fn render(&mut self, timeout_ms: u32) -> Result<bool, OutputError> {
        let Some(ring) = self.ring.as_mut() else {
            return Ok(false);
        };
        if !self.running {
            return Ok(false);
        }
        let available = ring.slots() / self.frame;
        let finished = ring.is_abandoned();
        let space = if self.primed {
            self.output.wait(timeout_ms)?
        } else {
            let space = self.output.wait(0)?;
            if available < space && !finished {
                return Ok(false);
            }
            self.scratch.reserve(space * self.frame);
            space
        };
        if space == 0 {
            return Ok(false);
        }
        let frames = available.min(space);
        // Exclusive mode must write every period (an empty write is a buffer
        // of silence); shared mode simply skips.
        if frames > 0 || self.exclusive {
            let chunk = ring
                .read_chunk(frames * self.frame)
                .expect("available counts readable slots");
            let (first, second) = chunk.as_slices();
            let scale = self.float && self.gain != 1.0;
            if second.is_empty() && !scale {
                self.output.write(first)?;
            } else {
                self.scratch.clear();
                self.scratch.extend_from_slice(first);
                self.scratch.extend_from_slice(second);
                if scale {
                    apply_gain_f32(&mut self.scratch, self.gain);
                }
                self.output.write(&self.scratch)?;
            }
            chunk.commit_all();
        }
        if !self.primed {
            self.primed = true;
            self.output.start()?;
        }
        Ok(frames > 0)
    }
}

/// Scales little-endian `f32` samples in place (shared-mode volume, applied
/// at the device so slider changes are heard at once, not after the ring).
fn apply_gain_f32(bytes: &mut [u8], gain: f32) {
    for sample in bytes.chunks_exact_mut(4) {
        let value = f32::from_le_bytes([sample[0], sample[1], sample[2], sample[3]]) * gain;
        sample.copy_from_slice(&value.to_le_bytes());
    }
}

/// Where the software volume is applied: at the renderer for float outputs
/// (instant), else in the converter (exclusive integer output with the
/// opt-in exclusive volume).
/// A levelled track is never bit-perfect; its signal path says why.
fn apply_level(negotiated: &mut Negotiated, level: f32) {
    if level != 1.0 && negotiated.bit_perfect {
        negotiated.bit_perfect = false;
        negotiated.reason = Some(Reason::VolumeLevelling);
    }
}

fn split_gain(negotiated: &Negotiated) -> (f32, f32) {
    if negotiated.output.float {
        (1.0, negotiated.gain)
    } else {
        (negotiated.gain, 1.0)
    }
}

// ---------------------------------------------------------------------------
// Workers: where the feeder and renderer run.

/// Registers the calling thread with MMCSS as a "Pro Audio" task. Best
/// effort: without the service the thread just keeps normal priority.
fn boost_render_thread() {
    #[cfg(windows)]
    unsafe {
        let mut task_index = 0u32;
        let _ = windows::Win32::System::Threading::AvSetMmThreadCharacteristicsW(
            windows::core::w!("Pro Audio"),
            &mut task_index,
        );
    }
}

pub struct Session {
    id: u64,
    feeder: Feeder,
    ring: Consumer<u8>,
    running: bool,
    render_gain: f32,
}

trait Workers {
    /// Opens an output, replacing any open one (render side).
    fn open(
        &mut self,
        device: Option<&str>,
        negotiated: Negotiated,
        volume: f32,
    ) -> Result<Negotiated, OutputError>;
    /// Drops the session and the output.
    fn close(&mut self);
    /// Flushes the output and starts a new session.
    fn start(&mut self, session: Session);
    /// Drops the session, keeping the output open.
    fn stop_session(&mut self);
    fn set_next(&mut self, next: Option<NextTrack>);
    fn pause(&mut self);
    fn resume(&mut self);
    fn set_gain(&mut self, converter: f32, render: f32);
    /// Frames played in `session`, or `None` until the renderer has begun it.
    fn played(&mut self, session: u64) -> Option<u64>;
}

/// Runs the feeder and renderer inline, one step per [`ManualEngine::pump`].
#[derive(Default)]
struct InlineWorkers {
    platform: Option<Arc<dyn Platform>>,
    feeder: Option<Feeder>,
    renderer: Option<Renderer>,
    session: u64,
    reports: Vec<Report>,
}

impl InlineWorkers {
    fn fail(&mut self, error: OutputError) {
        self.renderer = None;
        self.feeder = None;
        self.reports.push(Report::DeviceFailed(error));
    }

    fn step(&mut self) {
        if let Some(feeder) = self.feeder.as_mut() {
            let reports = &mut self.reports;
            if feeder.pump(&mut |report| reports.push(report)) == Fill::Done {
                self.feeder = None;
            }
        }
        if let Some(renderer) = self.renderer.as_mut() {
            if let Err(error) = renderer.render(0) {
                self.fail(error);
            }
        }
    }
}

impl Workers for InlineWorkers {
    fn open(
        &mut self,
        device: Option<&str>,
        negotiated: Negotiated,
        volume: f32,
    ) -> Result<Negotiated, OutputError> {
        self.renderer = None;
        let platform = self.platform.as_ref().expect("platform set");
        let (output, actual) = platform.open(device, negotiated, volume)?;
        self.renderer = Some(Renderer::new(output, &actual));
        Ok(actual)
    }

    fn close(&mut self) {
        self.feeder = None;
        self.renderer = None;
    }

    fn start(&mut self, session: Session) {
        self.feeder = Some(session.feeder);
        self.session = session.id;
        if let Some(renderer) = self.renderer.as_mut() {
            if let Err(error) = renderer.begin(session.ring, session.running, session.render_gain) {
                self.fail(error);
            }
        }
    }

    fn stop_session(&mut self) {
        self.feeder = None;
        if let Some(renderer) = self.renderer.as_mut() {
            if let Err(error) = renderer.end() {
                self.fail(error);
            }
        }
    }

    fn set_next(&mut self, next: Option<NextTrack>) {
        if let Some(feeder) = self.feeder.as_mut() {
            feeder.set_next(next);
        }
    }

    fn pause(&mut self) {
        if let Some(Err(error)) = self.renderer.as_mut().map(Renderer::pause) {
            self.fail(error);
        }
    }

    fn resume(&mut self) {
        if let Some(Err(error)) = self.renderer.as_mut().map(Renderer::resume) {
            self.fail(error);
        }
    }

    fn set_gain(&mut self, converter: f32, render: f32) {
        if let Some(feeder) = self.feeder.as_mut() {
            feeder.set_gain(converter);
        }
        if let Some(renderer) = self.renderer.as_mut() {
            renderer.gain = render;
        }
    }

    fn played(&mut self, session: u64) -> Option<u64> {
        if session != self.session {
            return None;
        }
        match self.renderer.as_mut()?.played() {
            Ok(played) => Some(played),
            Err(error) => {
                self.fail(error);
                None
            }
        }
    }
}

// ---------------------------------------------------------------------------
// Control

#[derive(Debug, Clone)]
struct Track {
    path: PathBuf,
    source: SourceFormat,
    /// Loudness-levelling gain in use for this track (1.0 = none).
    level: f32,
    /// What negotiation asked for (the open key) and what is in use.
    requested: Negotiated,
}

struct Current {
    track: Track,
    /// Session frame where this track starts.
    start_frame: u64,
    /// Track position (seconds) at `start_frame`.
    offset: f64,
}

/// The control state machine, generic over where the workers run.
struct Engine<W: Workers> {
    platform: Arc<dyn Platform>,
    workers: W,
    settings: Settings,
    volume: f32,
    leveler: Leveler,
    caps: Option<Box<dyn DeviceCaps>>,
    /// Requested and actual negotiation of the open output.
    open: Option<(Negotiated, Negotiated)>,
    state: PlayState,
    session: u64,
    current: Option<Current>,
    next_path: Option<PathBuf>,
    /// The next track, once negotiated: `true` when handed to the feeder.
    next: Option<(Track, bool)>,
    joined_at: Option<(Track, u64)>,
    ended_at: Option<u64>,
    paused_at: Option<Instant>,
    /// Where to resume after the device was released while paused.
    released_at: Option<f64>,
    /// Last `Position` sent and when.
    last_position: Option<(f64, Instant)>,
    events: Vec<Event>,
}

impl<W: Workers> Engine<W> {
    fn new(platform: Arc<dyn Platform>, workers: W, settings: Settings, volume: f32) -> Self {
        Self {
            platform,
            workers,
            settings,
            volume: volume.clamp(0.0, 1.0),
            leveler: Arc::new(|_| None),
            caps: None,
            open: None,
            state: PlayState::Idle,
            session: 0,
            current: None,
            next_path: None,
            next: None,
            joined_at: None,
            ended_at: None,
            paused_at: None,
            released_at: None,
            last_position: None,
            events: Vec::new(),
        }
    }

    /// The levelling gain for `path` on `actual`: none when levelling is off
    /// or software volume is not allowed (bit-perfect exclusive stays exact).
    fn level_for(&self, path: &Path, actual: &Negotiated) -> f32 {
        let allowed = actual.mode == OutputMode::Shared || self.settings.exclusive_volume;
        if !self.settings.levelling || !allowed {
            return 1.0;
        }
        (self.leveler)(path)
            .filter(|gain| gain.is_finite() && *gain > 0.0)
            .unwrap_or(1.0)
    }

    fn policy(&self) -> Policy {
        Policy {
            mode: self.settings.mode,
            rate_mismatch: self.settings.rate_mismatch,
            volume: self.volume,
            exclusive_volume: self.settings.exclusive_volume,
        }
    }

    fn set_state(&mut self, state: PlayState) {
        if self.state != state {
            self.state = state;
            self.events.push(Event::State(state));
        }
    }

    fn error(&mut self, code: &'static str) {
        self.events.push(Event::Error { code });
    }

    fn caps(&mut self) -> Result<&dyn DeviceCaps, OutputError> {
        if self.caps.is_none() {
            self.caps = Some(self.platform.caps(self.settings.device.as_deref())?);
        }
        Ok(self.caps.as_deref().expect("just set"))
    }

    fn bluetooth(&mut self) -> bool {
        self.caps().map(|caps| caps.is_bluetooth()).unwrap_or(false)
    }

    fn handle(&mut self, command: Command, now: Instant) {
        match command {
            Command::Play {
                path,
                start_seconds,
            } => {
                self.next = None;
                self.play(&path, start_seconds, true);
            }
            Command::Pause => self.pause(now),
            Command::Resume => self.resume(),
            Command::Seek(seconds) => self.seek(seconds),
            Command::Stop => self.stop(PlayState::Stopped),
            Command::SetVolume(volume) => self.set_volume(volume),
            Command::SetNext(path) => {
                self.next_path = path;
                self.next = None;
                self.workers.set_next(None);
                self.offer_next();
            }
            Command::SetSettings(settings) => self.set_settings(settings),
            Command::DefaultDeviceChanged => {
                if self.settings.device.is_none() {
                    self.caps = None;
                    self.reopen();
                }
            }
            Command::Release => {
                if self.state == PlayState::Playing {
                    self.pause(now);
                }
                self.release();
            }
        }
    }

    fn open_track(&mut self, path: &Path) -> Result<(Decoder, Track), &'static str> {
        let decoder = Decoder::open(path).map_err(|error| decode_code(error))?;
        let source = decoder.format().clone();
        let policy = self.policy();
        let requested = negotiate(&source, self.caps().map_err(|e| e.code())?, &policy);
        Ok((
            decoder,
            Track {
                path: path.to_path_buf(),
                source,
                level: 1.0,
                requested,
            },
        ))
    }

    /// Ensures the output for `requested` is open; returns what is in use.
    fn ensure_output(&mut self, requested: Negotiated) -> Result<Negotiated, OutputError> {
        if let Some((open_requested, actual)) = self.open {
            if same_output(&open_requested, &requested) {
                return Ok(Negotiated {
                    gain: requested.gain,
                    ..actual
                });
            }
        }
        self.open = None;
        let actual = self
            .workers
            .open(self.settings.device.as_deref(), requested, self.volume)?;
        self.open = Some((requested, actual));
        self.events.push(Event::DeviceOpened { negotiated: actual });
        Ok(actual)
    }

    /// Starts a session for `path` at `start_seconds`, announcing a new track.
    fn play(&mut self, path: &Path, start_seconds: f64, running: bool) {
        self.start(path, start_seconds, running, Announce::Track);
    }

    fn start(&mut self, path: &Path, start_seconds: f64, running: bool, announce: Announce) {
        if announce == Announce::Track {
            self.set_state(PlayState::Loading);
        }
        self.reset_session();
        let (mut decoder, track) = match self.open_track(path) {
            Ok(opened) => opened,
            Err(code) => return self.fail(code),
        };
        let offset = match decoder.seek(start_seconds) {
            Ok(frame) => frame as f64 / f64::from(track.source.sample_rate),
            Err(error) => return self.fail(decode_code(error)),
        };
        let mut actual = match self.ensure_output(track.requested) {
            Ok(actual) => actual,
            Err(error) => {
                self.caps = None;
                return self.fail(error.code());
            }
        };
        let policy = self.policy();
        let bluetooth = self.bluetooth();
        actual.apply_volume(&track.source, &policy, bluetooth);
        let mut track = track;
        track.level = self.level_for(&track.path, &actual);
        apply_level(&mut actual, track.level);
        let (converter_gain, render_gain) = split_gain(&actual);
        let mut converter = Converter::new(&track.source, &actual);
        converter.set_gain(converter_gain);
        converter.set_level(track.level);
        converter.set_bluetooth(bluetooth);
        let format = actual.output;
        let capacity = (format.rate as usize * RING_SECONDS).max(1) * format.bytes_per_frame();
        let (producer, consumer) = RingBuffer::new(capacity);
        self.session += 1;
        let mut feeder = Feeder::new(self.session, decoder, converter, producer);
        let source = track.source.clone();
        self.open = self.open.map(|(requested, _)| (requested, actual));
        self.current = Some(Current {
            track,
            start_frame: 0,
            offset,
        });
        // The next track travels with the session: sent separately, a short
        // track could be fully decoded before it arrived.
        feeder.set_next(self.prepare_next());
        self.workers.start(Session {
            id: self.session,
            feeder,
            ring: consumer,
            running,
            render_gain,
        });
        let track = &self.current.as_ref().expect("just set").track;
        if announce == Announce::Track {
            self.events.push(Event::TrackStarted {
                path: track.path.clone(),
                duration: duration(&track.source),
                source: track.source.clone(),
            });
        }
        if announce != Announce::Quiet {
            self.events.push(Event::SignalPath {
                source,
                negotiated: actual,
            });
        }
        self.last_position = None;
        self.set_state(if running {
            PlayState::Playing
        } else {
            PlayState::Paused
        });
    }

    fn reset_session(&mut self) {
        self.joined_at = None;
        self.ended_at = None;
        self.released_at = None;
    }

    fn fail(&mut self, code: &'static str) {
        self.error(code);
        self.stop(PlayState::Stopped);
    }

    /// Hands the queued next track to the running feeder.
    fn offer_next(&mut self) {
        if let Some(next) = self.prepare_next() {
            self.workers.set_next(Some(next));
        }
    }

    /// Opens and negotiates the queued next track. Returns it for the feeder
    /// when it can join gaplessly (same output); otherwise it waits in
    /// `self.next` for a new session after this one ends.
    fn prepare_next(&mut self) -> Option<NextTrack> {
        if self.next.is_some() || self.ended_at.is_some() {
            return None;
        }
        let (Some(path), Some(current)) = (self.next_path.clone(), self.current.as_ref()) else {
            return None;
        };
        let current_requested = current.track.requested;
        let (decoder, track) = match self.open_track(&path) {
            Ok(opened) => opened,
            Err(code) => {
                self.error(code);
                self.next_path = None;
                return None;
            }
        };
        if !same_output(&current_requested, &track.requested) {
            self.next = Some((track, false));
            return None;
        }
        let (_, mut actual) = self.open?;
        let policy = self.policy();
        let bluetooth = self.bluetooth();
        actual.apply_volume(&track.source, &policy, bluetooth);
        let mut track = track;
        track.level = self.level_for(&track.path, &actual);
        apply_level(&mut actual, track.level);
        let mut converter = Converter::new(&track.source, &actual);
        converter.set_gain(split_gain(&actual).0);
        converter.set_level(track.level);
        converter.set_bluetooth(bluetooth);
        self.next = Some((track, true));
        Some(NextTrack { decoder, converter })
    }

    fn pause(&mut self, now: Instant) {
        if self.state == PlayState::Playing {
            self.workers.pause();
            self.paused_at = Some(now);
            self.set_state(PlayState::Paused);
            // Exclusive mode silences every other app: give the device back
            // at once, so browsers and other players can open it while paused.
            if self
                .open
                .is_some_and(|(_, actual)| actual.mode == OutputMode::Exclusive)
            {
                self.release();
            }
        }
    }

    fn resume(&mut self) {
        if self.state != PlayState::Paused {
            return;
        }
        self.paused_at = None;
        if let Some(seconds) = self.released_at {
            let path = self.current.as_ref().map(|c| c.track.path.clone());
            if let Some(path) = path {
                self.start(&path, seconds, true, Announce::SignalPath);
            }
            return;
        }
        self.workers.resume();
        self.set_state(PlayState::Playing);
    }

    fn seek(&mut self, seconds: f64) {
        let Some(path) = self.current.as_ref().map(|c| c.track.path.clone()) else {
            return;
        };
        let running = self.state == PlayState::Playing;
        if !running && self.released_at.is_some() {
            // Stay released; resume opens the device at the new position.
            self.released_at = Some(seconds.max(0.0));
            return;
        }
        let paused_at = self.paused_at;
        self.next = None;
        self.start(&path, seconds, running, Announce::Quiet);
        self.paused_at = if running { None } else { paused_at };
    }

    fn stop(&mut self, state: PlayState) {
        self.workers.close();
        if self.open.take().is_some() {
            self.events.push(Event::DeviceReleased);
        }
        self.current = None;
        self.next = None;
        self.paused_at = None;
        self.reset_session();
        self.set_state(state);
    }

    /// Closes the device but keeps the paused track and position.
    fn release(&mut self) {
        if self.state != PlayState::Paused || self.released_at.is_some() {
            return;
        }
        let position = self.position().unwrap_or(0.0);
        self.workers.close();
        self.open = None;
        self.next = None;
        self.joined_at = None;
        self.ended_at = None;
        self.released_at = Some(position);
        self.events.push(Event::DeviceReleased);
    }

    fn set_volume(&mut self, volume: f32) {
        self.volume = volume.clamp(0.0, 1.0);
        let Some(current) = self.current.as_ref() else {
            return;
        };
        let source = current.track.source.clone();
        let Some((requested, mut actual)) = self.open else {
            return;
        };
        let before = actual;
        let level = current.track.level;
        let policy = self.policy();
        let bluetooth = self.bluetooth();
        actual.apply_volume(&source, &policy, bluetooth);
        apply_level(&mut actual, level);
        self.open = Some((requested, actual));
        let (converter, render) = split_gain(&actual);
        self.workers.set_gain(converter, render);
        if (before.bit_perfect, before.reason) != (actual.bit_perfect, actual.reason) {
            self.events.push(Event::SignalPath {
                source,
                negotiated: actual,
            });
        }
    }

    fn set_settings(&mut self, settings: Settings) {
        if settings == self.settings {
            return;
        }
        if settings.device != self.settings.device {
            self.caps = None;
        }
        self.settings = settings;
        self.reopen();
    }

    /// Reopens the output (new settings or device) at the same position. A
    /// released (long-paused) engine stays released; resume opens the device.
    fn reopen(&mut self) {
        if self.released_at.is_some() {
            return;
        }
        let resume = match self.state {
            PlayState::Playing | PlayState::Paused => self
                .current
                .as_ref()
                .map(|c| (c.track.path.clone(), self.state == PlayState::Playing)),
            _ => None,
        };
        // Reopen with the new settings at the same position.
        let position = self.released_at.or_else(|| self.position());
        self.workers.close();
        self.open = None;
        self.next = None;
        if let Some((path, running)) = resume {
            self.start(
                &path,
                position.unwrap_or(0.0),
                running,
                Announce::SignalPath,
            );
        }
    }

    fn position(&mut self) -> Option<f64> {
        if let Some(seconds) = self.released_at {
            return Some(seconds);
        }
        let current = self.current.as_ref()?;
        let rate = self.open.map(|(_, actual)| actual.output.rate)?;
        let start = current.start_frame;
        let offset = current.offset;
        let played = self.workers.played(self.session)?;
        Some(offset + played.saturating_sub(start) as f64 / f64::from(rate))
    }

    fn report(&mut self, report: Report) {
        match report {
            Report::Joined { session, at_frame } if session == self.session => {
                if let Some((track, true)) = self.next.take() {
                    self.joined_at = Some((track, at_frame));
                }
            }
            Report::Ended { session, at_frame } if session == self.session => {
                self.ended_at = Some(at_frame);
            }
            Report::DecodeFailed { session, error } if session == self.session => {
                self.fail(decode_code(error))
            }
            Report::DeviceFailed(error) => {
                self.caps = None;
                self.fail(error.code());
            }
            _ => {}
        }
    }

    fn boundary_due(&self) -> bool {
        self.state == PlayState::Playing && (self.ended_at.is_some() || self.joined_at.is_some())
    }

    /// Advances track boundaries, end of stream, position and the release
    /// timer from the device clock.
    fn tick(&mut self, now: Instant) {
        if let Some(paused_at) = self.paused_at {
            if now.duration_since(paused_at) >= RELEASE_AFTER {
                self.release();
            }
        }
        if self.state != PlayState::Playing {
            return;
        }
        let Some(played) = self.workers.played(self.session) else {
            return;
        };
        if let Some((_, at_frame)) = self.joined_at {
            if played >= at_frame {
                let (track, at_frame) = self.joined_at.take().expect("checked");
                self.advance(track, at_frame);
            }
        }
        if let Some(at_frame) = self.ended_at {
            if played >= at_frame {
                self.finish_track();
                return;
            }
        }
        if let Some(seconds) = self.position() {
            let due = self.last_position.map_or(true, |(last, at)| {
                last != seconds && now.duration_since(at) >= POSITION_EVERY
            });
            if due {
                self.last_position = Some((seconds, now));
                self.events.push(Event::Position { seconds });
            }
        }
    }

    /// The gapless join reached the speakers.
    fn advance(&mut self, track: Track, at_frame: u64) {
        if let Some(current) = self.current.take() {
            self.events.push(Event::TrackEnded {
                path: current.track.path,
            });
        }
        let mut actual = self.open.map(|(_, actual)| actual).expect("output open");
        let policy = self.policy();
        let bluetooth = self.bluetooth();
        actual.apply_volume(&track.source, &policy, bluetooth);
        self.events.push(Event::TrackStarted {
            path: track.path.clone(),
            duration: duration(&track.source),
            source: track.source.clone(),
        });
        self.events.push(Event::SignalPath {
            source: track.source.clone(),
            negotiated: actual,
        });
        self.current = Some(Current {
            track,
            start_frame: at_frame,
            offset: 0.0,
        });
        self.next_path = None;
        self.last_position = None;
    }

    /// The last frame played: start the queued track, or go idle.
    fn finish_track(&mut self) {
        if let Some(current) = self.current.take() {
            self.events.push(Event::TrackEnded {
                path: current.track.path,
            });
        }
        self.ended_at = None;
        let next = self.next.take().map(|(track, _)| track.path);
        match next.or_else(|| self.next_path.take()) {
            Some(path) => {
                self.next_path = None;
                self.workers.stop_session();
                self.play(&path, 0.0, true);
            }
            None => self.stop(PlayState::Idle),
        }
    }
}

/// What a new session tells the UI.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Announce {
    /// A new track: loading, `TrackStarted`, `SignalPath`.
    Track,
    /// Same track on a reopened output (settings, device, resume after
    /// release): only the new `SignalPath`.
    SignalPath,
    /// Same track and output (seek).
    Quiet,
}

fn same_output(a: &Negotiated, b: &Negotiated) -> bool {
    (a.mode, a.output) == (b.mode, b.output)
}

fn duration(source: &SourceFormat) -> Option<f64> {
    source
        .total_frames
        .map(|frames| frames as f64 / f64::from(source.sample_rate))
}

fn decode_code(error: DecodeError) -> &'static str {
    match error {
        DecodeError::Io => "audio_io",
        DecodeError::Unsupported => "audio_format_unsupported",
        DecodeError::Corrupt => "audio_decode_failed",
    }
}

// ---------------------------------------------------------------------------
// Single-threaded driver (tests)

/// The engine on one thread: commands run immediately; [`ManualEngine::pump`]
/// runs one feeder fill, one render period and one control tick.
pub struct ManualEngine {
    engine: Engine<InlineWorkers>,
}

impl ManualEngine {
    /// Songs play at the gains `leveler` reports (see `loudness.rs`).
    pub fn with_leveler(mut self, leveler: Leveler) -> Self {
        self.engine.leveler = leveler;
        self
    }

    pub fn new(platform: Arc<dyn Platform>, settings: Settings, volume: f32) -> Self {
        let workers = InlineWorkers {
            platform: Some(platform.clone()),
            ..InlineWorkers::default()
        };
        Self {
            engine: Engine::new(platform, workers, settings, volume),
        }
    }

    pub fn handle(&mut self, command: Command, now: Instant) {
        self.engine.handle(command, now);
        self.drain_reports();
    }

    pub fn pump(&mut self, now: Instant) {
        self.engine.workers.step();
        self.drain_reports();
        self.engine.tick(now);
        self.drain_reports();
    }

    fn drain_reports(&mut self) {
        while !self.engine.workers.reports.is_empty() {
            let reports = std::mem::take(&mut self.engine.workers.reports);
            for report in reports {
                self.engine.report(report);
            }
        }
    }

    pub fn state(&self) -> PlayState {
        self.engine.state
    }

    pub fn position(&mut self) -> Option<f64> {
        self.engine.position()
    }

    pub fn take_events(&mut self) -> Vec<Event> {
        std::mem::take(&mut self.engine.events)
    }
}

// ---------------------------------------------------------------------------
// Threaded driver

enum Message {
    Command(Command),
    Report(Report),
    Shutdown,
}

enum FeedCommand {
    Start(Feeder),
    Stop,
    SetNext(Option<NextTrack>),
    SetGain(f32),
    Shutdown,
}

enum RenderCommand {
    Open {
        device: Option<String>,
        negotiated: Negotiated,
        volume: f32,
        reply: SyncSender<Result<Negotiated, OutputError>>,
    },
    Close,
    Begin {
        session: u64,
        ring: Consumer<u8>,
        running: bool,
        gain: f32,
    },
    End,
    Pause,
    Resume,
    SetGain(f32),
    Shutdown,
}

/// Session id (top 16 bits) and frames played (low 48 bits) in one atomic,
/// so control never pairs a new session with the old session's position.
const SESSION_SHIFT: u32 = 48;
const FRAME_MASK: u64 = (1 << SESSION_SHIFT) - 1;

fn pack_played(session: u64, frames: u64) -> u64 {
    (session << SESSION_SHIFT) | (frames & FRAME_MASK)
}

struct ThreadWorkers {
    feed: Sender<FeedCommand>,
    render: Sender<RenderCommand>,
    played: Arc<AtomicU64>,
}

impl Workers for ThreadWorkers {
    fn open(
        &mut self,
        device: Option<&str>,
        negotiated: Negotiated,
        volume: f32,
    ) -> Result<Negotiated, OutputError> {
        let (reply, answer) = mpsc::sync_channel(1);
        self.render
            .send(RenderCommand::Open {
                device: device.map(str::to_owned),
                negotiated,
                volume,
                reply,
            })
            .map_err(|_| OutputError::Unavailable)?;
        answer
            .recv_timeout(Duration::from_secs(10))
            .unwrap_or(Err(OutputError::Unavailable))
    }

    fn close(&mut self) {
        let _ = self.feed.send(FeedCommand::Stop);
        let _ = self.render.send(RenderCommand::Close);
    }

    fn start(&mut self, session: Session) {
        let _ = self.feed.send(FeedCommand::Start(session.feeder));
        let _ = self.render.send(RenderCommand::Begin {
            session: session.id,
            ring: session.ring,
            running: session.running,
            gain: session.render_gain,
        });
    }

    fn stop_session(&mut self) {
        let _ = self.feed.send(FeedCommand::Stop);
        let _ = self.render.send(RenderCommand::End);
    }

    fn set_next(&mut self, next: Option<NextTrack>) {
        let _ = self.feed.send(FeedCommand::SetNext(next));
    }

    fn pause(&mut self) {
        let _ = self.render.send(RenderCommand::Pause);
    }

    fn resume(&mut self) {
        let _ = self.render.send(RenderCommand::Resume);
    }

    fn set_gain(&mut self, converter: f32, render: f32) {
        let _ = self.feed.send(FeedCommand::SetGain(converter));
        let _ = self.render.send(RenderCommand::SetGain(render));
    }

    fn played(&mut self, session: u64) -> Option<u64> {
        let packed = self.played.load(Ordering::Acquire);
        (packed >> SESSION_SHIFT == session & 0xFFFF).then_some(packed & FRAME_MASK)
    }
}

/// Handle to the threaded engine. Dropping it shuts the threads down.
pub struct AudioEngine {
    commands: Sender<Message>,
    threads: Vec<JoinHandle<()>>,
}

impl AudioEngine {
    pub fn spawn(
        platform: Arc<dyn Platform>,
        settings: Settings,
        volume: f32,
        leveler: Leveler,
        mut on_event: impl FnMut(Event) + Send + 'static,
    ) -> std::io::Result<Self> {
        let (commands, inbox) = mpsc::channel::<Message>();
        let (feed, feed_inbox) = mpsc::channel();
        let (render, render_inbox) = mpsc::channel();
        let played = Arc::new(AtomicU64::new(0));

        let reports = commands.clone();
        let feeder = std::thread::Builder::new()
            .name("qtmedia-audio-decode".into())
            .spawn(move || feed_loop(feed_inbox, reports))?;

        let reports = commands.clone();
        let render_platform = platform.clone();
        let render_played = played.clone();
        let renderer = std::thread::Builder::new()
            .name("qtmedia-audio-render".into())
            .spawn(move || {
                // Windows schedules "Pro Audio" threads ahead of normal work, so
                // a busy CPU (ffmpeg, covers, a 4K remux) cannot starve output.
                boost_render_thread();
                render_loop(render_platform, render_inbox, reports, render_played)
            })?;

        let control = std::thread::Builder::new()
            .name("qtmedia-audio-control".into())
            .spawn(move || {
                let workers = ThreadWorkers {
                    feed: feed.clone(),
                    render: render.clone(),
                    played,
                };
                let mut engine = Engine::new(platform, workers, settings, volume);
                engine.leveler = leveler;
                loop {
                    let wait = if engine.boundary_due() {
                        FAST_TICK
                    } else {
                        TICK
                    };
                    match inbox.recv_timeout(wait) {
                        Ok(Message::Command(command)) => engine.handle(command, Instant::now()),
                        Ok(Message::Report(report)) => engine.report(report),
                        Ok(Message::Shutdown) | Err(RecvTimeoutError::Disconnected) => break,
                        Err(RecvTimeoutError::Timeout) => {}
                    }
                    engine.tick(Instant::now());
                    for event in engine.events.drain(..) {
                        on_event(event);
                    }
                }
                engine.stop(PlayState::Stopped);
                let _ = feed.send(FeedCommand::Shutdown);
                let _ = render.send(RenderCommand::Shutdown);
            })?;

        Ok(Self {
            commands,
            threads: vec![control, feeder, renderer],
        })
    }

    pub fn send(&self, command: Command) {
        let _ = self.commands.send(Message::Command(command));
    }

    /// A cloneable handle for other threads (e.g. the device watcher).
    pub fn sender(&self) -> EngineSender {
        EngineSender(self.commands.clone())
    }
}

/// Sends commands to a running [`AudioEngine`]; a no-op once it has stopped.
#[derive(Clone)]
pub struct EngineSender(Sender<Message>);

impl EngineSender {
    pub fn send(&self, command: Command) {
        let _ = self.0.send(Message::Command(command));
    }
}

impl Drop for AudioEngine {
    fn drop(&mut self) {
        let _ = self.commands.send(Message::Shutdown);
        for thread in self.threads.drain(..) {
            let _ = thread.join();
        }
    }
}

fn feed_loop(inbox: Receiver<FeedCommand>, reports: Sender<Message>) {
    let mut feeder: Option<Feeder> = None;
    let mut full = false;
    loop {
        let command = if feeder.is_none() {
            match inbox.recv() {
                Ok(command) => Some(command),
                Err(_) => return,
            }
        } else if full {
            match inbox.recv_timeout(Duration::from_millis(10)) {
                Ok(command) => Some(command),
                Err(RecvTimeoutError::Timeout) => None,
                Err(RecvTimeoutError::Disconnected) => return,
            }
        } else {
            match inbox.try_recv() {
                Ok(command) => Some(command),
                Err(TryRecvError::Empty) => None,
                Err(TryRecvError::Disconnected) => return,
            }
        };
        match command {
            None => {}
            Some(FeedCommand::Shutdown) => return,
            Some(FeedCommand::Start(next)) => feeder = Some(next),
            Some(FeedCommand::Stop) => feeder = None,
            Some(FeedCommand::SetNext(next)) => {
                if let Some(feeder) = feeder.as_mut() {
                    feeder.set_next(next);
                }
            }
            Some(FeedCommand::SetGain(gain)) => {
                if let Some(feeder) = feeder.as_mut() {
                    feeder.set_gain(gain);
                }
            }
        }
        if let Some(active) = feeder.as_mut() {
            let state = active.pump(&mut |report| {
                let _ = reports.send(Message::Report(report));
            });
            full = state == Fill::Full;
            if state == Fill::Done {
                feeder = None;
            }
        }
    }
}

fn render_loop(
    platform: Arc<dyn Platform>,
    inbox: Receiver<RenderCommand>,
    reports: Sender<Message>,
    played: Arc<AtomicU64>,
) {
    let mut renderer: Option<Renderer> = None;
    let mut session = 0u64;
    loop {
        // Block for commands unless the device clock is driving the loop.
        let command = match &renderer {
            Some(active) if active.is_active() => match inbox.try_recv() {
                Ok(command) => Some(command),
                Err(TryRecvError::Empty) => None,
                Err(TryRecvError::Disconnected) => return,
            },
            Some(active) if active.ring.is_some() && active.running => {
                // Prefilling: poll the feeder briefly.
                match inbox.recv_timeout(Duration::from_millis(2)) {
                    Ok(command) => Some(command),
                    Err(RecvTimeoutError::Timeout) => None,
                    Err(RecvTimeoutError::Disconnected) => return,
                }
            }
            _ => match inbox.recv() {
                Ok(command) => Some(command),
                Err(_) => return,
            },
        };
        let result = match command {
            None => Ok(()),
            Some(RenderCommand::Shutdown) => return,
            Some(RenderCommand::Open {
                device,
                negotiated,
                volume,
                reply,
            }) => {
                renderer = None;
                let opened = platform.open(device.as_deref(), negotiated, volume);
                let _ = reply.send(match opened {
                    Ok((output, actual)) => {
                        renderer = Some(Renderer::new(output, &actual));
                        Ok(actual)
                    }
                    Err(error) => Err(error),
                });
                Ok(())
            }
            Some(RenderCommand::Close) => {
                renderer = None;
                Ok(())
            }
            Some(RenderCommand::Begin {
                session: id,
                ring,
                running,
                gain,
            }) => match renderer.as_mut() {
                Some(active) => {
                    session = id & 0xFFFF;
                    played.store(pack_played(session, 0), Ordering::Release);
                    active.begin(ring, running, gain)
                }
                None => Ok(()),
            },
            Some(RenderCommand::End) => renderer.as_mut().map_or(Ok(()), Renderer::end),
            Some(RenderCommand::Pause) => renderer.as_mut().map_or(Ok(()), Renderer::pause),
            Some(RenderCommand::Resume) => renderer.as_mut().map_or(Ok(()), Renderer::resume),
            Some(RenderCommand::SetGain(gain)) => {
                if let Some(active) = renderer.as_mut() {
                    active.gain = gain;
                }
                Ok(())
            }
        };
        let result = result.and_then(|()| match renderer.as_mut() {
            Some(active) => {
                active.render(RENDER_WAIT_MS)?;
                if active.ring.is_some() {
                    let frames = active.played()?;
                    played.store(pack_played(session, frames), Ordering::Release);
                }
                Ok(())
            }
            None => Ok(()),
        });
        if let Err(error) = result {
            renderer = None;
            let _ = reports.send(Message::Report(Report::DeviceFailed(error)));
        }
    }
}

// ---------------------------------------------------------------------------
// Production platform

#[cfg(windows)]
pub struct WasapiPlatform;

#[cfg(windows)]
impl Platform for WasapiPlatform {
    fn caps(&self, device: Option<&str>) -> Result<Box<dyn DeviceCaps>, OutputError> {
        Ok(Box::new(super::output::WasapiCaps::open(device)?))
    }

    fn open(
        &self,
        device: Option<&str>,
        negotiated: Negotiated,
        volume: f32,
    ) -> Result<(Box<dyn Output>, Negotiated), OutputError> {
        let caps = super::output::WasapiCaps::open(device)?;
        super::output::open_output(&caps, negotiated, volume)
    }
}
