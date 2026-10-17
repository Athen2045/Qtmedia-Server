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
/// Where the soft limiter starts bending peaks (−1 dBFS).
const LIMIT_KNEE: f32 = 0.891;
/// Headroom for Bluetooth: the headset's lossy codec rebuilds peaks above
/// the samples it was given, so leave it 1 dB (−1 dBTP, as streaming masters do).
pub const BLUETOOTH_HEADROOM: f32 = 0.891;

/// Bends samples above −1 dBFS smoothly towards full scale instead of
/// cutting them flat at ±1.0 (harsh clipping). Transparent below the knee;
/// continuous with slope 1 at the knee; never exceeds ±1.0.
pub fn soft_limit(sample: f32) -> f32 {
    let magnitude = sample.abs();
    if magnitude <= LIMIT_KNEE {
        return sample;
    }
    let room = 1.0 - LIMIT_KNEE;
    let limited = LIMIT_KNEE + room * ((magnitude - LIMIT_KNEE) / room).tanh();
    limited.copysign(sample)
}

pub struct Converter {
    source_channels: usize,
    output: PcmFormat,
    gain: f32,
    /// Extra gain before the limiter (Bluetooth headroom); 1.0 otherwise.
    headroom: f32,
    /// This track's loudness-levelling gain (fixed per track; 1.0 = off).
    level: f32,
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
            headroom: 1.0,
            level: 1.0,
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

    /// Loudness levelling for this track, applied with the volume. Set once
    /// when the track opens, so a gapless next track keeps its own level.
    pub fn set_level(&mut self, level: f32) {
        self.level = level;
    }

    /// Bluetooth outputs get 1 dB of headroom ahead of the headset's codec.
    /// (Bluetooth is never bit-perfect, so this never touches a bit-perfect path.)
    pub fn set_bluetooth(&mut self, bluetooth: bool) {
        self.headroom = if bluetooth { BLUETOOTH_HEADROOM } else { 1.0 };
    }

    /// Appends the device bytes for `block` to `out`. With resampling, output
    /// lags the input by up to one chunk until `finish`.
    pub fn convert(&mut self, block: &Block, out: &mut Vec<u8>) {
        match block {
            // Only an exact unity path may copy bits (a boost must be applied).
            Block::Int(samples) if self.copy_bits && self.gain == 1.0 && self.level == 1.0 => {
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
            self.gain * self.level * self.headroom,
            &mut mapped,
        );
        // Lossy decodes and resampling overshoot full scale: limit softly
        // rather than clip (the bit-perfect copy never comes through here).
        for sample in &mut mapped {
            *sample = soft_limit(*sample);
        }
        pack_float(&mapped, &self.output, out);
        self.mapped = mapped;
    }
}

/// −3 dB: how much of the centre and surround channels goes into each side.
const FOLD: f32 = std::f32::consts::FRAC_1_SQRT_2;

/// Left/right weights per input channel for a stereo downmix, in the FLAC /
/// WAVE channel order for that count (FLAC fixes the order by count). Centre
/// and surrounds fold in at −3 dB, LFE is left out (ITU-R BS.775 / Dolby
/// Lo/Ro), and each side is scaled so the sum can never pass full scale.
pub fn stereo_downmix(from: usize) -> Option<Vec<(f32, f32)>> {
    const L: (f32, f32) = (1.0, 0.0);
    const R: (f32, f32) = (0.0, 1.0);
    const C: (f32, f32) = (FOLD, FOLD);
    const LFE: (f32, f32) = (0.0, 0.0);
    const SL: (f32, f32) = (FOLD, 0.0);
    const SR: (f32, f32) = (0.0, FOLD);
    let layout: Vec<(f32, f32)> = match from {
        3 => vec![L, R, C],
        4 => vec![L, R, SL, SR],
        5 => vec![L, R, C, SL, SR],
        6 => vec![L, R, C, LFE, SL, SR],
        // 6.1: FL FR FC LFE BC SL SR (the back centre feeds both sides).
        7 => vec![L, R, C, LFE, (FOLD * FOLD, FOLD * FOLD), SL, SR],
        // 7.1: FL FR FC LFE BL BR SL SR.
        8 => vec![L, R, C, LFE, SL, SR, SL, SR],
        _ => return None,
    };
    let left: f32 = layout.iter().map(|weights| weights.0).sum();
    let right: f32 = layout.iter().map(|weights| weights.1).sum();
    let scale = 1.0 / left.max(right).max(1.0);
    Some(
        layout
            .into_iter()
            .map(|(l, r)| (l * scale, r * scale))
            .collect(),
    )
}

/// Maps interleaved frames from `from` to `to` channels and applies `gain`.
/// Mono feeds the first two outputs; stereo to mono averages; surround to
/// stereo is downmixed (centre and surrounds kept, see `stereo_downmix`);
/// otherwise the shared channels are copied and extra outputs stay silent.
pub fn map_channels(input: &[f32], from: usize, to: usize, gain: f32, out: &mut Vec<f32>) {
    if from == 0 || to == 0 {
        return;
    }
    out.reserve(input.len() / from * to);
    let downmix = (to == 2 && from > 2)
        .then(|| stereo_downmix(from))
        .flatten();
    for frame in input.chunks_exact(from) {
        if let Some(weights) = &downmix {
            let (left, right) = frame
                .iter()
                .zip(weights)
                .fold((0.0, 0.0), |(l, r), (sample, (wl, wr))| {
                    (l + sample * wl, r + sample * wr)
                });
            out.push(left * gain);
            out.push(right * gain);
        } else if from == to {
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
