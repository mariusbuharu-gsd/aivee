import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router';
import { App } from './App';
import { createApi } from './api/client';
import { ApiContext } from './api/context';
import { LiveDataProvider } from './state/LiveData';
import './styles.css';

const api = await createApi();

createRoot(document.getElementById('root') as HTMLElement).render(
  <StrictMode>
    <ApiContext.Provider value={api}>
      <BrowserRouter>
        <LiveDataProvider>
          <App />
        </LiveDataProvider>
      </BrowserRouter>
    </ApiContext.Provider>
  </StrictMode>,
);
