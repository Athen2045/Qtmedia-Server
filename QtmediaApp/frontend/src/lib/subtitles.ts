import { useEffect, useState } from "react";

import type { DesktopBridge } from "./bridge";

/** Subtitle tracks of a library video, as `read_subtitles` returns them. */
export type SubtitleTrack = {
  /** `file:<name>` or `stream:<index>`. */
  id: string;
  label: string | null;
  /** As written in the file name or stream tag: `en`, `eng`, `pt-BR`. */
  language: string | null;
  /** `qtmedia://` path of the WebVTT copy. */
  url: string;
};

export type Subtitles = { tracks: SubtitleTrack[]; unsupported: number };

/** ISO 639-2 codes (common in MKV tags) → the two-letter codes browsers use. */
const THREE_LETTER: Record<string, string> = {
  ara: "ar", bul: "bg", chi: "zh", zho: "zh", cze: "cs", ces: "cs", dan: "da", dut: "nl", nld: "nl", eng: "en", fin: "fi",
  fre: "fr", fra: "fr", ger: "de", deu: "de", gre: "el", ell: "el", heb: "he", hin: "hi", hun: "hu", hrv: "hr", ice: "is", isl: "is", est: "et", ind: "id",
  ita: "it", jpn: "ja", kor: "ko", mal: "ml", may: "ms", msa: "ms", nor: "no", per: "fa", fas: "fa", pol: "pl",
  por: "pt", rum: "ro", ron: "ro", rus: "ru", spa: "es", swe: "sv", tam: "ta", tel: "te", tha: "th", tur: "tr",
  ukr: "uk", vie: "vi",
};

/** A BCP 47 tag for `<track srclang>`, or "" when unknown. */
export function languageTag(language: string | null): string {
  if (!language) return "";
  const [base, ...region] = language.split("-");
  const lower = base.toLowerCase();
  const short = lower.length === 3 ? THREE_LETTER[lower] ?? lower : lower;
  return [short, ...region].join("-");
}

function languageName(language: string | null): string | null {
  const tag = languageTag(language);
  if (!tag) return null;
  try {
    const name = new Intl.DisplayNames(undefined, { type: "language" }).of(tag);
    return name && name.toLowerCase() !== tag.toLowerCase() ? name : language!.toUpperCase();
  } catch {
    return language!.toUpperCase();
  }
}

/** What the captions menu shows: "English", "English · Forced", "Director", "Subtitles 2". */
export function trackLabel(track: SubtitleTrack, index: number): string {
  const language = languageName(track.language);
  if (language && track.label) return `${language} · ${track.label}`;
  return language ?? track.label ?? (index === 0 ? "Subtitles" : `Subtitles ${index + 1}`);
}

/** The viewer's last subtitle choice, applied to every video. */
export type SubtitleChoice = { enabled: boolean; language?: string; label?: string };
const CHOICE_KEY = "qtmedia.video.subtitles";

export function readSubtitleChoice(): SubtitleChoice {
  try {
    const saved = JSON.parse(localStorage.getItem(CHOICE_KEY) ?? "null") as SubtitleChoice | null;
    if (!saved || typeof saved.enabled !== "boolean") return { enabled: false };
    return {
      enabled: saved.enabled,
      ...(typeof saved.language === "string" ? { language: saved.language } : {}),
      ...(typeof saved.label === "string" ? { label: saved.label } : {}),
    };
  } catch {
    return { enabled: false };
  }
}

export function writeSubtitleChoice(choice: SubtitleChoice) {
  try {
    localStorage.setItem(CHOICE_KEY, JSON.stringify(choice));
  } catch {
    // A convenience only.
  }
}

/** The track to show for `choice`: same language, else same label, else the first. */
export function pickTrack(tracks: SubtitleTrack[], choice: SubtitleChoice): SubtitleTrack | null {
  if (!choice.enabled || !tracks.length) return null;
  const wanted = languageTag(choice.language ?? null).toLowerCase();
  const byLanguage = wanted ? tracks.filter((track) => languageTag(track.language).toLowerCase() === wanted) : [];
  return (choice.label !== undefined ? byLanguage.find((track) => track.label === choice.label) : undefined)
    ?? byLanguage[0]
    ?? tracks.find((track) => choice.label && track.label === choice.label)
    ?? tracks[0];
}

/** Menu names for all tracks, numbering repeats: "English", "English (2)". */
export function trackLabels(tracks: SubtitleTrack[]): string[] {
  const seen = new Map<string, number>();
  return tracks.map((track, index) => {
    const label = trackLabel(track, index);
    const count = (seen.get(label) ?? 0) + 1;
    seen.set(label, count);
    return count === 1 ? label : `${label} (${count})`;
  });
}

/** A video's subtitle tracks; empty while loading, without a bridge, or on errors. */
export function useSubtitles(bridge: DesktopBridge, relativePath: string, token: number): Subtitles & { loading: boolean } {
  const [state, setState] = useState<Subtitles & { loading: boolean; path: string }>({ tracks: [], unsupported: 0, loading: true, path: relativePath });
  useEffect(() => {
    if (!bridge.readSubtitles) {
      setState({ tracks: [], unsupported: 0, loading: false, path: relativePath });
      return;
    }
    let active = true;
    setState((current) => (current.path === relativePath ? { ...current, loading: true } : { tracks: [], unsupported: 0, loading: true, path: relativePath }));
    bridge.readSubtitles(relativePath).then(
      (result) => { if (active) setState({ tracks: result.tracks ?? [], unsupported: result.unsupported ?? 0, loading: false, path: relativePath }); },
      () => { if (active) setState({ tracks: [], unsupported: 0, loading: false, path: relativePath }); },
    );
    return () => { active = false; };
  }, [bridge, relativePath, token]);
  // Never show the previous video's tracks on the next one.
  return state.path === relativePath ? state : { tracks: [], unsupported: 0, loading: true };
}
