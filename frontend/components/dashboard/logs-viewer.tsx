'use client';

import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { useEffect, useRef, useState } from 'react';
import { Skeleton } from '@/components/ui/skeleton';
import { getApiUrl } from '@/lib/api-config';
import { useLang } from '@/lib/i18n';

interface LogsViewerProps {
  logUrl: string | null;
  serviceName: string;
  isOpen: boolean;
  onClose: () => void;
}

export function LogsViewer({ logUrl, serviceName, isOpen, onClose }: LogsViewerProps) {
  const { t } = useLang();
  const [logs, setLogs] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Start at the bottom (newest entries); user scrolls up for older ones.
  useEffect(() => {
    if (logs && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [logs]);

  useEffect(() => {
    if (isOpen && logUrl) {
      setIsLoading(true);
      fetch(getApiUrl(logUrl))
        .then(res => res.json())
        .then(result => {
          if (result.success) {
            setLogs(result.logs || t('lv.empty'));
          } else {
            setLogs(t('lv.loadFailed', { msg: result.message }));
          }
        })
        .catch(error => {
          setLogs(t('lv.loadFailed', { msg: error.message }));
        })
        .finally(() => {
          setIsLoading(false);
        });
    }
  }, [isOpen, logUrl]);

  return (
    <Dialog open={isOpen} onOpenChange={onClose}>
      <DialogContent className="max-w-4xl max-h-[80vh] bg-background/95 backdrop-blur-xl border-border shadow-2xl">
        <DialogHeader>
          <DialogTitle className="font-display">{t('lv.logsTitle', { name: serviceName })}</DialogTitle>
        </DialogHeader>
        <div ref={scrollRef} className="mt-4 bg-black/50 rounded-lg p-4 max-h-[60vh] overflow-y-auto border border-border/50 custom-scrollbar">
          {isLoading ? (
            <div className="space-y-2">
              {[...Array(10)].map((_, i) => (
                <Skeleton key={i} className="h-4 w-full" />
              ))}
            </div>
          ) : (
            <pre className="text-xs font-mono text-foreground whitespace-pre-wrap">
              {logs}
            </pre>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
