'use client';

import { useServices, useGPU, useSystemInfo } from '@/hooks/use-dashboard-data';
import { SystemSidebar } from '@/components/dashboard/system-sidebar';
import { ServiceDetail } from '@/components/dashboard/service-detail';
import { ThroughputChart } from '@/components/dashboard/throughput-chart';
import { ComfyUIStats } from '@/components/dashboard/comfyui-stats';
import { LogsViewer } from '@/components/dashboard/logs-viewer';
import { AddServiceDialog } from '@/components/dashboard/add-service-dialog';
import { InstallerSection } from '@/components/dashboard/installer-section';
import { Skeleton } from '@/components/ui/skeleton';
import { Button } from '@/components/ui/button';
import { Toaster } from '@/components/ui/sonner';
import { useState } from 'react';
import { Server, ChevronDown, PowerOff, Plus } from 'lucide-react';
import { toast } from 'sonner';
import { getApiUrl } from '@/lib/api-config';
import { useLang } from '@/lib/i18n';

export default function DashboardPage() {
  // Dashboard refresh rate (seconds) — set by the 1/2/3 buttons in the
  // sidebar footer, next to the "Last updated" timer. Persisted so the
  // choice survives reloads. 2s is the default (see use-dashboard-data.ts).
  const [pollSeconds, setPollSeconds] = useState<number>(() => {
    try {
      const v = parseInt(localStorage.getItem('dashboard.pollSeconds') || '', 10);
      return v === 1 || v === 3 ? v : 2;
    } catch {
      return 2;
    }
  });
  const handlePollSecondsChange = (n: number) => {
    setPollSeconds(n);
    try {
      localStorage.setItem('dashboard.pollSeconds', String(n));
    } catch {
      // ignore
    }
  };

  const { data: services, isLoading: servicesLoading, error: servicesError } = useServices(pollSeconds * 1000);
  const { data: gpus, isLoading: gpusLoading, error: gpusError } = useGPU(pollSeconds * 1000);
  const { data: systemInfo, isLoading: systemLoading, error: systemError } = useSystemInfo(pollSeconds * 1000);
  const { t } = useLang();

  const [logsState, setLogsState] = useState<{
    logUrl: string | null;
    serviceName: string;
    isOpen: boolean;
  }>({
    logUrl: null,
    serviceName: '',
    isOpen: false,
  });

  // Which service is selected in the dropdown
  const [selectedKey, setSelectedKey] = useState<string>('big');

  const handleViewLogs = (serviceKey: string, serviceName: string) => {
    setLogsState({
      logUrl: `/api/service/${serviceKey}/logs?lines=200`,
      serviceName,
      isOpen: true,
    });
  };

  const handleViewComfyuiLogs = () => {
    setLogsState({
      logUrl: '/api/comfyui/logs?lines=200',
      serviceName: 'ComfyUI',
      isOpen: true,
    });
  };

  const handleCloseLogs = () => {
    setLogsState(prev => ({ ...prev, isOpen: false }));
  };

  // When a service is removed, re-select a valid service (the removed one is gone
  // from /api/services after the next 2s poll).
  const handleServiceRemoved = (removedKey: string) => {
    if (services) {
      const remaining = Object.keys(services).filter(k => k !== removedKey);
      setSelectedKey(remaining.length > 0 ? remaining[0] : '');
    }
  };

  // "Unload all" — stop every service (big, small, dual_tp, dual_pp) at once.
  const [stopAllLoading, setStopAllLoading] = useState(false);
  const [showAddService, setShowAddService] = useState(false);
  const handleStopAll = async () => {
    if (!confirm(t('page.unloadAllConfirm'))) {
      return;
    }
    setStopAllLoading(true);
    try {
      const response = await fetch(getApiUrl('/api/stop_all'), { method: 'POST' });
      const result: any = await response.json();
      if (result.success) {
        const results: Record<string, { success: boolean; message: string }> = result.results || {};
        const stopped = Object.entries(results)
          .filter(([, r]) => r.success)
          .map(([k]) => k);
        toast.success(t('page.unloaded', { list: stopped.length ? stopped.join(', ') : t('page.nothingStopped') }));
      } else {
        toast.error(t('page.unloadAllFailed', { msg: result.message }));
      }
    } catch (error) {
      toast.error(t('page.unloadAllFailed', { msg: error instanceof Error ? error.message : t('page.unknownError') }));
    } finally {
      setStopAllLoading(false);
    }
  };

  // Only show the "Connection failed" error if ALL 3 endpoints have failed
  // (not just one). A single slow response shouldn't show a full-screen
  // error — the backend can be slow during model load/unload.
  const allFailed = servicesError && gpusError && systemError;
  if (allFailed) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-center space-y-4">
          <h2 className="text-2xl font-bold text-destructive">{t('page.connectionFailed')}</h2>
          <p className="text-muted-foreground">
            {t('page.connectionFailedDesc')}
          </p>
          <p className="text-xs font-mono text-muted-foreground">
            {t('page.connectionFailedAddr')}
          </p>
        </div>
      </div>
    );
  }

  const serviceKeys = services ? Object.keys(services) : [];
  const selectedService = services?.[selectedKey];

  return (
    <div className="min-h-screen bg-background flex">
      <SystemSidebar
        systemInfo={systemInfo}
        loading={systemLoading}
        gpus={gpus}
        gpusLoading={gpusLoading}
        services={services}
        pollSeconds={pollSeconds}
        onPollSecondsChange={handlePollSecondsChange}
      />

      <main className="flex-1 ml-72 p-6 overflow-y-auto">
        <div className="max-w-7xl mx-auto space-y-6">
          <section>
            <div className="flex items-center gap-2 mb-6">
              <Server className="h-5 w-5 text-primary" />
              <h2 className="text-xl font-display font-bold text-foreground">{t('page.modelServices')}</h2>
              <div className="ml-auto flex items-center gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => setShowAddService(true)}
                >
                  <Plus className="h-3 w-3 mr-1" />
                  {t('page.addService')}
                </Button>
                <Button
                  size="sm"
                  variant="destructive"
                  onClick={handleStopAll}
                  disabled={stopAllLoading}
                >
                  <PowerOff className="h-3 w-3 mr-1" />
                  {stopAllLoading ? t('page.unloading') : t('page.unloadAll')}
                </Button>
              </div>
            </div>

            {servicesLoading ? (
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                <Skeleton className="h-64 rounded-xl" />
                <Skeleton className="h-64 rounded-xl" />
              </div>
            ) : services && selectedService ? (
              <>
                {/* Dropdown to select the service */}
                <div className="flex items-center gap-3 mb-6">
                  <label className="text-sm font-medium text-muted-foreground">{t('page.serviceLabel')}</label>
                  <div className="relative">
                    <select
                      value={selectedKey}
                      onChange={(e) => setSelectedKey(e.target.value)}
                      className="flex h-10 w-72 rounded-md border border-input bg-background px-3 py-2 pr-8 text-sm font-medium appearance-none cursor-pointer"
                    >
                      {serviceKeys.map((key) => (
                        <option key={key} value={key}>
                          {services[key].name}
                        </option>
                      ))}
                    </select>
                    <ChevronDown className="h-4 w-4 absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground pointer-events-none" />
                  </div>
                </div>

                {/* Layout: (ServiceDetail + ComfyUI) left, ThroughputChart right */}
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 items-start">
                  <div className="flex flex-col gap-6">
                    <ServiceDetail
                      serviceKey={selectedKey}
                      service={selectedService}
                      availableGpus={gpus || []}
                      onViewLogs={handleViewLogs}
                      onRemoved={handleServiceRemoved}
                    />
                    <ComfyUIStats onViewLogs={handleViewComfyuiLogs} />
                  </div>
                  <ThroughputChart
                    serviceKey={selectedKey}
                    isRunning={selectedService.status === 'running'}
                  />
                </div>
              </>
            ) : null}
          </section>

          <InstallerSection />
        </div>
      </main>

      <LogsViewer
        logUrl={logsState.logUrl}
        serviceName={logsState.serviceName}
        isOpen={logsState.isOpen}
        onClose={handleCloseLogs}
      />

      <AddServiceDialog
        open={showAddService}
        onOpenChange={setShowAddService}
        gpus={gpus || []}
        onGenerated={() => {}}
      />

      <Toaster position="top-right" />
    </div>
  );
}
