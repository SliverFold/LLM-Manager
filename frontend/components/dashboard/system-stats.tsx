'use client';

import { Database, HardDrive, Cpu } from 'lucide-react';
import type { SystemInfo } from '@/lib/types';
import { Skeleton } from '@/components/ui/skeleton';
import { useLang } from '@/lib/i18n';

interface SystemStatsProps {
  info?: SystemInfo;
  loading?: boolean;
}

export function SystemStats({ info, loading }: SystemStatsProps) {
  const { t } = useLang();
  if (loading || !info) {
    return (
      <div className="space-y-6 flex flex-col items-center">
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-24 w-full" />
      </div>
    );
  }

  // "AMD Ryzen 7 5800X3D 8-Core Processor" -> "Ryzen 7 5800X3D 8-Core"
  const shortCpuName = (info.cpu_name || '')
    .replace(/^AMD /, '')
    .replace(/ \d+-Core Processor$/, '')
    .replace(/ Processor$/, '');

  const stats = [
    {
      label: t('stat.cpu'),
      value: info.cpu_percent,
      detail: info.cpu_name || info.cpu_mhz
        ? `${Math.round(info.cpu_mhz || 0)} MHz · ${Math.round(info.cpu_temp_c || 0)}°C · ${shortCpuName}`
        : undefined,
      icon: Cpu,
      color: 'text-chart-1',
      bgColor: 'bg-chart-1',
    },
    {
      label: t('stat.memory'),
      value: info.memory_percent,
      detail: `${info.memory_used_gb.toFixed(0)}/${info.memory_total_gb.toFixed(0)} GB${info.ram_temp_c != null ? ` · ${Math.round(info.ram_temp_c)}°C` : ''}`,
      icon: Database,
      color: 'text-chart-2',
      bgColor: 'bg-chart-2',
    },
    {
      label: t('stat.disk'),
      value: info.disk_percent,
      detail: t('stat.gbUsed', { n: info.disk_used_gb.toFixed(0) }),
      icon: HardDrive,
      color: 'text-chart-3',
      bgColor: 'bg-chart-3',
    },
  ];

  return (
    <div className="w-full space-y-4">
      {stats.map((stat) => (
        <div key={stat.label} className="bg-sidebar-accent/50 p-3 rounded-lg border border-sidebar-border/50">
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-2 text-muted-foreground">
              <stat.icon className="h-4 w-4" />
              <span className="text-xs font-medium">{stat.label}</span>
            </div>
            <span className={`font-mono font-bold ${stat.color}`}>{stat.value.toFixed(0)}%</span>
          </div>
          <div className="h-1.5 w-full bg-sidebar-border rounded-full overflow-hidden">
            <div
              className={`h-full ${stat.bgColor} transition-all duration-500`}
              style={{ width: `${stat.value}%` }}
            />
          </div>
          {stat.detail && (
            <p className="text-[10px] text-right text-muted-foreground mt-1 font-mono">{stat.detail}</p>
          )}
        </div>
      ))}
    </div>
  );
}
