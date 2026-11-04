const API_ROOT = import.meta.env.VITE_API_ROOT || '';

export async function call(fn, ...args) {
  const response = await fetch(`${API_ROOT}/api/rpc/${encodeURIComponent(fn)}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ args })
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = data.detail;
    const error = new Error(typeof detail === 'string' ? detail :
      (detail?.message || `Request failed (${response.status})`));
    error.status = response.status;
    error.conflicts = detail?.conflicts || [];
    throw error;
  }
  return data;
}

window.ltmpApi = { call };
