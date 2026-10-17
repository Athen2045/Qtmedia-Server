//! The feeder (decoder thread) and renderer (render thread) halves of the
//! playback pipeline.

use super::*;

// ---------------------------------------------------------------------------
// Feeder (decoder thread)

/// A next track whose output matches the current one.
pub struct NextTrack {
    pub(super) decoder: Decoder,
    pub(super) converter: Converter,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(super) enum Fill {
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
    pub(super) fn new(
        session: u64,
        decoder: Decoder,
        converter: Converter,
        ring: Producer<u8>,
    ) -> Self {
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

    pub(super) fn set_next(&mut self, next: Option<NextTrack>) {
        if !self.finished {
            self.next = next;
        }
    }

    pub(super) fn set_gain(&mut self, gain: f32) {
        self.converter.set_gain(gain);
        if let Some(next) = self.next.as_mut() {
            next.converter.set_gain(gain);
        }
    }

    pub(super) fn frame_after_pending(&self) -> u64 {
        (self.pushed + (self.pending.len() - self.sent) as u64) / self.frame
    }

    pub(super) fn fill(&mut self) -> Result<Fill, DecodeError> {
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
    pub(super) fn pump(&mut self, report: &mut dyn FnMut(Report)) -> Fill {
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
pub(super) fn same_source(a: &SourceFormat, b: &SourceFormat) -> bool {
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
    pub(super) ring: Option<Consumer<u8>>,
    pub(super) running: bool,
    primed: bool,
    pub(super) gain: f32,
    scratch: Vec<u8>,
}

impl Renderer {
    pub(super) fn new(output: Box<dyn Output>, negotiated: &Negotiated) -> Self {
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

    pub(super) fn begin(
        &mut self,
        ring: Consumer<u8>,
        running: bool,
        gain: f32,
    ) -> Result<(), OutputError> {
        self.output.flush()?;
        self.ring = Some(ring);
        self.running = running;
        self.primed = false;
        self.gain = gain;
        Ok(())
    }

    pub(super) fn end(&mut self) -> Result<(), OutputError> {
        self.ring = None;
        self.primed = false;
        self.running = false;
        self.output.flush()
    }

    pub(super) fn pause(&mut self) -> Result<(), OutputError> {
        if self.running {
            self.running = false;
            if self.primed {
                self.output.pause()?;
            }
        }
        Ok(())
    }

    pub(super) fn resume(&mut self) -> Result<(), OutputError> {
        if !self.running {
            self.running = true;
            if self.primed {
                self.output.start()?;
            }
        }
        Ok(())
    }

    pub(super) fn played(&mut self) -> Result<u64, OutputError> {
        self.output.position_frames()
    }

    /// Whether the renderer is waiting on the device clock (rather than on
    /// the feeder or a command).
    pub(super) fn is_active(&self) -> bool {
        self.ring.is_some() && self.running && self.primed
    }

    /// One device period: wait for space, copy what the ring has. Before the
    /// stream starts it prefills a whole buffer (or the whole short track).
    /// Returns whether anything was written.
    pub(super) fn render(&mut self, timeout_ms: u32) -> Result<bool, OutputError> {
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
pub(super) fn apply_gain_f32(bytes: &mut [u8], gain: f32) {
    for sample in bytes.chunks_exact_mut(4) {
        let value = f32::from_le_bytes([sample[0], sample[1], sample[2], sample[3]]) * gain;
        sample.copy_from_slice(&value.to_le_bytes());
    }
}

/// Where the software volume is applied: at the renderer for float outputs
/// (instant), else in the converter (exclusive integer output with the
/// opt-in exclusive volume).
/// A levelled track is never bit-perfect; its signal path says why.
pub(super) fn apply_level(negotiated: &mut Negotiated, level: f32) {
    if level != 1.0 && negotiated.bit_perfect {
        negotiated.bit_perfect = false;
        negotiated.reason = Some(Reason::VolumeLevelling);
    }
}

pub(super) fn split_gain(negotiated: &Negotiated) -> (f32, f32) {
    if negotiated.output.float {
        (1.0, negotiated.gain)
    } else {
        (negotiated.gain, 1.0)
    }
}
