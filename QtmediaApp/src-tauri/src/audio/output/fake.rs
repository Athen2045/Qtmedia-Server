//! In-memory [`Output`] for tests: records every byte written (padding
//! included) and plays only when the test advances it with [`FakeOutput::play`].

use super::{Output, OutputError, PositionTracker};
use crate::audio::format::PcmFormat;

pub struct FakeOutput {
    format: PcmFormat,
    buffer_frames: usize,
    exclusive: bool,
    bytes: Vec<u8>,
    queued: usize,
    played: u64,
    started: bool,
    tracker: PositionTracker,
    fail: Option<OutputError>,
}

impl FakeOutput {
    /// Shared-mode semantics: any number of frames up to the free space.
    pub fn shared(format: PcmFormat, buffer_frames: usize) -> Self {
        Self::new(format, buffer_frames, false)
    }

    /// Exclusive event semantics: whole buffers only, short writes padded.
    pub fn exclusive(format: PcmFormat, buffer_frames: usize) -> Self {
        Self::new(format, buffer_frames, true)
    }

    fn new(format: PcmFormat, buffer_frames: usize, exclusive: bool) -> Self {
        Self {
            format,
            buffer_frames,
            exclusive,
            bytes: Vec::new(),
            queued: 0,
            played: 0,
            started: false,
            tracker: PositionTracker::default(),
            fail: None,
        }
    }

    /// Every byte written since open or flush, padding included.
    pub fn bytes(&self) -> &[u8] {
        &self.bytes
    }

    pub fn is_started(&self) -> bool {
        self.started
    }

    pub fn queued_frames(&self) -> usize {
        self.queued
    }

    /// Advances the device clock by up to `frames` (only while started).
    pub fn play(&mut self, frames: usize) {
        if self.started {
            let frames = frames.min(self.queued);
            self.queued -= frames;
            self.played += frames as u64;
        }
    }

    /// Makes the next call fail, e.g. with `OutputError::DeviceLost`.
    pub fn fail_with(&mut self, error: OutputError) {
        self.fail = Some(error);
    }

    fn check(&mut self) -> Result<(), OutputError> {
        match self.fail.take() {
            Some(error) => Err(error),
            None => Ok(()),
        }
    }

    fn space(&self) -> usize {
        if self.exclusive {
            if self.queued == 0 {
                self.buffer_frames
            } else {
                0
            }
        } else {
            self.buffer_frames - self.queued
        }
    }
}

impl Output for FakeOutput {
    fn format(&self) -> PcmFormat {
        self.format
    }

    fn wait(&mut self, _timeout_ms: u32) -> Result<usize, OutputError> {
        self.check()?;
        Ok(self.space())
    }

    fn write(&mut self, bytes: &[u8]) -> Result<usize, OutputError> {
        self.check()?;
        let frame = self.format.bytes_per_frame();
        assert_eq!(bytes.len() % frame, 0, "writes are whole frames");
        let frames = bytes.len() / frame;
        let space = self.space();
        assert!(frames <= space, "wrote {frames} frames into {space}");
        self.bytes.extend_from_slice(bytes);
        let padding = if self.exclusive { space - frames } else { 0 };
        self.bytes.resize(self.bytes.len() + padding * frame, 0);
        self.queued += frames + padding;
        self.tracker.wrote(frames as u64, padding as u64);
        Ok(frames)
    }

    fn start(&mut self) -> Result<(), OutputError> {
        self.check()?;
        self.started = true;
        Ok(())
    }

    fn pause(&mut self) -> Result<(), OutputError> {
        self.check()?;
        self.started = false;
        Ok(())
    }

    fn flush(&mut self) -> Result<(), OutputError> {
        self.check()?;
        self.started = false;
        self.queued = 0;
        self.played = 0;
        self.bytes.clear();
        self.tracker.reset();
        Ok(())
    }

    fn position_frames(&mut self) -> Result<u64, OutputError> {
        self.check()?;
        Ok(self.tracker.real_played(self.played))
    }
}
