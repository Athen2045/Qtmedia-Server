//! Format negotiation tests against mocked devices. `realtek()` mirrors the
//! Task 0 matrix: exclusive 44.1–192 kHz at 16, 24 and 24-in-32; no 32-bit
//! integer, no float; shared mix 48 kHz f32.

use std::collections::HashSet;

use qtmedia_app::audio::decoder::{Codec, SourceFormat};
use qtmedia_app::audio::format::{
    bit_perfect_blocker, candidates, negotiate, pack_float, pack_int, DeviceCaps, Negotiated,
    OutputMode, PcmFormat, Policy, RateMismatch, Reason,
};

struct MockDevice {
    exclusive: HashSet<PcmFormat>,
    mix: PcmFormat,
    bluetooth: bool,
}

impl DeviceCaps for MockDevice {
    fn supports_exclusive(&self, format: &PcmFormat) -> bool {
        self.exclusive.contains(format)
    }
    fn mix_format(&self) -> PcmFormat {
        self.mix
    }
    fn is_bluetooth(&self) -> bool {
        self.bluetooth
    }
}

fn device(rates: &[u32], layouts: &[(u16, u16)]) -> MockDevice {
    let mut exclusive = HashSet::new();
    for &rate in rates {
        for &(container, valid) in layouts {
            exclusive.insert(PcmFormat::int(rate, 2, container, valid));
        }
    }
    MockDevice {
        exclusive,
        mix: PcmFormat::float(48_000, 2),
        bluetooth: false,
    }
}

fn realtek() -> MockDevice {
    device(
        &[44_100, 48_000, 88_200, 96_000, 176_400, 192_000],
        &[(16, 16), (24, 24), (32, 24)],
    )
}

fn flac(rate: u32, bits: u32) -> SourceFormat {
    SourceFormat {
        codec: Codec::Flac,
        sample_rate: rate,
        channels: 2,
        bits_per_sample: Some(bits),
        total_frames: None,
    }
}

fn mp3(rate: u32) -> SourceFormat {
    SourceFormat {
        codec: Codec::Mp3,
        sample_rate: rate,
        channels: 2,
        bits_per_sample: None,
        total_frames: None,
    }
}

fn exclusive(rate_mismatch: RateMismatch) -> Policy {
    Policy {
        mode: OutputMode::Exclusive,
        rate_mismatch,
        volume: 1.0,
        exclusive_volume: false,
    }
}

fn layouts(list: &[PcmFormat]) -> Vec<(u16, u16, bool)> {
    list.iter()
        .map(|f| (f.container_bits, f.valid_bits, f.float))
        .collect()
}

// --- Candidate ordering -----------------------------------------------------

#[test]
fn candidates_for_24_bit_never_drop_bits() {
    let list = candidates(&flac(96_000, 24), 96_000);
    assert_eq!(
        layouts(&list),
        vec![(24, 24, false), (32, 24, false), (32, 32, false)]
    );
    assert!(list.iter().all(|f| f.rate == 96_000 && f.channels == 2));
}

#[test]
fn candidates_for_16_bit_prefer_the_native_depth_then_zero_padding() {
    let list = candidates(&flac(44_100, 16), 44_100);
    assert_eq!(
        layouts(&list),
        vec![
            (16, 16, false),
            (24, 24, false),
            (32, 24, false),
            (32, 32, false)
        ]
    );
}

#[test]
fn candidates_for_32_bit_only_offer_32_bit_integer() {
    assert_eq!(
        layouts(&candidates(&flac(48_000, 32), 48_000)),
        vec![(32, 32, false)]
    );
}

#[test]
fn candidates_for_lossy_sources_start_with_float() {
    assert_eq!(
        layouts(&candidates(&mp3(44_100), 44_100)),
        vec![
            (32, 32, true),
            (32, 32, false),
            (32, 24, false),
            (24, 24, false),
            (16, 16, false)
        ]
    );
}

// --- Negotiation ------------------------------------------------------------

#[test]
fn exclusive_opens_at_the_source_format_and_is_bit_perfect() {
    let n = negotiate(
        &flac(44_100, 16),
        &realtek(),
        &exclusive(RateMismatch::Strict),
    );
    assert_eq!(n.mode, OutputMode::Exclusive);
    assert_eq!(n.output, PcmFormat::int(44_100, 2, 16, 16));
    assert!(n.bit_perfect);
    assert_eq!(n.reason, None);
    assert_eq!(n.gain, 1.0);
}

#[test]
fn exclusive_uses_24_in_32_when_packed_24_is_refused() {
    let dac = device(&[96_000], &[(32, 24), (32, 32)]);
    let n = negotiate(&flac(96_000, 24), &dac, &exclusive(RateMismatch::Strict));
    assert_eq!(n.output, PcmFormat::int(96_000, 2, 32, 24));
    assert!(n.bit_perfect);
}

#[test]
fn strict_rate_mismatch_falls_back_to_shared_and_says_why() {
    let n = negotiate(
        &flac(352_800, 24),
        &realtek(),
        &exclusive(RateMismatch::Strict),
    );
    assert_eq!(n.mode, OutputMode::Shared);
    assert_eq!(n.output, PcmFormat::float(48_000, 2));
    assert!(!n.bit_perfect);
    assert_eq!(n.reason, Some(Reason::RateUnsupported { rate: 352_800 }));
}

#[test]
fn allow_resampling_stays_exclusive_at_the_best_rate_but_not_bit_perfect() {
    let n = negotiate(
        &flac(352_800, 24),
        &realtek(),
        &exclusive(RateMismatch::Resample),
    );
    assert_eq!(n.mode, OutputMode::Exclusive);
    // Same family as 352.8 kHz, highest the device takes.
    assert_eq!(n.output, PcmFormat::int(176_400, 2, 24, 24));
    assert!(!n.bit_perfect);
    assert_eq!(
        n.reason,
        Some(Reason::Resampled {
            from: 352_800,
            to: 176_400
        })
    );
}

#[test]
fn resampling_prefers_an_integer_ratio_above_the_source() {
    let dac = device(&[48_000, 88_200, 96_000], &[(24, 24)]);
    let n = negotiate(&flac(44_100, 24), &dac, &exclusive(RateMismatch::Resample));
    assert_eq!(n.output.rate, 88_200);
}

#[test]
fn unsupported_bit_depth_falls_back_to_shared_even_when_resampling_is_allowed() {
    let n = negotiate(
        &flac(48_000, 32),
        &realtek(),
        &exclusive(RateMismatch::Resample),
    );
    assert_eq!(n.mode, OutputMode::Shared);
    assert_eq!(n.reason, Some(Reason::BitDepthUnsupported { bits: 32 }));
}

#[test]
fn a_device_without_exclusive_support_falls_back_to_shared() {
    let n = negotiate(
        &flac(44_100, 16),
        &device(&[], &[]),
        &exclusive(RateMismatch::Resample),
    );
    assert_eq!(n.mode, OutputMode::Shared);
    assert_eq!(n.reason, Some(Reason::FormatUnsupported));
}

#[test]
fn shared_mode_uses_the_mix_format_and_software_volume() {
    let policy = Policy {
        mode: OutputMode::Shared,
        rate_mismatch: RateMismatch::Strict,
        volume: 0.5,
        exclusive_volume: false,
    };
    let n = negotiate(&flac(44_100, 16), &realtek(), &policy);
    assert_eq!(n.mode, OutputMode::Shared);
    assert_eq!(n.output, PcmFormat::float(48_000, 2));
    assert_eq!(n.gain, 0.5);
    assert!(!n.bit_perfect);
    assert_eq!(n.reason, Some(Reason::SharedMode));
}

#[test]
fn lossy_sources_play_exclusive_but_are_never_bit_perfect() {
    let n = negotiate(&mp3(44_100), &realtek(), &exclusive(RateMismatch::Strict));
    assert_eq!(n.mode, OutputMode::Exclusive);
    assert_eq!(n.output, PcmFormat::int(44_100, 2, 32, 24));
    assert!(!n.bit_perfect);
    assert_eq!(n.reason, Some(Reason::LossySource));
}

#[test]
fn exclusive_volume_is_fixed_at_full_unless_opted_in() {
    let mut policy = exclusive(RateMismatch::Strict);
    policy.volume = 0.4;
    let n = negotiate(&flac(44_100, 16), &realtek(), &policy);
    assert_eq!(n.gain, 1.0);
    assert!(n.bit_perfect);

    policy.exclusive_volume = true;
    let n = negotiate(&flac(44_100, 16), &realtek(), &policy);
    assert_eq!(n.gain, 0.4);
    assert!(!n.bit_perfect);
    assert_eq!(n.reason, Some(Reason::SoftwareVolume));
}

#[test]
fn bluetooth_is_never_bit_perfect() {
    let mut headphones = realtek();
    headphones.bluetooth = true;
    let n = negotiate(
        &flac(44_100, 16),
        &headphones,
        &exclusive(RateMismatch::Strict),
    );
    assert_eq!(n.mode, OutputMode::Exclusive);
    assert!(!n.bit_perfect);
    assert_eq!(n.reason, Some(Reason::Bluetooth));
}

// --- Bit-perfect predicate --------------------------------------------------

#[test]
fn bit_perfect_requires_exclusive_exact_rate_integer_full_volume_wired() {
    let source = flac(96_000, 24);
    let out = PcmFormat::int(96_000, 2, 32, 24);
    let check = |mode, output: &PcmFormat, gain, bluetooth| {
        bit_perfect_blocker(&source, mode, output, gain, bluetooth)
    };
    assert_eq!(check(OutputMode::Exclusive, &out, 1.0, false), None);
    assert_eq!(
        check(OutputMode::Shared, &out, 1.0, false),
        Some(Reason::SharedMode)
    );
    assert_eq!(
        check(OutputMode::Exclusive, &out, 1.0, true),
        Some(Reason::Bluetooth)
    );
    assert_eq!(
        check(OutputMode::Exclusive, &out, 0.99, false),
        Some(Reason::SoftwareVolume)
    );
    assert_eq!(
        check(
            OutputMode::Exclusive,
            &PcmFormat::int(48_000, 2, 32, 24),
            1.0,
            false
        ),
        Some(Reason::Resampled {
            from: 96_000,
            to: 48_000
        })
    );
    assert_eq!(
        check(
            OutputMode::Exclusive,
            &PcmFormat::int(96_000, 2, 16, 16),
            1.0,
            false
        ),
        Some(Reason::BitDepthUnsupported { bits: 24 })
    );
    assert_eq!(
        check(
            OutputMode::Exclusive,
            &PcmFormat::float(96_000, 2),
            1.0,
            false
        ),
        Some(Reason::FloatOutput)
    );
}

#[test]
fn reasons_have_stable_codes() {
    assert_eq!(
        Reason::RateUnsupported { rate: 1 }.code(),
        "exclusive_rate_unsupported"
    );
    assert_eq!(Reason::Bluetooth.code(), "bluetooth_output");
    assert_eq!(Reason::LossySource.code(), "lossy_source");
}

#[test]
fn negotiated_reports_resampling() {
    let n: Negotiated = negotiate(
        &flac(44_100, 16),
        &realtek(),
        &Policy {
            mode: OutputMode::Shared,
            rate_mismatch: RateMismatch::Strict,
            volume: 1.0,
            exclusive_volume: false,
        },
    );
    assert!(n.resampling(44_100));
    let n = negotiate(
        &flac(44_100, 16),
        &realtek(),
        &exclusive(RateMismatch::Strict),
    );
    assert!(!n.resampling(44_100));
}

// --- Packing ----------------------------------------------------------------

const S16: i32 = 0x1234 << 16; // 16-bit sample 0x1234, left-justified.
const S24: i32 = 0x12_3456 << 8; // 24-bit sample 0x123456, left-justified.

fn packed(samples: &[i32], container: u16, valid: u16) -> Vec<u8> {
    let mut out = Vec::new();
    pack_int(
        samples,
        &PcmFormat::int(44_100, 1, container, valid),
        &mut out,
    );
    out
}

#[test]
fn packs_16_bit_unchanged() {
    assert_eq!(packed(&[S16, -S16], 16, 16), [0x34, 0x12, 0xCC, 0xED]);
}

#[test]
fn packs_24_bit_unchanged() {
    assert_eq!(packed(&[S24], 24, 24), [0x56, 0x34, 0x12]);
    assert_eq!(packed(&[-S24], 24, 24), [0xAA, 0xCB, 0xED]);
}

#[test]
fn packs_24_in_32_left_justified_with_a_zero_low_byte() {
    assert_eq!(packed(&[S24], 32, 24), [0x00, 0x56, 0x34, 0x12]);
    assert_eq!(packed(&[S16], 32, 24), [0x00, 0x00, 0x34, 0x12]);
}

#[test]
fn zero_padding_a_16_bit_source_preserves_every_value() {
    let samples = [
        S16,
        -S16,
        i16::MAX as i32 * 65_536,
        i16::MIN as i32 * 65_536,
    ];
    for (container, valid) in [(24, 24), (32, 24), (32, 32)] {
        let bytes = packed(&samples, container, valid);
        let width = container as usize / 8;
        for (sample, chunk) in samples.iter().zip(bytes.chunks_exact(width)) {
            let mut word = [0u8; 4];
            word[4 - width..].copy_from_slice(chunk);
            assert_eq!(i32::from_le_bytes(word) >> 16, sample >> 16);
        }
    }
}

#[test]
fn packs_float_for_lossy_exclusive_output() {
    let mut out = Vec::new();
    pack_float(
        &[1.0, -1.0, 0.0, 2.0],
        &PcmFormat::int(44_100, 1, 16, 16),
        &mut out,
    );
    let values: Vec<i16> = out
        .chunks_exact(2)
        .map(|b| i16::from_le_bytes([b[0], b[1]]))
        .collect();
    assert_eq!(values, [i16::MAX, -i16::MAX, 0, i16::MAX]);

    let mut out = Vec::new();
    pack_float(&[0.25], &PcmFormat::float(44_100, 1), &mut out);
    assert_eq!(out, 0.25f32.to_le_bytes());
}
