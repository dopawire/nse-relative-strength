// Small inline icon set (stroke icons, 24×24 grid).
import type { SVGProps } from 'react';

const base = { viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 1.8,
  strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const };
const I = (d: string) => (p: SVGProps<SVGSVGElement>) => (
  <svg {...base} {...p} aria-hidden="true"><path d={d} /></svg>
);

export const IconHome = I('M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z');
export const IconTarget = I('M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zm0-4a5 5 0 1 0 0-10 5 5 0 0 0 0 10zm0-4a1 1 0 1 0 0-2 1 1 0 0 0 0 2z');
export const IconBolt = I('M13 2 4 14h7l-1 8 9-12h-7z');
export const IconLayers = I('m12 3 9 5-9 5-9-5zm-9 9 9 5 9-5M3 16l9 5 9-5');
export const IconPulse = I('M3 12h4l3-8 4 16 3-8h4');
export const IconRotate = I('M21 12a9 9 0 1 1-3-6.7M21 4v5h-5');
export const IconFlow = I('M4 20V10m6 10V4m6 16v-7m6 7V8');
export const IconScan = I('M4 7V5a1 1 0 0 1 1-1h2m10 0h2a1 1 0 0 1 1 1v2m0 10v2a1 1 0 0 1-1 1h-2M7 20H5a1 1 0 0 1-1-1v-2m4-5h8');
export const IconSpark = I('M12 3v4m0 10v4M3 12h4m10 0h4M6 6l2.5 2.5m7 7L18 18M6 18l2.5-2.5m7-7L18 6');
export const IconSearch = I('m21 21-4.3-4.3M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14z');
export const IconSun = I('M12 17a5 5 0 1 0 0-10 5 5 0 0 0 0 10zM12 1v2m0 18v2M4.2 4.2l1.4 1.4m12.8 12.8 1.4 1.4M1 12h2m18 0h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4');
export const IconMoon = I('M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z');
export const IconUser = I('M20 21a8 8 0 0 0-16 0M12 13a5 5 0 1 0 0-10 5 5 0 0 0 0 10z');
export const IconMenu = I('M4 6h16M4 12h16M4 18h16');
export const IconX = I('M18 6 6 18M6 6l12 12');
export const IconCopy = I('M9 9h11v11H9zM5 15H4V4h11v1');
export const IconDownload = I('M12 3v12m0 0-5-5m5 5 5-5M4 21h16');
export const IconRefresh = I('M20 11a8 8 0 0 0-14.9-3.9M4 4v4h4m-4 5a8 8 0 0 0 14.9 3.9M20 20v-4h-4');
export const IconLogout = I('M15 17l5-5-5-5m5 5H9m3 9H5a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h7');
export const IconStar = I('m12 3 2.8 5.7 6.2.9-4.5 4.4 1.1 6.2L12 17.3 6.4 20.2l1.1-6.2L3 9.6l6.2-.9z');

export function Logo({ size = 18 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2.6"
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M4 17l5-6 4 3 7-9" />
    </svg>
  );
}
