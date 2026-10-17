import { useSyncExternalStore } from "react";

/**
 * How far behind the music engine's clock a Bluetooth headset actually plays.
 * Windows' clock stops at the Bluetooth stack; the headset's codec and radio
 * add roughly 100–300 ms that no API reports, so lyrics would run ahead.
 * The viewer sets it once (Settings → Audio); 0 leaves timing untouched.
 */
const KEY = "qtmedia.audio.bluetoothDelayMs";
const EVENT = "qtmedia-bluetooth-delay";
export const MAX_BLUETOOTH_DELAY_MS = 500;

export function readBluetoothDelay(): number {
  try {
    const value = Number(localStorage.getItem(KEY) ?? 0);
    return Number.isFinite(value) ? Math.max(0, Math.min(MAX_BLUETOOTH_DELAY_MS, Math.round(value))) : 0;
  } catch {
    return 0;
  }
}

export function writeBluetoothDelay(ms: number) {
  try {
    localStorage.setItem(KEY, String(Math.max(0, Math.min(MAX_BLUETOOTH_DELAY_MS, Math.round(ms)))));
  } catch {
    // A convenience only.
  }
  window.dispatchEvent(new Event(EVENT));
}

function subscribe(listener: () => void) {
  window.addEventListener(EVENT, listener);
  return () => window.removeEventListener(EVENT, listener);
}

export function useBluetoothDelay() {
  return useSyncExternalStore(subscribe, readBluetoothDelay, readBluetoothDelay);
}
