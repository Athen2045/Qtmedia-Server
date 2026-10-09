import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";

import type { DesktopBridge, DesktopEvent, FormatOption, LibraryEntry } from "./bridge";

export type SessionState =
  | { status: "empty" }
  | { status: "inspecting" }
  | { status: "ready"; mediaId: string; title: string; site: string; durationSeconds: number | null; formats: FormatOption[]; selected: string; submitting: boolean }
  | { status: "downloading" | "cancelling"; jobId: string; title: string; formatLabel: string; downloadedBytes: number; totalBytes: number | null; percent: number | null }
  | { status: "completed"; entry: LibraryEntry }
  | { status: "error"; code: string };

type SessionContextValue = {
  state: SessionState;
  busy: boolean;
  libraryRevision: number;
  inspect(url: string): Promise<void>;
  selectFormat(key: string): void;
  startDownload(): Promise<void>;
  cancelDownload(): Promise<void>;
  reset(): void;
  refreshLibrary(): void;
};

const SessionContext = createContext<SessionContextValue | null>(null);

const safeErrorCodes = new Set([
  "invalid_url", "unsupported_source", "no_formats", "format_unavailable",
  "download_failed", "sidecar_unavailable", "provider_unavailable",
  "request_timeout", "storage_busy", "storage_unavailable", "cancelled",
]);

function safeCode(error: unknown, fallback: string) {
  const value = typeof error === "string"
    ? error
    : typeof error === "object" && error !== null && "code" in error
      ? String((error as { code: unknown }).code)
      : fallback;
  return safeErrorCodes.has(value) ? value : fallback;
}

export function DesktopSessionProvider({ bridge, children }: { bridge: DesktopBridge; children: React.ReactNode }) {
  const [state, setState] = useState<SessionState>({ status: "empty" });
  const [libraryRevision, setLibraryRevision] = useState(0);
  const stateRef = useRef(state);
  const submissionRef = useRef(false);
  stateRef.current = state;

  useEffect(() => {
    let mounted = true;
    let unlisten: () => void = () => undefined;
    void bridge.subscribe((event: DesktopEvent) => {
      if (!mounted) return;
      if (event.event === "inspection_started") setState({ status: "inspecting" });
      if (event.event === "inspection_ready") {
        submissionRef.current = false;
        setState({
          status: "ready",
          mediaId: event.mediaId,
          title: event.title,
          site: event.site,
          durationSeconds: event.durationSeconds,
          formats: event.formats,
          selected: event.formats[0]?.key ?? "",
          submitting: false,
        });
      }
      if (event.event === "download_started") {
        const current = stateRef.current;
        if (current.status !== "ready") return;
        const selected = current.formats.find((format) => format.key === current.selected);
        submissionRef.current = false;
        const next: SessionState = {
          status: "downloading",
          jobId: event.jobId,
          title: current.title,
          formatLabel: selected?.label ?? "Media",
          downloadedBytes: 0,
          totalBytes: null,
          percent: null,
        };
        stateRef.current = next;
        setState(next);
      }
      if (event.event === "download_progress") {
        const current = stateRef.current;
        if (!(current.status === "downloading" || current.status === "cancelling") || current.jobId !== event.jobId) return;
        const next: SessionState = { ...current, downloadedBytes: event.downloadedBytes, totalBytes: event.totalBytes, percent: event.percent };
        stateRef.current = next;
        setState(next);
      }
      if (event.event === "download_completed") {
        const current = stateRef.current;
        if ((current.status === "downloading" || current.status === "cancelling") && current.jobId !== event.jobId) return;
        submissionRef.current = false;
        setState({ status: "completed", entry: event.entry });
        setLibraryRevision((value) => value + 1);
      }
      if (event.event === "download_cancelled") {
        const current = stateRef.current;
        if ((current.status === "downloading" || current.status === "cancelling") && current.jobId !== event.jobId) return;
        submissionRef.current = false;
        setState({ status: "error", code: "cancelled" });
      }
      // A listing is a response to Files' own scan, not a new library mutation.
      if (event.event === "library_changed" && event.entries === undefined) setLibraryRevision((value) => value + 1);
      if (event.event === "error") {
        const current = stateRef.current;
        if (event.jobId && (current.status === "downloading" || current.status === "cancelling") && current.jobId !== event.jobId) return;
        submissionRef.current = false;
        setState({ status: "error", code: safeCode(event.code, "operation_failed") });
      }
    }).then((stop) => {
      if (mounted) unlisten = stop;
      else stop();
    });
    return () => {
      mounted = false;
      unlisten();
    };
  }, [bridge]);

  const inspect = useCallback(async (url: string) => {
    setState({ status: "inspecting" });
    try {
      await bridge.inspectLink(url);
    } catch (error) {
      setState({ status: "error", code: safeCode(error, "sidecar_unavailable") });
    }
  }, [bridge]);

  const selectFormat = useCallback((key: string) => {
    setState((current) => current.status === "ready" && !current.submitting ? { ...current, selected: key } : current);
  }, []);

  const startDownload = useCallback(async () => {
    const current = stateRef.current;
    if (current.status !== "ready" || current.submitting || submissionRef.current || !current.selected) return;
    submissionRef.current = true;
    setState({ ...current, submitting: true });
    try {
      await bridge.startDownload(current.mediaId, current.selected);
    } catch (error) {
      submissionRef.current = false;
      setState({ status: "error", code: safeCode(error, "sidecar_unavailable") });
    }
  }, [bridge]);

  const cancelDownload = useCallback(async () => {
    const current = stateRef.current;
    if (current.status !== "downloading") return;
    setState({ ...current, status: "cancelling" });
    try {
      await bridge.cancelDownload(current.jobId);
    } catch (error) {
      setState({ status: "error", code: safeCode(error, "sidecar_unavailable") });
    }
  }, [bridge]);

  const reset = useCallback(() => {
    if (!(["inspecting", "downloading", "cancelling"] as string[]).includes(stateRef.current.status)) {
      submissionRef.current = false;
      setState({ status: "empty" });
    }
  }, []);
  const refreshLibrary = useCallback(() => setLibraryRevision((value) => value + 1), []);
  const busy = ["inspecting", "downloading", "cancelling"].includes(state.status) || (state.status === "ready" && state.submitting);
  const value = useMemo(() => ({ state, busy, libraryRevision, inspect, selectFormat, startDownload, cancelDownload, reset, refreshLibrary }), [state, busy, libraryRevision, inspect, selectFormat, startDownload, cancelDownload, reset, refreshLibrary]);

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useDesktopSession() {
  const value = useContext(SessionContext);
  if (!value) throw new Error("DesktopSessionProvider is required");
  return value;
}
