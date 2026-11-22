import useSWR from 'swr';
import type { GPUInfo, ServicesMap, SystemInfo, LoadersMap, ModelInfo } from '@/lib/types';
import { getApiUrl } from '@/lib/api-config';

const fetcher = async (url: string) => {
  const res = await fetch(url);
  if (!res.ok) {
    throw new Error('An error occurred while fetching the data.');
  }
  return res.json();
};

// Poll every 2s (not 500ms) — the backend can be slow during model
// load/unload, and a 500ms poll causes the "Connection failed" error to
// flash on screen. 2s is a reasonable balance between freshness and
// not hammering the backend.
//
// Keep the DEFAULT shouldRetryOnError (true) on all three hooks — do NOT
// set it to false: with it false, the 2s polling loop skips revalidation
// while an error is set, so a transient backend hiccup (the werkzeug dev
// server drops connections under model-load load) latches the full-screen
// "Connection failed" until a tab-focus event. Default true gives SWR's
// ~5s-backoff error retries, which auto-clear the error once the backend
// recovers. The screen only shows when ALL 3 endpoints fail at once
// (page.tsx), so a single slow endpoint will never flash it.
export function useServices() {
  return useSWR<ServicesMap>(getApiUrl('/api/services'), fetcher, {
    refreshInterval: 2000,
  });
}

export function useGPU() {
  return useSWR<GPUInfo[]>(getApiUrl('/api/gpu'), fetcher, {
    refreshInterval: 2000,
  });
}

export function useSystemInfo() {
  return useSWR<SystemInfo>(getApiUrl('/api/system'), fetcher, {
    refreshInterval: 2000,
  });
}

// Loader registry (detection status + param_schema). Changes rarely (only when
// a loader is installed/uninstalled), so poll slowly.
export function useLoaders() {
  return useSWR<LoadersMap>(getApiUrl('/api/loaders'), fetcher, {
    refreshInterval: 30000,
  });
}

// Runnable models across installed loaders (for the Add Service wizard).
export function useModels() {
  return useSWR<ModelInfo[]>(getApiUrl('/api/models'), fetcher, {
    refreshInterval: 30000,
  });
}
