'use client';

import { useState, useEffect } from 'react';
import type { SystemInfo, GPUInfo } from '@/lib/types';
import { getApiUrl } from '@/lib/api-config';
import { SystemStats } from './system-stats';
import { GPUSidebar } from './gpu-sidebar';
import { LanguageToggle } from './language-toggle';
import { Separator } from '@/components/ui/separator';
import { Activity, Server, Bot, ExternalLink, RefreshCw, MessageSquare } from 'lucide-react';
import { useLang } from '@/lib/i18n';

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

  // The Hermes Webapp signs each browser in with a one-use launch ticket (valid ~60s).
  // Open the tab immediately (keeps the user-gesture context so the browser won't
  // block it), then point it at the freshly-minted link from the backend.
  const openHermes = async () => {
    const win = window.open('about:blank', '_blank');
    const fail = (msg: string) => {
      if (win) {
        win.document.title = t('sidebar.hermesFailTitle');
        win.document.body.innerHTML =
          '<div style="font-family:sans-serif;padding:2rem;max-width:40rem">' +
          '<h2>' + t('sidebar.hermesFailH2') + '</h2><p>' + msg + '</p></div>';
        win.focus();
      } else {
        alert(t('sidebar.hermesFailH2') + ': ' + msg);
      }
    };
    try {
      const res = await fetch(getApiUrl('/api/hermes/webapp-link'));
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

  // Open a model's chat in a Hermes Webapp tab (one-use launch ticket, like openHermes).
  // Each model maps to a Hermes profile: lmstudio -> small-brain, big -> default.
  const openModelChat = async (key: string) => {
    const profile = key === 'lmstudio' ? 'small-brain' : '';
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
      const url = `/api/hermes/webapp-link${profile ? `?profile=${profile}` : ''}`;
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
          <button
            onClick={openHermes}
            className="flex items-center gap-1.5 rounded-lg border border-sidebar-border bg-sidebar-accent/50 px-2.5 py-1.5 text-xs font-medium text-sidebar-foreground hover:bg-sidebar-accent transition-colors"
            title={t('sidebar.hermesTitle')}
          >
          <Bot className="h-3.5 w-3.5 text-primary" />
          Hermes
          <ExternalLink className="h-3 w-3 opacity-60" />
          </button>
          <LanguageToggle />
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
          <span className="text-foreground">0.5.0</span>
        </p>
      </div>
    </aside>
  );
}
