import { playlistStore } from "./playlists";
import { remapResumePositions } from "./resume";

/** A file the app renamed in the library (library-relative paths). */
export type Rename = { from: string; to: string };

/** Maps an old path to where it lives now, following renames made one after another. */
export function renamer(renames: Rename[]): (path: string) => string {
  const next = new Map(renames.map(({ from, to }) => [from, to]));
  return (path) => {
    let current = path;
    for (let step = 0; step < renames.length && next.has(current); step += 1) current = next.get(current)!;
    return current;
  };
}

/** Updates playlists and resume positions, which are kept by path. Safe to repeat. */
export function applyRenames(renames: Rename[]) {
  if (!renames.length) return;
  const rename = renamer(renames);
  playlistStore.remap(rename);
  remapResumePositions(rename);
}
