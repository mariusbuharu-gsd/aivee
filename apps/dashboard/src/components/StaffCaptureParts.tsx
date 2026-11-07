// Pieces shared by the camera dialog ("Adaugă angajat") and the one-phone page (/angajat-nou).
import { useId } from 'react';
import type { StaffCapture, StaffProfile } from '../api/client';
import { NEW_PROFILE } from '../staff/capture';
import { Select } from '../ui/Select';
import { Icon } from './Icon';
import './StaffCapture.css';

/** Step ①: a new employee's name, or an existing profile to add to. */
export function ProfileFields({
  profiles,
  profileId,
  onProfile,
  name,
  onName,
  onEnter,
}: {
  profiles: StaffProfile[];
  profileId: string;
  onProfile: (id: string) => void;
  name: string;
  onName: (name: string) => void;
  onEnter: () => void;
}) {
  const nameId = useId();
  const existing = profiles.find((p) => p.id === profileId) ?? null;
  return (
    <div className="stack-form">
      {profiles.length > 0 && (
        <Select
          label="Profil"
          value={profileId}
          onChange={onProfile}
          options={[
            { value: NEW_PROFILE, label: 'Angajat nou' },
            ...profiles.map((p) => ({
              value: p.id,
              label: p.name,
              hint: `${p.examples} ${p.examples === 1 ? 'exemplu' : 'exemple'}`,
            })),
          ]}
        />
      )}
      {!existing && (
        <label className="field" htmlFor={nameId}>
          <span>Nume</span>
          <input
            id={nameId}
            className="input"
            value={name}
            maxLength={80}
            autoComplete="off"
            placeholder="ex. Ana, ospătar"
            data-autofocus
            onChange={(e) => onName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') onEnter();
            }}
          />
        </label>
      )}
      {existing && <p className="small">Adăugăm imagini noi la profilul „{existing.name}”.</p>}
    </div>
  );
}

/** Step ③: the largest person of each frame, all ticked; a tap drops one. */
export function CandidateGrid({
  capture,
  kept,
  onToggle,
  who,
}: {
  capture: StaffCapture;
  kept: Set<number>;
  onToggle: (index: number) => void;
  who: string;
}) {
  return (
    <>
      <p className="small">
        Am găsit {capture.candidates.length}{' '}
        {capture.candidates.length === 1 ? 'imagine' : 'imagini'} cu {who}. Atinge una ca să o scoți
        (alte persoane, imagini neclare).
      </p>
      <ul className="staff-capture-grid">
        {capture.candidates.map((c) => {
          const on = kept.has(c.index);
          return (
            <li key={c.index}>
              <button
                type="button"
                className={`staff-capture-thumb ${on ? 'is-on' : 'is-off'}`}
                aria-pressed={on}
                aria-label={`Imaginea ${c.index + 1}${on ? ', păstrată' : ', scoasă'}`}
                onClick={() => onToggle(c.index)}
              >
                <img src={c.thumbnail} alt="" />
                <span className="staff-capture-tick" aria-hidden="true">
                  <Icon name={on ? 'check' : 'x'} size={16} />
                </span>
              </button>
            </li>
          );
        })}
      </ul>
      <p className="muted small">
        Păstrezi {kept.size} din {capture.candidates.length}. Fețele nu sunt folosite, doar ținuta.
      </p>
    </>
  );
}
