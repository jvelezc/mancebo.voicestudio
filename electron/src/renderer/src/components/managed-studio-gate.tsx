import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { LoaderCircleIcon } from 'lucide-react';
import { apiFetch, ApiError } from '@/lib/api/client';
import { requestStudioReconnect, studioMode, studioWorkspaceUrl } from '@/lib/managed-studio';
import { Button } from '@/components/ui/button';

/** Managed sessions never ask for an upstream API key or share PIN. */
export function ManagedStudioGate({ children }: { children: ReactNode }) {
  const { t } = useTranslation();
  const mode = studioMode();
  const studio = mode.kind === 'managed' ? mode.studio : undefined;
  const [state, setState] = useState<'loading' | 'ready' | 'expired' | 'unavailable'>('loading');
  const sequence = useRef(0);
  const reconnectRequested = useRef(false);
  const reconnect = useCallback(() => {
    if (studio && !reconnectRequested.current) {
      reconnectRequested.current = true;
      requestStudioReconnect(studio);
    }
  }, [studio?.workspaceId]);
  const check = useCallback(async () => {
    const current = ++sequence.current;
    if (!studio) {
      setState('unavailable');
      return;
    }
    setState('loading');
    try {
      const response = await apiFetch('/mancebo/session');
      const identity: unknown = await response.json();
      if (current !== sequence.current) return;
      if (
        !identity ||
        typeof identity !== 'object' ||
        (identity as Record<string, unknown>).workspace_id !== studio.workspaceId ||
        (identity as Record<string, unknown>).execution_available !== true
      ) {
        setState('unavailable');
        return;
      }
      reconnectRequested.current = false;
      setState('ready');
    } catch (error) {
      if (current !== sequence.current) return;
      if (error instanceof ApiError && [401, 403].includes(error.status)) {
        setState('expired');
        reconnect();
      } else setState('unavailable');
    }
  }, [studio?.workspaceId, reconnect]);

  useEffect(() => {
    const expired = () => {
      sequence.current += 1;
      setState('expired');
      reconnect();
    };
    window.addEventListener('ov:auth-required', expired);
    void check();
    return () => {
      sequence.current += 1;
      window.removeEventListener('ov:auth-required', expired);
    };
  }, [check, reconnect]);

  if (state === 'ready') return <>{children}</>;
  if (state === 'loading')
    return (
      <div
        role="status"
        aria-live="polite"
        className="flex min-h-screen items-center justify-center gap-3 bg-background p-6 text-muted-foreground"
      >
        <LoaderCircleIcon
          aria-hidden="true"
          className="size-5 animate-spin motion-reduce:animate-none"
        />
        {t('preferences.loading')}
      </div>
    );
  return (
    <main className="flex min-h-screen items-center justify-center bg-background p-6">
      <section
        aria-labelledby="managed-studio-access-title"
        className="w-full max-w-md space-y-4 rounded-lg border border-border bg-card p-6"
      >
        <p className="text-sm font-semibold">{t('managedStudio.productName')}</p>
        <h1 id="managed-studio-access-title" className="text-lg font-semibold">
          {t(state === 'expired' ? 'managedStudio.sessionExpired' : 'managedStudio.unavailable')}
        </h1>
        <div className="flex flex-wrap items-center gap-3">
          <a
            href={studioWorkspaceUrl(studio)}
            target="_top"
            className="rounded text-primary underline underline-offset-4 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            {t('managedStudio.openWorkspace')}
          </a>
          {studio && (
            <Button
              type="button"
              variant="outline"
              onClick={() => {
                reconnectRequested.current = false;
                void check();
              }}
            >
              {t('managedStudio.retry')}
            </Button>
          )}
        </div>
      </section>
    </main>
  );
}
