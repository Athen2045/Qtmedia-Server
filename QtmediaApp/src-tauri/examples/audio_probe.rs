//! Task 0 hardware probe for the native audio engine (dev-only, not shipped).
//!
//! cargo run --example audio_probe -- list
//! cargo run --example audio_probe -- matrix <index|default>
//! cargo run --example audio_probe -- tone <index|default> <rate> <store_bits> <valid_bits> [aligned|default|default-aligned|min]
//! cargo run --example audio_probe -- play <index|default> <file> <shared|exclusive> [volume]
//! cargo run --example audio_probe -- engine <index|default> <file> <shared|exclusive> [next_file]
//!
//! `play` runs the engine's own pipeline (decoder, negotiation, converter,
//! WasapiShared/WasapiExclusive). A volume below 1 in exclusive mode uses the
//! opt-in software volume, so the path is reported as not bit-perfect.
//! `engine` runs the threaded `AudioEngine` (control, decoder and render
//! threads) and prints its events; with `next_file` it queues a second track.
//!
//! The tone is a 440 Hz sine at -30 dBFS for 1.5 s. Exclusive mode bypasses the
//! Windows volume, so keep the amplifier low.

use std::error::Error;
use std::f64::consts::PI;
use std::path::Path;
use std::sync::Arc;
use std::time::{Duration, Instant};

use qtmedia_app::audio::convert::Converter;
use qtmedia_app::audio::decoder::Decoder;
use qtmedia_app::audio::engine::{
    AudioEngine, Command, Event, PlayState, Settings, WasapiPlatform,
};
use qtmedia_app::audio::format::{negotiate, OutputMode, Policy, RateMismatch};
use qtmedia_app::audio::output::{list_devices, open_output, WasapiCaps};

use wasapi::{
    initialize_mta, Device, DeviceEnumerator, Direction, SampleType, ShareMode, StreamMode,
    WaveFormat,
};

type Res<T> = Result<T, Box<dyn Error>>;

const RATES: [usize; 8] = [
    44_100, 48_000, 88_200, 96_000, 176_400, 192_000, 352_800, 384_000,
];
const LAYOUTS: [(usize, usize, SampleType, &str); 5] = [
    (16, 16, SampleType::Int, "16"),
    (24, 24, SampleType::Int, "24"),
    (32, 24, SampleType::Int, "24in32"),
    (32, 32, SampleType::Int, "32"),
    (32, 32, SampleType::Float, "f32"),
];

fn describe(format: &WaveFormat) -> String {
    let kind = match format.get_subformat() {
        Ok(SampleType::Float) => "float",
        Ok(SampleType::Int) => "int",
        Err(_) => "?",
    };
    format!(
        "{} Hz, {}-bit {} in {}-bit, {} ch",
        format.get_samplespersec(),
        format.get_validbitspersample(),
        kind,
        format.get_bitspersample(),
        format.get_nchannels()
    )
}

fn devices() -> Res<Vec<Device>> {
    let collection = DeviceEnumerator::new()?.get_device_collection(&Direction::Render)?;
    let mut all = Vec::new();
    for device in &collection {
        all.push(device?);
    }
    Ok(all)
}

fn pick(which: &str) -> Res<Device> {
    if which == "default" {
        return Ok(DeviceEnumerator::new()?.get_default_device(&Direction::Render)?);
    }
    let index: usize = which.parse()?;
    devices()?
        .into_iter()
        .nth(index)
        .ok_or_else(|| "no device at that index".into())
}

fn list() -> Res<()> {
    let default_id = DeviceEnumerator::new()?
        .get_default_device(&Direction::Render)?
        .get_id()?;
    for (index, device) in devices()?.iter().enumerate() {
        let marker = if device.get_id()? == default_id {
            " (default)"
        } else {
            ""
        };
        println!("[{index}] {}{marker}", device.get_friendlyname()?);
        println!("    state: {:?}", device.get_state()?);
        let client = device.get_iaudioclient()?;
        match client.get_mixformat() {
            Ok(mix) => println!("    shared mix format: {}", describe(&mix)),
            Err(error) => println!("    shared mix format: unavailable ({error})"),
        }
        if let Some(info) = list_devices()?
            .into_iter()
            .find(|info| info.id == device.get_id().unwrap_or_default())
        {
            println!("    transport: {:?}", info.transport);
        }
        match client.get_device_period() {
            Ok((default, minimum)) => println!(
                "    periods: default {:.2} ms, minimum {:.2} ms",
                default as f64 / 10_000.0,
                minimum as f64 / 10_000.0
            ),
            Err(error) => println!("    periods: unavailable ({error})"),
        }
    }
    Ok(())
}

fn matrix(which: &str) -> Res<()> {
    let device = pick(which)?;
    println!(
        "Exclusive-mode support for {} (stereo):",
        device.get_friendlyname()?
    );
    print!("{:>10}", "rate");
    for (_, _, _, name) in LAYOUTS {
        print!("{name:>9}");
    }
    println!();
    let client = device.get_iaudioclient()?;
    for rate in RATES {
        print!("{rate:>10}");
        for (store, valid, kind, _) in LAYOUTS {
            let format = WaveFormat::new(store, valid, &kind, rate, 2, None);
            let ok = client.is_supported_exclusive_with_quirks(&format).is_ok();
            print!("{:>9}", if ok { "yes" } else { "-" });
        }
        println!();
    }
    let shared_ok = |rate| {
        let format = WaveFormat::new(32, 32, &SampleType::Float, rate, 2, None);
        client
            .is_supported(&format, &ShareMode::Shared)
            .ok()
            .flatten()
            .is_none()
    };
    println!(
        "(shared mode accepts 48 kHz f32 as is: {})",
        shared_ok(48_000)
    );
    Ok(())
}

fn tone(which: &str, rate: usize, store: usize, valid: usize, strategy: &str) -> Res<()> {
    let device = pick(which)?;
    let mut client = device.get_iaudioclient()?;
    let format = WaveFormat::new(store, valid, &SampleType::Int, rate, 2, None);
    let format = client.is_supported_exclusive_with_quirks(&format)?;
    let (default_period, min_period) = client.get_device_period()?;
    let period = match strategy {
        "default" => default_period,
        "min" => min_period,
        "default-aligned" => {
            client.calculate_aligned_period_near(default_period, Some(128), &format)?
        }
        _ => client.calculate_aligned_period_near(3 * min_period / 2, Some(128), &format)?,
    };
    client.initialize_client(
        &format,
        &Direction::Render,
        &StreamMode::EventsExclusive { period_hns: period },
    )?;
    let event = client.set_get_eventhandle()?;
    let render = client.get_audiorenderclient()?;
    let buffer_frames = client.get_buffer_size()? as usize;
    println!(
        "Exclusive on {}: {}, period {:.2} ms, buffer {} frames",
        device.get_friendlyname()?,
        describe(&format),
        period as f64 / 10_000.0,
        buffer_frames
    );

    let bytes_per_sample = store / 8;
    let amplitude = 10f64.powf(-30.0 / 20.0);
    let full_scale = ((1i64 << (valid - 1)) - 1) as f64;
    let shift = store - valid; // 24-in-32 is left-justified.
    let total = rate * 3 / 2;
    let mut written = 0usize;
    let mut started = false;
    while written < total {
        let available = if started {
            client
                .get_available_space_in_frames()
                .map_err(|e| format!("available_space after {written} frames: {e:?}"))?
                as usize
        } else {
            buffer_frames
        };
        if std::env::var("PROBE_TRACE").is_ok() && written < 4 * buffer_frames {
            println!("  iteration at {written}: available {available} (buffer {buffer_frames})");
        }
        let frames = available;
        let mut data = Vec::with_capacity(frames * 2 * bytes_per_sample);
        for frame in 0..frames {
            let t = (written + frame) as f64 / rate as f64;
            let value = ((amplitude * (2.0 * PI * 440.0 * t).sin() * full_scale) as i64) << shift;
            for _ in 0..2 {
                data.extend_from_slice(&value.to_le_bytes()[..bytes_per_sample]);
            }
        }
        render
            .write_to_device(frames, &data, None)
            .map_err(|e| format!("write_to_device({frames} frames) after {written}: {e:?}"))?;
        written += frames;
        if !started {
            client.start_stream()?;
            started = true;
        }
        event
            .wait_for_event(1000)
            .map_err(|e| format!("wait_for_event after {written}: {e:?}"))?;
    }
    client.stop_stream()?;
    println!(
        "Played {total} frames ({:.2} s) in {written} buffered frames.",
        total as f64 / rate as f64
    );
    Ok(())
}

fn play(which: &str, file: &str, mode: &str, volume: f32) -> Res<()> {
    let id = match which {
        "default" => None,
        _ => Some(pick(which)?.get_id()?),
    };
    let caps = WasapiCaps::open(id.as_deref())?;
    let mut decoder = Decoder::open(Path::new(file))?;
    let source = decoder.format().clone();
    let policy = Policy {
        mode: if mode == "exclusive" {
            OutputMode::Exclusive
        } else {
            OutputMode::Shared
        },
        rate_mismatch: RateMismatch::Strict,
        volume,
        exclusive_volume: volume < 1.0,
    };
    let negotiated = negotiate(&source, &caps, &policy);
    println!("device: {} ({:?})", caps.id(), caps.transport());
    println!("source: {source:?}");
    let (mut output, negotiated) = open_output(&caps, negotiated, volume)?;
    println!(
        "output: {:?} {:?}, gain {}, bit-perfect {}, reason {:?}",
        negotiated.mode,
        negotiated.output,
        negotiated.gain,
        negotiated.bit_perfect,
        negotiated.reason.map(|reason| reason.code())
    );
    assert_eq!(output.format(), negotiated.output, "device format");
    let mut converter = Converter::new(&source, &negotiated);
    let frame = output.format().bytes_per_frame();
    let (mut pending, mut ended, mut started, mut real) = (Vec::new(), false, false, 0u64);
    let began = Instant::now();
    loop {
        let space = output.wait(1000)?;
        while pending.len() < space * frame && !ended {
            match decoder.next_block()? {
                Some(block) => converter.convert(&block, &mut pending),
                None => {
                    converter.finish(&mut pending);
                    ended = true;
                }
            }
        }
        if ended && pending.is_empty() && output.position_frames()? >= real {
            break;
        }
        if space == 0 {
            continue;
        }
        let take = (space * frame).min(pending.len());
        real += output.write(&pending[..take])? as u64;
        pending.drain(..take);
        if !started {
            output.start()?;
            started = true;
        }
        if began.elapsed() > Duration::from_secs(600) {
            break;
        }
    }
    output.pause()?;
    let rate = f64::from(output.format().rate);
    println!(
        "played {real} frames ({:.3} s) in {:.3} s wall time",
        real as f64 / rate,
        began.elapsed().as_secs_f64()
    );
    Ok(())
}

fn engine(which: &str, file: &str, mode: &str, next: Option<&str>) -> Res<()> {
    let device = match which {
        "default" => None,
        _ => Some(pick(which)?.get_id()?),
    };
    let settings = Settings {
        device,
        mode: if mode == "exclusive" {
            OutputMode::Exclusive
        } else {
            OutputMode::Shared
        },
        ..Settings::default()
    };
    let (events, inbox) = std::sync::mpsc::channel();
    let began = Instant::now();
    let engine = AudioEngine::spawn(Arc::new(WasapiPlatform), settings, 1.0, move |event| {
        let _ = events.send(event);
    })?;
    // Queue the next track first: a short file is fully decoded before a
    // later `SetNext` arrives, which would test the non-gapless path instead.
    if let Some(next) = next {
        engine.send(Command::SetNext(Some(next.into())));
    }
    engine.send(Command::Play {
        path: file.into(),
        start_seconds: 0.0,
    });
    while let Ok(event) = inbox.recv_timeout(Duration::from_secs(30)) {
        let at = began.elapsed().as_secs_f64();
        match &event {
            Event::Position { .. } => {}
            Event::SignalPath { negotiated, .. } => println!(
                "{at:7.3} s  signal: {:?} {:?} bit-perfect {} reason {:?}",
                negotiated.mode,
                negotiated.output,
                negotiated.bit_perfect,
                negotiated.reason.map(|reason| reason.code())
            ),
            other => println!("{at:7.3} s  {other:?}"),
        }
        if matches!(
            event,
            Event::State(PlayState::Idle) | Event::State(PlayState::Stopped)
        ) {
            break;
        }
    }
    drop(engine);
    Ok(())
}

fn main() -> Res<()> {
    initialize_mta().ok()?;
    let args: Vec<String> = std::env::args().skip(1).collect();
    match args
        .iter()
        .map(String::as_str)
        .collect::<Vec<_>>()
        .as_slice()
    {
        ["list"] => list(),
        ["matrix", which] => matrix(which),
        ["tone", which, rate, store, valid] => tone(
            which,
            rate.parse()?,
            store.parse()?,
            valid.parse()?,
            "aligned",
        ),
        ["tone", which, rate, store, valid, strategy] => tone(
            which,
            rate.parse()?,
            store.parse()?,
            valid.parse()?,
            strategy,
        ),
        ["play", which, file, mode] => play(which, file, mode, 1.0),
        ["play", which, file, mode, volume] => play(which, file, mode, volume.parse()?),
        ["engine", which, file, mode] => engine(which, file, mode, None),
        ["engine", which, file, mode, next] => engine(which, file, mode, Some(next)),
        _ => Err(
            "usage: list | matrix <index|default> | tone <index|default> <rate> <store> <valid> | play <index|default> <file> <shared|exclusive> [volume] | engine <index|default> <file> <shared|exclusive> [next_file]"
                .into(),
        ),
    }
}
