/**
 * @file main.tsx
 * @description Entrypoint for the React application.
 * Bootstraps the application, mounts it to the DOM, imports standard stylesheets, and integrates the routing context.
 *
 * Use Cases:
 * - Bootstrapping the React virtual DOM tree under the html '#root' node.
 * - Injecting react-router BrowserRouter context for shell routing.
 */

import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import App from './App';
import './index.css';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </React.StrictMode>
);
