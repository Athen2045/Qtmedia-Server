//! The threaded driver: the feeder and renderer on their own threads, with
//! control on a third.

use super::*;

// ---------------------------------------------------------------------------
// Threaded driver

enum Message {
    Command(Command),
    Report(Report),
    Shutdown,
}

enum FeedCommand {
    Start(Box<Feeder>),
    Stop,
    SetNext(Option<Box<NextTrack>>),
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
        let _ = self.feed.send(FeedCommand::Start(Box::new(session.feeder)));
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
        let _ = self.feed.send(FeedCommand::SetNext(next.map(Box::new)));
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
            Some(FeedCommand::Start(next)) => feeder = Some(*next),
            Some(FeedCommand::Stop) => feeder = None,
            Some(FeedCommand::SetNext(next)) => {
                if let Some(feeder) = feeder.as_mut() {
                    feeder.set_next(next.map(|next| *next));
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
