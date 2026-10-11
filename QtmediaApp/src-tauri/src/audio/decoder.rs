//! Library audio decoding for the native engine (FLAC and MP3, via symphonia).
//!
//! Lossless sources come out as interleaved **left-justified `i32`** samples
//! plus their true bit depth, so 16- and 24-bit PCM reaches an exclusive-mode
//! device unchanged (24-in-32 directly, or shifted down for packed formats).
//! Lossy sources come out as interleaved `f32`.

use std::fs::File;
use std::path::Path;

use symphonia::core::codecs::audio::well_known::{CODEC_ID_FLAC, CODEC_ID_MP3};
use symphonia::core::codecs::audio::{AudioDecoder, AudioDecoderOptions};
use symphonia::core::errors::Error as SymphoniaError;
use symphonia::core::formats::probe::Hint;
use symphonia::core::formats::{FormatOptions, FormatReader, SeekMode, SeekTo, TrackType};
use symphonia::core::io::MediaSourceStream;
use symphonia::core::meta::MetadataOptions;
use symphonia::core::units::Timestamp;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Codec {
    Flac,
    Mp3,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SourceFormat {
    pub codec: Codec,
    pub sample_rate: u32,
    pub channels: u16,
    /// Integer bit depth for lossless sources; `None` for lossy (float) ones.
    pub bits_per_sample: Option<u32>,
    pub total_frames: Option<u64>,
}

/// Interleaved samples for one decoded packet.
#[derive(Debug, Clone, PartialEq)]
pub enum Block {
    /// Left-justified: a 16-bit sample `s` is stored as `s << 16`.
    Int(Vec<i32>),
    Float(Vec<f32>),
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DecodeError {
    Io,
    Unsupported,
    Corrupt,
}

impl std::fmt::Display for DecodeError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(match self {
            Self::Io => "audio_io",
            Self::Unsupported => "audio_format_unsupported",
            Self::Corrupt => "audio_decode_failed",
        })
    }
}

impl std::error::Error for DecodeError {}

fn map_error(error: SymphoniaError) -> DecodeError {
    match error {
        SymphoniaError::IoError(_) => DecodeError::Io,
        SymphoniaError::Unsupported(_) => DecodeError::Unsupported,
        _ => DecodeError::Corrupt,
    }
}

pub struct Decoder {
    reader: Box<dyn FormatReader>,
    decoder: Box<dyn AudioDecoder>,
    track_id: u32,
    format: SourceFormat,
    /// Frames still to drop after an accurate seek lands before the target.
    skip_frames: u64,
    ended: bool,
}

impl Decoder {
    pub fn open(path: &Path) -> Result<Self, DecodeError> {
        let file = File::open(path).map_err(|_| DecodeError::Io)?;
        let stream = MediaSourceStream::new(Box::new(file), Default::default());
        let mut hint = Hint::new();
        if let Some(extension) = path.extension().and_then(|value| value.to_str()) {
            hint.with_extension(extension);
        }
        let reader = symphonia::default::get_probe()
            .probe(
                &hint,
                stream,
                FormatOptions::default(),
                MetadataOptions::default(),
            )
            .map_err(|error| match error {
                SymphoniaError::IoError(_) | SymphoniaError::Unsupported(_) => {
                    DecodeError::Unsupported
                }
                other => map_error(other),
            })?;
        let track = reader
            .default_track(TrackType::Audio)
            .ok_or(DecodeError::Unsupported)?;
        let params = track
            .codec_params
            .as_ref()
            .and_then(|params| params.audio())
            .ok_or(DecodeError::Unsupported)?;
        let codec = match params.codec {
            CODEC_ID_FLAC => Codec::Flac,
            CODEC_ID_MP3 => Codec::Mp3,
            _ => return Err(DecodeError::Unsupported),
        };
        let format = SourceFormat {
            codec,
            sample_rate: params.sample_rate.ok_or(DecodeError::Unsupported)?,
            channels: params
                .channels
                .as_ref()
                .map(|channels| channels.count() as u16)
                .ok_or(DecodeError::Unsupported)?,
            bits_per_sample: match codec {
                Codec::Flac => Some(params.bits_per_sample.ok_or(DecodeError::Unsupported)?),
                Codec::Mp3 => None,
            },
            total_frames: track.num_frames,
        };
        let decoder = symphonia::default::get_codecs()
            .make_audio_decoder(params, &AudioDecoderOptions::default())
            .map_err(map_error)?;
        let track_id = track.id;
        Ok(Self {
            reader,
            decoder,
            track_id,
            format,
            skip_frames: 0,
            ended: false,
        })
    }

    pub fn format(&self) -> &SourceFormat {
        &self.format
    }

    /// The next packet's samples, or `None` at the end of the track.
    pub fn next_block(&mut self) -> Result<Option<Block>, DecodeError> {
        let channels = self.format.channels as usize;
        loop {
            if self.ended {
                return Ok(None);
            }
            let packet = match self.reader.next_packet() {
                Ok(Some(packet)) => packet,
                Ok(None) => {
                    self.ended = true;
                    return Ok(None);
                }
                Err(error) => return Err(map_error(error)),
            };
            if packet.track_id != self.track_id {
                continue;
            }
            let decoded = self.decoder.decode(&packet).map_err(map_error)?;
            let frames = decoded.frames() as u64;
            let skip = self.skip_frames.min(frames) as usize * channels;
            self.skip_frames -= self.skip_frames.min(frames);
            let block = match self.format.codec {
                Codec::Flac => {
                    let mut samples: Vec<i32> = Vec::with_capacity(frames as usize * channels);
                    decoded.copy_to_vec_interleaved(&mut samples);
                    Block::Int(samples.split_off(skip))
                }
                Codec::Mp3 => {
                    let mut samples: Vec<f32> = Vec::with_capacity(frames as usize * channels);
                    decoded.copy_to_vec_interleaved(&mut samples);
                    Block::Float(samples.split_off(skip))
                }
            };
            let empty = match &block {
                Block::Int(samples) => samples.is_empty(),
                Block::Float(samples) => samples.is_empty(),
            };
            if !empty {
                return Ok(Some(block));
            }
        }
    }

    /// Seek to `seconds`, sample-accurately. Returns the frame playback resumes
    /// from (clamped to the track length).
    pub fn seek(&mut self, seconds: f64) -> Result<u64, DecodeError> {
        let rate = self.format.sample_rate as f64;
        let mut target = (seconds.max(0.0) * rate).round() as u64;
        if let Some(total) = self.format.total_frames {
            if target >= total {
                self.ended = true;
                self.skip_frames = 0;
                return Ok(total);
            }
            target = target.min(total);
        }
        let seeked = self
            .reader
            .seek(
                SeekMode::Accurate,
                SeekTo::Timestamp {
                    ts: Timestamp::new(target as i64),
                    track_id: self.track_id,
                },
            )
            .map_err(map_error)?;
        self.decoder.reset();
        self.ended = false;
        // The reader lands on or before the target; drop the difference.
        self.skip_frames = (target as i64 - seeked.actual_ts.get()).max(0) as u64;
        Ok(target)
    }
}
