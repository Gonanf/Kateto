import { Wheel } from 'spin-wheel';
import type { WheelItem } from './types.ts';

let wheel: Wheel | null = null;
let container: HTMLElement | null = null;

export function initWheel(
  el: HTMLElement,
  items: WheelItem[],
  onRest: (winnerIndex: number) => void
): void {
  container = el;
  const available = items.filter(i => !i.checked);

  wheel = new Wheel(el, {
    items: available.map(i => ({ label: i.label, weight: 1 })),
    isInteractive: true,
    radius: 0.7,
    rotationResistance: -35,
    itemLabelRadius: 0.92,
    itemLabelRadiusMax: 0.28,
    itemLabelRotation: 180,
    itemLabelAlign: 'left',
    itemLabelColors: ['#fff'],
    itemLabelBaselineOffset: -0.07,
    itemLabelFont:
      '"Inter", "Suez One", system-ui, sans-serif',
    itemLabelFontSizeMax: 44,
    itemBackgroundColors: [
      '#6366f1', '#8b5cf6', '#a855f7', '#d946ef',
      '#ec4899', '#f43f5e', '#e11d48', '#f97316',
      '#f59e0b', '#84cc16', '#10b981', '#06b6d4'
    ],
    rotationSpeedMax: 2000,
    lineWidth: 1,
    lineColor: '#ffffff20',
    pointerAngle: 270,
  });

  wheel.onRest = (event: { currentIndex: number }) => {
    onRest(event.currentIndex);
  };
}

export function spinWheel(): void {
  if (!wheel) return;
  wheel.spin(wheel.rotationSpeed + Math.floor(Math.random() * 600) + 800);
}

export function updateItems(items: WheelItem[]): void {
  if (!wheel) return;
  const available = items.filter(i => !i.checked);
  wheel.items = available.map(i => ({ label: i.label, weight: 1 }));
}

export function isSpinning(): boolean {
  return wheel ? wheel.rotationSpeed > 0.1 : false;
}

export function destroyWheel(): void {
  if (wheel) {
    wheel.remove();
    wheel = null;
  }
}
