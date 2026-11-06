import { createContext, useContext } from 'react';
import type { Capabilities } from '../api/client';

/**
 * `undefined` while the server has not answered; `null` when it could not say (an older API):
 * then nothing is hidden. Only an explicit `false` hides a feature.
 */
export const CapabilitiesContext = createContext<Capabilities | null | undefined>(null);

export const useCapabilities = () => useContext(CapabilitiesContext);
