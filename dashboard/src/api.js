// src/api.js
// Centralised API helper for the dashboard.
// Vite injects variables prefixed with VITE_ into import.meta.env.
const getApiUrl = () => {
  if (import.meta.env.VITE_API_URL) {
    return import.meta.env.VITE_API_URL;
  }
  const hostname = window.location.hostname || "localhost";
  return `http://${hostname}:8000`;
};
const BASE_URL = getApiUrl();

// Placeholder for future auth token. Currently not used.
const getAuthHeaders = () => {
  const token = import.meta.env.VITE_API_TOKEN;
  return token ? { Authorization: `Bearer ${token}` } : {};
};

/**
 * Generic request wrapper.
 * @param {"GET"|"POST"|"PUT"|"DELETE"} method HTTP method.
 * @param {string} path API path starting with '/'.
 * @param {object|null} payload JSON‑serialisable body for POST/PUT.
 * @returns {Promise<any>} Parsed JSON response.
 * @throws Will throw an Error with `status` and `body` if response not ok.
 */
export const request = async (method, path, payload = null) => {
  const url = `${BASE_URL}${path}`;
  const opts = {
    method,
    headers: {
      "Content-Type": "application/json",
      ...getAuthHeaders(),
    },
  };
  if (payload) {
    opts.body = JSON.stringify(payload);
  }
  const resp = await fetch(url, opts);
  const data = await resp.json();
  if (!resp.ok) {
    const err = new Error(data.detail || resp.statusText);
    err.status = resp.status;
    err.body = data;
    throw err;
  }
  return data;
};
