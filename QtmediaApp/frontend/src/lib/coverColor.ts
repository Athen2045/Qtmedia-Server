import { useEffect, useState } from "react";

export type Rgb = { r: number; g: number; b: number };

/** Stable fallback colour for covers without artwork, derived from the title. */
export function hashColor(text: string): Rgb {
  let hash = 0;
  for (const char of text) hash = (hash * 31 + char.charCodeAt(0)) >>> 0;
  return hslToRgb(hash % 360, 0.45, 0.42);
}

function hslToRgb(h: number, s: number, l: number): Rgb {
  const k = (n: number) => (n + h / 30) % 12;
  const a = s * Math.min(l, 1 - l);
  const f = (n: number) => l - a * Math.max(-1, Math.min(k(n) - 3, Math.min(9 - k(n), 1)));
  return { r: Math.round(f(0) * 255), g: Math.round(f(8) * 255), b: Math.round(f(4) * 255) };
}

/**
 * Averages pixels weighted by saturation, so vivid regions of the cover set
 * the tint instead of large grey or black areas.
 */
export function dominantColor(pixels: Uint8ClampedArray): Rgb | null {
  let r = 0, g = 0, b = 0, total = 0;
  for (let index = 0; index + 3 < pixels.length; index += 4) {
    const [pr, pg, pb, alpha] = [pixels[index], pixels[index + 1], pixels[index + 2], pixels[index + 3]];
    if (alpha < 128) continue;
    const max = Math.max(pr, pg, pb);
    const min = Math.min(pr, pg, pb);
    const weight = 0.15 + (max === 0 ? 0 : (max - min) / max);
    r += pr * weight; g += pg * weight; b += pb * weight; total += weight;
  }
  if (!total) return null;
  return { r: Math.round(r / total), g: Math.round(g / total), b: Math.round(b / total) };
}

function sample(src: string): Promise<Rgb | null> {
  return new Promise((resolve) => {
    const image = new Image();
    image.onload = () => {
      try {
        const canvas = document.createElement("canvas");
        canvas.width = 12;
        canvas.height = 12;
        const context = canvas.getContext("2d", { willReadFrequently: true });
        if (!context) return resolve(null);
        context.drawImage(image, 0, 0, 12, 12);
        resolve(dominantColor(context.getImageData(0, 0, 12, 12).data));
      } catch {
        resolve(null);
      }
    };
    image.onerror = () => resolve(null);
    image.src = src;
  });
}

/** Colour sampled from `src` (a local data URL), or a title-derived fallback. */
export function useCoverColor(src: string | null, fallbackKey: string): Rgb {
  const [color, setColor] = useState<Rgb>(() => hashColor(fallbackKey));
  useEffect(() => {
    let mounted = true;
    setColor(hashColor(fallbackKey));
    if (src) void sample(src).then((value) => { if (mounted && value) setColor(value); });
    return () => { mounted = false; };
  }, [src, fallbackKey]);
  return color;
}

/** Lifts very dark colours so tints and progress fills stay visible on ink. */
export function readable({ r, g, b }: Rgb, minimum = 110): Rgb {
  const brightest = Math.max(r, g, b, 1);
  const scale = brightest < minimum ? minimum / brightest : 1;
  return { r: Math.min(255, Math.round(r * scale)), g: Math.min(255, Math.round(g * scale)), b: Math.min(255, Math.round(b * scale)) };
}

export const rgb = ({ r, g, b }: Rgb, alpha = 1) => `rgba(${r}, ${g}, ${b}, ${alpha})`;
