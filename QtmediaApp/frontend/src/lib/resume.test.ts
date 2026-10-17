import { describe, expect, it } from "vitest";

import { createResumeStore, RESUME_KEY } from "./resume";

function memoryStorage(seed: Record<string, string> = {}) {
  const data = new Map(Object.entries(seed));
  return {
    getItem: (key: string) => data.get(key) ?? null,
    setItem: (key: string, value: string) => void data.set(key, value),
    removeItem: (key: string) => void data.delete(key),
    data,
  };
}

describe("resume store", () => {
  it("remembers a mid-video position per library path", () => {
    const store = createResumeStore(memoryStorage());

    store.save("video/A.mp4", 125.4, 600);

    expect(store.get("video/A.mp4")).toBe(125.4);
    expect(store.get("video/B.mp4")).toBeNull();
  });

  it("forgets positions near the start or the end, and when cleared", () => {
    const store = createResumeStore(memoryStorage());
    store.save("video/A.mp4", 300, 600);

    store.save("video/A.mp4", 6, 600);
    expect(store.get("video/A.mp4")).toBeNull();

    store.save("video/A.mp4", 300, 600);
    store.save("video/A.mp4", 590, 600);
    expect(store.get("video/A.mp4")).toBeNull();

    store.save("video/A.mp4", 300, 600);
    store.clear("video/A.mp4");
    expect(store.get("video/A.mp4")).toBeNull();
  });

  it("keeps only the most recently watched entries", () => {
    let clock = 0;
    const store = createResumeStore(memoryStorage(), { now: () => ++clock, limit: 2 });

    store.save("video/1.mp4", 60, 600);
    store.save("video/2.mp4", 60, 600);
    store.save("video/3.mp4", 60, 600);

    expect(store.get("video/1.mp4")).toBeNull();
    expect(store.get("video/2.mp4")).toBe(60);
    expect(store.get("video/3.mp4")).toBe(60);
  });

  it("survives corrupt data and storage that throws", () => {
    const corrupt = createResumeStore(memoryStorage({ [RESUME_KEY]: "{not json" }));
    expect(corrupt.get("video/A.mp4")).toBeNull();
    corrupt.save("video/A.mp4", 60, 600);
    expect(corrupt.get("video/A.mp4")).toBe(60);

    const throwing = createResumeStore({
      getItem: () => { throw new Error("blocked"); },
      setItem: () => { throw new Error("blocked"); },
      removeItem: () => { throw new Error("blocked"); },
    });
    expect(() => throwing.save("video/A.mp4", 60, 600)).not.toThrow();
    expect(throwing.get("video/A.mp4")).toBeNull();

    expect(createResumeStore(null).get("video/A.mp4")).toBeNull();
  });

  it("ignores unknown durations instead of guessing the end", () => {
    const store = createResumeStore(memoryStorage());

    store.save("video/A.mp4", 60, Number.NaN);

    expect(store.get("video/A.mp4")).toBe(60);
  });
});

describe("saved position list", () => {
  it("lists positions newest first", () => {
    const storage = new Map<string, string>();
    const store = createResumeStore({ getItem: (k) => storage.get(k) ?? null, setItem: (k, v) => void storage.set(k, v), removeItem: (k) => void storage.delete(k) }, { now: (() => { let t = 0; return () => (t += 1); })() });
    store.save("video/A.mp4", 20, 600);
    store.save("video/B.mp4", 40, 600);
    expect(store.list().map((item) => [item.relativePath, item.position])).toEqual([["video/B.mp4", 40], ["video/A.mp4", 20]]);
  });
});
