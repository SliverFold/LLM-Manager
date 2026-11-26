'use client';

import { useEffect, useRef, useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Skeleton } from '@/components/ui/skeleton';
import { Palette, PowerOff, FileText, Play, ExternalLink } from 'lucide-react';
import { getApiUrl } from '@/lib/api-config';
import { useLang } from '@/lib/i18n';
import { toast } from 'sonner';
import type { GPUInfo } from '@/lib/types';

interface ComfyUIDevice {
  name: string;
}

interface ComfyUIStatus {
  running: boolean;
  queue_running: number;
  queue_pending: number;
  devices: ComfyUIDevice[];
  avg_gen_s: number | null;
  last_gen_s: number | null;
  total_images: number;
  current_gen_s: number | null;
  port: number | null;
}

function cleanGpuName(name: string): string {
  return (name || '').replace(/^cuda:\d+\s+/, '').replace(/\s*:\s*native$/, '');
}

function Metric({ label, value, accent }: { label: string; value: string; accent?: boolean }) {
  return (
    <div className="flex items-center justify-between gap-2">
      <span className="text-muted-foreground">{label}</span>
      <span className={`font-mono truncate ${accent ? 'text-primary' : 'text-foreground'}`}>{value}</span>
    </div>
  );
}

export function ComfyUIStats({ onViewLogs }: { onViewLogs: () => void }) {
  const { t } = useLang();
  const [status, setStatus] = useState<ComfyUIStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [stopping, setStopping] = useState(false);
  const [gpus, setGpus] = useState<GPUInfo[]>([]);
  const [gpuDialog, setGpuDialog] = useState(false);
  const [selectedGpu, setSelectedGpu] = useState<number | null>(null);
  const [starting, setStarting] = useState(false);
  // Client-side smoothing for the "Current" timer: the server value is only
  // sampled every 2s poll, so between polls we extrapolate from the last
  // received (value, timestamp) anchor. Smooth 0.1s ticks, zero extra load.
  const [smoothGenS, setSmoothGenS] = useState<number | null>(null);
  const latestGenRef = useRef<number | null>(null);
  const baseRef = useRef<{ value: number; at: number } | null>(null);

  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      try {
        const res = await fetch(getApiUrl('/api/comfyui/status'));
        const data = await res.json();
        if (!cancelled) {
          latestGenRef.current = data.current_gen_s != null ? data.current_gen_s : null;
          if (data.current_gen_s != null) {
            baseRef.current = { value: data.current_gen_s, at: Date.now() };
          }
          setStatus(data);
          setLoading(false);
        }
      } catch {
        // ignore transient poll failures
      }
    };
    poll();
    const id = setInterval(poll, 2000);
    const ticker = setInterval(() => {
      if (latestGenRef.current == null || !baseRef.current) {
        setSmoothGenS(null);
        return;
      }
      setSmoothGenS(baseRef.current.value + (Date.now() - baseRef.current.at) / 1000);
    }, 100);
    return () => {
      cancelled = true;
      clearInterval(id);
      clearInterval(ticker);
    };
  }, []);

  const stop = async () => {
    setStopping(true);
    try {
      const res = await fetch(getApiUrl('/api/comfyui/stop'), { method: 'POST' });
      const data: { ok: boolean; error?: string } = await res.json();
      if (data.ok) toast.success(t('cu.stoppedToast'));
      else toast.error(data.error || t('cu.stopFailed'));
    } catch (e: any) {
      toast.error(t('cu.stopFailed', { msg: e?.message || String(e) }));
    }
    setStopping(false);
  };

  // --- Start (with GPU picker) ---
  // Default to the GPU with the most free VRAM — that's the card with the
  // headroom for a workflow.
  const defaultGpu = () => {
    let best: GPUInfo | null = null;
    for (const g of gpus) {
      const free = g.memory_total - g.memory_used;
      if (!best || free > best.memory_total - best.memory_used) best = g;
    }
    return best ? best.index : 0;
  };

  const openGpuDialog = () => {
    // Refresh the GPU list right before choosing (VRAM usage changes fast).
    fetch(getApiUrl('/api/gpu'))
      .then((r) => r.json())
      .then((data) => { if (Array.isArray(data)) setGpus(data); })
      .catch(() => {});
    setSelectedGpu(defaultGpu());
    setGpuDialog(true);
  };

  const start = async () => {
    if (selectedGpu === null) return;
    setStarting(true);
    try {
      const res = await fetch(getApiUrl('/api/comfyui/start'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ gpu: selectedGpu }),
      });
      const data: { success: boolean; message?: string } = await res.json();
      if (data.success) {
        setGpuDialog(false);
        toast.success(data.message || t('cu.started'));
      } else {
        toast.error(data.message || t('cu.startFailed'));
      }
    } catch (e: any) {
      toast.error(t('cu.startFailed', { msg: e?.message || String(e) }));
    } finally {
      setStarting(false);
    }
  };

  if (loading || !status) {
    return (
      <Card className="bg-card border border-border/50">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Palette className="h-4 w-4 text-primary" />
            ComfyUI
          </CardTitle>
        </CardHeader>
        <CardContent>
          <Skeleton className="h-16 w-full" />
        </CardContent>
      </Card>
    );
  }

  const gpu = status.devices.map((d) => cleanGpuName(d.name)).filter(Boolean).join(', ') || '—';

  return (
    <Card className="bg-card border border-border/50">
      <CardHeader>
        <CardTitle className="flex items-center justify-between">
          <span className="flex items-center gap-2">
            <Palette className="h-4 w-4 text-primary" />
            ComfyUI
          </span>
          <Badge
            variant={status.running ? 'default' : 'secondary'}
            className={status.running ? 'bg-secondary text-secondary-foreground' : 'bg-muted text-muted-foreground'}
          >
            {status.running ? t('cu.running') : t('cu.stopped')}
          </Badge>
          <div className="flex items-center gap-1">
            {status.running && (
              <Button
                variant="outline"
                size="sm"
                className="h-7 px-2 text-xs"
                onClick={() => window.open(`http://127.0.0.1:${status.port || 8188}`, '_blank', 'noopener')}
              >
                <ExternalLink className="h-3 w-3 mr-1" />
                {t('cu.openUi')}
              </Button>
            )}
            {!status.running && (
              <Button
                size="sm"
                className="h-7 px-2 text-xs"
                disabled={starting}
                onClick={openGpuDialog}
              >
                <Play className="h-3 w-3 mr-1" />
                {starting ? t('cu.starting') : t('cu.start')}
              </Button>
            )}
            <Button variant="outline" size="sm" className="h-7 px-2 text-xs" onClick={onViewLogs}>
              <FileText className="h-3 w-3 mr-1" />
              {t('cu.logs')}
            </Button>
            {status.running && (
              <Button
                variant="outline"
                size="sm"
                className="h-7 px-2 text-xs border-destructive/40 text-destructive hover:bg-destructive/10"
                disabled={stopping}
                onClick={stop}
              >
                <PowerOff className="h-3 w-3 mr-1" />
                {stopping ? t('cu.stopping') : t('cu.stop')}
              </Button>
            )}
          </div>
        </CardTitle>
      </CardHeader>

      <CardContent>
        {!status.running ? (
          <div className="text-sm text-muted-foreground">
            {t('cu.notRunning')}
          </div>
        ) : (
          <div className="grid grid-cols-2 gap-x-6 gap-y-1.5 text-xs">
            <Metric label={t('cu.gpu')} value={gpu} />
            <Metric label={t('cu.queue')} value={t('cu.queueVal', { r: status.queue_running, p: status.queue_pending })} />
            <Metric
              label={t('cu.avgGenTime')}
              value={status.avg_gen_s != null ? `${status.avg_gen_s.toFixed(1)} s` : '—'}
              accent
            />
            <Metric label={t('cu.lastGen')} value={status.last_gen_s != null ? `${status.last_gen_s.toFixed(1)} s` : '—'} />
            <Metric label={t('cu.generations')} value={String(status.total_images)} />
            <Metric
              label={t('cu.current')}
              value={smoothGenS != null ? t('cu.elapsed', { n: smoothGenS.toFixed(1) }) : t('cu.idle')}
              accent={smoothGenS != null}
            />
          </div>
        )}
      </CardContent>

      {/* GPU picker for starting ComfyUI */}
      <Dialog open={gpuDialog} onOpenChange={(open) => { if (!open) setGpuDialog(false); }}>
        <DialogContent className="max-w-md bg-background/95 backdrop-blur-xl border-border shadow-2xl">
          <DialogHeader>
            <DialogTitle className="font-display flex items-center gap-2">
              <Palette className="h-4 w-4 text-primary" />
              {t('cu.gpuSelectTitle')}
            </DialogTitle>
          </DialogHeader>
          <p className="mt-2 text-xs text-muted-foreground">{t('cu.gpuSelectDesc')}</p>
          <div className="mt-3 space-y-2">
            {gpus.length === 0 && (
              <div className="text-xs text-muted-foreground">{t('cu.gpuLoading')}</div>
            )}
            {gpus.map((g) => {
              const freeGb = (g.memory_total - g.memory_used) / 1024;
              const usedGb = g.memory_used / 1024;
              return (
                <label
                  key={g.index}
                  className={`flex items-center gap-3 rounded-lg border p-3 cursor-pointer transition-colors ${
                    selectedGpu === g.index
                      ? 'border-primary bg-primary/10'
                      : 'border-border hover:border-primary/50'
                  }`}
                >
                  <input
                    type="radio"
                    name="comfyui-gpu"
                    checked={selectedGpu === g.index}
                    onChange={() => setSelectedGpu(g.index)}
                    className="h-4 w-4"
                  />
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-medium">
                      GPU {g.index} — {g.name}
                    </div>
                    <div className="text-xs text-muted-foreground">
                      {freeGb.toFixed(1)} GB free · {usedGb.toFixed(1)} GB in use
                    </div>
                  </div>
                  {g.utilization > 0 && (
                    <Badge variant="secondary" className="shrink-0">
                      {g.utilization}%
                    </Badge>
                  )}
                </label>
              );
            })}
          </div>
          <div className="mt-4 flex gap-2">
            <Button onClick={start} disabled={starting || selectedGpu === null || gpus.length === 0}>
              <Play className="h-3 w-3 mr-1" />
              {starting ? t('cu.starting') : t('cu.gpuStart')}
            </Button>
            <Button variant="outline" onClick={() => setGpuDialog(false)}>
              {t('asd.cancel')}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </Card>
  );
}
