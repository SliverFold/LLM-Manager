export interface GPUInfo {
  index: number;
  name: string;
  temperature: number;
  memory_temperature: number;
  utilization: number;
  memory_used: number;
  memory_total: number;
  power_draw: number;
  clock_mhz?: number;
  mem_clock_mhz?: number;
  power_limit: number;
}

export interface DefaultParams {
  gpus: number[];
  port: number;
  tensor_parallel_size: number;
  gpu_memory_utilization: number;
  max_model_len: number;
  dtype: string;
}

export interface ServiceInfo {
  name: string;
  port: number;
  gpus: number[];
  status: 'running' | 'stopped' | 'error';
  pid?: number;
  cpu_percent?: number;
  memory_mb?: number;
  gpu_memory_mb?: number;
  uptime?: string;
  uptime_seconds?: number;
  message?: string;
  default_params?: DefaultParams;
  loader?: string;
  model?: string;
}

export interface StartConfig {
  gpus: number[];
  port: number;
  saveAsDefault: boolean;
  // loader-specific params, keyed by param_schema field name (snake_case)
  params: Record<string, number | string>;
  // vLLM only (passed via env to the start script)
  parallelMode?: string;
}

export interface SystemInfo {
  cpu_percent: number;
  cpu_name?: string;
  cpu_mhz?: number;
  cpu_temp_c?: number;
  ram_temp_c?: number | null;
  memory_percent: number;
  memory_used_gb: number;
  memory_total_gb: number;
  disk_percent: number;
  disk_used_gb: number;
  disk_total_gb: number;
}

export interface VllmMetrics {
  prompt_tokens: number;
  generation_tokens: number;
  live_tokens_per_sec: number | null;
  live_max: number | null;
  live_min: number | null;
  prefill_avg: number | null;
  live_prefill: number | null;
  prefill_max: number | null;
  prefill_min: number | null;
  avg_tokens_per_sec: number | null;
  ttft_avg_s: number | null;
  ttft_min_s: number | null;
  ttft_max_s: number | null;
  cache_hit_pct: number | null;
  requests_running: number;
  requests_waiting: number;
}

export interface ServicesMap {
  [key: string]: ServiceInfo;
}

export interface MetricPoint {
  timestamp: string;
  value: number;
}

// --- Loader registry (from GET /api/loaders) ---
export interface ParamSchemaField {
  name: string;
  label: string;
  type: 'int' | 'float' | 'select';
  default: number | string;
  min?: number;
  max?: number;
  step?: number;
  options?: string[];
}

export interface LoaderInfo {
  name: string;
  installed: boolean;
  version: string | null;
  detail: string | null;
  param_schema: ParamSchemaField[];
  requires_model: boolean;
  fixed_port: number | null;
}

export interface LoadersMap {
  [key: string]: LoaderInfo;
}

// --- Models (from GET /api/models) ---
export interface ModelInfo {
  loader: string;
  name: string;
  path: string | null;
  size_gb: number;
  format: string;
  source: string;
}

// --- Unified live metrics (from GET /api/service/<key>/metrics) ---
export interface LoadedModel {
  name: string;
  size_gb?: number;
  vram_gb?: number;
}

export interface ServiceMetrics {
  success: boolean;
  loader: string;
  message?: string;
  // vllm (rich throughput):
  prompt_tokens?: number;
  generation_tokens?: number;
  live_tokens_per_sec?: number | null;
  live_max?: number | null;
  live_min?: number | null;
  prefill_avg?: number | null;
  live_prefill?: number | null;
  prefill_max?: number | null;
  prefill_min?: number | null;
  avg_tokens_per_sec?: number | null;
  ttft_avg_s?: number | null;
  ttft_min_s?: number | null;
  ttft_max_s?: number | null;
  cache_hit_pct?: number | null;
  requests_running?: number;
  requests_waiting?: number;
  // ollama / lmstudio / llama_cpp:
  loaded_models?: LoadedModel[];
  version?: string;
  detail?: string;
}
