'use client';

import { useState } from 'react';
import { Globe, Check } from 'lucide-react';
import { LANGS, useLang } from '@/lib/i18n';

// Language picker for the sidebar header. The chosen language is persisted
// in localStorage (by the LanguageProvider) and applied to every UI string
// via t().
export function LanguageToggle() {
  const { lang, setLang, t } = useLang();
  const [open, setOpen] = useState(false);
  const current = LANGS.find((l) => l.code === lang) ?? LANGS[0];

  return (
    <div className="relative">
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-1.5 rounded-lg border border-sidebar-border bg-sidebar-accent/50 px-2.5 py-1.5 text-xs font-medium text-sidebar-foreground hover:bg-sidebar-accent transition-colors"
        title="Language"
      >
        <Globe className="h-3.5 w-3.5 text-primary" />
        {current.label}
      </button>
      {open && (
        <>
          {/* backdrop so a click outside closes the menu */}
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <div className="absolute right-0 top-full mt-1 z-50 w-36 bg-background border border-border rounded-lg shadow-lg p-1">
            {LANGS.map((l) => (
              <button
                key={l.code}
                onClick={() => {
                  setLang(l.code);
                  setOpen(false);
                }}
                className={`w-full flex items-center justify-between gap-2 px-2.5 py-1.5 text-xs rounded-md ${
                  l.code === lang
                    ? 'bg-primary/10 text-primary font-semibold'
                    : 'text-foreground hover:bg-sidebar-accent'
                }`}
              >
                {l.label}
                {l.code === lang && <Check className="h-3 w-3" />}
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
