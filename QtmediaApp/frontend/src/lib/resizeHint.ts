/** How long after the last resize event the window counts as settled. */
const SETTLE_MS = 180;

/**
 * Marks the document while the window is being resized (`html.is-resizing`),
 * so CSS can drop transitions that would otherwise animate behind the moving
 * edge. Returns a function that removes the listener.
 */
export function installResizeHint(target: Window = window) {
  const root = target.document.documentElement;
  let timer = 0;
  const onResize = () => {
    root.classList.add("is-resizing");
    target.clearTimeout(timer);
    timer = target.setTimeout(() => root.classList.remove("is-resizing"), SETTLE_MS);
  };
  target.addEventListener("resize", onResize);
  return () => {
    target.removeEventListener("resize", onResize);
    target.clearTimeout(timer);
    root.classList.remove("is-resizing");
  };
}
