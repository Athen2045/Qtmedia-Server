//! WASAPI shared, event-driven output in the device mix format. Volume and
//! resampling happen before this (see `convert::Converter`); Windows' own
//! mixer and volume still apply.

use wasapi::{AudioClient, AudioClock, AudioRenderClient, Direction, Handle, StreamMode};

use super::device::{ensure_com, find_device, from_waveformat, map_error};
use super::{Output, OutputError, PositionTracker};
use crate::audio::format::PcmFormat;

/// 200 ms: generous for Bluetooth, still quick to pause (pause stops at once).
const BUFFER_HNS: i64 = 2_000_000;

pub struct WasapiShared {
    client: AudioClient,
    render: AudioRenderClient,
    event: Handle,
    clock: AudioClock,
    clock_frequency: u64,
    format: PcmFormat,
    started: bool,
    tracker: PositionTracker,
}

impl WasapiShared {
    pub fn open(device_id: Option<&str>) -> Result<Self, OutputError> {
        ensure_com();
        let device = find_device(device_id)?;
        let mut client = device.get_iaudioclient().map_err(map_error)?;
        let wave = client.get_mixformat().map_err(map_error)?;
        client
            .initialize_client(
                &wave,
                &Direction::Render,
                &StreamMode::EventsShared {
                    autoconvert: false,
                    buffer_duration_hns: BUFFER_HNS,
                },
            )
            .map_err(map_error)?;
        let event = client.set_get_eventhandle().map_err(map_error)?;
        let render = client.get_audiorenderclient().map_err(map_error)?;
        let clock = client.get_audioclock().map_err(map_error)?;
        let clock_frequency = clock.get_frequency().map_err(map_error)?;
        Ok(Self {
            client,
            render,
            event,
            clock,
            clock_frequency,
            format: from_waveformat(&wave),
            started: false,
            tracker: PositionTracker::default(),
        })
    }
}

impl Output for WasapiShared {
    fn format(&self) -> PcmFormat {
        self.format
    }

    fn wait(&mut self, timeout_ms: u32) -> Result<usize, OutputError> {
        if self.started {
            match self.event.wait_for_event(timeout_ms) {
                Ok(()) => {}
                Err(wasapi::WasapiError::EventTimeout) => return Ok(0),
                Err(error) => return Err(map_error(error)),
            }
        }
        Ok(self
            .client
            .get_available_space_in_frames()
            .map_err(map_error)? as usize)
    }

    fn write(&mut self, bytes: &[u8]) -> Result<usize, OutputError> {
        let frame = self.format.bytes_per_frame();
        let frames = bytes.len() / frame;
        self.render
            .write_to_device(frames, &bytes[..frames * frame], None)
            .map_err(map_error)?;
        self.tracker.wrote(frames as u64, 0);
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
