import { useMemo } from 'react';
import { encode } from 'uqr';

/**
 * A QR code drawn locally as SVG: the link never leaves the browser.
 * One path for all dark modules keeps the DOM small; the 4-module quiet zone keeps it scannable.
 */
export function QrCode({
  value,
  label,
  size = 168,
}: {
  value: string;
  label: string;
  size?: number;
}) {
  const { d, n } = useMemo(() => {
    const qr = encode(value, { ecc: 'M', border: 4 });
    let path = '';
    qr.data.forEach((row, y) =>
      row.forEach((on, x) => {
        if (on) path += `M${x} ${y}h1v1h-1z`;
      }),
    );
    return { d: path, n: qr.size };
  }, [value]);

  return (
    <svg
      className="qr"
      role="img"
      aria-label={label}
      viewBox={`0 0 ${n} ${n}`}
      width={size}
      height={size}
      shapeRendering="crispEdges"
    >
      <rect width={n} height={n} fill="#fff" />
      <path d={d} fill="#14161b" />
    </svg>
  );
}
