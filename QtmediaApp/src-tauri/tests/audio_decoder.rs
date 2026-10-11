//! Decoder tests against synthetic fixtures (scripts/make-audio-fixtures.ps1).
//! Each FLAC was encoded from the same PCM as its `.raw` twin, so integer
//! decoding must reproduce the raw samples exactly.

use std::path::PathBuf;

use qtmedia_app::audio::decoder::{Block, Codec, DecodeError, Decoder};

fn fixture(name: &str) -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("tests/fixtures/audio")
        .join(name)
}

fn raw_s16(name: &str) -> Vec<i32> {
    std::fs::read(fixture(name))
        .unwrap()
        .chunks_exact(2)
        .map(|b| i16::from_le_bytes([b[0], b[1]]) as i32)
        .collect()
}

fn raw_s24(name: &str) -> Vec<i32> {
    std::fs::read(fixture(name))
        .unwrap()
        .chunks_exact(3)
        .map(|b| i32::from_le_bytes([0, b[0], b[1], b[2]]) >> 8)
        .collect()
}

/// Decodes every block; integer samples are returned in their native bit depth.
fn decode_all(decoder: &mut Decoder) -> (Vec<i32>, Vec<f32>) {
    let bits = decoder.format().bits_per_sample;
    let (mut ints, mut floats) = (Vec::new(), Vec::new());
    while let Some(block) = decoder.next_block().unwrap() {
        match block {
            Block::Int(samples) => {
                let shift = 32 - bits.expect("integer blocks carry a bit depth");
                ints.extend(samples.iter().map(|s| s >> shift));
            }
            Block::Float(samples) => floats.extend(samples),
        }
    }
    (ints, floats)
}

#[test]
fn reports_the_source_format() {
    let flac16 = Decoder::open(&fixture("sine_16_44100.flac")).unwrap();
    let f = flac16.format();
    assert_eq!(
        (f.codec, f.sample_rate, f.channels, f.bits_per_sample),
        (Codec::Flac, 44_100, 2, Some(16))
    );
    assert_eq!(f.total_frames, Some(11_025));

    let flac24 = Decoder::open(&fixture("sine_24_96000.flac")).unwrap();
    let f = flac24.format();
    assert_eq!(
        (f.codec, f.sample_rate, f.bits_per_sample, f.total_frames),
        (Codec::Flac, 96_000, Some(24), Some(24_000))
    );

    let mp3 = Decoder::open(&fixture("sine_44100.mp3")).unwrap();
    let f = mp3.format();
    assert_eq!(
        (f.codec, f.sample_rate, f.channels, f.bits_per_sample),
        (Codec::Mp3, 44_100, 2, None)
    );
}

#[test]
fn flac_16_bit_decodes_bit_exactly() {
    let mut decoder = Decoder::open(&fixture("sine_16_44100.flac")).unwrap();
    let (ints, floats) = decode_all(&mut decoder);

    assert!(floats.is_empty());
    assert_eq!(ints, raw_s16("sine_16_44100.raw"));
}

#[test]
fn flac_24_bit_decodes_bit_exactly() {
    let mut decoder = Decoder::open(&fixture("sine_24_96000.flac")).unwrap();
    let (ints, _) = decode_all(&mut decoder);

    assert_eq!(ints, raw_s24("sine_24_96000.raw"));
}

#[test]
fn integer_blocks_are_left_justified_for_24_in_32_output() {
    let mut decoder = Decoder::open(&fixture("sine_16_44100.flac")).unwrap();
    let Some(Block::Int(samples)) = decoder.next_block().unwrap() else {
        panic!("expected integer samples");
    };
    assert!(
        samples.iter().all(|s| s & 0xFFFF == 0),
        "16-bit samples occupy the top bits"
    );
}

#[test]
fn mp3_decodes_gaplessly_to_the_encoded_length() {
    let mut decoder = Decoder::open(&fixture("sine_44100.mp3")).unwrap();
    let (ints, floats) = decode_all(&mut decoder);

    assert!(ints.is_empty());
    // LAME delay and padding are trimmed: 0.25 s at 44.1 kHz, stereo.
    assert_eq!(floats.len(), 11_025 * 2);
}

#[test]
fn seeking_lands_on_the_exact_frame() {
    let mut decoder = Decoder::open(&fixture("sine_16_44100.flac")).unwrap();

    let frame = decoder.seek(0.1).unwrap();
    assert_eq!(frame, 4_410);

    let (ints, _) = decode_all(&mut decoder);
    let raw = raw_s16("sine_16_44100.raw");
    assert_eq!(ints, raw[4_410 * 2..]);
}

#[test]
fn seeking_past_the_end_is_clamped() {
    let mut decoder = Decoder::open(&fixture("sine_16_44100.flac")).unwrap();

    assert_eq!(decoder.seek(99.0).unwrap(), 11_025);
    assert!(decoder.next_block().unwrap().is_none());
}

#[test]
fn unreadable_inputs_are_errors_not_panics() {
    let missing = Decoder::open(&fixture("does-not-exist.flac"));
    assert!(matches!(missing, Err(DecodeError::Io)));

    let raw_pcm = Decoder::open(&fixture("sine_16_44100.raw"));
    assert!(matches!(raw_pcm, Err(DecodeError::Unsupported)));
}

/// Opt-in check on a real library file:
/// `QTMEDIA_DECODE_FILE=<path> cargo test --test audio_decoder -- --ignored`
#[test]
#[ignore = "needs QTMEDIA_DECODE_FILE pointing at a real FLAC or MP3"]
fn decodes_a_real_library_file() {
    let path =
        PathBuf::from(std::env::var("QTMEDIA_DECODE_FILE").expect("set QTMEDIA_DECODE_FILE"));
    let mut decoder = Decoder::open(&path).unwrap();
    let format = decoder.format().clone();
    let (ints, floats) = decode_all(&mut decoder);
    let frames = (ints.len() + floats.len()) as u64 / format.channels as u64;
    println!(
        "{format:?} -> decoded {frames} frames ({:.2} s)",
        frames as f64 / format.sample_rate as f64
    );
    if let Some(total) = format.total_frames {
        assert_eq!(frames, total);
    }
    assert!(frames > 0);
}
