import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';

vi.mock('@nekazari/sdk', () => ({
  useTranslation: () => ({ t: (k: string, o?: Record<string, unknown>) => (o ? `${k}:${JSON.stringify(o)}` : k),
    i18n: { language: 'en' } }),
}));

import { MonitoringPromptView } from './MonitoringPromptView';

const view = (over: Record<string, unknown> = {}) => renderToStaticMarkup(
  <MonitoringPromptView start="2026-11-18" busy={false} result={null} onActivate={() => {}} onSkip={() => {}} {...over} />);

describe('MonitoringPromptView', () => {
  it('asks with the local sowing date and offers both actions', () => {
    const h = view();
    expect(h).toContain('monitoring.title');
    expect(h).toContain('monitoring.body');
    expect(h).toContain('18');
    expect(h).toContain('monitoring.activate');
    expect(h).toContain('monitoring.skip');
  });
  it('busy disables activate', () => {
    expect(view({ busy: true })).toMatch(/id="monitoring-activate"[^>]*\sdisabled=""/);
  });
  it.each(['ok', 'pending', 'forbidden', 'error'])('shows the %s result', (r) => {
    expect(view({ result: r })).toContain(`monitoring.result.${r}`);
  });
});
