//! Output format negotiation for the native engine: pure functions over
//! [`DeviceCaps`], so every policy decision is testable without hardware.
//!
//! Exclusive mode opens the device at the file's own rate with a layout that
//! holds every source bit; samples are copied unchanged (zero-padded when the
//! container is wider). Shared mode always uses the device mix format.

use super::decoder::SourceFormat;

/// Rates probed when looking for a resampling target or a usable device.
pub const STANDARD_RATES: [u32; 8] = [
    44_100, 48_000, 88_200, 96_000, 176_400, 192_000, 352_800, 384_000,
];

/// Integer layouts as (container, valid) bits, narrowest first.
const INT_LAYOUTS: [(u16, u16); 4] = [(16, 16), (24, 24), (32, 24), (32, 32)];

/// One concrete device stream format. Integer samples are left-justified in
/// their container (24-in-32 has a zero low byte).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct PcmFormat {
    pub rate: u32,
    pub channels: u16,
    pub container_bits: u16,
    pub valid_bits: u16,
    pub float: bool,
}

impl PcmFormat {
    pub fn int(rate: u32, channels: u16, container_bits: u16, valid_bits: u16) -> Self {
        Self {
            rate,
            channels,
            container_bits,
            valid_bits,
            float: false,
        }
    }

    pub fn float(rate: u32, channels: u16) -> Self {
        Self {
            rate,
            channels,
            container_bits: 32,
            valid_bits: 32,
            float: true,
        }
    }

    pub fn bytes_per_frame(&self) -> usize {
        self.container_bits as usize / 8 * self.channels as usize
    }
}

/// What the engine needs to know about an output device. Production wraps
/// `is_supported_exclusive_with_quirks` and the endpoint form factor (Task 3).
pub trait DeviceCaps {
    fn supports_exclusive(&self, format: &PcmFormat) -> bool;
    fn mix_format(&self) -> PcmFormat;
    fn is_bluetooth(&self) -> bool;
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum OutputMode {
    Shared,
    Exclusive,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RateMismatch {
    /// Fall back to shared mode and say why (default).
    Strict,
    /// Stay exclusive at the closest supported rate; not bit-perfect.
    Resample,
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Policy {
    pub mode: OutputMode,
    pub rate_mismatch: RateMismatch,
    /// 0..=1, the user's volume slider.
    pub volume: f32,
    /// Allow software volume in exclusive mode (drops bit-perfect below 100 %).
    pub exclusive_volume: bool,
}

/// Why playback is not bit-perfect, or why exclusive mode was not used.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Reason {
    SharedMode,
    RateUnsupported {
        rate: u32,
    },
    BitDepthUnsupported {
        bits: u32,
    },
    FormatUnsupported,
    /// Windows' "Allow applications to take exclusive control" is off.
    ExclusiveDenied,
    Resampled {
        from: u32,
        to: u32,
    },
    LossySource,
    FloatOutput,
    Bluetooth,
    SoftwareVolume,
    /// Loudness levelling changed this song's level.
    VolumeLevelling,
}

impl Reason {
    pub fn code(&self) -> &'static str {
        match self {
            Self::SharedMode => "shared_mode",
            Self::RateUnsupported { .. } => "exclusive_rate_unsupported",
            Self::BitDepthUnsupported { .. } => "exclusive_bits_unsupported",
            Self::FormatUnsupported => "exclusive_format_unsupported",
            Self::ExclusiveDenied => "exclusive_denied",
            Self::Resampled { .. } => "resampled",
            Self::LossySource => "lossy_source",
            Self::FloatOutput => "float_output",
            Self::Bluetooth => "bluetooth_output",
            Self::SoftwareVolume => "software_volume",
            Self::VolumeLevelling => "volume_levelling",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Negotiated {
    pub mode: OutputMode,
    pub output: PcmFormat,
    /// Software gain the output applies (1.0 = untouched).
    pub gain: f32,
    pub bit_perfect: bool,
    /// The exclusive-mode fallback reason, else why it is not bit-perfect.
    pub reason: Option<Reason>,
}

impl Negotiated {
    /// Shared mode in the device mix format with software volume.
    pub fn shared(mix: PcmFormat, volume: f32, reason: Reason) -> Self {
        Self {
            mode: OutputMode::Shared,
            output: mix,
            gain: volume,
            bit_perfect: false,
            reason: Some(reason),
        }
    }

    pub fn resampling(&self, source_rate: u32) -> bool {
        self.output.rate != source_rate
    }

    /// Re-applies the volume slider without reopening the device. Exclusive
    /// mode ignores it unless `exclusive_volume` is set; a fallback reason
    /// (shared despite asking for exclusive) is kept.
    pub fn apply_volume(&mut self, source: &SourceFormat, policy: &Policy, bluetooth: bool) {
        match self.mode {
            OutputMode::Shared => self.gain = policy.volume,
            OutputMode::Exclusive => {
                self.gain = if policy.exclusive_volume {
                    policy.volume
                } else {
                    1.0
                };
                let blocker = bit_perfect_blocker(
                    source,
                    OutputMode::Exclusive,
                    &self.output,
                    self.gain,
                    bluetooth,
                );
                self.bit_perfect = blocker.is_none();
                self.reason = blocker;
            }
        }
    }
}

/// Exclusive formats to try at `rate`, most preferred first. Integer sources
/// only get layouts that hold every bit; lossy sources start with float.
pub fn candidates(source: &SourceFormat, rate: u32) -> Vec<PcmFormat> {
    let channels = source.channels;
    match source.bits_per_sample {
        Some(bits) => INT_LAYOUTS
            .iter()
            .filter(|(_, valid)| u32::from(*valid) >= bits)
            .map(|&(container, valid)| PcmFormat::int(rate, channels, container, valid))
            .collect(),
        None => std::iter::once(PcmFormat::float(rate, channels))
            .chain(
                INT_LAYOUTS
                    .iter()
                    .rev()
                    .map(|&(container, valid)| PcmFormat::int(rate, channels, container, valid)),
            )
            .collect(),
    }
}

/// `None` when the path is bit-perfect, else the first reason it is not.
pub fn bit_perfect_blocker(
    source: &SourceFormat,
    mode: OutputMode,
    output: &PcmFormat,
    gain: f32,
    bluetooth: bool,
) -> Option<Reason> {
    if mode == OutputMode::Shared {
        return Some(Reason::SharedMode);
    }
    let Some(bits) = source.bits_per_sample else {
        return Some(Reason::LossySource);
    };
    if bluetooth {
        return Some(Reason::Bluetooth);
    }
    if output.rate != source.sample_rate {
        return Some(Reason::Resampled {
            from: source.sample_rate,
            to: output.rate,
        });
    }
    if output.float {
        return Some(Reason::FloatOutput);
    }
    if u32::from(output.valid_bits) < bits {
        return Some(Reason::BitDepthUnsupported { bits });
    }
    if gain < 1.0 {
        return Some(Reason::SoftwareVolume);
    }
    None
}

pub fn negotiate(source: &SourceFormat, caps: &dyn DeviceCaps, policy: &Policy) -> Negotiated {
    let shared = |reason: Reason| Negotiated::shared(caps.mix_format(), policy.volume, reason);
    if policy.mode == OutputMode::Shared {
        return shared(Reason::SharedMode);
    }

    let output = match exclusive_format(source, caps, policy.rate_mismatch) {
        Ok(output) => output,
        Err(reason) => return shared(reason),
    };
    let gain = if policy.exclusive_volume {
        policy.volume
    } else {
        1.0
    };
    let blocker = bit_perfect_blocker(
        source,
        OutputMode::Exclusive,
        &output,
        gain,
        caps.is_bluetooth(),
    );
    Negotiated {
        mode: OutputMode::Exclusive,
        output,
        gain,
        bit_perfect: blocker.is_none(),
        reason: blocker,
    }
}

fn first_supported(source: &SourceFormat, caps: &dyn DeviceCaps, rate: u32) -> Option<PcmFormat> {
    candidates(source, rate)
        .into_iter()
        .find(|format| caps.supports_exclusive(format))
}

/// Whether the device takes `rate` at all, in any standard layout.
fn takes_rate(caps: &dyn DeviceCaps, channels: u16, rate: u32) -> bool {
    std::iter::once(PcmFormat::float(rate, channels))
        .chain(
            INT_LAYOUTS
                .iter()
                .map(|&(container, valid)| PcmFormat::int(rate, channels, container, valid)),
        )
        .any(|format| caps.supports_exclusive(&format))
}

fn exclusive_format(
    source: &SourceFormat,
    caps: &dyn DeviceCaps,
    rate_mismatch: RateMismatch,
) -> Result<PcmFormat, Reason> {
    let rate = source.sample_rate;
    if let Some(format) = first_supported(source, caps, rate) {
        return Ok(format);
    }
    // The rate works but no layout holds every bit: never truncate.
    let depth_problem = || match source.bits_per_sample {
        Some(bits) => Reason::BitDepthUnsupported { bits },
        None => Reason::FormatUnsupported,
    };
    if takes_rate(caps, source.channels, rate) {
        return Err(depth_problem());
    }
    if !STANDARD_RATES
        .iter()
        .any(|&other| takes_rate(caps, source.channels, other))
    {
        return Err(Reason::FormatUnsupported);
    }
    if rate_mismatch == RateMismatch::Strict {
        return Err(Reason::RateUnsupported { rate });
    }
    let usable: Vec<PcmFormat> = STANDARD_RATES
        .iter()
        .filter_map(|&other| first_supported(source, caps, other))
        .collect();
    let rates: Vec<u32> = usable.iter().map(|format| format.rate).collect();
    let target = resample_target(rate, &rates).ok_or_else(depth_problem)?;
    Ok(*usable
        .iter()
        .find(|format| format.rate == target)
        .expect("target comes from usable"))
}

fn same_family(a: u32, b: u32) -> bool {
    let (low, high) = if a < b { (a, b) } else { (b, a) };
    low > 0 && high % low == 0
}

/// The best resampling target: an integer-ratio rate at or above the source,
/// then any rate above it, then the highest integer-ratio rate below it, then
/// the highest rate below it.
pub fn resample_target(source_rate: u32, supported: &[u32]) -> Option<u32> {
    let above = |family: bool| {
        supported
            .iter()
            .copied()
            .filter(|&r| r >= source_rate && (!family || same_family(r, source_rate)))
            .min()
    };
    let below = |family: bool| {
        supported
            .iter()
            .copied()
            .filter(|&r| r < source_rate && (!family || same_family(r, source_rate)))
            .max()
    };
    above(true)
        .or_else(|| above(false))
        .or_else(|| below(true))
        .or_else(|| below(false))
}

/// Writes left-justified integer samples into `output`'s layout, little-endian.
/// For integer outputs at least as wide as the source this is lossless.
pub fn pack_int(samples: &[i32], output: &PcmFormat, out: &mut Vec<u8>) {
    if output.float {
        out.reserve(samples.len() * 4);
        for &sample in samples {
            out.extend_from_slice(&(sample as f32 / 2_147_483_648.0).to_le_bytes());
        }
        return;
    }
    let width = output.container_bits as usize / 8;
    let mask = if output.valid_bits >= 32 {
        -1i32
    } else {
        -1i32 << (32 - output.valid_bits)
    };
    out.reserve(samples.len() * width);
    for &sample in samples {
        // Left-justified in 32 bits: the container keeps the top `width` bytes.
        out.extend_from_slice(&(sample & mask).to_le_bytes()[4 - width..]);
    }
}

/// Writes float samples (lossy sources) into `output`'s layout, clamped to
/// full scale and rounded to the valid bit depth.
pub fn pack_float(samples: &[f32], output: &PcmFormat, out: &mut Vec<u8>) {
    if output.float {
        out.reserve(samples.len() * 4);
        for &sample in samples {
            out.extend_from_slice(&sample.to_le_bytes());
        }
        return;
    }
    let full_scale = ((1i64 << (output.valid_bits - 1)) - 1) as f64;
    let shift = 32 - u32::from(output.valid_bits);
    let left_justified: Vec<i32> = samples
        .iter()
        .map(|&sample| {
            let value = (f64::from(sample).clamp(-1.0, 1.0) * full_scale).round() as i64;
            (value << shift) as i32
        })
        .collect();
    pack_int(&left_justified, output, out);
}
