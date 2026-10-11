/** Truthful wording for an active download: what is happening now, never an
 * invented overall percentage. Post-processing stages have no percentage. */

export type DownloadStage = "downloading" | "merging" | "converting" | "processing" | "saving";

export type ProgressInput = {
  status: "downloading" | "cancelling";
  formatLabel: string;
  stage: DownloadStage;
  stream: "video" | "audio" | null;
  part: number;
  parts: number;
  percent: number | null;
};

export type ProgressText = {
  /** Sentence for the Home panel. */
  label: string;
  /** Right-aligned value next to the label. */
  value: string;
  /** Compact text for the toolbar download ring. */
  short: string;
  /** Determinate bar value, or null for an indeterminate bar. */
  percent: number | null;
};

const stageText: Record<Exclude<DownloadStage, "downloading" | "converting">, [string, string]> = {
  merging: ["Merging video and audio", "Merging…"],
  processing: ["Finishing up", "Finishing…"],
  saving: ["Saving to your library", "Saving…"],
};

export function describeProgress(input: ProgressInput): ProgressText {
  if (input.status === "cancelling") return { label: "Cancelling download", value: "", short: "Cancelling…", percent: null };
  if (input.stage === "converting") {
    // Name the target from the chosen format ("FLAC · from …", "MP3 · 192 kbps").
    const target = input.formatLabel.split(" ")[0] || "audio";
    return { label: `Converting to ${target}`, value: "", short: "Converting…", percent: null };
  }
  if (input.stage !== "downloading") {
    const [label, short] = stageText[input.stage] ?? stageText.processing;
    return { label, value: "", short, percent: null };
  }
  const label = input.parts > 1 && input.stream
    ? `Downloading ${input.stream} (${input.part} of ${input.parts})`
    : `Downloading ${input.formatLabel}`;
  if (input.percent === null) return { label, value: "Starting", short: "Starting", percent: null };
  const value = `${Math.round(input.percent)}%`;
  return { label, value, short: value, percent: input.percent };
}
