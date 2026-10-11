import { useEffect, useState } from "react";

import type { DesktopBridge, LibraryEntry, TrackInfo } from "./bridge";
import { mediaTitle } from "./library";

export type LyricLine = { time: number; text: string };
/** Song details carried by lyrics: LRC `[ti:]`/`[ar:]`/`[al:]` headers or the LRCLIB match. */
export type SongMeta = { title: string | null; artist: string | null; album: string | null };
export type Lyrics =
  | { kind: "synced"; lines: LyricLine[]; source: "local" | "lrclib"; meta?: SongMeta }
  | { kind: "plain"; text: string; source: "local" | "lrclib"; meta?: SongMeta };
export type LyricsState = { status: "loading" } | { status: "none" } | { status: "ready"; lyrics: Lyrics };

const LRCLIB = "https://lrclib.net/api";
const CACHE_PREFIX = "qtmedia.lyrics.v4:";
const ONLINE_KEY = "qtmedia.lyrics.online";
/** Re-check songs that had no lyrics after a week. */
const MISS_TTL_MS = 7 * 24 * 3600 * 1000;

/**
 * Parses LRC text. Supports several timestamps per line, `[mm:ss]` and
 * `[mm:ss.xx]`/`[mm:ss.xxx]`, and the `[offset:±ms]` tag; ignores other tags.
 */
export function parseLrc(text: string): LyricLine[] {
  const lines: LyricLine[] = [];
  let offset = 0;
  for (const raw of text.split(/\r?\n/)) {
    const offsetTag = /^\[offset:\s*([+-]?\d+)\s*\]/i.exec(raw.trim());
    if (offsetTag) {
      offset = Number(offsetTag[1]) / 1000;
      continue;
    }
    const stamps = [...raw.matchAll(/\[(\d{1,3}):(\d{1,2})(?:[.:](\d{1,3}))?\]/g)];
    if (!stamps.length) continue;
    const lyric = raw.replace(/\[[^\]]*\]/g, "").trim();
    for (const [, minutes, seconds, fraction = "0"] of stamps) {
      const fractionSeconds = Number(fraction) / 10 ** fraction.length;
      lines.push({ time: Number(minutes) * 60 + Number(seconds) + fractionSeconds, text: lyric });
    }
  }
  // A positive offset means lyrics should appear earlier.
  return lines.map((line) => ({ ...line, time: Math.max(0, line.time - offset) })).sort((a, b) => a.time - b.time);
}

/** Index of the line being sung at `seconds`, or -1 before the first line. */
export function activeLineIndex(lines: LyricLine[], seconds: number) {
  let low = 0;
  let high = lines.length - 1;
  let found = -1;
  while (low <= high) {
    const middle = (low + high) >> 1;
    if (lines[middle].time <= seconds) {
      found = middle;
      low = middle + 1;
    } else {
      high = middle - 1;
    }
  }
  return found;
}

const NOISE = /\s*[([][^)\]]*\b(official|video|audio|lyrics?|visuali[sz]er|hd|hq|4k|mv|remaster(ed)?|explicit|clean)\b[^)\]]*[)\]]/gi;

/** Strips download noise like "(Official Video)" or "[Lyrics]" from a title. */
export function searchQuery(title: string) {
  return title.replace(NOISE, "").replace(/\s+/g, " ").replace(/[\s\-–|]+$/, "").trim();
}

type LrclibResult = { trackName?: string; artistName?: string; albumName?: string; duration?: number; instrumental?: boolean; syncedLyrics?: string | null; plainLyrics?: string | null };

/** Letters outside the Latin script (CJK, Cyrillic, Arabic, …). */
const NON_LATIN = /[^\p{Script=Latin}\p{Script=Common}\p{Script=Inherited}]/u;
const normalize = (value: string) => value.toLocaleLowerCase().replace(/[^\p{L}\p{N}]+/gu, " ").trim();

/**
 * Chooses the best search result: duration close to the song, synced
 * preferred, then the cleanest entry for display (same track name, and Latin
 * names for a Latin title rather than a translated duplicate).
 */
export function pickBest(results: LrclibResult[], durationSeconds: number | null, track: string | null = null): LrclibResult | null {
  let best: LrclibResult | null = null;
  let bestScore = -Infinity;
  const latinTitle = track !== null && !NON_LATIN.test(track);
  for (const result of results) {
    if (result.instrumental || !(result.syncedLyrics || result.plainLyrics)) continue;
    let score = result.syncedLyrics ? 10 : 0;
    if (durationSeconds && result.duration) {
      const gap = Math.abs(result.duration - durationSeconds);
      if (gap > 8) continue; // probably a different recording
      score += 10 - gap;
    }
    if (track && result.trackName && normalize(result.trackName) === normalize(track)) score += 3;
    if (latinTitle && NON_LATIN.test(`${result.artistName ?? ""} ${result.albumName ?? ""}`)) score -= 5;
    if (result.albumName && PLACEHOLDER_ALBUM.test(result.albumName.trim())) score -= 1;
    if (score > bestScore) {
      best = result;
      bestScore = score;
    }
  }
  return best;
}

/** LRCLIB entries sometimes carry a filler album name. */
const PLACEHOLDER_ALBUM = /^(unnamed|unknown|untitled|null|none|n\/a|-+)$/i;

/** "Song (Remastered 2011)" / "Song - Live" → "Song" (as SpotiFLAC does). */
export function simplifyTrackName(name: string) {
  let simple = name;
  const paren = simple.indexOf("(");
  if (paren > 0) simple = simple.slice(0, paren).trim();
  const dash = simple.indexOf(" - ");
  if (dash > 0) simple = simple.slice(0, dash).trim();
  return simple;
}

/** "A, B & C feat. D" → "A": LRCLIB lists the lead artist. */
export function primaryArtist(credit: string | null | undefined) {
  const lead = credit?.split(/\s*(?:,|&|;|\/|\bfeat\.?\s|\bft\.?\s)\s*/i)[0]?.trim();
  return lead || null;
}

export type SongQuery = { track: string; artist: string | null; album: string | null; duration: number | null };

/**
 * What to match on: the file's tags when present; otherwise the cleaned
 * file title, split as "Artist - Title" when it has that shape.
 */
export function songQuery(entry: LibraryEntry, info: TrackInfo | null): SongQuery | null {
  const duration = info?.durationSeconds ?? entry.durationSeconds ?? null;
  const artist = primaryArtist(info?.artist);
  const album = info?.album?.trim() || null;
  const title = searchQuery(info?.title?.trim() || mediaTitle(entry));
  if (!title) return null;
  if (artist) return { track: title, artist, album, duration };
  const split = /^(.+?)\s+[-–]\s+(.+)$/.exec(title);
  if (split) return { track: split[2].trim(), artist: primaryArtist(split[1]), album: null, duration };
  return { track: title, artist, album, duration };
}

type Step = { kind: "get" | "search"; track: string; artist: string | null; album: string | null };

/**
 * LRCLIB lookups in order, after SpotiFLAC's `FetchLyricsAllSources`
 * (github.com/spotbye/SpotiFLAC, MIT): exact match with album, exact without
 * album, artist + title search, title-only search, then the same with the
 * simplified title. For untagged "Artist - Title" names the title-only search
 * also tries the whole name.
 */
export function lookupSteps(query: SongQuery, wholeName: string | null = null): Step[] {
  const steps: Step[] = [];
  const add = (step: Step) => {
    if (!steps.some((other) => JSON.stringify(other) === JSON.stringify(step))) steps.push(step);
  };
  const forTrack = (track: string) => {
    if (query.artist) {
      add({ kind: "get", track, artist: query.artist, album: query.album });
      if (query.album) add({ kind: "get", track, artist: query.artist, album: null });
      add({ kind: "search", track, artist: query.artist, album: null });
    }
    add({ kind: "search", track, artist: null, album: null });
  };
  forTrack(query.track);
  if (wholeName && wholeName !== query.track) add({ kind: "search", track: wholeName, artist: null, album: null });
  const simple = simplifyTrackName(query.track);
  if (simple && simple !== query.track) forTrack(simple);
  return steps;
}

function stepUrl(step: Step, duration: number | null) {
  const params = new URLSearchParams({ track_name: step.track });
  if (step.artist) params.set("artist_name", step.artist);
  if (step.kind === "get") {
    if (step.album) params.set("album_name", step.album);
    if (duration) params.set("duration", String(Math.round(duration)));
  }
  return `${LRCLIB}/${step.kind}?${params}`;
}

/** Synced lyrics that plausibly cover the song (not a few stray lines). */
export function isLikelyComplete(lines: LyricLine[], durationSeconds: number | null) {
  const sung = lines.filter((line) => line.text);
  if (sung.length < 4) return false;
  if (!durationSeconds || durationSeconds < 60) return true;
  const last = sung[sung.length - 1].time;
  return sung.length >= 8 || last * 2 >= durationSeconds;
}

function cacheKey(query: SongQuery) {
  return `${CACHE_PREFIX}${[query.artist ?? "", query.track].join("|").toLocaleLowerCase()}|${Math.round(query.duration ?? 0)}`;
}

type CacheRecord = { at: number; lyrics: Lyrics | null };

function readCache(key: string): CacheRecord | null {
  try {
    const raw = localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as CacheRecord) : null;
  } catch {
    return null;
  }
}

function writeCache(key: string, record: CacheRecord) {
  try {
    localStorage.setItem(key, JSON.stringify(record));
  } catch {
    /* storage full or unavailable: lyrics still show this time */
  }
}

export function onlineLyricsEnabled() {
  try {
    return localStorage.getItem(ONLINE_KEY) !== "off";
  } catch {
    return true;
  }
}

export function setOnlineLyricsEnabled(enabled: boolean) {
  try {
    localStorage.setItem(ONLINE_KEY, enabled ? "on" : "off");
  } catch {
    /* preference not persisted */
  }
}

/** `[ti:]`, `[ar:]` and `[al:]` headers of an LRC file. */
export function lrcHeaders(text: string): SongMeta {
  const header = (tag: string) => new RegExp(`^\\[${tag}:\\s*(.*?)\\s*\\]\\s*$`, "im").exec(text)?.[1]?.trim() || null;
  return { title: header("ti"), artist: header("ar"), album: header("al") };
}

function withHeaders(meta: SongMeta, body: string) {
  const lines = ([["ti", meta.title], ["ar", meta.artist], ["al", meta.album]] as const)
    .filter(([, value]) => value)
    .map(([tag, value]) => `[${tag}: ${String(value).replace(/[\]\r\n]/g, " ").trim()}]`);
  return [...lines, body].join("\n");
}

function fromText(text: string, source: "local" | "lrclib", meta: SongMeta = lrcHeaders(text)): Lyrics | null {
  const lines = parseLrc(text);
  if (lines.some((line) => line.text)) return { kind: "synced", lines, source, meta };
  const plain = text.replace(/\[[^\]]*\]/g, "").trim();
  return plain ? { kind: "plain", text: plain, source, meta } : null;
}

type Found = { lyrics: Lyrics; text: string };

function toFound(result: LrclibResult): Found | null {
  if (result.instrumental) return null;
  // The match names the song; saved as LRC headers so it shows next time too.
  const album = result.albumName?.trim() || null;
  const meta: SongMeta = { title: result.trackName?.trim() || null, artist: result.artistName?.trim() || null, album: album && !PLACEHOLDER_ALBUM.test(album) ? album : null };
  const synced = result.syncedLyrics?.trim();
  if (synced) {
    const lyrics = fromText(synced, "lrclib", meta);
    if (lyrics) return { lyrics, text: withHeaders(meta, synced) };
  }
  const plain = result.plainLyrics?.trim();
  return plain ? { lyrics: { kind: "plain", text: plain, source: "lrclib", meta }, text: withHeaders(meta, plain) } : null;
}

/**
 * Runs the LRCLIB cascade. Returns the first complete synced lyrics; else
 * plain lyrics; else the most complete partial synced lyrics. `transient` is
 * set when a request failed for a reason worth retrying later.
 */
async function lookUpOnline(query: SongQuery, wholeName: string | null, signal?: AbortSignal) {
  let plain: Found | null = null;
  let partial: Found | null = null;
  let transient = false;
  for (const step of lookupSteps(query, wholeName)) {
    let response: Response;
    try {
      response = await fetch(stepUrl(step, query.duration), { signal, credentials: "omit", referrerPolicy: "no-referrer" });
    } catch (error) {
      if (signal?.aborted) throw error;
      transient = true;
      continue;
    }
    if (!response.ok) {
      if (response.status >= 500 || response.status === 429) transient = true;
      continue; // 404: no exact match
    }
    const body = (await response.json()) as LrclibResult | LrclibResult[];
    const result = Array.isArray(body) ? pickBest(body, query.duration, step.track) : body;
    const found = result ? toFound(result) : null;
    if (!found) continue;
    if (found.lyrics.kind === "plain") {
      plain ??= found;
    } else if (isLikelyComplete(found.lyrics.lines, query.duration)) {
      return { found, transient };
    } else if (!partial || (partial.lyrics.kind === "synced" && found.lyrics.lines.length > partial.lyrics.lines.length)) {
      partial = found;
    }
  }
  return { found: plain ?? partial, transient };
}

/**
 * Lyrics for a song: a local `.lrc` next to the file first, then (if enabled)
 * LRCLIB, matched on the song's tags (title, artist, album, duration). What is
 * found online is saved next to the song, so each song is looked up once;
 * results and misses are also cached.
 */
export async function findLyrics(bridge: DesktopBridge, entry: LibraryEntry, signal?: AbortSignal): Promise<Lyrics | null> {
  const local = await Promise.resolve(bridge.readLyrics?.(entry.relativePath)).catch(() => null);
  if (local) {
    const lyrics = fromText(local, "local");
    if (lyrics) return lyrics;
  }
  if (!onlineLyricsEnabled() || typeof fetch !== "function") return null;

  const info = await Promise.resolve(bridge.readTrackInfo?.(entry.relativePath)).catch(() => null);
  const query = songQuery(entry, info ?? null);
  if (!query) return null;
  const key = cacheKey(query);
  const cached = readCache(key);
  if (cached && (cached.lyrics || Date.now() - cached.at < MISS_TTL_MS)) return cached.lyrics;

  const wholeName = info?.artist ? null : searchQuery(info?.title?.trim() || mediaTitle(entry));
  const { found, transient } = await lookUpOnline(query, wholeName, signal);
  if (!found && transient) return cached?.lyrics ?? null; // retry next time
  writeCache(key, { at: Date.now(), lyrics: found?.lyrics ?? null });
  if (found) await Promise.resolve(bridge.saveLyrics?.(entry.relativePath, found.text)).catch(() => false);
  return found?.lyrics ?? null;
}

const trackInfoCache = new Map<string, TrackInfo | null>();

/** The song's tags and duration (cached per file for the session). */
export function useTrackInfo(bridge: DesktopBridge, entry: LibraryEntry | null): TrackInfo | null {
  const path = entry?.relativePath ?? null;
  // A re-downloaded file at the same path has a new size or time.
  const key = entry ? `${entry.relativePath}|${entry.sizeBytes}|${entry.modifiedAt}` : null;
  const [info, setInfo] = useState<TrackInfo | null>(key ? trackInfoCache.get(key) ?? null : null);
  useEffect(() => {
    if (!key || !path || entry?.mediaType !== "audio" || !bridge.readTrackInfo) { setInfo(null); return; }
    if (trackInfoCache.has(key)) { setInfo(trackInfoCache.get(key) ?? null); return; }
    let mounted = true;
    setInfo(null);
    void bridge.readTrackInfo(path).then((value) => {
      trackInfoCache.set(key, value ?? null);
      if (mounted) setInfo(value ?? null);
    }).catch(() => undefined);
    return () => { mounted = false; };
  }, [bridge, key]); // eslint-disable-line react-hooks/exhaustive-deps
  return info;
}

export function useLyrics(bridge: DesktopBridge, entry: LibraryEntry | null): LyricsState {
  const [state, setState] = useState<LyricsState>({ status: "loading" });
  useEffect(() => {
    if (!entry) return;
    const controller = new AbortController();
    setState({ status: "loading" });
    findLyrics(bridge, entry, controller.signal)
      .then((lyrics) => { if (!controller.signal.aborted) setState(lyrics ? { status: "ready", lyrics } : { status: "none" }); })
      .catch(() => { if (!controller.signal.aborted) setState({ status: "none" }); });
    return () => controller.abort();
  }, [bridge, entry?.relativePath]); // eslint-disable-line react-hooks/exhaustive-deps
  return state;
}
