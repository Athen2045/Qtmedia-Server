//! Decoded blocks → device bytes for one negotiated output.
//!
//! The bit-perfect path (exclusive, integer source, same rate, unity gain) only
//! repacks the left-justified samples. Every other path goes through `f32`:
//! FFT resampling (rubato) when the rates differ, channel mapping to the
//! device layout, then software gain. This runs on the decoder thread, never
//! on the render thread, so it may allocate.

use rubato::audioadapter_buffers::direct::InterleavedSlice;
use rubato::{Fft, FixedSync, Indexing, Resampler};

use super::decoder::{Block, SourceFormat};
use super::format::{pack_float, pack_int, Negotiated, OutputMode, PcmFormat};

/// Input frames per resampler chunk.
const RESAMPLE_CHUNK: usize = 1024;

pub struct Converter {
    source_channels: usize,
    output: PcmFormat,
    gain: f32,
    copy_bits: bool,
    resampler: Option<Resampling>,
    floats: Vec<f32>,
    resampled: Vec<f32>,
    mapped: Vec<f32>,
}

impl Converter {
    pub fn new(source: &SourceFormat, negotiated: &Negotiated) -> Self {
        let output = negotiated.output;
        let resampler = (source.sample_rate != output.rate).then(|| {
            Resampling::new(
                source.sample_rate,
                output.rate,
                usize::from(source.channels),
            )
        });
        Self {
            source_channels: usize::from(source.channels),
            output,
            gain: negotiated.gain,
            copy_bits: negotiated.mode == OutputMode::Exclusive
                && !output.float
                && resampler.is_none()
                && output.channels == source.channels,
            resampler,
            floats: Vec::new(),
            resampled: Vec::new(),
            mapped: Vec::new(),
        }
    }

    pub fn output(&self) -> &PcmFormat {
        &self.output
    }

    /// Takes effect from the next block (see `Negotiated::apply_volume`).
    pub fn set_gain(&mut self, gain: f32) {
        self.gain = gain;
    }

    /// Appends the device bytes for `block` to `out`. With resampling, output
    /// lags the input by up to one chunk until `finish`.
    pub fn convert(&mut self, block: &Block, out: &mut Vec<u8>) {
        match block {
            Block::Int(samples) if self.copy_bits && self.gain >= 1.0 => {
                pack_int(samples, &self.output, out)
            }
            Block::Int(samples) => {
                let mut floats = std::mem::take(&mut self.floats);
                floats.clear();
                floats.extend(samples.iter().map(|&s| s as f32 / 2_147_483_648.0));
                self.float_path(&floats, out);
                self.floats = floats;
            }
            Block::Float(samples) => self.float_path(samples, out),
        }
    }

    /// Flushes the resampler tail at the end of the stream (not between
    /// gapless tracks of the same format).
    pub fn finish(&mut self, out: &mut Vec<u8>) {
        let Some(resampler) = self.resampler.as_mut() else {
            return;
        };
        let mut tail = std::mem::take(&mut self.resampled);
        tail.clear();
        resampler.finish(&mut tail);
        self.emit(&tail, out);
        self.resampled = tail;
    }

    /// Drops buffered audio (seek).
    pub fn reset(&mut self) {
        if let Some(resampler) = self.resampler.as_mut() {
            resampler.reset();
        }
    }

    fn float_path(&mut self, samples: &[f32], out: &mut Vec<u8>) {
        match self.resampler.as_mut() {
            Some(resampler) => {
                let mut resampled = std::mem::take(&mut self.resampled);
                resampled.clear();
                resampler.push(samples, &mut resampled);
                self.emit(&resampled, out);
                self.resampled = resampled;
            }
            None => self.emit(samples, out),
        }
    }

    fn emit(&mut self, samples: &[f32], out: &mut Vec<u8>) {
        let mut mapped = std::mem::take(&mut self.mapped);
        mapped.clear();
        map_channels(
            samples,
            self.source_channels,
            usize::from(self.output.channels),
            self.gain,
            &mut mapped,
        );
        pack_float(&mapped, &self.output, out);
        self.mapped = mapped;
    }
}

/// Maps interleaved frames from `from` to `to` channels and applies `gain`.
/// Mono feeds the first two outputs; stereo to mono averages; otherwise the
/// shared channels are copied and extra outputs stay silent.
pub fn map_channels(input: &[f32], from: usize, to: usize, gain: f32, out: &mut Vec<f32>) {
    if from == 0 || to == 0 {
        return;
    }
    out.reserve(input.len() / from * to);
    for frame in input.chunks_exact(from) {
        if from == to {
            out.extend(frame.iter().map(|s| s * gain));
        } else if to == 1 {
            out.push(frame.iter().sum::<f32>() / from as f32 * gain);
        } else if from == 1 {
            let value = frame[0] * gain;
            out.extend((0..to).map(|channel| if channel < 2 { value } else { 0.0 }));
        } else {
            out.extend((0..to).map(|channel| frame.get(channel).map_or(0.0, |s| s * gain)));
        }
    }
}

/// Streaming fixed-ratio resampler: trims the filter delay at the start and
/// pads the tail so the output length is exactly `ceil(input × ratio)`.
struct Resampling {
    resampler: Fft<f32>,
    channels: usize,
    from: u64,
    to: u64,
    pending: Vec<f32>,
    scratch: Vec<f32>,
    trim: usize,
    input_frames: u64,
    output_frames: u64,
}

impl Resampling {
    fn new(from: u32, to: u32, channels: usize) -> Self {
        let resampler = Fft::<f32>::new(
            from as usize,
            to as usize,
            RESAMPLE_CHUNK,
            channels,
            FixedSync::Input,
        )
        .expect("standard sample rates and a non-zero channel count");
        let scratch = vec![0.0; resampler.output_frames_max() * channels];
        let trim = resampler.output_delay();
        Self {
            resampler,
            channels,
            from: u64::from(from),
            to: u64::from(to),
            pending: Vec::new(),
            scratch,
            trim,
            input_frames: 0,
            output_frames: 0,
        }
    }

    fn push(&mut self, input: &[f32], out: &mut Vec<f32>) {
        let channels = self.channels;
        self.pending.extend_from_slice(input);
        self.input_frames += (input.len() / channels) as u64;
        let total = self.pending.len() / channels;
        let mut offset = 0;
        while total - offset >= self.resampler.input_frames_next() {
            let (consumed, produced) = self.process(offset, total, None);
            offset += consumed;
            self.take(produced, out);
        }
        self.pending.drain(..offset * channels);
    }

    fn finish(&mut self, out: &mut Vec<f32>) {
        let channels = self.channels;
        let expected = (self.input_frames * self.to).div_ceil(self.from);
        let start = out.len();
        let remaining = self.pending.len() / channels;
        if remaining > 0 {
            let (_, produced) = self.process(0, remaining, Some(remaining));
            self.take(produced, out);
        }
        self.pending.clear();
        while self.output_frames < expected {
            let (_, produced) = self.process(0, 0, Some(0));
            self.take(produced, out);
        }
        let excess = (self.output_frames - expected) as usize;
        let keep = out.len() - excess * channels;
        out.truncate(keep.max(start));
        self.reset();
    }

    fn process(&mut self, offset: usize, frames: usize, partial: Option<usize>) -> (usize, usize) {
        let input = InterleavedSlice::new(&self.pending, self.channels, frames)
            .expect("pending holds whole frames");
        let output_frames = self.scratch.len() / self.channels;
        let mut output = InterleavedSlice::new_mut(&mut self.scratch, self.channels, output_frames)
            .expect("scratch is sized to output_frames_max");
        let mut indexing = Indexing::new();
        indexing.input_offset = offset;
        indexing.partial_len = partial;
        self.resampler
            .process_into_buffer(&input, &mut output, Some(&indexing))
            .expect("buffers are sized for the resampler")
    }

    fn take(&mut self, produced: usize, out: &mut Vec<f32>) {
        let skip = self.trim.min(produced);
        self.trim -= skip;
        out.extend_from_slice(&self.scratch[skip * self.channels..produced * self.channels]);
        self.output_frames += (produced - skip) as u64;
    }

    fn reset(&mut self) {
        self.resampler.reset();
        self.pending.clear();
        self.trim = self.resampler.output_delay();
        self.input_frames = 0;
        self.output_frames = 0;
    }
}
