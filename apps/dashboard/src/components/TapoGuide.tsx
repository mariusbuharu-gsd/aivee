import { useState } from 'react';
import './CameraSetup.css';

/**
 * Tapo cameras refuse the owner's Tapo account over RTSP: they need a separate "camera
 * account" made in the app. Three steps, drawn as simple phone sketches (no app screenshots,
 * no logos). Collapsed by default; `open` takes over when a wrong password points here.
 */
export function TapoGuide({
  open,
  onToggle,
}: {
  open?: boolean;
  onToggle?: (open: boolean) => void;
}) {
  const [own, setOwn] = useState(false);
  const isOpen = open ?? own;
  return (
    <div className="tapo-guide">
      <p className="small">
        <strong>Tapo cere contul camerei</strong>, diferit de contul tău Tapo.
      </p>
      <details
        open={isOpen}
        onToggle={(e) => {
          const next = e.currentTarget.open;
          if (next === isOpen) return;
          setOwn(next);
          onToggle?.(next);
        }}
      >
        <summary>Cum faci contul camerei în aplicația Tapo (3 pași)</summary>
        <ol className="tapo-steps">
          <li>
            <PhoneSketch step={1} />
            <p>
              În aplicația Tapo, deschide camera și apasă <span aria-hidden="true">⚙</span>
              <span className="visually-hidden">rotița de setări</span> →{' '}
              <strong>Setări avansate</strong> → <strong>Cont cameră</strong>. Creează un utilizator
              și o parolă. Sunt altele decât contul tău Tapo.
            </p>
          </li>
          <li>
            <PhoneSketch step={2} />
            <p>
              Apoi <strong>Eu</strong> → <strong>Tapo Lab</strong> →{' '}
              <strong>Third-Party Compatibility</strong> → <strong>Pornit</strong>, dacă ai
              opțiunea.
            </p>
          </li>
          <li>
            <PhoneSketch step={3} />
            <p>Revino aici și scrie acel utilizator și acea parolă.</p>
          </li>
        </ol>
      </details>
    </div>
  );
}

/** A phone outline with the one thing to tap highlighted. Decorative: the text says it all. */
function PhoneSketch({ step }: { step: 1 | 2 | 3 }) {
  return (
    <svg className="tapo-sketch" viewBox="0 0 64 104" aria-hidden="true" focusable="false">
      <rect className="sk-frame" x="2" y="2" width="60" height="100" rx="9" />
      <rect className="sk-notch" x="24" y="6" width="16" height="3" rx="1.5" />
      {step === 1 && (
        <>
          {/* The gear, top right, then the menu with "Cont cameră" picked. */}
          <circle className="sk-hit" cx="50" cy="18" r="6" />
          <circle className="sk-line" cx="50" cy="18" r="2.4" />
          <rect className="sk-row" x="9" y="32" width="46" height="9" rx="3" />
          <rect className="sk-row" x="9" y="45" width="46" height="9" rx="3" />
          <rect className="sk-row is-hit" x="9" y="58" width="46" height="9" rx="3" />
          <circle className="sk-ink" cx="15" cy="62.5" r="2.2" />
          <rect className="sk-ink" x="21" y="61" width="22" height="3" rx="1.5" />
          <rect className="sk-row" x="9" y="71" width="46" height="9" rx="3" />
        </>
      )}
      {step === 2 && (
        <>
          {/* A list with the switch turned on, and "Eu" picked in the bottom bar. */}
          <rect className="sk-row" x="9" y="20" width="46" height="9" rx="3" />
          <rect className="sk-row is-hit" x="9" y="34" width="46" height="12" rx="3" />
          <rect className="sk-ink" x="13" y="38.5" width="20" height="3" rx="1.5" />
          <rect className="sk-switch" x="39" y="36.5" width="12" height="7" rx="3.5" />
          <circle className="sk-knob" cx="47.5" cy="40" r="2.4" />
          <rect className="sk-row" x="9" y="51" width="46" height="9" rx="3" />
          <line className="sk-line" x1="2" y1="86" x2="62" y2="86" />
          <circle className="sk-row" cx="16" cy="94" r="3" />
          <circle className="sk-row" cx="32" cy="94" r="3" />
          <circle className="sk-hit" cx="48" cy="94" r="4.5" />
        </>
      )}
      {step === 3 && (
        <>
          {/* Back in AiVee: user and password filled in, and the test still. */}
          <rect className="sk-row" x="9" y="20" width="46" height="26" rx="3" />
          <path className="sk-line" d="M14 40l9-9 7 6 6-5 13 8" />
          <rect className="sk-field" x="9" y="54" width="46" height="10" rx="3" />
          <rect className="sk-ink" x="13" y="57.5" width="16" height="3" rx="1.5" />
          <rect className="sk-field" x="9" y="68" width="46" height="10" rx="3" />
          {[15, 21, 27, 33].map((x) => (
            <circle key={x} className="sk-ink" cx={x} cy="73" r="1.6" />
          ))}
          <rect className="sk-hit" x="9" y="83" width="46" height="10" rx="3" />
        </>
      )}
    </svg>
  );
}
