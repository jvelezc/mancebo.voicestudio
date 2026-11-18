import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';

const mode = vi.hoisted(() => vi.fn());
vi.mock('@/lib/managed-studio', () => ({ studioMode: mode }));
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
import { ManagedStudioSource } from './managed-studio-source';
afterEach(cleanup);

it('keeps the fork source offer visible and tied to the packaged build', () => {
  mode.mockReturnValue({ kind: 'managed' });
  render(<ManagedStudioSource />);
  const link = screen.getByRole('link', { name: 'managedStudio.sourceCode' });
  expect(link).toHaveAttribute(
    'href',
    'https://github.com/jvelezc/mancebo.voicestudio/tree/000000000',
  );
  expect(link).toHaveAttribute('rel', 'noopener noreferrer');
  expect(link).toHaveTextContent('managedStudio.sourceCode');
});

it('names the compact icon for keyboard and screen-reader access', () => {
  mode.mockReturnValue({ kind: 'managed' });
  render(<ManagedStudioSource compact />);
  expect(screen.getByRole('link', { name: 'managedStudio.sourceCode' })).not.toHaveTextContent(
    'managedStudio.sourceCode',
  );
});

it('does not add Mancebo links to a standalone installation', () => {
  mode.mockReturnValue({ kind: 'standalone' });
  render(<ManagedStudioSource />);
  expect(screen.queryByRole('link')).not.toBeInTheDocument();
});
