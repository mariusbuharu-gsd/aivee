import { useId, useState, type ChangeEvent } from 'react';
import { useApi } from '../api/context';
import { Icon } from './Icon';

export function StaffPhotoUpload() {
  const api = useApi();
  const id = useId();
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState(false);

  async function onChange(e: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(e.target.files ?? []);
    e.target.value = '';
    if (files.length === 0) return;
    setError(false);
    setStatus('Se încarcă…');
    try {
      for (const f of files) await api.uploadStaffPhoto(f);
      setStatus(
        files.length === 1 ? 'Poza a fost adăugată ca exemplu.' : `${files.length} poze adăugate.`,
      );
    } catch (err) {
      setError(true);
      setStatus(err instanceof Error ? err.message : 'Încărcarea a eșuat');
    }
  }

  return (
    <div className="upload">
      <input
        id={id}
        className="visually-hidden"
        type="file"
        accept="image/*"
        multiple
        onChange={onChange}
      />
      <label htmlFor={id} className="btn">
        <Icon name="upload" /> Încarcă poză uniformă
      </label>
      <p className="muted small">
        2–3 poze cu tricoul sau șorțul personalului. Fețele nu sunt folosite.
      </p>
      {status && (
        <p className={error ? 'error' : 'small'} role="status">
          {status}
        </p>
      )}
    </div>
  );
}
