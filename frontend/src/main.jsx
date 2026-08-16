import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import './index.css';
import App from './App.jsx';

// StrictMode mantido de propósito: monta/desmonta cada componente duas vezes
// em dev, o que expõe qualquer vazamento de GPUDevice/rVFC que o teardown de
// motorAnime4k.js não cubra corretamente (ver useMotorAnime4k.js).
createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
  </StrictMode>
);
