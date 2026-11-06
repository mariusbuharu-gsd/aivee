import type { ReactNode } from 'react';
import { Logo } from './Icon';

/** Two-panel frame for the sign-in pages: a night story panel and the form on light ground. */
export function AuthShell({ aside, children }: { aside: ReactNode; children: ReactNode }) {
  return (
    <div className="auth">
      <section className="auth-side on-night" aria-label="Despre AiVee">
        <Logo />
        <div className="auth-story">{aside}</div>
      </section>
      <main id="main" className="auth-main">
        {children}
      </main>
    </div>
  );
}
