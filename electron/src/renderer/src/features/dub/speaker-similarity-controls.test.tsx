import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { SpeakerSimilarityControls } from './speaker-similarity-controls';

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
afterEach(cleanup);

it('changes the reference strategy and can disable source matching', () => {
  const onChange = vi.fn();
  render(
    <SpeakerSimilarityControls
      speaker="Alice"
      mode="consistent"
      disabled={false}
      onChange={onChange}
    />,
  );
  expect(screen.getByRole('checkbox')).toBeChecked();
  expect(screen.getByRole('button', { name: 'dub.similarity_consistent' })).toHaveAttribute(
    'aria-pressed',
    'true',
  );
  fireEvent.click(screen.getByRole('button', { name: 'dub.similarity_per_line' }));
  expect(onChange).toHaveBeenLastCalledWith('per_line');
  fireEvent.click(screen.getByRole('checkbox'));
  expect(onChange).toHaveBeenLastCalledWith('off');
});

it('re-enables a stable voice match and does not expose a fake percentage slider', () => {
  const onChange = vi.fn();
  render(
    <SpeakerSimilarityControls speaker="Alice" mode="off" disabled={false} onChange={onChange} />,
  );
  expect(screen.queryByRole('slider')).toBeNull();
  expect(screen.queryByRole('button')).toBeNull();
  fireEvent.click(screen.getByRole('checkbox'));
  expect(onChange).toHaveBeenCalledWith('consistent');
});

it('locks all controls while generation is running', () => {
  render(
    <SpeakerSimilarityControls speaker="Alice" mode="consistent" disabled onChange={vi.fn()} />,
  );
  expect(screen.getByRole('checkbox')).toBeDisabled();
  for (const button of screen.getAllByRole('button')) expect(button).toBeDisabled();
});
