//! Output-path tests: decoded fixtures → `Converter` → `FakeOutput`.
//! Exclusive bytes must equal the source PCM exactly; shared output must be
//! resampled, channel-mapped and gain-scaled.

use std::path::PathBuf;

use qtmedia_app::audio::convert::{map_channels, Converter};
use qtmedia_app::audio::decoder::Decoder;
use qtmedia_app::audio::format::{Negotiated, OutputMode, PcmFormat, Policy, RateMismatch, Reason};
use qtmedia_app::audio::output::fake::FakeOutput;
use qtmedia_app::audio::output::{
    classify_transport, map_hresult, Output, OutputError, PositionTracker, Transport,
};

fn fixture(name: &str) -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("tests/fixtures/audio")
        .join(name)
}

fn exclusive(output: PcmFormat) -> Negotiated {
    Negotiated {
        mode: OutputMode::Exclusive,
        output,
        gain: 1.0,
        bit_perfect: true,
        reason: None,
    }
}

fn shared(output: PcmFormat, gain: f32) -> Negotiated {
    Negotiated {
        mode: OutputMode::Shared,
        output,
        gain,
        bit_perfect: false,
        reason: Some(Reason::SharedMode),
    }
}

/// Decodes `file` through a converter into `output`, the way the engine
/// will: prefill, start, then wait/write until the converted bytes run out.
fn render(file: &str, negotiated: &Negotiated, output: &mut FakeOutput) -> (Vec<u8>, u64) {
    let mut decoder = Decoder::open(&fixture(file)).unwrap();
    let mut converter = Converter::new(decoder.format(), negotiated);
    let mut bytes = Vec::new();
    while let Some(block) = decoder.next_block().unwrap() {
        converter.convert(&block, &mut bytes);
    }
    converter.finish(&mut bytes);

    let frame = output.format().bytes_per_frame();
    let mut offset = 0;
    let mut real = 0u64;
    while offset < bytes.len() {
        let space = output.wait(100).unwrap();
        let take = (space * frame).min(bytes.len() - offset);
        real += output.write(&bytes[offset..offset + take]).unwrap() as u64;
        offset += take;
        if !output.is_started() {
            output.start().unwrap();
        }
        let queued = output.queued_frames();
        output.play(queued);
    }
    (bytes, real)
}

fn raw(name: &str) -> Vec<u8> {
    std::fs::read(fixture(name)).unwrap()
}

// --- Exclusive: bytes identical to the source -------------------------------

#[test]
fn exclusive_16_bit_writes_the_source_pcm_unchanged() {
    let format = PcmFormat::int(44_100, 2, 16, 16);
    let mut output = FakeOutput::exclusive(format, 441);
    let (bytes, real) = render("sine_16_44100.flac", &exclusive(format), &mut output);

    let source = raw("sine_16_44100.raw");
    assert_eq!(bytes, source);
    assert_eq!(real, 11_025);
    // Whole buffers only: the tail is padded with silence after the real audio.
    let written = output.bytes();
    assert_eq!(written.len() % (441 * 4), 0);
    assert_eq!(&written[..source.len()], &source[..]);
    assert!(written[source.len()..].iter().all(|&b| b == 0));
}

#[test]
fn exclusive_24_bit_packed_writes_the_source_pcm_unchanged() {
    let format = PcmFormat::int(96_000, 2, 24, 24);
    let mut output = FakeOutput::exclusive(format, 960);
    let (bytes, real) = render("sine_24_96000.flac", &exclusive(format), &mut output);

    assert_eq!(bytes, raw("sine_24_96000.raw"));
    assert_eq!(real, 24_000);
}

#[test]
fn exclusive_24_in_32_is_the_source_with_a_zero_low_byte() {
    let format = PcmFormat::int(96_000, 2, 32, 24);
    let mut output = FakeOutput::exclusive(format, 960);
    let (bytes, _) = render("sine_24_96000.flac", &exclusive(format), &mut output);

    let expected: Vec<u8> = raw("sine_24_96000.raw")
        .chunks_exact(3)
        .flat_map(|s| [0, s[0], s[1], s[2]])
        .collect();
    assert_eq!(bytes, expected);
}

#[test]
fn exclusive_16_bit_source_in_24_in_32_keeps_every_value() {
    let format = PcmFormat::int(44_100, 2, 32, 24);
    let mut output = FakeOutput::exclusive(format, 441);
    let (bytes, _) = render("sine_16_44100.flac", &exclusive(format), &mut output);

    let expected: Vec<u8> = raw("sine_16_44100.raw")
        .chunks_exact(2)
        .flat_map(|s| [0, 0, s[0], s[1]])
        .collect();
    assert_eq!(bytes, expected);
}

// --- Shared: gain, resampling, channel mapping ------------------------------

fn floats(bytes: &[u8]) -> Vec<f32> {
    bytes
        .chunks_exact(4)
        .map(|b| f32::from_le_bytes([b[0], b[1], b[2], b[3]]))
        .collect()
}

fn zero_crossings(channel: impl Iterator<Item = f32>) -> usize {
    let samples: Vec<f32> = channel.collect();
    samples
        .windows(2)
        .filter(|pair| (pair[0] < 0.0) != (pair[1] < 0.0))
        .count()
}

#[test]
fn shared_resamples_to_the_mix_rate_with_exact_length_and_pitch() {
    let mix = PcmFormat::float(48_000, 2);
    let mut output = FakeOutput::shared(mix, 4_800);
    let (bytes, real) = render("sine_16_44100.flac", &shared(mix, 1.0), &mut output);

    // 0.25 s at 48 kHz.
    assert_eq!(real, 12_000);
    let samples = floats(&bytes);
    let left = zero_crossings(samples.iter().step_by(2).copied());
    let right = zero_crossings(samples.iter().skip(1).step_by(2).copied());
    // 440 Hz and 660 Hz over 0.25 s: 220 and 330 crossings.
    assert!((218..=222).contains(&left), "left crossings {left}");
    assert!((328..=332).contains(&right), "right crossings {right}");
    // Steady-state amplitude survives resampling (fixture is half scale).
    let peak = samples[2_000..22_000]
        .iter()
        .fold(0f32, |m, s| m.max(s.abs()));
    assert!((peak - 0.5).abs() < 0.01, "peak {peak}");
}

#[test]
fn shared_applies_software_gain() {
    let mix = PcmFormat::float(44_100, 2);
    let mut output = FakeOutput::shared(mix, 4_410);
    let (bytes, real) = render("sine_16_44100.flac", &shared(mix, 0.5), &mut output);

    assert_eq!(real, 11_025);
    let source: Vec<f32> = raw("sine_16_44100.raw")
        .chunks_exact(2)
        .map(|b| i16::from_le_bytes([b[0], b[1]]) as f32 / 32_768.0)
        .collect();
    for (out, src) in floats(&bytes).iter().zip(&source) {
        assert!((out - src * 0.5).abs() < 1e-6);
    }
}

#[test]
fn gain_changes_apply_from_the_next_block() {
    let mut decoder = Decoder::open(&fixture("sine_16_44100.flac")).unwrap();
    let mix = PcmFormat::float(44_100, 2);
    let mut converter = Converter::new(decoder.format(), &shared(mix, 1.0));
    let block = decoder.next_block().unwrap().unwrap();

    let (mut full, mut muted) = (Vec::new(), Vec::new());
    converter.convert(&block, &mut full);
    converter.set_gain(0.0);
    converter.convert(&block, &mut muted);
    assert!(floats(&full).iter().any(|s| *s != 0.0));
    assert!(floats(&muted).iter().all(|s| *s == 0.0));
}

#[test]
fn lossy_sources_render_through_shared_mode() {
    let mix = PcmFormat::float(48_000, 2);
    let mut output = FakeOutput::shared(mix, 4_800);
    let (_, real) = render("sine_44100.mp3", &shared(mix, 1.0), &mut output);
    assert_eq!(real, 12_000);
}

#[test]
fn lossy_sources_render_to_an_integer_exclusive_format() {
    let format = PcmFormat::int(44_100, 2, 32, 24);
    let negotiated = Negotiated {
        bit_perfect: false,
        reason: Some(Reason::LossySource),
        ..exclusive(format)
    };
    let mut output = FakeOutput::exclusive(format, 441);
    let (bytes, real) = render("sine_44100.mp3", &negotiated, &mut output);
    assert_eq!(real, 11_025);
    // 24-in-32: low byte always zero.
    assert!(bytes.chunks_exact(4).all(|s| s[0] == 0));
}

#[test]
fn channel_mapping_covers_mono_stereo_and_surround() {
    let mut out = Vec::new();
    map_channels(&[0.5, -0.5], 1, 2, 1.0, &mut out);
    assert_eq!(out, [0.5, 0.5, -0.5, -0.5]);

    out.clear();
    map_channels(&[0.2, 0.4], 2, 1, 1.0, &mut out);
    assert!((out[0] - 0.3).abs() < 1e-6);

    out.clear();
    map_channels(&[0.2, 0.4], 2, 6, 0.5, &mut out);
    assert_eq!(out, [0.1, 0.2, 0.0, 0.0, 0.0, 0.0]);
}

// --- Volume and bit-perfect -------------------------------------------------

#[test]
fn exclusive_volume_below_full_clears_bit_perfect() {
    let mut decoder = Decoder::open(&fixture("sine_16_44100.flac")).unwrap();
    let source = decoder.format().clone();
    let mut negotiated = exclusive(PcmFormat::int(44_100, 2, 16, 16));
    let mut policy = Policy {
        mode: OutputMode::Exclusive,
        rate_mismatch: RateMismatch::Strict,
        volume: 0.5,
        exclusive_volume: false,
    };

    negotiated.apply_volume(&source, &policy, false);
    assert!(
        negotiated.bit_perfect,
        "volume is ignored without the opt-in"
    );
    assert_eq!(negotiated.gain, 1.0);

    policy.exclusive_volume = true;
    negotiated.apply_volume(&source, &policy, false);
    assert!(!negotiated.bit_perfect);
    assert_eq!(negotiated.reason, Some(Reason::SoftwareVolume));
    assert_eq!(negotiated.gain, 0.5);

    // The converter then scales instead of copying bits.
    let mut converter = Converter::new(&source, &negotiated);
    let block = decoder.next_block().unwrap().unwrap();
    let mut scaled = Vec::new();
    converter.convert(&block, &mut scaled);
    let mut unity = Vec::new();
    Converter::new(&source, &exclusive(negotiated.output)).convert(&block, &mut unity);
    assert_ne!(scaled, unity);

    policy.volume = 1.0;
    negotiated.apply_volume(&source, &policy, false);
    assert!(negotiated.bit_perfect);

    negotiated.apply_volume(&source, &policy, true);
    assert_eq!(negotiated.reason, Some(Reason::Bluetooth));
}

// --- Device output contract -------------------------------------------------

#[test]
fn exclusive_output_pads_short_writes_and_counts_only_real_frames() {
    let format = PcmFormat::int(48_000, 2, 16, 16);
    let mut output = FakeOutput::exclusive(format, 100);
    assert_eq!(output.wait(10).unwrap(), 100);
    assert_eq!(output.write(&[1; 30 * 4]).unwrap(), 30);
    output.start().unwrap();
    output.play(100);
    assert_eq!(output.bytes().len(), 100 * 4);
    assert_eq!(output.position_frames().unwrap(), 30);
}

#[test]
fn position_skips_padding_wherever_it_was_written() {
    let mut tracker = PositionTracker::default();
    tracker.wrote(1_000, 200); // end of a short burst
    tracker.wrote(500, 0);
    assert_eq!(tracker.real_played(0), 0);
    assert_eq!(tracker.real_played(900), 900);
    assert_eq!(tracker.real_played(1_100), 1_000);
    assert_eq!(tracker.real_played(1_200), 1_000);
    assert_eq!(tracker.real_played(1_450), 1_250);
    assert_eq!(tracker.real_played(9_999), 1_500);
}

#[test]
fn flush_discards_buffered_audio_and_restarts_the_position() {
    let format = PcmFormat::float(48_000, 2);
    let mut output = FakeOutput::shared(format, 1_000);
    output.write(&[0; 600 * 8]).unwrap();
    output.start().unwrap();
    output.play(200);
    assert_eq!(output.position_frames().unwrap(), 200);
    output.flush().unwrap();
    assert_eq!(output.position_frames().unwrap(), 0);
    assert_eq!(output.wait(10).unwrap(), 1_000);
    assert!(!output.is_started());
}

#[test]
fn device_errors_surface_with_stable_codes() {
    let mut output = FakeOutput::shared(PcmFormat::float(48_000, 2), 1_000);
    output.fail_with(OutputError::DeviceLost);
    assert_eq!(output.wait(10), Err(OutputError::DeviceLost));
    assert_eq!(OutputError::DeviceLost.code(), "audio_device_lost");

    assert_eq!(map_hresult(0x8889_000A), OutputError::Busy);
    assert_eq!(map_hresult(0x8889_000E), OutputError::ExclusiveDenied);
    assert_eq!(map_hresult(0x8889_0008), OutputError::FormatUnsupported);
    assert_eq!(map_hresult(0x8889_0004), OutputError::DeviceLost);
    assert_eq!(map_hresult(0x8000_4005), OutputError::Unavailable);
}

// --- Transport --------------------------------------------------------------

#[test]
fn bluetooth_endpoints_are_recognised_by_profile() {
    // Synthetic instance paths in the shape Windows uses (no real addresses).
    let a2dp = r"{1}.BTHENUM\{0000110B-0000-1000-8000-00805F9B34FB}_VID&0001_PID&0001\7&0&000000000000_C00000000";
    let hands_free = r"{1}.BTHENUM\{0000111E-0000-1000-8000-00805F9B34FB}_VID&0001_PID&0001\7&0&000000000000_C00000000";
    let le_audio = r"{1}.BTHLEDEVICE\{00001850-0000-1000-8000-00805F9B34FB}_DEV_000000000000";
    let usb = r"{1}.USB\VID_0000&PID_0000&MI_00\6&0&0&0000";

    assert_eq!(classify_transport(a2dp, ""), Transport::Bluetooth);
    assert_eq!(
        classify_transport(hands_free, ""),
        Transport::BluetoothHandsFree
    );
    assert_eq!(classify_transport(le_audio, ""), Transport::Bluetooth);
    assert_eq!(classify_transport(usb, "USB Audio DAC"), Transport::Wired);
    assert_eq!(classify_transport("", "Realtek(R) Audio"), Transport::Wired);
    // Offloaded Bluetooth (no BTHENUM path) still shows in the adapter name.
    assert_eq!(
        classify_transport("", "Intel Smart Sound Technology for Bluetooth Audio"),
        Transport::Bluetooth
    );
}

#[test]
fn exclusive_refusals_at_open_fall_back_to_shared_with_a_reason() {
    use qtmedia_app::audio::output::exclusive_fallback;
    assert_eq!(
        exclusive_fallback(OutputError::FormatUnsupported),
        Some(Reason::FormatUnsupported)
    );
    assert_eq!(
        exclusive_fallback(OutputError::ExclusiveDenied),
        Some(Reason::ExclusiveDenied)
    );
    // A busy or lost device fails in shared mode too: report it instead.
    assert_eq!(exclusive_fallback(OutputError::Busy), None);
    assert_eq!(exclusive_fallback(OutputError::DeviceLost), None);

    let fallback = Negotiated::shared(PcmFormat::float(48_000, 2), 0.7, Reason::ExclusiveDenied);
    assert_eq!(
        (fallback.mode, fallback.gain, fallback.bit_perfect),
        (OutputMode::Shared, 0.7, false)
    );
    assert_eq!(Reason::ExclusiveDenied.code(), "exclusive_denied");
}
