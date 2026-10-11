import { useId } from "react";

/** The Qtmedia monogram: a gradient ring whose tail is a rounded play triangle. */
export function QMark({ size, tile = true, className }: { size: number; tile?: boolean; className?: string }) {
  const id = useId().replace(/:/g, "");
  return (
    <svg className={className} width={size} height={size} viewBox="0 0 100 100" aria-hidden="true">
      <defs>
        <linearGradient id={`${id}g`} x1="18" y1="20" x2="80" y2="82" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="#6f7bff" />
          <stop offset=".5" stopColor="#9b6cff" />
          <stop offset="1" stopColor="#e65bd2" />
        </linearGradient>
        {tile ? (
          <linearGradient id={`${id}b`} x1="0" y1="0" x2="0" y2="100" gradientUnits="userSpaceOnUse">
            <stop offset="0" stopColor="#1b1926" />
            <stop offset="1" stopColor="#0a0a10" />
          </linearGradient>
        ) : null}
      </defs>
      {tile ? (
        <>
          <rect x="4" y="4" width="92" height="92" rx="27" fill={`url(#${id}b)`} />
          <rect x="4.5" y="4.5" width="91" height="91" rx="26.5" fill="none" stroke="rgba(255,255,255,.09)" />
        </>
      ) : null}
      <g transform="translate(-3 -3)">
        <path d="M54.18 66.73 A21 21 0 1 1 66.73 54.18" fill="none" stroke={`url(#${id}g)`} strokeWidth="10.5" strokeLinecap="round" />
        <path d="M63.26 74.58 L74.58 63.26 L78.75 78.75 Z" fill={`url(#${id}g)`} stroke={`url(#${id}g)`} strokeWidth="7" strokeLinejoin="round" />
      </g>
    </svg>
  );
}
