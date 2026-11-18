import { CodeIcon } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { studioMode } from '@/lib/managed-studio';

/** Keep the modified application's network source offer visible in hosted mode. */
export function ManagedStudioSource({ compact = false }: { compact?: boolean }) {
  const { t } = useTranslation();
  if (studioMode().kind !== 'managed') return null;
  return (
    <a
      href={`https://github.com/jvelezc/mancebo.voicestudio/tree/${__BUILD_COMMIT__}`}
      target="_blank"
      rel="noopener noreferrer"
      title={t('managedStudio.sourceCode')}
      aria-label={t('managedStudio.sourceCode')}
      className="flex min-h-7 items-center justify-center gap-2 rounded px-2 text-xs text-muted-foreground underline underline-offset-4 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      <CodeIcon aria-hidden="true" className="size-4" />
      {!compact && t('managedStudio.sourceCode')}
    </a>
  );
}
