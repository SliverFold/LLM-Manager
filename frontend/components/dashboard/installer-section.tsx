'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { toast } from 'sonner';
import { getApiUrl } from '@/lib/api-config';
import { useLang } from '@/lib/i18n';
import { Cpu, Bot, Download, RefreshCw, ExternalLink, CheckCircle2, AlertCircle, Trash2, XCircle, Image as ImageIcon, Sparkles, Brain, ChevronDown } from 'lucide-react';

interface InstallerStatus {
  system: {
    vendor: string;
    vendor_detail: string;
    python: string | null;
    python312: string | null;
    uv: string | null;
    disk_free_gb: number;
  };
  vllm: { installed: boolean; venv: string; version: string | null; rocm_version: string | null; detail: string };
  docker: { installed: boolean; running: boolean; detail: string };
  paiton_docker: { installed: boolean; running: boolean; image: string | null; version: string | null; detail: string };
  paiton: { installed: boolean; version: string | null; detail: string };
  qwen: { installed: boolean; agent: boolean; code: boolean; detail: string };
  hermes: {
    installed: boolean;
    version: string | null;
    webapp_enabled: boolean | null;
    webapp_reachable: boolean;
    detail: string;
  };
  comfyui: { installed: boolean; dir: string; detail: string };
  lmstudio: {
    installed: boolean;
    lms: string | null;
    detail: string;
    suite: { installed: boolean; dir: string; revision: number | null; detail: string };
  };
  openviking: {
    installed: boolean;
    server: boolean;
    server_version: string | null;
    embed: boolean;
    plugin: boolean;
    hermes_configured: boolean;
    detail: string;
  };
  jobs: { kind: string; status: string; log_file: string; started_at: string }[];
}

// The Paiton release models available in the paiton-vllm-plugin repo. The slug
// is passed to the backend's install_paiton.sh; the name is the dropdown label.
// `size` is the total download estimate (image + weights, which are a separate
// download — the docker image does NOT bundle the weights).
const PAITON_MODELS = [
  { slug: 'qwen38', name: 'Qwen3.8 27B', size: '~66 GB' },
  { slug: 'gpt-oss-20b', name: 'GPT-OSS 20B', size: '~44 GB' },
  { slug: 'minicpm5-2b', name: 'MiniCPM5 2B', size: '~40 GB' },
  { slug: 'ornith-1.5', name: 'Ornith 1.5 35B', size: '~28 GB' },
  { slug: 'qwen3-coder-30b', name: 'Qwen3-Coder 30B', size: '~30 GB' },
  { slug: 'qwen38-neo-coder', name: 'Qwen3.8 NEO CODER MAX', size: '~25 GB' },
];

// A collapsible installer card: the header (icon + title + status badge +
// chevron) is always visible and clickable; clicking it toggles the full
// content. Collapsed cards show only the minimal "installed / not installed"
// status so the section stays clean.
function CollapsibleCard({
  icon,
  title,
  headerRight,
  statusBadges,
  expanded,
  onToggle,
  children,
}: {
  icon: React.ReactNode;
  title: string;
  headerRight?: React.ReactNode;
  statusBadges: React.ReactNode;
  expanded: boolean;
  onToggle: () => void;
  children: React.ReactNode;
}) {
  return (
    <Card>
      <CardHeader className="cursor-pointer select-none" onClick={onToggle}>
        <CardTitle className="flex items-center gap-2 justify-between">
          <span className="flex items-center gap-2">
            {icon}
            {title}
          </span>
          <span className="flex items-center gap-2">
            {headerRight}
            <ChevronDown className={`h-4 w-4 text-muted-foreground transition-transform ${expanded ? 'rotate-180' : ''}`} />
          </span>
        </CardTitle>
        <div className="flex flex-wrap items-center gap-2">
          {statusBadges}
        </div>
      </CardHeader>
      {expanded && (
        <CardContent className="space-y-4">
          {children}
        </CardContent>
      )}
    </Card>
  );
}

export function InstallerSection() {
  const { t } = useLang();
  const [status, setStatus] = useState<InstallerStatus | null>(null);
  const [venv, setVenv] = useState('~/vllm-venv');
  const [channel, setChannel] = useState<'nightly' | 'stable'>('nightly');
  const [qwenTools, setQwenTools] = useState(false);
  const [comfyDir, setComfyDir] = useState('~/ComfyUI-plain');
  const [installing, setInstalling] = useState<null | 'vllm' | 'hermes' | 'comfyui' | 'lmstudio' | 'openviking'>(null);
  const [paitonInstalling, setPaitonInstalling] = useState(false);
  const [paitonModel, setPaitonModel] = useState('qwen38');
  // Model downloaders (vLLM + LM Studio)
  const [vllmModels, setVllmModels] = useState<{ slug: string; name: string; size: string; vram?: number | null }[]>([]);
  const [lmstudioModels, setLmstudioModels] = useState<{ slug: string; name: string; size: string; vram?: number | null }[]>([]);
  const [vllmModel, setVllmModel] = useState('');
  const [lmstudioModel, setLmstudioModel] = useState('');
  const [vllmModelDownloading, setVllmModelDownloading] = useState(false);
  const [lmstudioModelDownloading, setLmstudioModelDownloading] = useState(false);
  const [uninstalling, setUninstalling] = useState<null | 'vllm' | 'hermes' | 'comfyui' | 'lmstudio' | 'openviking'>(null);
  const [updating, setUpdating] = useState<null | 'vllm' | 'hermes' | 'comfyui' | 'lmstudio' | 'openviking'>(null);
  const [removeVenv, setRemoveVenv] = useState(false);
  const [removeCheckout, setRemoveCheckout] = useState(false);
  const [removeWorkspace, setRemoveWorkspace] = useState(false);
  const [logJob, setLogJob] = useState<string | null>(null);
  const [logJobType, setLogJobType] = useState<'install' | 'uninstall' | 'update'>('install');
  const [logText, setLogText] = useState('');
  const [logStatus, setLogStatus] = useState('running');
  const [restartingGateway, setRestartingGateway] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  // Which installer cards are expanded (collapsed by default for a cleaner look).
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const toggleCard = (key: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  // Poll the detection status (venv changes what we check for vLLM).
  useEffect(() => {
    let active = true;
    const poll = async () => {
      try {
        const res = await fetch(getApiUrl(`/api/installer/status?venv=${encodeURIComponent(venv)}&comfy_dir=${encodeURIComponent(comfyDir)}`));
        const data: InstallerStatus = await res.json();
        if (active) setStatus(data);
      } catch {
        // backend briefly down — ignore
      }
    };
    poll();
    const id = setInterval(poll, 5000);
    return () => {
      active = false;
      clearInterval(id);
    };
  }, [venv, comfyDir]);

  // Fetch the curated model lists for the vLLM + LM Studio downloaders.
  useEffect(() => {
    let active = true;
    const load = async () => {
      try {
        const [vres, lres] = await Promise.all([
          fetch(getApiUrl('/api/installer/vllm-models')),
          fetch(getApiUrl('/api/installer/lmstudio-models')),
        ]);
        const vdata = await vres.json();
        const ldata = await lres.json();
        if (!active) return;
        if (vdata.success) {
          setVllmModels(vdata.models);
          if (vdata.models.length) setVllmModel(vdata.models[0].slug);
        }
        if (ldata.success) {
          setLmstudioModels(ldata.models);
          if (ldata.models.length) setLmstudioModel(ldata.models[0].slug);
        }
      } catch {
        // backend briefly down — ignore
      }
    };
    load();
    return () => { active = false; };
  }, []);

  // Live log while an install job is running (or just finished).
  useEffect(() => {
    if (!logJob) return;
    let active = true;
    const poll = async () => {
      try {
        const res = await fetch(getApiUrl(`/api/installer/logs?job=${encodeURIComponent(logJob)}`));
        const data: { success: boolean; logs: string; status: string } = await res.json();
        if (!active) return;
        if (data.success) {
          setLogText(data.logs || '');
          setLogStatus(data.status);
          if (data.status !== 'running') {
            setInstalling(null);
            setUninstalling(null);
            setUpdating(null);
            setLogJob(null);
            const done = data.status === 'done';
            const okKey = logJobType === 'uninstall' ? 'inst.uninstallDone' : logJobType === 'update' ? 'inst.updateDone' : 'inst.installDone';
            const failKey = logJobType === 'uninstall' ? 'inst.uninstallFailed' : logJobType === 'update' ? 'inst.updateFailed' : 'inst.installFailed';
            toast.success(done ? t(okKey) : t(failKey));
          }
        }
      } catch {
        // ignore
      }
    };
    poll();
    const id = setInterval(poll, 2000);
    return () => {
      active = false;
      clearInterval(id);
    };
  }, [logJob, logJobType, t]);

  // Keep the log scrolled to the bottom while new lines arrive.
  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [logText]);

  const startInstall = useCallback(
    async (kind: 'vllm' | 'hermes' | 'comfyui' | 'lmstudio' | 'openviking') => {
      const body = kind === 'vllm' ? { venv, channel, qwentools: qwenTools } : kind === 'comfyui' ? { dir: comfyDir } : {};
      setInstalling(kind);
      try {
        const res = await fetch(getApiUrl(`/api/installer/${kind}`), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        });
        const data: { success: boolean; job?: string; message?: string } = await res.json();
        if (data.success && data.job) {
          setLogJobType('install');
          setLogJob(data.job);
          setLogText('');
          setLogStatus('running');
        } else {
          toast.error(data.message || t('inst.startFailed'));
          setInstalling(null);
        }
      } catch (e: any) {
        toast.error(t('inst.startFailed', { msg: e?.message || String(e) }));
        setInstalling(null);
      }
    },
    [venv, channel, qwenTools, comfyDir, t]
  );

  const startUninstall = useCallback(
    async (kind: 'vllm' | 'hermes' | 'comfyui' | 'lmstudio' | 'openviking') => {
      if (kind === 'vllm') {
        if (!window.confirm(t('inst.uninstallConfirm', { venv: venv }))) return;
      } else if (kind === 'hermes') {
        if (!window.confirm(t('inst.disableWebappConfirm'))) return;
      } else if (kind === 'comfyui') {
        if (!window.confirm(t('inst.comfyuiUninstallConfirm', { dir: comfyDir }))) return;
      } else if (kind === 'openviking') {
        if (!window.confirm(t('inst.ovUninstallConfirm'))) return;
      } else {
        if (!window.confirm(t('inst.lmsUninstallConfirm'))) return;
      }
      setUninstalling(kind);
      try {
        const body = {
          kind,
          ...(kind === 'vllm' ? { venv, remove_venv: removeVenv } : {}),
          ...(kind === 'comfyui' ? { dir: comfyDir, remove_checkout: removeCheckout } : {}),
          ...(kind === 'openviking' ? { remove_workspace: removeWorkspace } : {}),
        };
        const res = await fetch(getApiUrl('/api/installer/uninstall'), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        });
        const data: { success: boolean; job?: string; message?: string } = await res.json();
        if (data.success && data.job) {
          setLogJobType('uninstall');
          setLogJob(data.job);
          setLogText('');
          setLogStatus('running');
        } else {
          toast.error(data.message || t('inst.uninstallStartFailed'));
          setUninstalling(null);
        }
      } catch (e: any) {
        toast.error(t('inst.uninstallStartFailed', { msg: e?.message || String(e) }));
        setUninstalling(null);
      }
    },
    [venv, removeVenv, comfyDir, removeCheckout, removeWorkspace, t]
  );

  // Update = re-run the idempotent install script in place. For vLLM this
  // re-resolves the latest vendor-correct PyTorch wheels (ROCm from AMD,
  // CUDA from NVIDIA) + the latest vLLM; the others do a quick refresh.
  const startUpdate = useCallback(
    async (kind: 'vllm' | 'hermes' | 'comfyui' | 'lmstudio' | 'openviking') => {
      if (kind === 'vllm') {
        if (!window.confirm(t('inst.vllmUpdateConfirm', { venv: venv }))) return;
      }
      setUpdating(kind);
      try {
        const body = kind === 'vllm'
          ? { kind, venv, channel, qwentools: !!status?.qwen?.installed }
          : kind === 'comfyui' ? { kind, dir: comfyDir } : { kind };
        const res = await fetch(getApiUrl('/api/installer/update'), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        });
        const data: { success: boolean; job?: string; message?: string } = await res.json();
        if (data.success && data.job) {
          setLogJobType('update');
          setLogJob(data.job);
          setLogText('');
          setLogStatus('running');
        } else {
          toast.error(data.message || t('inst.updateStartFailed'));
          setUpdating(null);
        }
      } catch (e: any) {
        toast.error(t('inst.updateStartFailed', { msg: e?.message || String(e) }));
        setUpdating(null);
      }
    },
    [venv, channel, comfyDir, status, t]
  );

  const startPaiton = useCallback(
    async () => {
      const dockerOk = status?.docker?.installed && status?.docker?.running;
      if (!dockerOk) {
        toast.error(t('inst.paitonNoDocker'));
        return;
      }
      if (!window.confirm(t('inst.paitonConfirm'))) return;
      setPaitonInstalling(true);
      try {
        const res = await fetch(getApiUrl('/api/installer/paiton'), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ model: paitonModel }),
        });
        const data: { success: boolean; job?: string; message?: string } = await res.json();
        if (data.success && data.job) {
          setLogJobType('install');
          setLogJob(data.job);
          setLogText('');
          setLogStatus('running');
        } else {
          toast.error(data.message || t('inst.startFailed'));
          setPaitonInstalling(false);
        }
      } catch (e: any) {
        toast.error(t('inst.startFailed', { msg: e?.message || String(e) }));
        setPaitonInstalling(false);
      }
    },
    [status, t, paitonModel]
  );

  const startVllmModel = useCallback(
    async () => {
      if (!vllmModel) return;
      setVllmModelDownloading(true);
      try {
        const res = await fetch(getApiUrl('/api/installer/vllm-model'), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ model: vllmModel }),
        });
        const data: { success: boolean; job?: string; message?: string } = await res.json();
        if (data.success && data.job) {
          setLogJobType('install');
          setLogJob(data.job);
          setLogText('');
          setLogStatus('running');
        } else {
          toast.error(data.message || t('inst.startFailed'));
          setVllmModelDownloading(false);
        }
      } catch (e: any) {
        toast.error(t('inst.startFailed', { msg: e?.message || String(e) }));
        setVllmModelDownloading(false);
      }
    },
    [t, vllmModel]
  );

  const startLmstudioModel = useCallback(
    async () => {
      if (!lmstudioModel) return;
      setLmstudioModelDownloading(true);
      try {
        const res = await fetch(getApiUrl('/api/installer/lmstudio-model'), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ model: lmstudioModel }),
        });
        const data: { success: boolean; job?: string; message?: string } = await res.json();
        if (data.success && data.job) {
          setLogJobType('install');
          setLogJob(data.job);
          setLogText('');
          setLogStatus('running');
        } else {
          toast.error(data.message || t('inst.startFailed'));
          setLmstudioModelDownloading(false);
        }
      } catch (e: any) {
        toast.error(t('inst.startFailed', { msg: e?.message || String(e) }));
        setLmstudioModelDownloading(false);
      }
    },
    [t, lmstudioModel]
  );

  const restartGateway = async () => {
    if (!window.confirm(t('inst.gatewayRestartConfirm'))) return;
    setRestartingGateway(true);
    try {
      const res = await fetch(getApiUrl('/api/installer/gateway/restart'), { method: 'POST' });
      const data: { success: boolean; message?: string } = await res.json();
      if (data.success) toast.success(data.message || t('inst.gatewayRestarting'));
      else toast.error(data.message || t('inst.gatewayRestartFailed'));
    } catch (e: any) {
      toast.error(t('inst.gatewayRestartFailed', { msg: e?.message || String(e) }));
    } finally {
      setRestartingGateway(false);
    }
  };

  // Open the Hermes Web UI in a new tab via a one-use launch ticket (minted by
  // the gateway) — a plain :9120 tab has no session and shows the sign-in wall.
  const openWebUi = async () => {
    const win = window.open('about:blank', '_blank');
    const fail = (msg: string) => {
      if (win) {
        win.document.title = 'Web UI failed';
        win.document.body.innerHTML =
          '<div style="font-family:sans-serif;padding:2rem;max-width:40rem"><h2>Could not open Web UI</h2><p>' + msg + '</p></div>';
        win.focus();
      } else {
        alert('Could not open Web UI: ' + msg);
      }
    };
    try {
      const res = await fetch(getApiUrl('/api/hermes/webapp-link'));
      const data: { success: boolean; url?: string; message?: string } = await res.json();
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

  const sys = status?.system;
  const docker = status?.docker;
  const paitonDocker = status?.paiton_docker;
  const vllm = status?.vllm;
  const qwenStatus = status?.qwen;
  const hermes = status?.hermes;
  const comfyui = status?.comfyui;
  const lms = status?.lmstudio;
  const ov = status?.openviking;

  // Small "Website" link for the installer cards — opens the project's site
  // in a new tab so users can see what a tool is before installing it.
  const siteLink = (href: string) => (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      onClick={(e) => e.stopPropagation()}
      className="inline-flex items-center gap-1 text-xs text-primary hover:underline"
    >
      <ExternalLink className="h-3 w-3" />
      {t('inst.website')}
    </a>
  );

  return (
    <section>
      <div className="flex items-center gap-2 mb-6">
        <Download className="h-5 w-5 text-primary" />
        <h2 className="text-xl font-display font-bold text-foreground">{t('inst.title')}</h2>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* left column: vLLM + LM Studio stacked */}
        <div className="flex flex-col gap-6">
        <CollapsibleCard
          icon={<Cpu className="h-4 w-4 text-primary" />}
          title="vLLM"
          headerRight={siteLink('https://github.com/vllm-project/vllm')}
          statusBadges={
            vllm?.installed ? (
              <Badge className="bg-emerald-500/15 text-emerald-600 dark:text-emerald-400">
                <CheckCircle2 className="mr-1 h-3 w-3" />
                {t('inst.installed')} {vllm.version}
              </Badge>
            ) : (
              <Badge variant="outline">{t('inst.notInstalled')}</Badge>
            )
          }
          expanded={expanded.has('vllm')}
          onToggle={() => toggleCard('vllm')}
        >
          <CardDescription>{t('inst.vllmDesc')}</CardDescription>
          <div className="flex flex-wrap items-center gap-2">
            {sys && (
              <Badge variant="secondary">
                {sys.vendor === 'amd'
                  ? 'AMD GPU'
                  : sys.vendor === 'nvidia'
                    ? `NVIDIA ${sys.vendor_detail}`
                    : t('inst.noGpuStack')}
              </Badge>
            )}
            {vllm?.installed && vllm.rocm_version && (
              <Badge className="bg-sky-500/15 text-sky-600 dark:text-sky-400">
                {t('inst.rocmVersion')} {vllm.rocm_version}
              </Badge>
            )}
            {sys && <span className="text-xs text-muted-foreground">{sys.disk_free_gb} GB free</span>}
          </div>

          <div className="space-y-2">
            <label className="text-xs font-medium text-muted-foreground">{t('inst.venvLabel')}</label>
            <input
              value={venv}
              onChange={(e) => setVenv(e.target.value)}
              className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm font-mono"
              placeholder="~/vllm-venv"
            />
          </div>

          <div className="space-y-2">
            <label className="text-xs font-medium text-muted-foreground">{t('inst.channelLabel')}</label>
            <div className="flex gap-2">
              <Button
                size="sm"
                variant={channel === 'nightly' ? 'default' : 'outline'}
                onClick={() => setChannel('nightly')}
              >
                {t('inst.nightly')}
              </Button>
              <Button
                size="sm"
                variant={channel === 'stable' ? 'default' : 'outline'}
                onClick={() => setChannel('stable')}
              >
                {t('inst.stable')}
              </Button>
            </div>
            <p className="text-xs text-muted-foreground">{t('inst.channelNote')}</p>
            {qwenStatus?.installed ? (
              <Badge className="bg-emerald-500/15 text-emerald-600 dark:text-emerald-400">
                <CheckCircle2 className="mr-1 h-3 w-3" />
                {t('inst.qwenTools')}
              </Badge>
            ) : (
              <label className="flex items-start gap-2 text-xs text-muted-foreground cursor-pointer">
                <input
                  type="checkbox"
                  checked={qwenTools}
                  onChange={(e) => setQwenTools(e.target.checked)}
                  className="h-3 w-3 rounded border-input mt-0.5"
                />
                <span>
                  {t('inst.qwenTools')}
                  <span className="block text-muted-foreground/70">{t('inst.qwenToolsHint')}</span>
                </span>
              </label>
            )}
          </div>

          <div className="space-y-2">
            <div className="flex items-center gap-2 flex-wrap">
              <Button onClick={() => startInstall('vllm')} disabled={installing !== null || uninstalling !== null || updating !== null}>
                <Download className="h-3 w-3 mr-1" />
                {installing === 'vllm' ? t('inst.installing') : t('inst.install')}
              </Button>
              {vllm?.installed && (
                <Button variant="outline" onClick={() => startUpdate('vllm')} disabled={updating !== null || installing !== null || uninstalling !== null}>
                  <RefreshCw className={`h-3 w-3 mr-1 ${updating === 'vllm' ? 'animate-spin' : ''}`} />
                  {updating === 'vllm' ? t('inst.updating') : t('inst.update')}
                </Button>
              )}
              {vllm?.installed && (
                <Button variant="destructive" onClick={() => startUninstall('vllm')} disabled={uninstalling !== null || installing !== null || updating !== null}>
                  <Trash2 className="h-3 w-3 mr-1" />
                  {uninstalling === 'vllm' ? t('inst.uninstalling') : t('inst.uninstall')}
                </Button>
              )}
              {vllm?.installed && (
                <span className="text-xs text-muted-foreground font-mono truncate">{vllm.venv}</span>
              )}
            </div>
            {vllm?.installed && (
              <label className="flex items-center gap-2 text-xs text-muted-foreground cursor-pointer">
                <input
                  type="checkbox"
                  checked={removeVenv}
                  onChange={(e) => setRemoveVenv(e.target.checked)}
                  className="h-3 w-3 rounded border-input"
                />
                {t('inst.removeVenv')}
              </label>
            )}
          </div>

          {/* Model downloader (vLLM) */}
          <div className="space-y-2">
            <label className="text-xs font-medium text-muted-foreground">{t('inst.vllmModelLabel')}</label>
            <div className="flex items-center gap-2 flex-wrap">
              <select
                value={vllmModel}
                onChange={(e) => setVllmModel(e.target.value)}
                className="w-[220px] rounded-md border border-input bg-transparent px-3 py-1.5 text-sm shadow-sm outline-none focus-visible:ring-1 focus-visible:ring-ring"
              >
                {vllmModels.map((m) => (
                  <option key={m.slug} value={m.slug}>{m.name} ({m.size})</option>
                ))}
              </select>
              <Button onClick={startVllmModel} disabled={vllmModelDownloading || installing !== null || uninstalling !== null || updating !== null}>
                {vllmModelDownloading ? <RefreshCw className="h-3 w-3 mr-1 animate-spin" /> : <Download className="h-3 w-3 mr-1" />}
                {vllmModelDownloading ? t('inst.downloading') : t('inst.download')}
              </Button>
            </div>
          </div>
        </CollapsibleCard>

        {/* Paiton — Docker container install (any release model) */}
        <CollapsibleCard
          icon={<Brain className="h-4 w-4 text-primary" />}
          title={t('inst.paitonTitle')}
          headerRight={siteLink('https://github.com/Eliovp-BV/paiton-vllm-plugin')}
          statusBadges={
            <>
              {paitonDocker?.installed ? (
                paitonDocker.running ? (
                  <Badge className="bg-emerald-500/15 text-emerald-600 dark:text-emerald-400">
                    <CheckCircle2 className="mr-1 h-3 w-3" />
                    {t('inst.installed')}
                  </Badge>
                ) : (
                  <Badge className="bg-amber-500/15 text-amber-600 dark:text-amber-400">
                    <AlertCircle className="mr-1 h-3 w-3" />
                    {t('inst.paitonStopped')}
                  </Badge>
                )
              ) : (
                <Badge variant="outline">{t('inst.notInstalled')}</Badge>
              )}
              {docker && !docker.installed && (
                <Badge variant="destructive">
                  <AlertCircle className="mr-1 h-3 w-3" />
                  {t('inst.paitonNoDocker')}
                </Badge>
              )}
            </>
          }
          expanded={expanded.has('paiton')}
          onToggle={() => toggleCard('paiton')}
        >
          <CardDescription>{t('inst.paitonDesc')}</CardDescription>
          <div className="flex flex-wrap items-center gap-2">
            {docker && (
              docker.installed && docker.running ? (
                <Badge className="bg-sky-500/15 text-sky-600 dark:text-sky-400">
                  <CheckCircle2 className="mr-1 h-3 w-3" />
                  {t('inst.paitonDockerOk')}
                </Badge>
              ) : (
                <Badge variant="destructive">
                  <AlertCircle className="mr-1 h-3 w-3" />
                  {t('inst.paitonNoDocker')}
                </Badge>
              )
            )}
            <span className="text-xs text-muted-foreground">
              {t('inst.paitonSize', { size: PAITON_MODELS.find((m) => m.slug === paitonModel)?.size || '~66 GB' })}
            </span>
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            <select
              value={paitonModel}
              onChange={(e) => setPaitonModel(e.target.value)}
              className="w-[220px] rounded-md border border-input bg-transparent px-3 py-1.5 text-sm shadow-sm outline-none focus-visible:ring-1 focus-visible:ring-ring"
            >
              {PAITON_MODELS.map((m) => (
                <option key={m.slug} value={m.slug}>{m.name}</option>
              ))}
            </select>
            <Button
              onClick={startPaiton}
              disabled={paitonInstalling || installing !== null || uninstalling !== null || updating !== null || !docker?.installed || !docker?.running}
            >
              {paitonDocker?.installed ? <RefreshCw className={`h-3 w-3 mr-1 ${paitonInstalling ? 'animate-spin' : ''}`} /> : <Download className="h-3 w-3 mr-1" />}
              {paitonInstalling ? t('inst.paitonInstalling') : paitonDocker?.installed ? t('inst.paitonUpdate') : t('inst.paitonInstall')}
            </Button>
            {paitonDocker?.running && (
              <span className="text-xs text-muted-foreground font-mono truncate">{paitonDocker.detail}</span>
            )}
          </div>
        </CollapsibleCard>

        {/* LM Studio + Beledarian Suite card */}
        <CollapsibleCard
          icon={<Sparkles className="h-4 w-4 text-primary" />}
          title={t('inst.lmsTitle')}
          headerRight={siteLink('https://lmstudio.ai')}
          statusBadges={
            <>
              {lms?.installed ? (
                <Badge className="bg-emerald-500/15 text-emerald-600 dark:text-emerald-400">
                  <CheckCircle2 className="mr-1 h-3 w-3" />
                  {t('inst.installed')}
                </Badge>
              ) : (
                <Badge variant="outline">{t('inst.notInstalled')}</Badge>
              )}
              {lms?.suite?.installed ? (
                <Badge className="bg-violet-500/15 text-violet-600 dark:text-violet-400">
                  <CheckCircle2 className="mr-1 h-3 w-3" />
                  {t('inst.lmsSuite')}{lms.suite.revision ? ` rev ${lms.suite.revision}` : ''}
                </Badge>
              ) : (
                <Badge variant="secondary">{t('inst.lmsSuiteMissing')}</Badge>
              )}
            </>
          }
          expanded={expanded.has('lmstudio')}
          onToggle={() => toggleCard('lmstudio')}
        >
          <CardDescription>{t('inst.lmsDesc')}</CardDescription>
          <div className="flex items-center gap-2 flex-wrap">
            <Button onClick={() => startInstall('lmstudio')} disabled={installing !== null || uninstalling !== null || updating !== null}>
              <Download className="h-3 w-3 mr-1" />
              {installing === 'lmstudio' ? t('inst.installing') : t('inst.install')}
            </Button>
            {lms?.installed && (
              <Button variant="outline" onClick={() => startUpdate('lmstudio')} disabled={updating !== null || installing !== null || uninstalling !== null}>
                <RefreshCw className={`h-3 w-3 mr-1 ${updating === 'lmstudio' ? 'animate-spin' : ''}`} />
                {updating === 'lmstudio' ? t('inst.updating') : t('inst.update')}
              </Button>
            )}
            {lms?.installed && (
              <Button variant="destructive" onClick={() => startUninstall('lmstudio')} disabled={uninstalling !== null || installing !== null || updating !== null}>
                <Trash2 className="h-3 w-3 mr-1" />
                {uninstalling === 'lmstudio' ? t('inst.uninstalling') : t('inst.uninstall')}
              </Button>
            )}
            {lms?.installed && (
              <span className="text-xs text-muted-foreground font-mono truncate">{lms.lms}</span>
            )}
          </div>

          {/* Model downloader (LM Studio) */}
          <div className="space-y-2">
            <label className="text-xs font-medium text-muted-foreground">{t('inst.lmsModelLabel')}</label>
            <div className="flex items-center gap-2 flex-wrap">
              <select
                value={lmstudioModel}
                onChange={(e) => setLmstudioModel(e.target.value)}
                className="w-[220px] rounded-md border border-input bg-transparent px-3 py-1.5 text-sm shadow-sm outline-none focus-visible:ring-1 focus-visible:ring-ring"
              >
                {lmstudioModels.map((m) => (
                  <option key={m.slug} value={m.slug}>{m.name} ({m.size})</option>
                ))}
              </select>
              <Button onClick={startLmstudioModel} disabled={lmstudioModelDownloading || installing !== null || uninstalling !== null || updating !== null}>
                {lmstudioModelDownloading ? <RefreshCw className="h-3 w-3 mr-1 animate-spin" /> : <Download className="h-3 w-3 mr-1" />}
                {lmstudioModelDownloading ? t('inst.downloading') : t('inst.download')}
              </Button>
            </div>
          </div>
        </CollapsibleCard>
        </div>

        {/* right column: Hermes (compact) + ComfyUI stacked */}
        <div className="flex flex-col gap-6">
          {/* Hermes webapp card (compact) */}
          <CollapsibleCard
            icon={<Bot className="h-4 w-4 text-primary" />}
            title={t('inst.hermesTitle')}
            headerRight={siteLink('https://hermes-agent.nousresearch.com')}
            statusBadges={
              hermes?.installed ? (
                <Badge className="bg-emerald-500/15 text-emerald-600 dark:text-emerald-400">
                  <CheckCircle2 className="mr-1 h-3 w-3" />
                  {t('inst.installed')} {hermes.version}
                </Badge>
              ) : (
                <Badge variant="outline">{t('inst.notInstalled')}</Badge>
              )
            }
            expanded={expanded.has('hermes')}
            onToggle={() => toggleCard('hermes')}
          >
            <div className="flex flex-wrap items-center gap-2">
              {hermes && (
                <>
                  {hermes.webapp_enabled === true && <Badge variant="secondary">{t('inst.webappEnabled')}</Badge>}
                  {hermes.webapp_reachable && (
                    <Badge className="bg-emerald-500/15 text-emerald-600 dark:text-emerald-400">{t('inst.webappUp')}</Badge>
                  )}
                </>
              )}
            </div>

            <div className="flex items-center gap-2 flex-wrap">
              <Button onClick={() => startInstall('hermes')} disabled={installing !== null || updating !== null}>
                <Download className="h-3 w-3 mr-1" />
                {installing === 'hermes' ? t('inst.installing') : t('inst.install')}
              </Button>
              {hermes?.installed && (
                <Button variant="outline" onClick={() => startUpdate('hermes')} disabled={updating !== null || installing !== null || uninstalling !== null}>
                  <RefreshCw className={`h-3 w-3 mr-1 ${updating === 'hermes' ? 'animate-spin' : ''}`} />
                  {updating === 'hermes' ? t('inst.updating') : t('inst.update')}
                </Button>
              )}
              {hermes?.installed && (
                <Button variant="outline" onClick={restartGateway} disabled={restartingGateway}>
                  <RefreshCw className={`h-3 w-3 mr-1 ${restartingGateway ? 'animate-spin' : ''}`} />
                  {t('inst.restartGateway')}
                </Button>
              )}
              {hermes?.installed && hermes.webapp_enabled === true && (
                <Button variant="outline" onClick={() => startUninstall('hermes')} disabled={uninstalling !== null || installing !== null || updating !== null}>
                  <XCircle className="h-3 w-3 mr-1" />
                  {uninstalling === 'hermes' ? t('inst.uninstalling') : t('inst.disableWebapp')}
                </Button>
              )}
              {hermes?.webapp_reachable && (
                <Button variant="ghost" size="sm" onClick={openWebUi}>
                  <ExternalLink className="h-3 w-3 mr-1" />
                  {t('inst.openWebUi')}
                </Button>
              )}
            </div>
          </CollapsibleCard>

          {/* OpenViking — Hermes long-term memory (compact) */}
          <CollapsibleCard
            icon={<Brain className="h-4 w-4 text-primary" />}
            title={t('inst.ovTitle')}
            headerRight={siteLink('https://github.com/volcengine/OpenViking')}
            statusBadges={
              ov?.installed ? (
                <Badge className="bg-emerald-500/15 text-emerald-600 dark:text-emerald-400">
                  <CheckCircle2 className="mr-1 h-3 w-3" />
                  {t('inst.installed')}
                </Badge>
              ) : (
                <Badge variant="outline">{t('inst.notInstalled')}</Badge>
              )
            }
            expanded={expanded.has('openviking')}
            onToggle={() => toggleCard('openviking')}
          >
            <CardDescription>{t('inst.ovDesc')}</CardDescription>
            <div className="flex flex-wrap items-center gap-2">
              {ov && (
                <>
                  {ov.server && (
                    <Badge className="bg-emerald-500/15 text-emerald-600 dark:text-emerald-400">
                      {t('inst.ovServer')} {ov.server_version || ''}
                    </Badge>
                  )}
                  {ov.embed && <Badge variant="secondary">{t('inst.ovEmbed')}</Badge>}
                  {ov.plugin ? (
                    <Badge variant="secondary">{t('inst.ovPlugin')}</Badge>
                  ) : (
                    <Badge variant="outline">{t('inst.ovPluginMissing')}</Badge>
                  )}
                  {ov.hermes_configured ? (
                    <Badge className="bg-violet-500/15 text-violet-600 dark:text-violet-400">{t('inst.ovHermes')}</Badge>
                  ) : (
                    <Badge variant="outline">{t('inst.ovHermesMissing')}</Badge>
                  )}
                </>
              )}
            </div>

            <div className="flex items-center gap-2 flex-wrap">
              <Button onClick={() => startInstall('openviking')} disabled={installing !== null || uninstalling !== null || updating !== null}>
                <Download className="h-3 w-3 mr-1" />
                {installing === 'openviking' ? t('inst.installing') : t('inst.install')}
              </Button>
              {ov?.installed && (
                <Button variant="outline" onClick={() => startUpdate('openviking')} disabled={updating !== null || installing !== null || uninstalling !== null}>
                  <RefreshCw className={`h-3 w-3 mr-1 ${updating === 'openviking' ? 'animate-spin' : ''}`} />
                  {updating === 'openviking' ? t('inst.updating') : t('inst.update')}
                </Button>
              )}
              {ov?.installed && (
                <Button variant="destructive" onClick={() => startUninstall('openviking')} disabled={uninstalling !== null || installing !== null || updating !== null}>
                  <Trash2 className="h-3 w-3 mr-1" />
                  {uninstalling === 'openviking' ? t('inst.uninstalling') : t('inst.uninstall')}
                </Button>
              )}
              {ov?.installed && (
                <Button variant="outline" onClick={restartGateway} disabled={restartingGateway}>
                  <RefreshCw className={`h-3 w-3 mr-1 ${restartingGateway ? 'animate-spin' : ''}`} />
                  {t('inst.restartGateway')}
                </Button>
              )}
            </div>
            {ov?.installed && (
              <label className="flex items-center gap-2 text-xs text-muted-foreground cursor-pointer">
                <input
                  type="checkbox"
                  checked={removeWorkspace}
                  onChange={(e) => setRemoveWorkspace(e.target.checked)}
                  className="h-3 w-3 rounded border-input"
                />
                {t('inst.ovRemoveWorkspace')}
              </label>
            )}
          </CollapsibleCard>

          {/* ComfyUI card */}
          <CollapsibleCard
            icon={<ImageIcon className="h-4 w-4 text-primary" />}
            title={t('inst.comfyuiTitle')}
            headerRight={siteLink('https://github.com/comfyanonymous/ComfyUI')}
            statusBadges={
              comfyui?.installed ? (
                <Badge className="bg-emerald-500/15 text-emerald-600 dark:text-emerald-400">
                  <CheckCircle2 className="mr-1 h-3 w-3" />
                  {t('inst.installed')}
                </Badge>
              ) : (
                <Badge variant="outline">{t('inst.notInstalled')}</Badge>
              )
            }
            expanded={expanded.has('comfyui')}
            onToggle={() => toggleCard('comfyui')}
          >
            <CardDescription>{t('inst.comfyuiDesc')}</CardDescription>
            <div className="space-y-2">
              <label className="text-xs font-medium text-muted-foreground">{t('inst.comfyuiDirLabel')}</label>
              <input
                value={comfyDir}
                onChange={(e) => setComfyDir(e.target.value)}
                className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm font-mono"
                placeholder="~/ComfyUI-plain"
              />
            </div>

            <div className="flex items-center gap-2 flex-wrap">
              <Button onClick={() => startInstall('comfyui')} disabled={installing !== null || uninstalling !== null || updating !== null}>
                <Download className="h-3 w-3 mr-1" />
                {installing === 'comfyui' ? t('inst.installing') : t('inst.install')}
              </Button>
              {comfyui?.installed && (
                <Button variant="outline" onClick={() => startUpdate('comfyui')} disabled={updating !== null || installing !== null || uninstalling !== null}>
                  <RefreshCw className={`h-3 w-3 mr-1 ${updating === 'comfyui' ? 'animate-spin' : ''}`} />
                  {updating === 'comfyui' ? t('inst.updating') : t('inst.update')}
                </Button>
              )}
              {comfyui?.installed && (
                <Button variant="destructive" onClick={() => startUninstall('comfyui')} disabled={uninstalling !== null || installing !== null || updating !== null}>
                  <Trash2 className="h-3 w-3 mr-1" />
                  {uninstalling === 'comfyui' ? t('inst.uninstalling') : t('inst.uninstall')}
                </Button>
              )}
              {comfyui?.installed && (
                <span className="text-xs text-muted-foreground font-mono truncate">{comfyui.dir}</span>
              )}
            </div>
            {comfyui?.installed && (
              <label className="flex items-center gap-2 text-xs text-muted-foreground cursor-pointer">
                <input
                  type="checkbox"
                  checked={removeCheckout}
                  onChange={(e) => setRemoveCheckout(e.target.checked)}
                  className="h-3 w-3 rounded border-input"
                />
                {t('inst.comfyuiRemoveCheckout')}
              </label>
            )}
          </CollapsibleCard>
        </div>
      </div>

      {/* Live install log */}
      <Dialog open={logJob !== null} onOpenChange={(open) => { if (!open) { setLogJob(null); setInstalling(null); setUninstalling(null); } }}>
        <DialogContent className="max-w-4xl max-h-[80vh] bg-background/95 backdrop-blur-xl border-border shadow-2xl">
          <DialogHeader>
            <DialogTitle className="font-display flex items-center gap-2">
              {logStatus === 'running' ? (
                <RefreshCw className="h-4 w-4 text-primary animate-spin" />
              ) : logStatus === 'done' ? (
                <CheckCircle2 className="h-4 w-4 text-emerald-500" />
              ) : (
                <AlertCircle className="h-4 w-4 text-destructive" />
              )}
              {t('inst.logTitle')}
            </DialogTitle>
          </DialogHeader>
          <div ref={scrollRef} className="mt-4 bg-black/50 rounded-lg p-4 max-h-[60vh] overflow-y-auto border border-border/50 custom-scrollbar">
            <pre className="text-xs font-mono text-foreground whitespace-pre-wrap">{logText || t('inst.logWaiting')}</pre>
          </div>
        </DialogContent>
      </Dialog>
    </section>
  );
}
