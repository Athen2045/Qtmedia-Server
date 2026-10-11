import { useEffect, useRef, useState } from "react";

/**
 * "Stable volume" for the video player, like YouTube's: quiet passages are
 * lifted and peaks held so a film's dynamics fit laptop speakers or
 * headphones. Applied while playing (Web Audio), so the saved file keeps
 * the original mix and the switch works both ways at any time.
 *
 * The chain is a 2:1 compressor, make-up gain, then a fast limiter so the
 * lifted signal never clips. Tuned with offline renders in Chromium (whose
 * compressor adds its own make-up gain) against YouTube's stable-volume track
 * for a film scene: steady tones at -50/-40/-30/-24/-18/-12/-6 dBFS come out
 * +10.3/+10.3/+10.1/+8.4/+5.5/+2.6/-0.4 dB, with peaks at or below -0.8 dBFS.
 */
export const STABLE_VOLUME = {
  compressor: { threshold: -30, knee: 10, ratio: 2, attack: 0.01, release: 0.4 },
  makeupDb: 2,
  limiter: { threshold: -1.5, knee: 0, ratio: 20, attack: 0.002, release: 0.1 },
} as const;

const STORAGE_KEY = "qtmedia.video.stableVolume";

export function readStableVolume() {
  try {
    return localStorage.getItem(STORAGE_KEY) === "on";
  } catch {
    return false;
  }
}

function writeStableVolume(enabled: boolean) {
  try {
    localStorage.setItem(STORAGE_KEY, enabled ? "on" : "off");
  } catch {
    // A remembered choice is a convenience only.
  }
}

type Chain = { input: AudioNode; output: AudioNode };

/** Builds the compressor → make-up → limiter chain in `context`. */
export function buildStableVolumeChain(context: BaseAudioContext): Chain {
  const set = (node: DynamicsCompressorNode, values: { threshold: number; knee: number; ratio: number; attack: number; release: number }) => {
    node.threshold.value = values.threshold;
    node.knee.value = values.knee;
    node.ratio.value = values.ratio;
    node.attack.value = values.attack;
    node.release.value = values.release;
    return node;
  };
  const compressor = set(context.createDynamicsCompressor(), STABLE_VOLUME.compressor);
  const makeup = context.createGain();
  makeup.gain.value = 10 ** (STABLE_VOLUME.makeupDb / 20);
  const limiter = set(context.createDynamicsCompressor(), STABLE_VOLUME.limiter);
  compressor.connect(makeup).connect(limiter);
  return { input: compressor, output: limiter };
}

type Graph = { context: AudioContext; source: MediaElementAudioSourceNode; chain: Chain };

/**
 * The remembered on/off choice, applied to `video`. The audio graph is built
 * only once stable volume is first turned on (a media element can be routed
 * through Web Audio only once); after that, switching only reconnects nodes.
 */
export function useStableVolume(video: HTMLVideoElement | null) {
  const [enabled, setEnabled] = useState(readStableVolume);
  const graph = useRef<Graph | null>(null);

  useEffect(() => {
    if (!video || typeof AudioContext === "undefined") return;
    if (!enabled && !graph.current) return;
    if (!graph.current || graph.current.source.mediaElement !== video) {
      try {
        const context = new AudioContext();
        graph.current = { context, source: context.createMediaElementSource(video), chain: buildStableVolumeChain(context) };
      } catch {
        return; // Web Audio unavailable: playback continues untouched.
      }
    }
    const { context, source, chain } = graph.current;
    source.disconnect();
    chain.output.disconnect();
    if (enabled) {
      source.connect(chain.input);
      chain.output.connect(context.destination);
    } else {
      source.connect(context.destination);
    }
    if (context.state === "suspended") void context.resume().catch(() => undefined);
  }, [enabled, video]);

  useEffect(() => () => {
    void graph.current?.context.close().catch(() => undefined);
    graph.current = null;
  }, []);

  const toggle = () => {
    setEnabled((current) => {
      writeStableVolume(!current);
      return !current;
    });
  };
  return { enabled, toggle };
}
