import React, { useEffect } from 'react';
import { createRoot } from 'react-dom/client';
import shell from './original-shell.html?raw';
import './original.css';
import './api.js';

/**
 * Phase-1 compatibility shell: original markup, styles and navigation
 * are preserved verbatim. React owns the outer shell; legacy.js manages
 * the existing dynamic content inside it. Port modules to React one by one.
 */
function LTMPApp() {
  useEffect(() => {
    const script = document.createElement('script');
    script.src = '/legacy.js';
    script.id = 'ltmp-legacy';
    document.body.appendChild(script);
    return () => script.remove();
  }, []);
  return <div dangerouslySetInnerHTML={{ __html: shell }} />;
}

createRoot(document.getElementById('root')).render(<LTMPApp />);
