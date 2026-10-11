//! WASAPI exclusive, event-driven output (Task 0 rules 1–2): aligned period
//! with Microsoft's realignment retry, whole-buffer writes padded with silence.

use wasapi::{
    calculate_period_100ns, AudioClient, AudioClock, AudioRenderClient, Direction, Handle,
    StreamMode,
};

use super::device::{ensure_com, find_device, from_waveformat, hresult, map_error, to_waveformat};
use super::{Output, OutputError, PositionTracker, AUDCLNT_E_BUFFER_SIZE_NOT_ALIGNED};
use crate::audio::format::PcmFormat;

pub struct WasapiExclusive {
    client: AudioClient,
    render: AudioRenderClient,
    event: Handle,
    clock: AudioClock,
    clock_frequency: u64,
    format: PcmFormat,
    buffer_frames: usize,
    started: bool,
    prefill: bool,
    tracker: PositionTracker,
    staging: Vec<u8>,
}

impl WasapiExclusive {
    /// Opens `device_id` (or the default output) at exactly `format`.
    pub fn open(device_id: Option<&str>, format: PcmFormat) -> Result<Self, OutputError> {
        ensure_com();
        let device = find_device(device_id)?;
        let mut client = device.get_iaudioclient().map_err(map_error)?;
        let wave = client
            .is_supported_exclusive_with_quirks(&to_waveformat(&format))
            .map_err(|_| OutputError::FormatUnsupported)?;
        let (_, min_period) = client.get_device_period().map_err(map_error)?;
        let period = client
            .calculate_aligned_period_near(3 * min_period / 2, Some(128), &wave)
            .map_err(map_error)?;
        let mode = |period_hns| StreamMode::EventsExclusive { period_hns };
        if let Err(error) = client.initialize_client(&wave, &Direction::Render, &mode(period)) {
            if hresult(&error) != Some(AUDCLNT_E_BUFFER_SIZE_NOT_ALIGNED) {
                return Err(map_error(error));
            }
            // The failed client reports the aligned buffer size; retry with it.
            let frames = client.get_buffer_size().map_err(map_error)?;
            let period = calculate_period_100ns(frames.into(), format.rate.into());
            client = device.get_iaudioclient().map_err(map_error)?;
            client
                .initialize_client(&wave, &Direction::Render, &mode(period))
                .map_err(map_error)?;
        }
        let event = client.set_get_eventhandle().map_err(map_error)?;
        let render = client.get_audiorenderclient().map_err(map_error)?;
        let clock = client.get_audioclock().map_err(map_error)?;
        let clock_frequency = clock.get_frequency().map_err(map_error)?;
        let buffer_frames = client.get_buffer_size().map_err(map_error)? as usize;
        Ok(Self {
            client,
            render,
            event,
            clock,
            clock_frequency,
            format: from_waveformat(&wave),
            buffer_frames,
            started: false,
            prefill: true,
            tracker: PositionTracker::default(),
            staging: Vec::with_capacity(buffer_frames * format.bytes_per_frame()),
        })
    }

    pub fn buffer_frames(&self) -> usize {
        self.buffer_frames
    }
}

impl Output for WasapiExclusive {
    fn format(&self) -> PcmFormat {
        self.format
    }

    fn wait(&mut self, timeout_ms: u32) -> Result<usize, OutputError> {
        if !self.started {
            return Ok(if self.prefill { self.buffer_frames } else { 0 });
        }
        match self.event.wait_for_event(timeout_ms) {
            Ok(()) => Ok(self.buffer_frames),
            Err(wasapi::WasapiError::EventTimeout) => Ok(0),
            Err(error) => Err(map_error(error)),
        }
    }

    fn write(&mut self, bytes: &[u8]) -> Result<usize, OutputError> {
        let frame = self.format.bytes_per_frame();
        let frames = (bytes.len() / frame).min(self.buffer_frames);
        self.staging.clear();
        self.staging.extend_from_slice(&bytes[..frames * frame]);
        self.staging.resize(self.buffer_frames * frame, 0);
        self.render
            .write_to_device(self.buffer_frames, &self.staging, None)
            .map_err(map_error)?;
        self.tracker
            .wrote(frames as u64, (self.buffer_frames - frames) as u64);
        self.prefill = false;
        Ok(frames)
    }

    fn start(&mut self) -> Result<(), OutputError> {
        self.client.start_stream().map_err(map_error)?;
        self.started = true;
        Ok(())
    }

    fn pause(&mut self) -> Result<(), OutputError> {
        self.client.stop_stream().map_err(map_error)?;
        self.started = false;
        Ok(())
    }

    fn flush(&mut self) -> Result<(), OutputError> {
        if self.started {
            self.client.stop_stream().map_err(map_error)?;
        }
        self.client.reset_stream().map_err(map_error)?;
        self.started = false;
        self.prefill = true;
        self.tracker.reset();
        Ok(())
    }

    fn position_frames(&mut self) -> Result<u64, OutputError> {
        let (position, _) = self.clock.get_position().map_err(map_error)?;
        let played = (u128::from(position) * u128::from(self.format.rate)
            / u128::from(self.clock_frequency.max(1))) as u64;
        Ok(self.tracker.real_played(played))
    }
}
