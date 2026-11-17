import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import type { DubSegment } from './dub-session';

export type SpeakerSimilarityMode = NonNullable<DubSegment['speaker_similarity']>;

/** Reference selection is real engine input; it is not an acoustic quality score. */
export function SpeakerSimilarityControls({
  speaker,
  mode,
  disabled,
  onChange,
}: {
  speaker: string;
  mode: SpeakerSimilarityMode;
  disabled: boolean;
  onChange: (mode: SpeakerSimilarityMode) => void;
}) {
  const { t } = useTranslation();
  return (
    <fieldset disabled={disabled} className="mt-3 space-y-2 border-t border-border/50 pt-3">
      <legend className="sr-only">{t('dub.similarity_for', { speaker })}</legend>
      <label className="flex min-h-9 items-center gap-2 text-xs font-medium">
        <input
          type="checkbox"
          checked={mode !== 'off'}
          onChange={(event) => onChange(event.target.checked ? 'consistent' : 'off')}
          className="size-5 accent-primary"
        />
        {t('dub.similarity_title')}
      </label>
      <p className="text-xs leading-5 text-muted-foreground">{t('dub.similarity_help')}</p>
      {mode !== 'off' && (
        <div
          className="flex flex-wrap gap-2"
          role="group"
          aria-label={t('dub.similarity_strategy')}
        >
          {(['consistent', 'per_line'] as const).map((value) => (
            <Button
              key={value}
              type="button"
              size="sm"
              disabled={disabled}
              variant={mode === value ? 'secondary' : 'outline'}
              aria-pressed={mode === value}
              onClick={() => onChange(value)}
            >
              {t(`dub.similarity_${value}`)}
            </Button>
          ))}
        </div>
      )}
      <p className="text-xs leading-5 text-muted-foreground">
        {t(mode === 'off' ? 'dub.similarity_off_help' : `dub.similarity_${mode}_help`)}
      </p>
    </fieldset>
  );
}
