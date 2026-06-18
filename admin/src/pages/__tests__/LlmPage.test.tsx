import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

vi.mock('../../api/client', () => ({
  getLLMModels: vi.fn(),
  refreshLLMModels: vi.fn(),
}));

import { LlmPage } from '../LlmPage';
import { getLLMModels, refreshLLMModels } from '../../api/client';

const activeModel = {
  model_id: 'gpt-4o',
  position: 1,
  is_active: true,
  active_now: true,
  context_length: 128000,
  created_upstream: null,
  added_at: new Date().toISOString(),
  last_refresh_at: new Date().toISOString(),
  last_error: null,
  consecutive_failures: 0,
  disabled_until: null,
};

const disabledModel = {
  model_id: 'gpt-3.5-turbo',
  position: 2,
  is_active: true,
  active_now: false,
  context_length: 16000,
  created_upstream: null,
  added_at: new Date().toISOString(),
  last_refresh_at: new Date().toISOString(),
  last_error: 'rate limit exceeded',
  consecutive_failures: 5,
  disabled_until: new Date(Date.now() + 3600_000).toISOString(), // 1h in future
};

beforeEach(() => {
  vi.clearAllMocks();
});

describe('LlmPage', () => {
  it('renders one row per model with id and context length', async () => {
    vi.mocked(getLLMModels).mockResolvedValue([activeModel]);

    render(
      <MemoryRouter>
        <LlmPage />
      </MemoryRouter>,
    );

    await waitFor(() => expect(screen.getByText('gpt-4o')).toBeInTheDocument());
    // context_length 128000 / 1000 = 128, rendered as "128k"
    expect(screen.getByText('128k')).toBeInTheDocument();
  });

  it('shows an Aktiv badge for an active model', async () => {
    vi.mocked(getLLMModels).mockResolvedValue([activeModel]);

    render(
      <MemoryRouter>
        <LlmPage />
      </MemoryRouter>,
    );

    // "Aktiv" appears twice: once as the table column header, once inside the status badge
    await waitFor(() => expect(screen.getAllByText('Aktiv').length).toBeGreaterThanOrEqual(2));
  });

  it('shows a Pausiert badge with countdown for a disabled model', async () => {
    vi.mocked(getLLMModels).mockResolvedValue([disabledModel]);

    render(
      <MemoryRouter>
        <LlmPage />
      </MemoryRouter>,
    );

    await waitFor(() => {
      const badge = screen.getByText((text) => text.startsWith('Pausiert bis'));
      expect(badge).toBeInTheDocument();
    });
  });

  it('calls refreshLLMModels and updates rows on Aktualisieren', async () => {
    vi.mocked(getLLMModels).mockResolvedValue([activeModel]);

    const updatedModel = { ...activeModel, model_id: 'gpt-4o-mini' };
    vi.mocked(refreshLLMModels).mockResolvedValue([updatedModel]);

    render(
      <MemoryRouter>
        <LlmPage />
      </MemoryRouter>,
    );

    // Wait for initial load
    await waitFor(() => expect(screen.getByText('gpt-4o')).toBeInTheDocument());

    const refreshBtn = screen.getByRole('button', { name: /aktualisieren/i });
    fireEvent.click(refreshBtn);

    await waitFor(() => expect(refreshLLMModels).toHaveBeenCalled());
    await waitFor(() => expect(screen.getByText('gpt-4o-mini')).toBeInTheDocument());
  });
});
