'use client';

import type { GPUInfo } from '@/lib/types';
import { Skeleton } from '@/components/ui/skeleton';
import { useLang } from '@/lib/i18n';

interface GPUSidebarProps {
  gpus: GPUInfo[] | undefined;
  loading: boolean;
}

export function GPUSidebar({ gpus, loading }: GPUSidebarProps) {
  const { t } = useLang();
  if (loading || !gpus || gpus.length === 0) {
    return (
      <div className="space-y-3">
        {[...Array(2)].map((_, i) => (
          <Skeleton key={i} className="h-24 w-full rounded-lg" />
        ))}
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {gpus.map((gpu) => {
        const memoryPercent = gpu.memory_total > 0 ? (gpu.memory_used / gpu.memory_total) * 100 : 0;
        return (
          <div key={gpu.index} className="bg-sidebar-accent/50 p-3 rounded-lg border border-sidebar-border/50">
            <div className="flex items-center justify-between mb-2 gap-2">
              <div className="flex items-center gap-2 min-w-0">
                <span
                  className="shrink-0 font-mono text-[10px] font-bold px-1.5 py-0.5 rounded bg-primary/10 border border-primary/30 text-primary"
                  title={gpu.name}
                >
                  {gpu.index}
                </span>
                <span className="text-xs font-semibold text-foreground truncate max-w-[130px]" title={gpu.name}>
                  {gpu.name.replace('AMD Radeon ', '').replace('NVIDIA ', '').replace('GeForce ', '')}
                </span>
              </div>
              {/* 2x2 grid so the Hotspot/VRAM columns line up across cards */}
              <div className="grid grid-cols-2 gap-x-2 text-[10px] font-mono shrink-0">
                <span className="text-muted-foreground">{t('gpu.hotspot')}</span>
                <span className="text-muted-foreground">{t('gpu.vram')}</span>
                <span className="text-foreground tabular-nums">{gpu.temperature}°C</span>
                <span className="text-foreground tabular-nums">{gpu.memory_temperature}°C</span>
              </div>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-sm font-mono font-bold text-foreground">
                {gpu.utilization.toFixed(0)}%{gpu.clock_mhz ? <span className="text-xs font-medium text-muted-foreground"> · {Math.round(gpu.clock_mhz)} MHz</span> : null}
              </span>
              <span className="text-[10px] font-mono text-muted-foreground">
                {gpu.power_draw.toFixed(0)}W · {Math.round(gpu.memory_used / 1024)}/{Math.round(gpu.memory_total / 1024)} GB
              </span>
            </div>
            <div className="h-1.5 w-full bg-sidebar-border rounded-full overflow-hidden mt-1">
              <div
                className="h-full bg-chart-4 transition-all duration-500"
                style={{ width: `${memoryPercent}%` }}
              />
            </div>
            {gpu.mem_clock_mhz ? (
              <div className="text-[10px] font-mono text-muted-foreground mt-1">
                {t('gpu.vramClock', { n: Math.round(gpu.mem_clock_mhz) })}
              </div>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}
