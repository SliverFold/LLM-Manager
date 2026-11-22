'use client';

import { useEffect, useRef, useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { Palette, PowerOff, FileText } from 'lucide-react';
import { getApiUrl } from '@/lib/api-config';
import { useLang } from '@/lib/i18n';

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
      await fetch(getApiUrl('/api/comfyui/stop'), { method: 'POST' });
    } catch {
      // transient failure; the 2s poll will refresh the badge
    }
    setStopping(false);
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
                {stopping ? t('cu.stopping') : t('cu.kill')}
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
    </Card>
  );
}
