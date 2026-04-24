export interface WheelItem {
  id: string;
  label: string;
  checked: boolean;
}

export interface SpinResult {
  winner: string;
  remaining: number;
}

export interface SprintDocRequest {
  feature: string;
}

export interface ApiState {
  items: WheelItem[];
}

export interface AppConfig {
  availability: string;
  teamPersons: string[];
}

export interface WindowAPI {
  spin: () => void;
  getItems: () => WheelItem[];
  setItems: (items: string[]) => Promise<void>;
  addItem: (label: string) => Promise<void>;
  removeItem: (index: number) => Promise<void>;
  resetUsed: () => Promise<void>;
  isSpinning: () => boolean;
}

declare global {
  interface Window {
    wheelAPI: WindowAPI;
  }
}
