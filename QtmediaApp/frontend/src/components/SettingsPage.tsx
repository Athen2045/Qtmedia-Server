import { useEffect, useState } from "react";

import { useDesktopSession } from "../lib/DesktopSession";
import type {
  AudioDevice,
  AudioSettings,
  NativeAudio,
  DesktopBridge,
  CookieSource,
  DohProvider,
  LibraryLocation,
  NetworkSettings,
  YtdlpChannel,
  YtdlpStatus,
  YtdlpUpdateResult,
} from "../lib/bridge";
import { onlineLyricsEnabled, setOnlineLyricsEnabled } from "../lib/lyrics";
import { useOptionalPlayer } from "../lib/player";
import { Icon } from "./Icon";
import { QMark } from "./QMark";
import { Toolbar } from "./Shell";

const messages: Record<string, string> = {
  storage_busy: "Wait for the current media job to finish before changing folders.",
  storage_unavailable: "That folder could not be prepared. Your current location was kept.",
  sidecar_unavailable: "The media engine could not switch folders. Your current location was kept.",
};

function codeOf(error: unknown) {
  if (typeof error === "string") return error;
  if (typeof error === "object" && error !== null && "code" in error) return String((error as { code: unknown }).code);
  return "storage_unavailable";
}

export function SettingsPage({ bridge, onShowDownload }: { bridge: DesktopBridge; onShowDownload?: () => void }) {
  const { busy, refreshLibrary } = useDesktopSession();
  const player = useOptionalPlayer();
  const [location, setLocation] = useState<LibraryLocation | null>(null);
  const [loading, setLoading] = useState(true);
  const [changing, setChanging] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [retryToken, setRetryToken] = useState(0);
  const [version, setVersion] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;
    setLoading(true);
    setError(null);
    void bridge.getDownloadLocation().then((value) => {
      if (mounted) setLocation(value);
    }).catch(() => {
      if (mounted) setError("storage_unavailable");
    }).finally(() => {
      if (mounted) setLoading(false);
    });
    return () => { mounted = false; };
  }, [bridge, retryToken]);

  useEffect(() => {
    let mounted = true;
    void bridge.appVersion?.().then((value) => { if (mounted) setVersion(value); }).catch(() => undefined);
    return () => { mounted = false; };
  }, [bridge]);

  const apply = async (change: () => Promise<LibraryLocation | null>) => {
    setChanging(true);
    setError(null);
    try {
      const next = await change();
      if (next) {
        // The playing file belongs to the previous library.
        if (next.path !== location?.path) player?.stop();
        setLocation(next);
        refreshLibrary();
      }
    } catch (caught) {
      setError(codeOf(caught));
    } finally {
      setChanging(false);
    }
  };

  const disabled = busy || changing;
  return (
    <section className="page settings-page" aria-labelledby="settings-title">
      <Toolbar title="Settings" onShowDownload={onShowDownload} />
      <span id="settings-title" className="sr-only">Settings</span>
      <div className="page-body">
        <div className="settings-column">
          <h2 className="group-title">Downloads</h2>
          <div className="group">
            <div className="group-row">
              <span className="row-icon row-icon--accent" aria-hidden="true"><Icon name="folder" /></span>
              <div className="row-label">
                <h3>Download location</h3>
                {loading ? <span className="settings-skeleton" aria-label="Loading download location" /> : <span className="row-path" title={location?.path}>{location?.path ?? "Location unavailable"}</span>}
              </div>
              <span className="badge">{location ? location.isDefault ? "Default" : "Custom" : "Unavailable"}</span>
              <button type="button" className="btn btn-default" aria-label="Change folder" disabled={disabled} onClick={() => void apply(() => bridge.chooseDownloadLocation())}>Change…</button>
            </div>
            <div className="group-row">
              <span className="row-icon" aria-hidden="true"><Icon name="open" /></span>
              <div className="row-label"><h3>Show library in File Explorer</h3></div>
              <button type="button" className="btn btn-default" aria-label="Open folder" disabled={!location} onClick={() => void bridge.openLibrary()}>Open</button>
            </div>
            <div className="group-row">
              <span className="row-icon" aria-hidden="true"><Icon name="settings" /></span>
              <div className="row-label"><h3>Use default location</h3>{location?.isDefault ? <span>You’re already using the default</span> : null}</div>
              <button type="button" className="btn btn-default" aria-label="Use default" disabled={disabled || location?.isDefault} onClick={() => void apply(() => bridge.useDefaultDownloadLocation())}>Restore</button>
            </div>
          </div>
          <p className="group-foot">Changing locations keeps existing files where they are. New downloads, Files and Music use the selected library.</p>
          {busy ? <p className="group-foot group-foot--notice">A media job is active. Location controls will unlock when it finishes.</p> : null}
          {error ? <div className="settings-error"><p className="inline-error" role="alert">{messages[error] ?? messages.storage_unavailable}</p>{!location ? <button type="button" className="btn btn-default" onClick={() => setRetryToken((value) => value + 1)}>Retry</button> : null}</div> : null}

          {bridge.getNetworkSettings && bridge.setNetworkSettings ? <NetworkGroup bridge={bridge} busy={busy} /> : null}

          {bridge.audio ? <AudioGroup audio={bridge.audio} /> : null}

          {bridge.getYtdlpStatus && bridge.updateYtdlp ? <YtdlpGroup bridge={bridge} busy={busy} /> : null}

          <h2 className="group-title">Privacy</h2>
          <div className="group">
            <div className="group-row">
              <span className="row-icon row-icon--green" aria-hidden="true"><Icon name="lock" /></span>
              <div className="row-label"><h3>Links are never stored</h3><span>Used once to find formats. No accounts, and your files are never uploaded.</span></div>
            </div>
            <LyricsRow />
          </div>

          <h2 className="group-title">About</h2>
          <div className="group">
            <div className="group-row">
              <QMark size={28} />
              <div className="row-label"><h3>Qtmedia</h3></div>
              <span className="row-value">{version ? `Version ${version}` : ""}</span>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

const dohChoices: Array<{ value: DohProvider; label: string }> = [
  { value: "off", label: "Off (system DNS)" },
  { value: "cloudflare", label: "Cloudflare (1.1.1.1)" },
  { value: "google", label: "Google (8.8.8.8)" },
  { value: "quad9", label: "Quad9 (9.9.9.9)" },
];

const cookieChoices: Array<{ value: CookieSource; label: string }> = [
  { value: "off", label: "Off" },
  { value: "firefox", label: "Firefox" },
];

const networkMessages: Record<string, string> = {
  invalid_proxy: "Enter a proxy like socks5h://host:port or http://host:port.",
  storage_busy: "Wait for the current media job to finish before changing network settings.",
  sidecar_unavailable: "The media engine could not restart with these settings. Your previous settings were kept.",
};

function NetworkGroup({ bridge, busy }: { bridge: DesktopBridge; busy: boolean }) {
  const [saved, setSaved] = useState<NetworkSettings | null>(null);
  const [doh, setDoh] = useState<DohProvider>("off");
  const [proxy, setProxy] = useState("");
  const [cookies, setCookies] = useState<CookieSource>("off");
  const [applying, setApplying] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [applied, setApplied] = useState(false);

  useEffect(() => {
    let mounted = true;
    void bridge.getNetworkSettings?.().then((value) => {
      if (!mounted) return;
      setSaved(value);
      setDoh(value.doh);
      setProxy(value.proxy ?? "");
      setCookies(value.cookies ?? "off");
    }).catch(() => undefined);
    return () => { mounted = false; };
  }, [bridge]);

  const trimmed = proxy.trim();
  const changed = saved !== null && (doh !== saved.doh || trimmed !== (saved.proxy ?? "") || cookies !== (saved.cookies ?? "off"));
  const locked = busy || applying || saved === null;

  const apply = async () => {
    setApplying(true);
    setError(null);
    setApplied(false);
    try {
      const next = await bridge.setNetworkSettings!(doh, trimmed || null, cookies);
      setSaved(next);
      setDoh(next.doh);
      setProxy(next.proxy ?? "");
      setCookies(next.cookies ?? "off");
      setApplied(true);
    } catch (caught) {
      setError(codeOf(caught));
    } finally {
      setApplying(false);
    }
  };

  return (
    <>
      <h2 className="group-title">Network</h2>
      <div className="group">
        <div className="group-row">
          <span className="row-icon" aria-hidden="true"><Icon name="lock" /></span>
          <div className="row-label"><h3 id="doh-label">Secure DNS</h3><span>Use when your network blocks or redirects supported sites.</span></div>
          <select className="row-select" aria-labelledby="doh-label" value={doh} disabled={locked} onChange={(event) => { setDoh(event.target.value as DohProvider); setApplied(false); }}>
            {dohChoices.map((choice) => <option key={choice.value} value={choice.value}>{choice.label}</option>)}
          </select>
        </div>
        <div className="group-row">
          <span className="row-icon" aria-hidden="true"><Icon name="link" /></span>
          <div className="row-label"><h3 id="proxy-label">Proxy</h3><span>Optional. For sites your network blocks entirely.</span></div>
          <label className="field row-field"><input aria-labelledby="proxy-label" value={proxy} disabled={locked} placeholder="socks5h://127.0.0.1:1080" spellCheck={false} autoComplete="off" onChange={(event) => { setProxy(event.target.value); setApplied(false); }} /></label>
        </div>
        <div className="group-row">
          <span className="row-icon" aria-hidden="true"><Icon name="check" /></span>
          <div className="row-label"><h3 id="cookies-label">Browser cookies</h3><span>For SpankBang when it shows an anti-bot check (common on VPNs). Open the video once in Firefox on the same network, then try again here.</span></div>
          <select className="row-select" aria-labelledby="cookies-label" value={cookies} disabled={locked} onChange={(event) => { setCookies(event.target.value as CookieSource); setApplied(false); }}>
            {cookieChoices.map((choice) => <option key={choice.value} value={choice.value}>{choice.label}</option>)}
          </select>
        </div>
        <div className="group-row group-row--end">
          <span className="row-label">{applied ? <span role="status">Network settings applied.</span> : <span>Applying restarts the media engine.</span>}</span>
          <button type="button" className="btn btn-default" aria-label="Apply network settings" disabled={locked || !changed} onClick={() => void apply()}>{applying ? "Applying…" : "Apply"}</button>
        </div>
      </div>
      {busy ? <p className="group-foot group-foot--notice">A media job is active. Network controls will unlock when it finishes.</p> : null}
      {error ? <div className="settings-error"><p className="inline-error" role="alert">{networkMessages[error] ?? networkMessages.sidecar_unavailable}</p></div> : null}
    </>
  );
}

const ytdlpMessages: Record<string, string> = {
  update_unavailable: "Couldn’t reach GitHub. Check your connection or proxy and try again.",
  update_verification_failed: "The download failed its signature check and was discarded. Your current version was kept.",
  update_failed: "The update couldn’t be saved. Your current version was kept.",
  storage_busy: "Wait for the current media job to finish before updating.",
  sidecar_unavailable: "The media engine couldn’t restart. Your current version was kept.",
};

function YtdlpGroup({ bridge, busy }: { bridge: DesktopBridge; busy: boolean }) {
  const [status, setStatus] = useState<YtdlpStatus | null>(null);
  const [channel, setChannel] = useState<YtdlpChannel>("stable");
  const [updating, setUpdating] = useState(false);
  const [result, setResult] = useState<YtdlpUpdateResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;
    void bridge.getYtdlpStatus?.().then((value) => {
      if (!mounted) return;
      setStatus(value);
      if (value.channel) setChannel(value.channel);
    }).catch(() => undefined);
    return () => { mounted = false; };
  }, [bridge]);

  const update = async () => {
    setUpdating(true);
    setError(null);
    setResult(null);
    try {
      const next = await bridge.updateYtdlp!(channel);
      setStatus(next);
      setResult(next);
    } catch (caught) {
      setError(codeOf(caught));
    } finally {
      setUpdating(false);
    }
  };

  const locked = busy || updating;
  const source = status ? status.source === "updated" ? `Updated · ${status.channel === "nightly" ? "Nightly" : "Stable"}` : "Bundled" : "Unavailable";
  return (
    <>
      <h2 className="group-title">Media engine</h2>
      <div className="group">
        <div className="group-row">
          <span className="row-icon" aria-hidden="true"><Icon name="settings" /></span>
          <div className="row-label"><h3>yt-dlp</h3><span>{status ? `Version ${status.version}` : "Checking version…"}</span></div>
          <span className="badge">{source}</span>
        </div>
        <div className="group-row">
          <span className="row-icon" aria-hidden="true"><Icon name="link" /></span>
          <div className="row-label"><h3 id="ytdlp-channel-label">Update channel</h3><span>Nightly gets site fixes sooner; Stable is released about monthly.</span></div>
          <select className="row-select" aria-labelledby="ytdlp-channel-label" value={channel} disabled={locked} onChange={(event) => { setChannel(event.target.value as YtdlpChannel); setResult(null); }}>
            <option value="stable">Stable</option>
            <option value="nightly">Nightly</option>
          </select>
        </div>
        <div className="group-row group-row--end">
          <span className="row-label">{result
            ? <span role="status">{result.status === "updated" ? `Updated to ${result.version}. The media engine restarted.` : `Already up to date (${result.version}).`}</span>
            : <span>Downloads the official release from GitHub and checks its signature.</span>}</span>
          <button type="button" className="btn btn-default" aria-label="Check for yt-dlp update" disabled={locked || status === null} onClick={() => void update()}>{updating ? "Checking…" : "Check for update"}</button>
        </div>
      </div>
      <p className="group-foot">If downloads from a site start failing, updating yt-dlp usually fixes it.</p>
      {busy ? <p className="group-foot group-foot--notice">A media job is active. Updates will unlock when it finishes.</p> : null}
      {error ? <div className="settings-error"><p className="inline-error" role="alert">{ytdlpMessages[error] ?? ytdlpMessages.update_failed}</p></div> : null}
    </>
  );
}

/** Online lyrics lookup: on by default; sends only a song title to lrclib.net. */
function LyricsRow() {
  const [enabled, setEnabled] = useState(onlineLyricsEnabled);
  const toggle = () => {
    setOnlineLyricsEnabled(!enabled);
    setEnabled(!enabled);
  };
  return (
    <div className="group-row">
      <span className="row-icon" aria-hidden="true"><Icon name="lyrics" /></span>
      <div className="row-label">
        <h3 id="lyrics-online-label">Find lyrics online</h3>
        <span>Looks up the song title on lrclib.net. A .lrc file next to a song is always used first.</span>
      </div>
      <button type="button" role="switch" className="switch" aria-checked={enabled} aria-labelledby="lyrics-online-label" onClick={toggle}>
        <span className="switch__thumb" />
      </button>
    </div>
  );
}

const audioMessages: Record<string, string> = {
  invalid_request: "That audio setting isn't valid.",
  storage_unavailable: "The audio settings couldn't be saved.",
  audio_unavailable: "The audio engine isn't available on this device.",
};

function transportLabel(device: AudioDevice) {
  if (device.transport === "bluetoothHandsFree") return " · Headset (call quality)";
  if (device.transport === "bluetooth") return " · Bluetooth";
  return "";
}

/** Settings → Audio: output device, shared/exclusive mode, rate fallback, exclusive volume. */
function AudioGroup({ audio }: { audio: NativeAudio }) {
  const [settings, setSettings] = useState<AudioSettings | null>(null);
  const [devices, setDevices] = useState<AudioDevice[]>([]);
  const [fallback, setFallback] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let mounted = true;
    let stop: (() => void) | null = null;
    void audio.getSettings().then((value) => { if (mounted) setSettings(value); }).catch(() => undefined);
    void audio.devices().then((value) => { if (mounted) setDevices(value); }).catch((code) => { if (mounted) setError(codeOf(code)); });
    void audio.subscribe((event) => {
      if (event.type === "deviceChanged" && mounted) {
        setDevices(event.devices);
        setFallback(event.fallback);
      }
    }).then((unlisten) => { if (mounted) stop = unlisten; else unlisten(); }, () => undefined);
    return () => { mounted = false; stop?.(); };
  }, [audio]);

  const change = async (patch: Partial<AudioSettings>) => {
    if (!settings) return;
    const next = { ...settings, ...patch };
    setSettings(next);
    setSaving(true);
    setError(null);
    try {
      setSettings(await audio.setSettings(next));
    } catch (caught) {
      setSettings(settings);
      setError(codeOf(caught));
    } finally {
      setSaving(false);
    }
  };

  const chosen = settings?.deviceId ? devices.find((device) => device.id === settings.deviceId) : undefined;
  const fallbackDefault = devices.find((device) => device.isDefault);
  const active = chosen ?? fallbackDefault;
  const missing = Boolean(settings?.deviceId && !chosen && devices.length);
  const locked = settings === null || saving;
  const exclusive = settings?.mode === "exclusive";

  return (
    <>
      <h2 className="group-title">Audio</h2>
      <div className="group">
        <div className="group-row">
          <span className="row-icon" aria-hidden="true"><Icon name="volume" /></span>
          <div className="row-label"><h3 id="audio-device-label">Output device</h3><span>Where music plays. Video always uses the Windows default.</span></div>
          <select className="row-select" aria-labelledby="audio-device-label" value={settings?.deviceId ?? ""} disabled={locked} onChange={(event) => void change({ deviceId: event.target.value || null })}>
            <option value="">Windows default{fallbackDefault ? ` (${fallbackDefault.name})` : ""}</option>
            {devices.map((device) => <option key={device.id} value={device.id}>{device.name}{transportLabel(device)}</option>)}
            {missing ? <option value={settings!.deviceId!}>Disconnected device</option> : null}
          </select>
        </div>
        <div className="group-row">
          <span className="row-icon" aria-hidden="true"><Icon name="music" /></span>
          <div className="row-label"><h3 id="audio-mode-label">Mode</h3><span>{exclusive ? "Plays the file's exact samples. Other apps go quiet while music plays." : "Mixes with other apps like any Windows sound."}</span></div>
          <select className="row-select" aria-labelledby="audio-mode-label" value={settings?.mode ?? "shared"} disabled={locked} onChange={(event) => void change({ mode: event.target.value as AudioSettings["mode"] })}>
            <option value="shared">Shared</option>
            <option value="exclusive">Exclusive · bit-perfect</option>
          </select>
        </div>
        {exclusive ? (
          <>
            <div className="group-row">
              <span className="row-icon" aria-hidden="true"><Icon name="settings" /></span>
              <div className="row-label"><h3 id="audio-rate-label">If the device can't play the file's sample rate</h3><span>Resampling stays exclusive but is no longer bit-perfect.</span></div>
              <select className="row-select" aria-labelledby="audio-rate-label" value={settings?.rateMismatch ?? "strict"} disabled={locked} onChange={(event) => void change({ rateMismatch: event.target.value as AudioSettings["rateMismatch"] })}>
                <option value="strict">Fall back to shared</option>
                <option value="resample">Resample</option>
              </select>
            </div>
            <div className="group-row">
              <span className="row-icon" aria-hidden="true"><Icon name="volume" /></span>
              <div className="row-label"><h3 id="audio-volume-label">Allow volume control in exclusive mode</h3><span>Below 100 % the output is no longer bit-perfect.</span></div>
              <button type="button" role="switch" className="switch" aria-checked={settings?.exclusiveVolume ?? false} aria-labelledby="audio-volume-label" disabled={locked} onClick={() => void change({ exclusiveVolume: !settings?.exclusiveVolume })}>
                <span className="switch__thumb" />
              </button>
            </div>
          </>
        ) : null}
      </div>
      {active?.transport === "bluetoothHandsFree" ? (
        <p className="group-foot group-foot--notice" role="status">This is the headset's call profile: mono, phone quality. Choose its "Headphones" output for music.</p>
      ) : active?.transport === "bluetooth" ? (
        <p className="group-foot">Bluetooth re-compresses audio, so it is never lossless. For bit-perfect playback use speakers, wired headphones or a USB DAC.</p>
      ) : (
        <p className="group-foot">The player shows the signal path; "Bit-perfect" means the file's samples reach the device unchanged.</p>
      )}
      {fallback || missing ? <p className="group-foot group-foot--notice" role="status">Your chosen device isn't connected, so music plays on the Windows default.</p> : null}
      {error ? <div className="settings-error"><p className="inline-error" role="alert">{audioMessages[error] ?? audioMessages.storage_unavailable}</p></div> : null}
    </>
  );
}
