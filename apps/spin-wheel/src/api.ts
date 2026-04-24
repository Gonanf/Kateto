import type { ApiState, SpinResult, SprintDocRequest, AppConfig, WheelItem } from './types.ts';

const API_BASE = '/api';

export async function getItems(): Promise<ApiState> {
  const res = await fetch(`${API_BASE}/items`);
  if (!res.ok) throw new Error('Failed to load items');
  return res.json();
}

export async function addItem(label: string): Promise<void> {
  const res = await fetch(`${API_BASE}/items/add`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ label })
  });
  if (!res.ok) throw new Error('Failed to add item');
}

export async function removeItem(id: string): Promise<void> {
  const res = await fetch(`${API_BASE}/items/${encodeURIComponent(id)}`, {
    method: 'DELETE'
  });
  if (!res.ok) throw new Error('Failed to remove item');
}

export async function resetUsed(): Promise<void> {
  const res = await fetch(`${API_BASE}/reset`, {
    method: 'POST'
  });
  if (!res.ok) throw new Error('Failed to reset items');
}

export async function recordSpin(winner: string): Promise<SpinResult> {
  const res = await fetch(`${API_BASE}/spin`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ winner })
  });
  if (!res.ok) throw new Error('Failed to record spin');
  return res.json();
}

export async function generateSprintDoc(feature: string): Promise<string> {
  const res = await fetch(`${API_BASE}/generate-sprint-doc`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ feature } satisfies SprintDocRequest)
  });
  if (!res.ok) throw new Error('Failed to generate sprint doc');
  const data = await res.json();
  return data.document;
}

export async function getConfig(): Promise<AppConfig> {
  const res = await fetch(`${API_BASE}/config`);
  if (!res.ok) throw new Error('Failed to load config');
  return res.json();
}

export async function setConfig(config: Partial<AppConfig>): Promise<void> {
  const res = await fetch(`${API_BASE}/config`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(config)
  });
  if (!res.ok) throw new Error('Failed to save config');
}
