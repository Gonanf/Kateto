export interface WheelProps {
  items?: Array<{ label?: string; weight?: number; backgroundColor?: string }>;
  isInteractive?: boolean;
  radius?: number;
  rotationResistance?: number;
  itemLabelRadius?: number;
  itemLabelRadiusMax?: number;
  itemLabelRotation?: number;
  itemLabelAlign?: string;
  itemLabelColors?: string[];
  itemLabelBaselineOffset?: number;
  itemLabelFont?: string;
  itemLabelFontSizeMax?: number;
  itemBackgroundColors?: string[];
  rotationSpeedMax?: number;
  lineWidth?: number;
  lineColor?: string;
  pointerAngle?: number;
}

export interface WheelEvent {
  currentIndex: number;
}

export class Wheel {
  constructor(container: Element, props?: WheelProps);
  items: Array<{ label?: string; weight?: number; backgroundColor?: string }>;
  rotationSpeed: number;
  onRest?: (event: WheelEvent) => void;
  onSpin?: () => void;
  onCurrentIndexChange?: () => void;
  spin(rotationSpeed?: number): void;
  spinTo(rotation?: number, duration?: number, easingFunction?: (n: number) => number): void;
  spinToItem(
    itemIndex?: number,
    duration?: number,
    spinToCenter?: boolean,
    numberOfRevolutions?: number,
    direction?: number,
    easingFunction?: (n: number) => number
  ): void;
  stop(): void;
  remove(): void;
}
