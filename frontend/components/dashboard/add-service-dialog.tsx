'use client';

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { HardDrive, Plus, Loader2 } from 'lucide-react';
import type { GPUInfo, ParamSchemaField, StartConfig } from '@/lib/types';
import { useState, useEffect } from 'react';
import { useLoaders, useModels } from '@/hooks/use-dashboard-data';
import { toast } from 'sonner';
import { getApiUrl } from '@/lib/api-config';
import { useLang } from '@/lib/i18n';

interface AddServiceDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  gpus: GPUInfo[];
  onGenerated: (key: string) => void;
}

// Render a single param field based on its param_schema type (shared pattern with ServiceDetail).
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

export function AddServiceDialog({ open, onOpenChange, gpus = [], onGenerated }: AddServiceDialogProps) {
  const { data: loaders } = useLoaders();
  const { data: models } = useModels();
  const { t } = useLang();

  const [loaderKey, setLoaderKey] = useState('');
  const [model, setModel] = useState('');
  const [selectedGpus, setSelectedGpus] = useState<number[]>([]);
  const [port, setPort] = useState<number>(8000);
  const [params, setParams] = useState<Record<string, number | string>>({});
  const [saving, setSaving] = useState(false);

  const loader = loaders?.[loaderKey];
  const installedLoaders = loaders
    ? Object.entries(loaders).filter(([, l]) => l.installed)
    : [];
  // models for the selected loader (only shown if the loader requires a model)
  const loaderModels = (models || []).filter((m) => m.loader === loaderKey);
  // param_schema fields to render (skip selects with no options, e.g. vllm's 'image')
  const schema = (loader?.param_schema || []).filter(
    (f) => !(f.type === 'select' && (!f.options || f.options.length === 0))
  );

  // When the loader changes, reset model + params + port to the loader's defaults
  useEffect(() => {
    if (!loader) return;
    const p: Record<string, number | string> = {};
    for (const field of schema) p[field.name] = field.default;
    setParams(p);
    if (loader.fixed_port) setPort(loader.fixed_port);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loaderKey]);

  const handleGenerate = async () => {
    if (!loaderKey) {
      toast.error(t('asd.selectLoader'));
      return;
    }
    if (loader?.requires_model && !model) {
      toast.error(t('asd.selectModelToast'));
      return;
    }
    if (selectedGpus.length === 0) {
      toast.error(t('asd.selectGpu'));
      return;
    }
    setSaving(true);
    try {
      const body: Record<string, unknown> = {
        loader: loaderKey,
        model: model || undefined,
        gpus: selectedGpus,
        port: loader?.fixed_port ? undefined : port,
        params,
      };
      const response = await fetch(getApiUrl('/api/services/generate'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const result = await response.json();
      if (!result.success) {
        toast.error(t('asd.generateFailed', { msg: result.message }));
        return;
      }
      toast.success(t('asd.created', { key: result.key }));
      // The new service only activates after a backend restart (config-reload gotcha).
      // Fire the restart (it returns before the backend is back), then poll until it is.
      await fetch(getApiUrl('/api/manager/restart'), { method: 'POST' }).catch(() => {});
      for (let i = 0; i < 15; i++) {
        await new Promise((r) => setTimeout(r, 2000));
        try {
          const res = await fetch(getApiUrl('/api/system'));
          if (res.ok) break;
        } catch {
          // backend still restarting
        }
      }
      onGenerated(result.key);
      onOpenChange(false);
      toast.success(t('asd.backendRestarted'));
    } catch (error) {
      toast.error(t('asd.generateFailed', { msg: error instanceof Error ? error.message : t('page.unknownError') }));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[520px]">
        <DialogHeader>
          <DialogTitle>{t('asd.title')}</DialogTitle>
          <DialogDescription>
            {t('asd.desc')}
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-4 py-4 max-h-[60vh] overflow-y-auto">
          {/* Loader selection */}
          <div className="space-y-2">
            <label className="text-sm font-medium">{t('asd.backend')}</label>
            <select
              value={loaderKey}
              onChange={(e) => setLoaderKey(e.target.value)}
              className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm"
            >
              <option value="" className="bg-background">{t('asd.selectBackend')}</option>
              {installedLoaders.map(([key, l]) => (
                <option key={key} value={key} className="bg-background">
                  {l.name}{l.version ? ` (${l.version})` : ''}
                </option>
              ))}
            </select>
            {loader && (
              <p className="text-xs text-muted-foreground">{loader.detail}</p>
            )}
          </div>

          {/* Model selection (only if the loader requires one) */}
          {loader?.requires_model && (
            <div className="space-y-2">
              <label className="text-sm font-medium">{t('asd.model')}</label>
              <select
                value={model}
                onChange={(e) => setModel(e.target.value)}
                className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm"
              >
                <option value="" className="bg-background">
                  {t('asd.selectModel')}{loaderModels.length === 0 ? t('asd.noneFound') : ''}
                </option>
                {loaderModels.map((m) => (
                  <option key={m.name} value={m.name} className="bg-background">
                    {m.name}
                    {m.size_gb ? ` (${m.size_gb} GB)` : ''}
                    {m.source ? ` [${m.source.replace('_', ' ')}]` : ''}
                    {m.format && m.format !== 'service' ? ` · ${m.format}` : ''}
                  </option>
                ))}
              </select>
            </div>
          )}

          {/* GPU selection */}
          <div className="space-y-2">
            <label className="text-sm font-medium">{t('asd.gpuSelection')}</label>
            <div className="grid grid-cols-2 gap-2 p-3 border rounded-md">
              {gpus.map((gpu) => (
                <div key={gpu.index} className="flex items-center space-x-2">
                  <input
                    type="checkbox"
                    id={`add-gpu-${gpu.index}`}
                    checked={selectedGpus.includes(gpu.index)}
                    onChange={(e) =>
                      setSelectedGpus((prev) =>
                        e.target.checked
                          ? [...prev, gpu.index].sort((a, b) => a - b)
                          : prev.filter((g) => g !== gpu.index)
                      )
                    }
                    className="h-4 w-4 rounded border-primary"
                  />
                  <label htmlFor={`add-gpu-${gpu.index}`} className="text-xs cursor-pointer">
                    [{gpu.index}] {gpu.name}
                  </label>
                </div>
              ))}
              {gpus.length === 0 && (
                <span className="text-sm text-muted-foreground">{t('asd.noGpus')}</span>
              )}
            </div>
          </div>

          {/* Port (hidden for fixed-port loaders like ollama / lmstudio) */}
          {!loader?.fixed_port && (
            <div className="space-y-2">
              <label className="text-sm font-medium">{t('asd.port')}</label>
              <input
                type="number"
                value={port}
                onChange={(e) => setPort(parseInt(e.target.value) || 0)}
                className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm"
              />
            </div>
          )}

          {/* Loader-specific params */}
          {schema.length > 0 && (
            <div className="grid grid-cols-2 gap-4">
              {schema.map((field) => (
                <div key={field.name} className={field.type === 'float' ? 'col-span-2' : ''}>
                  <ParamField
                    field={field}
                    value={params[field.name] ?? field.default}
                    onChange={(v) => setParams((prev) => ({ ...prev, [field.name]: v }))}
                  />
                </div>
              ))}
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={saving}>
            {t('asd.cancel')}
          </Button>
          <Button onClick={handleGenerate} disabled={saving}>
            {saving ? (
              <Loader2 className="h-4 w-4 mr-1 animate-spin" />
            ) : (
              <Plus className="h-4 w-4 mr-1" />
            )}
            {saving ? t('asd.generating') : t('asd.generate')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
