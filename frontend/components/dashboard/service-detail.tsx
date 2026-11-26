'use client';

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Play, Square, FileText, HardDrive, Trash2 } from 'lucide-react';
import type { ServiceInfo, GPUInfo, StartConfig, ParamSchemaField } from '@/lib/types';
import { useState } from 'react';
import { useLoaders } from '@/hooks/use-dashboard-data';
import { toast } from 'sonner';
import { getApiUrl } from '@/lib/api-config';
import { useLang } from '@/lib/i18n';

interface ServiceDetailProps {
  serviceKey: string;
  service: ServiceInfo;
  availableGpus: GPUInfo[];
  onViewLogs: (serviceKey: string, serviceName: string) => void;
  onRemoved?: (serviceKey: string) => void;
}

const formatUptime = (secs: number) => {
  const d = Math.floor(secs / 86400);
  const h = Math.floor((secs % 86400) / 3600);
  const m = Math.floor((secs % 3600) / 60);
  if (d > 0) return `${d}d ${h}h`;
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
};

// Render a single param field based on its param_schema type.
function ParamField({ field, value, onChange }: {
  field: ParamSchemaField;
  value: number | string;
  onChange: (v: number | string) => void;
}) {
  if (field.type === 'select') {
    return (
      <div className="space-y-2">
        <label className="text-sm font-medium">{field.label}</label>
        <select
          value={String(value)}
          onChange={(e) => onChange(e.target.value)}
          className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm"
        >
          {(field.options || []).map((o) => (
            <option key={o} value={o} className="bg-background">{o}</option>
          ))}
        </select>
      </div>
    );
  }
  if (field.type === 'float') {
    return (
      <div className="space-y-2">
        <div className="flex justify-between">
          <label className="text-sm font-medium">{field.label}</label>
          <span className="text-sm text-muted-foreground">{value}</span>
        </div>
        <input
          type="range"
          min={field.min}
          max={field.max}
          step={field.step || 0.05}
          value={Number(value)}
          onChange={(e) => onChange(parseFloat(e.target.value))}
          className="w-full h-2 bg-secondary rounded-lg cursor-pointer"
        />
      </div>
    );
  }
  // int
  return (
    <div className="space-y-2">
      <label className="text-sm font-medium">{field.label}</label>
      <input
        type="number"
        min={field.min}
        max={field.max}
        value={Number(value)}
        onChange={(e) => onChange(parseInt(e.target.value) || 0)}
        className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm"
      />
    </div>
  );
}

export function ServiceDetail({ serviceKey, service, availableGpus = [], onViewLogs, onRemoved }: ServiceDetailProps) {
  const { data: loaders } = useLoaders();
  const { t } = useLang();
  const [isLoading, setIsLoading] = useState(false);
  const [showConfig, setShowConfig] = useState(false);
  const [config, setConfig] = useState<StartConfig | null>(null);
  const isRunning = service.status === 'running';

  // The service's loader (default to vllm for legacy services without the field)
  const loaderKey = service.loader || 'vllm';
  const loader = loaders?.[loaderKey];
  // param_schema fields to render, skipping selects with no options (e.g. vllm's 'image')
  const schema = (loader?.param_schema || []).filter(
    (f) => !(f.type === 'select' && (!f.options || f.options.length === 0))
  );

  const buildConfig = (): StartConfig => {
    const dp = (service.default_params || {}) as Record<string, unknown>;
    const params: Record<string, number | string> = {};
    for (const field of schema) {
      params[field.name] = (dp[field.name] as number | string) ?? field.default;
    }
    return {
      gpus: (dp.gpus as number[]) || service.gpus || (availableGpus.length > 0 ? [availableGpus[0].index] : []),
      port: (dp.port as number) || service.port,
      saveAsDefault: false,
      params,
      parallelMode: (dp.parallel_mode as string) || 'tp',
    };
  };

  const handleStartClick = () => {
    setConfig(buildConfig());
    setShowConfig(true);
  };

  const handleConfirmStart = async () => {
    if (!config) return;
    if (config.gpus.length === 0) {
      toast.error(t('sd.selectGpu'));
      return;
    }
    setShowConfig(false);
    setIsLoading(true);
    try {
      const body: Record<string, unknown> = {
        gpus: config.gpus,
        port: config.port,
        saveAsDefault: config.saveAsDefault,
        ...config.params, // top-level snake_case fields the backend reads
      };
      if (loaderKey === 'vllm' && config.parallelMode) {
        body.parallelMode = config.parallelMode;
      }
      const response = await fetch(getApiUrl(`/api/service/${serviceKey}/start`), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const result = await response.json();
      if (result.success) toast.success(t('sd.startSuccess'));
      else toast.error(t('sd.startFailed', { msg: result.message }));
    } catch (error) {
      toast.error(t('sd.startFailed', { msg: error instanceof Error ? error.message : t('page.unknownError') }));
    } finally {
      setIsLoading(false);
    }
  };

  const handleStop = async () => {
    setIsLoading(true);
    try {
      const response = await fetch(getApiUrl(`/api/service/${serviceKey}/stop`), { method: 'POST' });
      const result = await response.json();
      if (result.success) toast.success(t('sd.stopSuccess'));
      else toast.error(t('sd.stopFailed', { msg: result.message }));
    } catch (error) {
      toast.error(t('sd.stopFailed', { msg: error instanceof Error ? error.message : t('page.unknownError') }));
    } finally {
      setIsLoading(false);
    }
  };

  const handleRemove = async () => {
    if (!window.confirm(
      t('sd.removeConfirm', { name: service.name })
    )) {
      return;
    }
    setIsLoading(true);
    try {
      const response = await fetch(getApiUrl(`/api/service/${serviceKey}/remove`), { method: 'POST' });
      const result = await response.json();
      if (result.success) {
        toast.success(t('sd.removeSuccess'));
        onRemoved?.(serviceKey);
      } else {
        toast.error(t('sd.removeFailed', { msg: result.message }));
      }
    } catch (error) {
      toast.error(t('sd.removeFailed', { msg: error instanceof Error ? error.message : t('page.unknownError') }));
    } finally {
      setIsLoading(false);
    }
  };

  const handleAddToHermes = async () => {
    setIsLoading(true);
    try {
      const response = await fetch(getApiUrl('/api/hermes/add-service'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ service: serviceKey }),
      });
      const result = await response.json();
      if (result.success) toast.success(t('sd.addToHermesSuccess', { profile: result.profile }));
      else toast.error(t('sd.addToHermesFailed', { msg: result.message }));
    } catch (error) {
      toast.error(t('sd.addToHermesFailed', { msg: error instanceof Error ? error.message : t('page.unknownError') }));
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <Card className="bg-card border border-border/50">
      <CardHeader>
        <CardTitle className="flex items-center justify-between">
          <span className="text-base font-bold font-display tracking-tight">{service.name}</span>
          <Badge
            variant={isRunning ? 'default' : 'secondary'}
            className={isRunning ? 'bg-secondary text-secondary-foreground' : 'bg-muted text-muted-foreground'}
          >
            {isRunning ? t('sd.running') : t('sd.stopped')}
          </Badge>
        </CardTitle>
      </CardHeader>

      <CardContent className="space-y-4">
        <div className="grid grid-cols-2 gap-2 text-xs">
          <div className="flex items-center gap-1 text-muted-foreground">
            <span>{t('sd.port')}</span>
            <span className="font-mono text-foreground">{service.port}</span>
          </div>
          <div className="flex items-center gap-1 text-muted-foreground">
            <HardDrive className="h-3 w-3" />
            <span>{t('sd.gpu')}</span>
            <span className="font-mono text-foreground">{service.gpus.join(', ')}</span>
          </div>
          {loader && (
            <div className="flex items-center gap-1 text-muted-foreground">
              <span>{t('sd.backend')}</span>
              <span className="font-mono text-foreground">{loader.name}</span>
            </div>
          )}
          {isRunning && (
            <>
              <div className="flex items-center gap-1 text-muted-foreground">
                <span>{t('sd.pid')}</span>
                <span className="font-mono text-foreground">{service.pid}</span>
              </div>
              <div className="flex items-center gap-1 text-muted-foreground col-span-2 text-[10px]">
                <span>{t('sd.started')}</span>
                <span className="font-mono">{service.uptime}</span>
                {service.uptime_seconds !== undefined && (
                  <span className="font-mono text-foreground">
                    ({formatUptime(service.uptime_seconds)})
                  </span>
                )}
              </div>
            </>
          )}
        </div>

        <div className="flex gap-2 pt-2">
          <Button
            size="sm"
            variant="default"
            className="flex-1 font-semibold"
            onClick={handleStartClick}
            disabled={isRunning || isLoading}
          >
            <Play className="h-3 w-3 mr-1" />
            {t('sd.start')}
          </Button>
          <Button
            size="sm"
            variant="destructive"
            className="flex-1"
            onClick={handleStop}
            disabled={!isRunning || isLoading}
          >
            <Square className="h-3 w-3 mr-1" />
            {t('sd.stop')}
          </Button>
          <Button
            size="sm"
            variant="outline"
            className="flex-1"
            onClick={() => onViewLogs(serviceKey, service.name)}
          >
            <FileText className="h-3 w-3 mr-1" />
            {t('sd.logs')}
          </Button>
        </div>
        <div className="pt-1">
          <Button
            size="sm"
            variant="ghost"
            className="text-destructive hover:text-destructive hover:bg-destructive/10"
            onClick={handleRemove}
            disabled={isLoading}
          >
            <Trash2 className="h-3 w-3 mr-1" />
            {t('sd.removeService')}
          </Button>
        </div>
      </CardContent>

      <Dialog open={showConfig} onOpenChange={setShowConfig}>
        <DialogContent className="sm:max-w-[500px]">
          <DialogHeader>
            <DialogTitle>{t('sd.startConfigTitle', { name: service.name })}</DialogTitle>
            <DialogDescription>
              {t('sd.startConfigDesc')}{loader ? ` (${loader.name})` : ''}
            </DialogDescription>
          </DialogHeader>

          <div className="grid gap-4 py-4">
            {config && (
              <>
                <div className="space-y-2">
                  <label className="text-sm font-medium">{t('sd.gpuSelection')}</label>
                  <div className="grid grid-cols-2 gap-2 p-3 border rounded-md max-h-40 overflow-y-auto">
                    {availableGpus.map((gpu) => (
                      <div key={gpu.index} className="flex items-center space-x-2">
                        <input
                          type="checkbox"
                          id={`gpu-${serviceKey}-${gpu.index}`}
                          checked={config.gpus.includes(gpu.index)}
                          onChange={(e) =>
                            setConfig((prev) =>
                              prev
                                ? {
                                    ...prev,
                                    gpus: e.target.checked
                                      ? [...prev.gpus, gpu.index].sort((a, b) => a - b)
                                      : prev.gpus.filter((g) => g !== gpu.index),
                                  }
                                : prev
                            )
                          }
                          className="h-4 w-4 rounded border-primary"
                        />
                        <label htmlFor={`gpu-${serviceKey}-${gpu.index}`} className="text-xs cursor-pointer">
                          [{gpu.index}] {gpu.name}
                        </label>
                      </div>
                    ))}
                    {availableGpus.length === 0 && (
                      <span className="text-sm text-muted-foreground">{t('sd.noGpus')}</span>
                    )}
                  </div>
                </div>

                <div className="space-y-2">
                  <label className="text-sm font-medium">{t('sd.portLabel')}</label>
                  <input
                    type="number"
                    value={config.port}
                    onChange={(e) =>
                      setConfig((prev) =>
                        prev ? { ...prev, port: parseInt(e.target.value) || 0 } : prev
                      )
                    }
                    className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm"
                  />
                </div>

                {schema.length > 0 && (
                  <div className="grid grid-cols-2 gap-4">
                    {schema.map((field) => (
                      <div key={field.name} className={field.type === 'float' ? 'col-span-2' : ''}>
                        <ParamField
                          field={field}
                          value={config.params[field.name] ?? field.default}
                          onChange={(v) =>
                            setConfig((prev) =>
                              prev
                                ? { ...prev, params: { ...prev.params, [field.name]: v } }
                                : prev
                            )
                          }
                        />
                      </div>
                    ))}
                  </div>
                )}

                {loaderKey === 'vllm' && (
                  <div className="space-y-2">
                    <label className="text-sm font-medium">{t('sd.parallelMode')}</label>
                    <select
                      value={config.parallelMode}
                      onChange={(e) =>
                        setConfig((prev) =>
                          prev ? { ...prev, parallelMode: e.target.value } : prev
                        )
                      }
                      className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm"
                    >
                      <option value="tp" className="bg-background">{t('sd.tp')}</option>
                      <option value="pp" className="bg-background">{t('sd.pp')}</option>
                    </select>
                  </div>
                )}

                <div className="flex items-center space-x-2 pt-2">
                  <input
                    type="checkbox"
                    id={`save-default-${serviceKey}`}
                    checked={config.saveAsDefault}
                    onChange={(e) =>
                      setConfig((prev) =>
                        prev ? { ...prev, saveAsDefault: e.target.checked } : prev
                      )
                    }
                    className="h-4 w-4 rounded border-primary"
                  />
                  <label htmlFor={`save-default-${serviceKey}`} className="text-sm font-medium">
                    {t('sd.saveAsDefault')}
                  </label>
                </div>
              </>
            )}
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setShowConfig(false)}>{t('sd.cancel')}</Button>
            <Button onClick={handleConfirmStart} disabled={isLoading}>
              {isLoading ? t('sd.starting') : t('sd.confirmStart')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  );
}
