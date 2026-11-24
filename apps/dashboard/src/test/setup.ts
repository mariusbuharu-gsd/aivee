import '@testing-library/jest-dom/vitest';
import { cleanup, configure } from '@testing-library/react';
import { afterEach } from 'vitest';

afterEach(() => cleanup());

// Pages are lazy chunks (App.tsx): under a full parallel run the first import of one can take
// longer than the default 1 s that findBy/waitFor wait.
configure({ asyncUtilTimeout: 4_000 });

// jsdom has no modal dialogs yet: enough of HTMLDialogElement for <Dialog>.
if (typeof HTMLDialogElement !== 'undefined' && !HTMLDialogElement.prototype.showModal) {
  HTMLDialogElement.prototype.showModal = function showModal(this: HTMLDialogElement) {
    this.setAttribute('open', '');
  };
  HTMLDialogElement.prototype.close = function close(this: HTMLDialogElement) {
    this.removeAttribute('open');
    this.dispatchEvent(new Event('close'));
  };
}
