// Vite entry point: mounts <App/> inside the dialog provider so every component
// can open themed confirm/prompt dialogs.
import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.jsx'
import { DialogProvider } from './components/Dialog.jsx'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <DialogProvider>
      <App />
    </DialogProvider>
  </React.StrictMode>,
)
