'use client';

import { useEffect, useRef, useState } from 'react';
import { getApiUrl } from '@/lib/api-config';
import { Activity, Zap, Clock, Layers, List, Cpu, HardDrive } from 'lucide-react';
import { Skeleton } from '@/components/ui/skeleton';
import type { ServiceMetrics } from '@/lib/types';
import { useLang } from '@/lib/i18n';

interface DataPoint {
  liveRate: number;
  avgRate: number;
}

interface CurrentMetrics {
  live?: number;
  avg?: number;
  prefill?: number;
  prefillAvg?: number;
  ttftAvg?: number;
  ttftMin?: number;
  ttftMax?: number;
  cacheHit?: number;
  running?: number;
  waiting?: number;
}

interface ThroughputChartProps {
  serviceKey: string;
  isRunning: boolean;
}

const MAX_POINTS = 60; // ~2 minutes at 2s polling

// Loaders that serve the vLLM-style metrics payload (live/avg tok/s, prefill,
// TTFT, cache hits): vLLM directly, LM Studio (shaped like it), and Paiton
// (OpenAI-compatible API, _vllm_metrics_payload in app.py).
const VLLM_COMPATIBLE = new Set(['vllm', 'lmstudio', 'paiton']);

export function ThroughputChart({ serviceKey, isRunning }: ThroughputChartProps) {
  const { t } = useLang();
  const [history, setHistory] = useState<DataPoint[]>([]);
  const [current, setCurrent] = useState<CurrentMetrics>({});
  const [metrics, setMetrics] = useState<ServiceMetrics | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [chartSize, setChartSize] = useState({ w: 560, h: 160 });

  // Measure the actual container size so the chart scales with zoom/resize
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const { width } = entry.contentRect;
        if (width > 0) {
          // Keep a fixed aspect ratio (width:height = 3.5:1) — flat so the card stays compact
          setChartSize({ w: width, h: Math.max(120, width / 3.5) });
        }
      }
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!isRunning) {
      setHistory([]);
      setCurrent({});
      setMetrics(null);
      return;
    }
    let cancelled = false;
    const poll = async () => {
      try {
        const res = await fetch(getApiUrl(`/api/service/${serviceKey}/metrics`));
        const data: ServiceMetrics = await res.json();
        if (!cancelled && data.success) {
          setMetrics(data);
          if (VLLM_COMPATIBLE.has(data.loader)) {
            const live = data.live_tokens_per_sec ?? 0;
            const avg = data.avg_tokens_per_sec ?? 0;
            const prefill = data.live_prefill ?? 0;
            setCurrent({
              live,
              avg,
              prefill,
              prefillAvg: data.prefill_avg ?? undefined,
              ttftAvg: data.ttft_avg_s ?? undefined,
              ttftMin: data.ttft_min_s ?? undefined,
              ttftMax: data.ttft_max_s ?? undefined,
              cacheHit: data.cache_hit_pct ?? undefined,
              running: data.requests_running,
              waiting: data.requests_waiting,
            });
            setHistory((prev) => {
              const point: DataPoint = { liveRate: live, avgRate: avg };
              return [...prev, point].slice(-MAX_POINTS);
            });
          }
        }
      } catch {
        // ignore transient poll failures
      }
    };
    poll();
    const id = setInterval(poll, 2000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [isRunning, serviceKey]);

  // Reset the chart when the service key changes
  useEffect(() => {
    setHistory([]);
    setMetrics(null);
  }, [serviceKey]);

  const { w: width, h: height } = chartSize;
  const pad = { top: 16, right: 16, bottom: 28, left: 48 };
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;

  // Scale to the GENERATION rates only (not prefill, which is 100x larger)
  const genValues = history.flatMap((p) => [p.liveRate, p.avgRate]);
  const maxY = Math.max(20, ...genValues) * 1.2;

  const x = (i: number) => pad.left + (i / Math.max(1, MAX_POINTS - 1)) * plotW;
  const y = (v: number) => pad.top + plotH - (v / maxY) * plotH;

  const toPath = (key: keyof DataPoint) =>
    history.map((p, i) => `${i === 0 ? 'M' : 'L'} ${x(i).toFixed(1)} ${y(p[key]).toFixed(1)}`).join(' ');

  const fmt = (n: number) => (n >= 1000 ? `${(n / 1000).toFixed(1)}k` : `${n.toFixed(0)}`);

  // Non-vLLM-compatible loaders: show loaded models + VRAM instead of a throughput chart
  const isVllm = !metrics || VLLM_COMPATIBLE.has(metrics.loader);

  return (
    <div className="bg-card border border-border/50 rounded-xl p-4 flex flex-col">
      <div className="flex items-center gap-2 mb-3">
        <Activity className="h-4 w-4 text-primary" />
        <h3 className="text-sm font-semibold text-foreground">{t('tc.title')}</h3>
        <span className="ml-auto text-xs font-mono text-muted-foreground">
          {isRunning && isVllm && current.live !== undefined
            ? `${current.live.toFixed(0)} tok/s`
            : isRunning && metrics?.loaded_models?.length
              ? t('tc.modelsLoaded', { n: metrics.loaded_models.length })
              : '—'}
        </span>
      </div>

      {!isRunning ? (
        <div className="flex-1 flex items-center justify-center text-sm text-muted-foreground min-h-[160px]">
          {t('tc.stoppedMsg')}
        </div>
      ) : isVllm ? (
        <>
          <div className="flex items-center gap-4 mb-2 text-xs">
            <span className="flex items-center gap-1">
              <span className="h-2 w-2 rounded-full bg-blue-500" /> {t('tc.live')}
            </span>
            <span className="flex items-center gap-1">
              <span className="h-2 w-2 rounded-full bg-emerald-500" /> {t('tc.avg')}
            </span>
          </div>

          <div ref={containerRef} className="w-full">
            {history.length < 2 ? (
              <Skeleton className="h-[160px] w-full" />
            ) : (
              <svg
                viewBox={`0 0 ${width} ${height}`}
                width={width}
                height={height}
                className="w-full h-auto"
                preserveAspectRatio="xMidYMid meet"
              >
                {/* grid lines */}
                {[0, 0.25, 0.5, 0.75, 1].map((f) => (
                  <line
                    key={f}
                    x1={pad.left}
                    y1={y(maxY * f)}
                    x2={width - pad.right}
                    y2={y(maxY * f)}
                    stroke="currentColor"
                    className="text-muted-foreground/20"
                    strokeWidth={1}
                  />
                ))}
                {/* y-axis labels */}
                {[0, 0.5, 1].map((f) => (
                  <text
                    key={f}
                    x={pad.left - 8}
                    y={y(maxY * f) + 4}
                    textAnchor="end"
                    className="fill-muted-foreground text-[10px] font-mono"
                  >
                    {fmt(maxY * f)}
                  </text>
                ))}
                {/* lines */}
                <path d={toPath('liveRate')} fill="none" stroke="#3b82f6" strokeWidth={2} />
                <path d={toPath('avgRate')} fill="none" stroke="#10b981" strokeWidth={2} />
              </svg>
            )}
          </div>

          {/* Prefill + averages + extra metrics — shown below the chart because
              prefill runs ~100x faster than generation (different scale) */}
          <div className="mt-3 pt-3 border-t border-border/40 text-xs space-y-1.5">
            <div className="flex items-center gap-2">
              <Zap className="h-3.5 w-3.5 text-amber-500" />
              <span className="text-muted-foreground">{t('tc.prefill')}</span>
              <span className="font-mono text-foreground">
                {current.prefill !== undefined ? `${current.prefill.toFixed(0)} tok/s` : '—'}
              </span>
              <span className="text-muted-foreground">{t('tc.prefillAvg')}</span>
              <span className="font-mono text-foreground">
                {current.prefillAvg !== undefined ? `${current.prefillAvg.toFixed(0)} tok/s` : '—'}
              </span>
            </div>
            <div className="flex items-center gap-2">
              <Activity className="h-3.5 w-3.5 text-emerald-500" />
              <span className="text-muted-foreground">{t('tc.avgGen')}</span>
              <span className="font-mono text-foreground">
                {current.avg !== undefined ? `${current.avg.toFixed(1)} tok/s` : '—'}
              </span>
              <span className="text-muted-foreground text-[10px]">{t('tc.avgGenNote')}</span>
            </div>
            <div className="flex items-center gap-2">
              <Clock className="h-3.5 w-3.5 text-sky-500" />
              <span className="text-muted-foreground">{t('tc.ttft')}</span>
              <span className="font-mono text-foreground">
                {current.ttftAvg !== undefined ? `${current.ttftAvg.toFixed(2)}s` : '—'}
              </span>
              <span className="text-muted-foreground">
                {current.ttftMin !== undefined && current.ttftMax !== undefined
                  ? `(${current.ttftMin.toFixed(2)}s–${current.ttftMax.toFixed(2)}s)`
                  : ''}
              </span>
            </div>
            <div className="flex items-center gap-2">
              <Layers className="h-3.5 w-3.5 text-violet-500" />
              <span className="text-muted-foreground">{t('tc.cacheHit')}</span>
              <span className="font-mono text-foreground">
                {current.cacheHit !== undefined ? `${current.cacheHit.toFixed(1)}%` : '—'}
              </span>
            </div>
            <div className="flex items-center gap-2">
              <List className="h-3.5 w-3.5 text-rose-500" />
              <span className="text-muted-foreground">{t('tc.requests')}</span>
              <span className="font-mono text-foreground">
                {current.running !== undefined
                  ? t('tc.runningWaiting', { r: current.running, w: current.waiting ?? 0 })
                  : '—'}
              </span>
            </div>
          </div>
        </>
      ) : (
        // Non-vLLM backend: show what's loaded (models + VRAM) instead of a chart
        <div className="flex-1 flex flex-col min-h-[160px]">
          {metrics?.detail && (
            <div className="text-xs text-muted-foreground mb-3">{metrics.detail}</div>
          )}
          {metrics?.loaded_models && metrics.loaded_models.length > 0 ? (
            <div className="space-y-2">
              {metrics.loaded_models.map((m, i) => (
                <div key={i} className="flex items-center justify-between gap-2 text-xs border border-border/40 rounded-md p-2">
                  <div className="flex items-center gap-2 min-w-0">
                    <Cpu className="h-3.5 w-3.5 text-primary shrink-0" />
                    <span className="font-mono text-foreground truncate" title={m.name}>{m.name}</span>
                  </div>
                  <div className="flex items-center gap-3 font-mono text-muted-foreground shrink-0">
                    {m.size_gb !== undefined && <span>{m.size_gb.toFixed(1)} GB</span>}
                    {m.vram_gb !== undefined && (
                      <span className="flex items-center gap-1">
                        <HardDrive className="h-3 w-3" />
                        {m.vram_gb.toFixed(1)} GB VRAM
                      </span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="flex-1 flex items-center justify-center text-sm text-muted-foreground">
              {metrics?.loaded_models?.length === 0
                ? t('tc.noModels')
                : t('tc.loading')}
            </div>
          )}
          {metrics?.version && (
            <div className="mt-3 pt-3 border-t border-border/40 text-[10px] font-mono text-muted-foreground">
              {metrics.loader} {metrics.version}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
