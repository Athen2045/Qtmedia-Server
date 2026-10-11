import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { DesktopBridge, LibraryEntry } from "./bridge";
import { activeLineIndex, findLyrics, isLikelyComplete, lrcHeaders, lookupSteps, parseLrc, pickBest, primaryArtist, searchQuery, setOnlineLyricsEnabled, simplifyTrackName, songQuery } from "./lyrics";

const song = (relativePath = "audio/Night Drive (Official Video).mp3", durationSeconds: number | null = 241): LibraryEntry => ({
  relativePath, mediaType: "audio", extension: "mp3", sizeBytes: 1, modifiedAt: 1, durationSeconds, artworkPath: null,
});

function bridge(local: string | null = null, info: Record<string, unknown> | null = null) {
  return {
    readLyrics: vi.fn().mockResolvedValue(local),
    readTrackInfo: vi.fn().mockResolvedValue(info),
    saveLyrics: vi.fn().mockResolvedValue(true),
  } as unknown as DesktopBridge & { saveLyrics: ReturnType<typeof vi.fn> };
}

const complete = Array.from({ length: 10 }, (_, i) => `[00:${String(i * 5).padStart(2, "0")}.00] Line ${i + 1}`).join("\n");
const reply = (body: unknown, status = 200) => ({ ok: status < 400, status, json: async () => body });

describe("parseLrc", () => {
  it("reads repeated stamps, short and long fractions, offsets and ignores tags", () => {
    const lines = parseLrc("[ar:Someone]\n[offset:+500]\n[00:05.50][01:05.5] Chorus\n[00:01] Intro\n[00:03.250] Verse\nno stamp");
    expect(lines).toEqual([
      { time: 0.5, text: "Intro" },
      { time: 2.75, text: "Verse" },
      { time: 5, text: "Chorus" },
      { time: 65, text: "Chorus" },
    ]);
  });

  it("finds the active line by binary search", () => {
    const lines = parseLrc("[00:01.00]a\n[00:02.00]b\n[00:03.00]c");
    expect(activeLineIndex(lines, 0.5)).toBe(-1);
    expect(activeLineIndex(lines, 2)).toBe(1);
    expect(activeLineIndex(lines, 99)).toBe(2);
  });
});

describe("matching", () => {
  it("strips download noise from titles", () => {
    expect(searchQuery("Night Drive (Official Video)")).toBe("Night Drive");
    expect(searchQuery("Artist - Song [Lyrics] (HD) -")).toBe("Artist - Song");
    expect(searchQuery("Harbour Lights (Live Session)")).toBe("Harbour Lights (Live Session)");
  });

  it("prefers synced lyrics with a close duration and rejects other recordings", () => {
    const results = [
      { duration: 300, syncedLyrics: "[00:01]far" },
      { duration: 242, plainLyrics: "plain close" },
      { duration: 239, syncedLyrics: "[00:01]synced close" },
      { duration: 241, instrumental: true },
    ];
    expect(pickBest(results, 241)?.syncedLyrics).toBe("[00:01]synced close");
    expect(pickBest([{ duration: 300, syncedLyrics: "x" }], 241)).toBeNull();
  });
});

describe("findLyrics", () => {
  const store = new Map<string, string>();
  beforeEach(() => {
    store.clear();
    vi.stubGlobal("localStorage", {
      getItem: (key: string) => store.get(key) ?? null,
      setItem: (key: string, value: string) => void store.set(key, value),
      removeItem: (key: string) => void store.delete(key),
    });
  });
  afterEach(() => vi.unstubAllGlobals());

  it("uses a local .lrc file without touching the network", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const lyrics = await findLyrics(bridge("[00:01.00] Mine"), song());
    expect(lyrics).toEqual({ kind: "synced", source: "local", lines: [{ time: 1, text: "Mine" }], meta: { title: null, artist: null, album: null } });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("matches on the song's tags with LRCLIB's exact endpoint and saves the result", async () => {
    const fetchMock = vi.fn().mockResolvedValue(reply({ duration: 186, syncedLyrics: complete }));
    vi.stubGlobal("fetch", fetchMock);
    const tagged = bridge(null, { title: "Mona Lisa", artist: "Dominic Fike", album: "Sunburn", durationSeconds: 186.07 });
    const lyrics = await findLyrics(tagged, song("audio/Mona Lisa [media-x].flac", null));
    expect(lyrics).toMatchObject({ kind: "synced", source: "lrclib" });
    expect(fetchMock).toHaveBeenCalledOnce();
    expect(String(fetchMock.mock.calls[0][0])).toBe(
      "https://lrclib.net/api/get?track_name=Mona+Lisa&artist_name=Dominic+Fike&album_name=Sunburn&duration=186",
    );
    expect(fetchMock.mock.calls[0][1]).toMatchObject({ credentials: "omit", referrerPolicy: "no-referrer" });
    expect(tagged.saveLyrics).toHaveBeenCalledWith("audio/Mona Lisa [media-x].flac", complete);

    await findLyrics(tagged, song("audio/Mona Lisa [media-x].flac", null));
    expect(fetchMock).toHaveBeenCalledOnce(); // cached
  });

  it("falls through the cascade and skips partial synced lyrics for a complete match", async () => {
    const partial = "[00:01.00] Only\n[00:02.00] Two lines";
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(reply({}, 404)) // exact with album
      .mockResolvedValueOnce(reply({ duration: 200, syncedLyrics: partial })) // exact, no album: partial
      .mockResolvedValueOnce(reply([{ duration: 201, syncedLyrics: complete }])); // artist search
    vi.stubGlobal("fetch", fetchMock);
    const lyrics = await findLyrics(bridge(null, { title: "Song", artist: "Band", album: "LP", durationSeconds: 200 }), song("audio/Song.flac", null));
    expect(lyrics?.kind === "synced" && lyrics.lines).toHaveLength(10);
    expect(fetchMock.mock.calls.map(([url]) => String(url).split("?")[0])).toEqual([
      "https://lrclib.net/api/get", "https://lrclib.net/api/get", "https://lrclib.net/api/search",
    ]);
  });

  it("uses plain lyrics when nothing synced is found, and partial synced only as a last resort", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(reply([{ duration: 200, plainLyrics: "Just words" }])));
    expect(await findLyrics(bridge(null, { title: "A", artist: null, album: null, durationSeconds: 200 }), song("audio/A.flac", null)))
      .toMatchObject({ kind: "plain", text: "Just words", source: "lrclib" });

    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(reply([{ duration: 200, syncedLyrics: "[00:01.00] a\n[00:02.00] b" }])));
    expect(await findLyrics(bridge(null, { title: "B", artist: null, album: null, durationSeconds: 200 }), song("audio/B.flac", null)))
      .toMatchObject({ kind: "synced" });
  });

  it("caches misses but not server errors, and stays offline when turned off", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(reply({}, 503)).mockResolvedValue(reply([]));
    vi.stubGlobal("fetch", fetchMock);
    expect(await findLyrics(bridge(), song())).toBeNull(); // 5xx: not cached
    expect(await findLyrics(bridge(), song())).toBeNull(); // miss: cached
    expect(await findLyrics(bridge(), song())).toBeNull();
    expect(fetchMock).toHaveBeenCalledTimes(2);

    setOnlineLyricsEnabled(false);
    expect(await findLyrics(bridge(), song("audio/Other.mp3"))).toBeNull();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});

describe("lookup plan", () => {
  it("splits untagged 'Artist - Title' names and keeps the whole name as a search", () => {
    const query = songQuery(song("audio/Dominic Fike - Mona Lisa (Official Video).mp3", 186), null);
    expect(query).toEqual({ track: "Mona Lisa", artist: "Dominic Fike", album: null, duration: 186 });
    const steps = lookupSteps(query!, "Dominic Fike - Mona Lisa");
    expect(steps.map((step) => `${step.kind}:${step.artist ?? "-"}:${step.track}`)).toEqual([
      "get:Dominic Fike:Mona Lisa",
      "search:Dominic Fike:Mona Lisa",
      "search:-:Mona Lisa",
      "search:-:Dominic Fike - Mona Lisa",
    ]);
  });

  it("matches on the lead artist, even when only the title tag exists", () => {
    expect(primaryArtist("Metro Boomin, Swae Lee, Lil Wayne & Offset")).toBe("Metro Boomin");
    expect(primaryArtist("JVKE feat. John Michael Howell")).toBe("JVKE");
    expect(primaryArtist("Lil Nas X")).toBe("Lil Nas X");
    const info = { title: "Metro Boomin, Swae Lee - Annihilate (Official Video)", artist: null, album: null, durationSeconds: 231 };
    expect(songQuery(song("audio/x.mp3", null), info)).toEqual({ track: "Annihilate", artist: "Metro Boomin", album: null, duration: 231 });
  });

  it("follows SpotiFLAC's order, then retries with the simplified title", () => {
    const steps = lookupSteps({ track: "Annihilate (Spider-Man: Across the Spider-Verse)", artist: "Metro Boomin", album: "Score", duration: 231 });
    const full = "Annihilate (Spider-Man: Across the Spider-Verse)";
    expect(steps.map((step) => [step.kind, step.artist, step.album, step.track])).toEqual([
      ["get", "Metro Boomin", "Score", full],
      ["get", "Metro Boomin", null, full],
      ["search", "Metro Boomin", null, full],
      ["search", null, null, full],
      ["get", "Metro Boomin", "Score", "Annihilate"],
      ["get", "Metro Boomin", null, "Annihilate"],
      ["search", "Metro Boomin", null, "Annihilate"],
      ["search", null, null, "Annihilate"],
    ]);
    expect(simplifyTrackName("Song (Remastered 2011) - Live")).toBe("Song");
  });

  it("treats a handful of synced lines as incomplete", () => {
    const lines = [1, 2, 3, 4, 5].map((time) => ({ time, text: "x" }));
    expect(isLikelyComplete(lines.slice(0, 3), 200)).toBe(false);
    expect(isLikelyComplete(lines, 200)).toBe(false); // 5 lines ending at 5 s of 200 s
    expect(isLikelyComplete(lines, 50)).toBe(true);
  });
});

describe("song details from lyrics", () => {
  const store = new Map<string, string>();
  beforeEach(() => {
    store.clear();
    vi.stubGlobal("localStorage", { getItem: (key: string) => store.get(key) ?? null, setItem: (key: string, value: string) => void store.set(key, value), removeItem: () => undefined });
  });
  afterEach(() => vi.unstubAllGlobals());

  it("reads [ti:], [ar:] and [al:] headers from a local .lrc", async () => {
    expect(lrcHeaders("[id: x]\n[ar: Dominic Fike]\n[al: Sunburn]\n[ti: Mona Lisa]\n[00:01.00] a")).toEqual({ title: "Mona Lisa", artist: "Dominic Fike", album: "Sunburn" });
    const lyrics = await findLyrics(bridge("[ar: AURORA]\n[00:01.00] Line"), song());
    expect(lyrics?.meta?.artist).toBe("AURORA");
  });

  it("saves the LRCLIB match's names as headers so they show next time", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(reply([{ duration: 180, trackName: "A Thousand Years", artistName: "JVKE", albumName: "Single", syncedLyrics: complete }])));
    const target = bridge(null, { title: null, artist: null, album: null, durationSeconds: 180 });
    const lyrics = await findLyrics(target, song("audio/A Thousand Years.flac", null));
    expect(lyrics?.meta).toEqual({ title: "A Thousand Years", artist: "JVKE", album: "Single" });
    const saved = String(target.saveLyrics.mock.calls[0][1]);
    expect(saved.startsWith("[ti: A Thousand Years]\n[ar: JVKE]\n[al: Single]\n[00:00.00] Line 1")).toBe(true);
    expect(lrcHeaders(saved).artist).toBe("JVKE");
  });
});

describe("choosing a clean match", () => {
  it("prefers the same track name and Latin names for a Latin title", () => {
    const results = [
      { duration: 189, trackName: "Self Love", artistName: "Metro Boomin和Coi Leray", albumName: "Soundtrack", syncedLyrics: "[00:01]a" },
      { duration: 189, trackName: "Self Love (Spider-Man)", artistName: "Metro Boomin", albumName: "Soundtrack", syncedLyrics: "[00:01]b" },
      { duration: 190, trackName: "Self Love", artistName: "Metro Boomin & Coi Leray", albumName: "Soundtrack", syncedLyrics: "[00:01]c" },
    ];
    expect(pickBest(results, 189, "Self Love")?.syncedLyrics).toBe("[00:01]c");
  });

  it("drops a placeholder album from the saved names", async () => {
    vi.stubGlobal("localStorage", { getItem: () => null, setItem: () => undefined, removeItem: () => undefined });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(reply([{ duration: 180, trackName: "Song", artistName: "Band", albumName: "Unnamed", syncedLyrics: complete }])));
    const lyrics = await findLyrics(bridge(null, { title: "Song", artist: null, album: null, durationSeconds: 180 }), song("audio/Song.flac", null));
    expect(lyrics?.meta).toEqual({ title: "Song", artist: "Band", album: null });
    vi.unstubAllGlobals();
  });
});
