import type { SignalPath } from "./bridge";

const kHz = (rate: number) => `${Number((rate / 1000).toFixed(1))} kHz`;

/** "FLAC 96 kHz · 24-bit" / "MP3 44.1 kHz". */
export function describeSource(source: SignalPath["source"]) {
  const codec = source.codec.toUpperCase();
  return source.bitsPerSample ? `${codec} ${kHz(source.sampleRate)} · ${source.bitsPerSample}-bit` : `${codec} ${kHz(source.sampleRate)}`;
}

/** "Exclusive 96 kHz · 24-bit" / "Shared 48 kHz". */
export function describeOutput(output: SignalPath["output"]) {
  const mode = output.mode === "exclusive" ? "Exclusive" : "Shared";
  return output.mode === "exclusive" && !output.float ? `${mode} ${kHz(output.sampleRate)} · ${output.bits}-bit` : `${mode} ${kHz(output.sampleRate)}`;
}

export type SignalBadge = { label: string; tone: "perfect" | "info" | "warn" };

/** The short quality label for the player bar and Now Playing. */
export function signalBadge(signal: SignalPath): SignalBadge {
  if (signal.bitPerfect) return { label: "Bit-perfect", tone: "perfect" };
  if (signal.device?.transport === "bluetoothHandsFree") return { label: "Call-quality headset", tone: "warn" };
  if (signal.device?.transport === "bluetooth" || signal.reason === "bluetooth_output") return { label: "Bluetooth · not lossless", tone: "info" };
  switch (signal.reason) {
    case "exclusive_rate_unsupported":
    case "exclusive_bits_unsupported":
    case "exclusive_format_unsupported":
    case "exclusive_denied":
      return { label: "Shared · exclusive unavailable", tone: "warn" };
    case "resampled":
      return { label: "Exclusive · resampled", tone: "info" };
    case "software_volume":
      return { label: "Exclusive · volume active", tone: "info" };
    case "lossy_source":
      return { label: "Exclusive · lossy file", tone: "info" };
    default:
      return { label: "Shared", tone: "info" };
  }
}

const reasons: Record<string, string> = {
  shared_mode: "Shared mode: Windows mixes and may resample this audio.",
  exclusive_rate_unsupported: "This device can't play the file's sample rate in exclusive mode, so Qtmedia used shared mode.",
  exclusive_bits_unsupported: "This device can't take the file's bit depth without losing bits, so Qtmedia used shared mode.",
  exclusive_format_unsupported: "This device refused exclusive mode for this format, so Qtmedia used shared mode.",
  exclusive_denied: "Windows doesn't allow apps to take exclusive control of this device (Sound settings → device properties).",
  resampled: "Resampled to a rate the device supports.",
  lossy_source: "The file itself is lossy (MP3).",
  float_output: "Converted to floating point for this device.",
  bluetooth_output: "Bluetooth re-compresses audio, so it is never lossless.",
  software_volume: "Software volume is below 100 %.",
};

/** One sentence explaining why the path is not bit-perfect (or null). */
export function signalReason(signal: SignalPath) {
  if (signal.bitPerfect) return null;
  if (signal.device?.transport === "bluetoothHandsFree") {
    return "This is the headset's call profile (mono, phone quality). Pick its \"Headphones\" output for music.";
  }
  if (signal.device?.transport === "bluetooth" && signal.reason === "shared_mode") return reasons.bluetooth_output;
  return signal.reason ? reasons[signal.reason] ?? null : null;
}
