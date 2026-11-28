'use client';

import { useState, useEffect } from 'react';
import type { SystemInfo, GPUInfo } from '@/lib/types';
import { getApiUrl } from '@/lib/api-config';
import { SystemStats } from './system-stats';
import { GPUSidebar } from './gpu-sidebar';
import { LanguageToggle } from './language-toggle';
import { Separator } from '@/components/ui/separator';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Activity, Server, ExternalLink, RefreshCw, MessageSquare, CheckCircle2, AlertCircle } from 'lucide-react';
import { useLang } from '@/lib/i18n';
import { toast } from 'sonner';

interface SystemSidebarProps {
  systemInfo: SystemInfo | undefined;
  loading: boolean;
  gpus: GPUInfo[] | undefined;
  gpusLoading: boolean;
  services?: Record<string, { name: string; port: number; status: string }>;
  pollSeconds?: number;
  onPollSecondsChange?: (n: number) => void;
}

export function SystemSidebar({ systemInfo, loading, gpus, gpusLoading, services, pollSeconds, onPollSecondsChange }: SystemSidebarProps) {
  const { t } = useLang();

  // Open a model's chat in a Hermes Webapp tab (one-use launch ticket).
  // The backend resolves the service key to the right Hermes profile
  // (big -> default, lmstudio -> small-brain, strata_* -> a per-service
  // profile bound to that service's model/port/key — created on first use).
  const openModelChat = async (key: string) => {
    const win = window.open('about:blank', '_blank');
    const fail = (msg: string) => {
      if (win) {
        win.document.title = 'Chat failed';
        win.document.body.innerHTML =
          '<div style="font-family:sans-serif;padding:2rem;max-width:40rem"><h2>Could not open chat</h2><p>' + msg + '</p></div>';
        win.focus();
      } else {
        alert('Could not open chat: ' + msg);
      }
    };
    try {
      const url = `/api/hermes/webapp-link?service=${encodeURIComponent(key)}`;
      const res = await fetch(getApiUrl(url));
      const data = await res.json();
      if (data.success && data.url) {
        if (win) win.location.href = data.url;
        else window.open(data.url, '_blank');
      } else {
        fail(data.message || 'unknown error');
      }
    } catch (e: any) {
      fail(e?.message || String(e));
    }
  };

  const [restarting, setRestarting] = useState(false);

  // Manager version for the footer (from the repo's VERSION file — the
  // updater bumps it on each applied update: 0.5.0 -> 0.5.1 -> ...).
  // The second line of the file is the date the version first landed.
  const [version, setVersion] = useState('0.5.0');
  const [versionDate, setVersionDate] = useState('');
  useEffect(() => {
    fetch(getApiUrl('/api/manager/version'))
      .then((r) => r.json())
      .then((d) => {
        if (d && d.version) setVersion(d.version);
        if (d && d.date) setVersionDate(d.date);
      })
      .catch(() => {});
  }, []);

  // --- LLM Manager updater (check GitHub for updates) ---
  interface UpdateCheck {
    up_to_date: boolean;
    commit: string;
    remote_commit?: string;
    behind?: number;
    ahead?: number;
    commits?: string[];
    diffstat?: string[];
  }
  const [updateCheck, setUpdateCheck] = useState<UpdateCheck | null>(null);
  const [checking, setChecking] = useState(false);
  const [updating, setUpdating] = useState(false);

  const checkForUpdates = async () => {
    setChecking(true);
    try {
      const res = await fetch(getApiUrl('/api/updater/check'));
      const data: { success: boolean; message?: string } & UpdateCheck = await res.json();
      if (data.success) {
        setUpdateCheck(data);
      } else {
        toast.error(data.message || t('sidebar.checkFailed'));
      }
    } catch (e: any) {
      toast.error(t('sidebar.checkFailed', { msg: e?.message || String(e) }));
    } finally {
      setChecking(false);
    }
  };

  const applyUpdate = async () => {
    setUpdating(true);
    try {
      const res = await fetch(getApiUrl('/api/updater/apply'), { method: 'POST' });
      const data: { success: boolean; message?: string } = await res.json();
      if (data.success) {
        toast.success(data.message || t('sidebar.updated'));
        // The backend restarts itself (and the frontend was rebuilt) — the page
        // reloads itself shortly; give the toast a moment to show.
        setTimeout(() => window.location.reload(), 3000);
      } else {
        toast.error(data.message || t('sidebar.updateFailed'));
      }
    } catch (e: any) {
      // The backend restarts itself mid-update, so a dropped response is expected —
      // the page reload will confirm the result.
      setTimeout(() => window.location.reload(), 3000);
    } finally {
      setUpdating(false);
    }
  };

  // Live "last updated" time for the footer: the systemInfo object is replaced
  // on every successful poll (2s), so tracking it reflects when data actually
  // arrived (the old static "0.5s" label was wrong — the real interval is 2s).
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  useEffect(() => {
    if (systemInfo) setLastUpdated(new Date());
  }, [systemInfo]);

  // Restart the manager backend (vllm-manager-backend) to reload config (services.json).
  // The backend loads services.json only at import, so an on-disk edit is invisible until
  // a restart. The POST may not return a response (the backend is killed by its own
  // restart), so we poll for the backend to come back up; SWR auto-recovers after that.
  const restartManager = async () => {
    if (restarting) return;
    if (!window.confirm(t('sidebar.restartConfirm'))) {
      return;
    }
    setRestarting(true);
    try {
      await fetch(getApiUrl('/api/manager/restart'), { method: 'POST' });
    } catch (e) {
      // expected — the backend is restarting, so the POST may not return a response
    }
    const start = Date.now();
    const timeout = 30000;
    while (Date.now() - start < timeout) {
      await new Promise(r => setTimeout(r, 1000));
      try {
        const res = await fetch(getApiUrl('/api/system'));
        if (res.ok) break;
      } catch (e) {
        // backend still down
      }
    }
    setRestarting(false);
  };

  return (
    <aside className="w-72 fixed left-0 top-0 bottom-0 bg-sidebar border-r border-sidebar-border p-6 flex flex-col z-30">
      <div className="flex items-center gap-3 mb-8">
        <div className="relative flex h-10 w-10 items-center justify-center rounded-xl bg-primary/10">
          <Server className="h-6 w-6 text-primary" />
          <span className="absolute right-0 top-0 flex h-3 w-3">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-secondary opacity-75" />
            <span className="relative inline-flex rounded-full h-3 w-3 bg-secondary" />
          </span>
        </div>
        <div>
          <h1 className="font-display font-bold text-lg leading-tight tracking-tight">
            LLM
            <span className="block text-muted-foreground text-xs font-normal">{t('app.titleBottom')}</span>
          </h1>
        </div>
        <div className="ml-auto flex flex-col items-end gap-2">
          <LanguageToggle />
          <button
            onClick={checkForUpdates}
            disabled={checking || updating}
            className="flex items-center gap-1.5 rounded-lg border border-sidebar-border bg-sidebar-accent/50 px-2.5 py-1.5 text-xs font-medium text-sidebar-foreground hover:bg-sidebar-accent transition-colors disabled:opacity-60"
            title={t('sidebar.updaterTitle')}
          >
          <RefreshCw className={`h-3.5 w-3.5 text-primary ${checking ? 'animate-spin' : ''}`} />
          {checking ? t('sidebar.checking') : t('sidebar.updater')}
          </button>
        </div>
      </div>

      <Separator className="bg-sidebar-border mb-6" />

      {/* Per-model chat buttons — each opens a minimal web chat for that model in a new tab */}
      {services && Object.keys(services).length > 0 && (
        <div className="mb-4">
          <div className="flex items-center gap-2 mb-2">
            <MessageSquare className="h-3.5 w-3.5 text-primary" />
            <h2 className="text-xs font-semibold tracking-wide text-sidebar-foreground/80 uppercase">
              {t('sidebar.modelChats')}
            </h2>
          </div>
          <div className="space-y-1.5">
            {Object.entries(services).map(([key, svc]) => (
              <button
                key={key}
                onClick={() => openModelChat(key)}
                className="w-full flex items-center justify-between gap-2 rounded-lg border border-sidebar-border bg-sidebar-accent/50 px-3 py-1.5 text-xs font-medium text-sidebar-foreground hover:bg-sidebar-accent transition-colors"
                title={`Open a chat with ${svc.name} in a new tab`}
              >
                <span className="truncate text-left">{svc.name}</span>
                <span className="flex items-center gap-1.5 font-mono shrink-0">
                  <span className={`h-1.5 w-1.5 rounded-full ${svc.status === 'running' ? 'bg-emerald-500' : 'bg-muted-foreground/40'}`} />
                  <span className="text-muted-foreground">:{svc.port}</span>
                  <ExternalLink className="h-3 w-3 opacity-60" />
                </span>
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="space-y-6 flex-1 overflow-y-auto pr-2">
        <div className="flex items-center gap-2 mb-4">
          <Activity className="h-4 w-4 text-primary" />
          <h2 className="text-sm font-semibold tracking-wide text-sidebar-foreground/80 uppercase">
            {t('sidebar.systemMonitor')}
          </h2>
        </div>
        <GPUSidebar gpus={gpus} loading={gpusLoading} />
        <SystemStats info={systemInfo} loading={loading} />
      </div>

      <button
        onClick={restartManager}
        disabled={restarting}
        className="mt-4 w-full flex items-center justify-center gap-2 rounded-lg border border-sidebar-border bg-sidebar-accent/50 px-3 py-2 text-xs font-medium text-sidebar-foreground hover:bg-sidebar-accent transition-colors disabled:opacity-50"
        title="Restart the manager backend to reload config (services.json)"
      >
        <RefreshCw className={`h-3.5 w-3.5 text-primary ${restarting ? 'animate-spin' : ''}`} />
        {restarting ? t('sidebar.restarting') : t('sidebar.restartManager')}
      </button>

      <div className="mt-auto pt-6 text-xs text-muted-foreground font-mono border-t border-sidebar-border">
        <p className="flex items-center gap-1.5">
          <span>{t('sidebar.lastUpdated')}</span>
          {onPollSecondsChange && (
            <span className="flex items-center gap-1 ml-1">
              {[1, 2, 3].map(n => (
                <button
                  key={n}
                  onClick={() => onPollSecondsChange(n)}
                  title={t('sidebar.refreshEvery', { n })}
                  className={`h-5 w-5 rounded-full text-[10px] font-semibold leading-none transition-colors ${
                    pollSeconds === n
                      ? 'bg-primary text-primary-foreground'
                      : 'border border-sidebar-border text-sidebar-foreground hover:bg-sidebar-accent'
                  }`}
                >
                  {n}
                </button>
              ))}
            </span>
          )}
          <span className="ml-auto text-foreground">{lastUpdated ? lastUpdated.toLocaleTimeString([], { hour12: false }) : '—'}</span>
        </p>
        <p className="flex justify-between mt-1">
          <span>{t('sidebar.version')}</span>
          <span className="text-foreground">
            {version}{versionDate ? ` (${versionDate})` : ''}
          </span>
        </p>
      </div>

      {/* LLM Manager updater dialog */}
      <Dialog open={updateCheck !== null} onOpenChange={(open) => { if (!open) setUpdateCheck(null); }}>
        <DialogContent className="max-w-md bg-background/95 backdrop-blur-xl border-border shadow-2xl">
          <DialogHeader>
            <DialogTitle className="font-display flex items-center gap-2">
              {updateCheck?.up_to_date ? (
                <CheckCircle2 className="h-4 w-4 text-emerald-500" />
              ) : (
                <RefreshCw className="h-4 w-4 text-primary" />
              )}
              {t('sidebar.updaterTitle')}
            </DialogTitle>
          </DialogHeader>
          {updateCheck?.up_to_date ? (
            <p className="mt-3 text-sm text-muted-foreground">
              {t('sidebar.upToDate')} <span className="font-mono">({updateCheck.commit})</span>
            </p>
          ) : (
            updateCheck && (
              <div className="mt-3 space-y-3">
                {(updateCheck.ahead ?? 0) > 0 && (
                  <div className="flex items-start gap-2 text-xs text-amber-600 dark:text-amber-400">
                    <AlertCircle className="h-3.5 w-3.5 mt-0.5 shrink-0" />
                    {t('sidebar.localAhead')}
                  </div>
                )}
                <div>
                  <div className="text-xs font-medium text-muted-foreground mb-1">{t('sidebar.changes')}</div>
                  <div className="bg-black/50 rounded-lg p-3 max-h-40 overflow-y-auto border border-border/50">
                    <pre className="text-xs font-mono text-foreground whitespace-pre-wrap">
                      {updateCheck.commits?.join('\n') || '—'}
                    </pre>
                  </div>
                </div>
                {updateCheck.diffstat && updateCheck.diffstat.length > 0 && (
                  <div>
                    <div className="text-xs font-medium text-muted-foreground mb-1">{t('sidebar.filesChanged')}</div>
                    <div className="bg-black/50 rounded-lg p-3 max-h-24 overflow-y-auto border border-border/50">
                      <pre className="text-xs font-mono text-muted-foreground whitespace-pre-wrap">
                        {updateCheck.diffstat.join('\n')}
                      </pre>
                    </div>
                  </div>
                )}
                <div className="flex items-center gap-2">
                  <span className="text-xs text-muted-foreground font-mono">
                    {updateCheck.commit} → {updateCheck.remote_commit}
                  </span>
                  <div className="ml-auto flex gap-2">
                    <Button onClick={applyUpdate} disabled={updating || (updateCheck.ahead ?? 0) > 0}>
                      <RefreshCw className={`h-3 w-3 mr-1 ${updating ? 'animate-spin' : ''}`} />
                      {updating ? t('sidebar.updating') : t('sidebar.installUpdates')}
                    </Button>
                    <Button variant="outline" onClick={() => setUpdateCheck(null)}>
                      {t('sidebar.decline')}
                    </Button>
                  </div>
                </div>
              </div>
            )
          )}
        </DialogContent>
      </Dialog>
    </aside>
  );
}
