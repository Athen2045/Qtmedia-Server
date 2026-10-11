import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

type Drag = { from: number; to: number; dy: number; size: number };

/** Pointer travel before a press becomes a drag (so plain clicks still work). */
const DRAG_THRESHOLD = 5;
/** Distance from the scroller's edge that starts auto-scrolling while dragging. */
const EDGE = 48;

/**
 * Drag-to-reorder for a vertical list, built on pointer events (HTML5 drag and
 * drop is unreliable inside the Tauri webview). Rows other than the dragged one
 * slide out of the way; dropping calls `onMove(from, to)`. Alt+Up/Down moves the
 * focused row from the keyboard. Rows before `first` stay fixed.
 */
export function useDragReorder({ count, first = 0, onMove, list, scroller }: {
  count: number;
  first?: number;
  onMove: (from: number, to: number) => void;
  list: React.RefObject<HTMLElement | null>;
  scroller?: React.RefObject<HTMLElement | null>;
}) {
  const [drag, setDragState] = useState<Drag | null>(null);
  const [settling, setSettling] = useState(false);
  const dragRef = useRef<Drag | null>(null);
  const suppressClick = useRef(false);
  const focusAfter = useRef<number | null>(null);
  const cleanup = useRef<(() => void) | null>(null);
  const onMoveRef = useRef(onMove);
  onMoveRef.current = onMove;

  const setDrag = (value: Drag | null) => {
    dragRef.current = value;
    setDragState(value);
  };

  // After a drop the rows swap places in the DOM; skip one frame of transitions
  // so they don't animate back from their old offsets.
  useEffect(() => {
    if (!settling) return;
    const frame = requestAnimationFrame(() => setSettling(false));
    return () => cancelAnimationFrame(frame);
  }, [settling]);

  useEffect(() => () => cleanup.current?.(), []);

  // Keep keyboard focus on the row that moved.
  useLayoutEffect(() => {
    if (focusAfter.current === null) return;
    const target = list.current?.querySelector<HTMLElement>(`[data-reorder-index="${focusAfter.current}"] button`);
    focusAfter.current = null;
    target?.focus();
  });

  const commit = useCallback((from: number, to: number) => {
    setSettling(true);
    if (from !== to) onMoveRef.current(from, to);
  }, []);

  const start = (event: React.PointerEvent<HTMLElement>, index: number) => {
    if (event.button !== 0 || index < first || count - first < 2) return;
    const row = event.currentTarget;
    const rect = row.getBoundingClientRect();
    const sibling = row.nextElementSibling ?? row.previousElementSibling;
    const size = (sibling ? Math.abs(sibling.getBoundingClientRect().top - rect.top) : rect.height) || rect.height || 1;
    const box = scroller?.current ?? null;
    const startY = event.clientY;
    const startScroll = box?.scrollTop ?? 0;
    let lastY = startY;
    let active = false;
    let frame = 0;

    const measure = () => {
      const dy = lastY - startY + ((box?.scrollTop ?? 0) - startScroll);
      const to = Math.max(first, Math.min(count - 1, index + Math.round(dy / size)));
      setDrag({ from: index, to, dy, size });
    };
    const autoScroll = () => {
      if (box) {
        const bounds = box.getBoundingClientRect();
        const step = lastY < bounds.top + EDGE ? -8 : lastY > bounds.bottom - EDGE ? 8 : 0;
        if (step) {
          box.scrollTop += step;
          measure();
        }
      }
      frame = requestAnimationFrame(autoScroll);
    };
    const onPointerMove = (moveEvent: PointerEvent) => {
      lastY = moveEvent.clientY;
      if (!active) {
        if (Math.abs(lastY - startY) < DRAG_THRESHOLD) return;
        active = true;
        document.body.classList.add("is-reordering");
        frame = requestAnimationFrame(autoScroll);
      }
      moveEvent.preventDefault();
      measure();
    };
    const finish = (drop: boolean) => {
      cleanup.current?.();
      if (!active) return;
      suppressClick.current = true;
      // The click (if any) fires right after pointerup; clear the guard afterwards.
      window.setTimeout(() => { suppressClick.current = false; }, 0);
      const last = dragRef.current;
      setDrag(null);
      if (drop && last) commit(last.from, last.to);
      else setSettling(true);
    };
    const onUp = () => finish(true);
    const onCancel = () => finish(false);
    const onKey = (keyEvent: KeyboardEvent) => { if (keyEvent.key === "Escape") finish(false); };

    cleanup.current?.();
    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", onUp);
    window.addEventListener("pointercancel", onCancel);
    window.addEventListener("keydown", onKey, true);
    cleanup.current = () => {
      cancelAnimationFrame(frame);
      document.body.classList.remove("is-reordering");
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerup", onUp);
      window.removeEventListener("pointercancel", onCancel);
      window.removeEventListener("keydown", onKey, true);
      cleanup.current = null;
    };
  };

  const itemProps = (index: number) => {
    let offset = 0;
    if (drag) {
      if (index === drag.from) offset = drag.dy;
      else if (drag.from < index && index <= drag.to) offset = -drag.size;
      else if (drag.to <= index && index < drag.from) offset = drag.size;
    }
    const movable = index >= first;
    return {
      "data-reorder-index": index,
      className: `reorder-item ${drag?.from === index ? "is-dragging" : ""}`,
      style: offset ? { transform: `translateY(${offset}px)` } : undefined,
      onPointerDown: movable ? (event: React.PointerEvent<HTMLElement>) => start(event, index) : undefined,
      onClickCapture: (event: React.MouseEvent) => {
        if (!suppressClick.current) return;
        suppressClick.current = false;
        event.preventDefault();
        event.stopPropagation();
      },
      onKeyDown: movable ? (event: React.KeyboardEvent) => {
        if (!event.altKey) return;
        const to = event.key === "ArrowUp" ? index - 1 : event.key === "ArrowDown" ? index + 1 : null;
        if (to === null || to < first || to >= count) return;
        event.preventDefault();
        focusAfter.current = to;
        commit(index, to);
      } : undefined,
    };
  };

  return { itemProps, dragging: drag !== null, listClassName: `reorder-list ${drag ? "is-dragging" : ""} ${settling ? "is-settling" : ""}` };
}
