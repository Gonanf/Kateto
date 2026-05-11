<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed } from 'vue';
import type { WheelItem } from './types';
import { getItems, addItem, removeItem, resetUsed, recordSpin, generateSprintDoc } from './api';
import WheelComponent from './components/WheelComponent.vue';
import ItemsPanel from './components/ItemsPanel.vue';
import ResultPanel from './components/ResultPanel.vue';
import SprintDocPanel from './components/SprintDocPanel.vue';
import ConfigPanel from './components/ConfigPanel.vue';
import Button from './components/ui/Button.vue';
import { TargetIcon } from '@lucide/vue';

const items = ref<WheelItem[]>([]);
const winner = ref<string | null>(null);
const sprintDoc = ref('');
const sprintLoading = ref(false);
const isProcessing = ref(false);
const pendingWinner = ref<string | null>(null);
const wheelRef = ref<InstanceType<typeof WheelComponent> | null>(null);

const availableItems = computed(() => items.value.filter(i => !i.checked));
const hasPending = computed(() => pendingWinner.value !== null);
const canSpin = computed(() => availableItems.value.length > 0 && !isProcessing.value && !hasPending.value);

async function loadItems() {
  try {
    const state = await getItems();
    items.value = state.items;
  } catch (err) {
    console.error('Failed to load items:', err);
  }
}

function handleSpinRest(winnerIndex: number) {
  const avail = availableItems.value;
  const win = avail[winnerIndex];
  if (!win) return;

  winner.value = win.label;
  pendingWinner.value = win.label;
}

async function onConfirm() {
  const label = pendingWinner.value;
  if (!label) return;

  pendingWinner.value = null;
  isProcessing.value = true;

  try {
    const spinResult = await recordSpin(label);
    items.value = items.value.map(i => i.label === label ? { ...i, checked: true } : i);

    if (spinResult.remaining === 0) return;

    sprintDoc.value = '';
    sprintLoading.value = true;
    const doc = await generateSprintDoc(label);
    sprintDoc.value = doc;
  } catch (err) {
    console.error('Spin processing failed:', err);
    sprintDoc.value = 'No se pudo generar el documento.';
  } finally {
    sprintLoading.value = false;
    isProcessing.value = false;
  }
}

function doSpin() {
  if (isProcessing.value || !canSpin.value) return;
  wheelRef.value?.spin();
}

async function onAddItem(label: string) {
  try {
    await addItem(label);
    await loadItems();
  } catch (err) {
    console.error('Failed to add item:', err);
  }
}

async function onRemoveItem(id: string) {
  try {
    await removeItem(id);
    await loadItems();
  } catch (err) {
    console.error('Failed to remove item:', err);
  }
}

async function onReset() {
  pendingWinner.value = null;
  try {
    await resetUsed();
    items.value = items.value.map(i => ({ ...i, checked: false }));
    winner.value = null;
    sprintDoc.value = '';
  } catch (err) {
    console.error('Failed to reset:', err);
  }
}

onMounted(() => {
  loadItems();

  const onKeydown = (e: KeyboardEvent) => {
    if (e.code === 'Space' || e.code === 'KeyS') {
      const active = document.activeElement;
      if (active && (active.tagName === 'INPUT' || active.tagName === 'TEXTAREA')) return;
      e.preventDefault();
      doSpin();
    }
  };
  document.addEventListener('keydown', onKeydown);

  const cleanup = () => document.removeEventListener('keydown', onKeydown);
  onUnmounted(cleanup);

  window.wheelAPI = {
    spin: doSpin,
    getItems: () => items.value,
    setItems: async (labels: string[]) => {
      items.value = labels.map((l, idx) => ({ id: String(idx), label: l, checked: false }));
      winner.value = null;
      sprintDoc.value = '';
    },
    addItem: async (label: string) => {
      await onAddItem(label);
    },
    removeItem: async (index: number) => {
      const item = items.value[index];
      if (item) await onRemoveItem(item.id);
    },
    resetUsed: onReset,
    isSpinning: () => false // simplified; wheel library doesn't expose this cleanly from here
  };
});
</script>

<template>
  <div class="min-h-screen bg-transparent text-[#e4e6eb]">
    <header class="text-center py-6">
      <h1 class="text-3xl font-bold tracking-tight flex justify-center gap-6 items-center">
        <TargetIcon size="48" /> Carrera Armamentistica
      </h1>
      <p class="text-sm text-slate-400 mt-1">Gira para empezar el JUICIOOOOOOOOO</p>
    </header>

    <div class="max-w-7xl mx-auto px-4 pb-10">
      <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <!-- Wheel Section -->
        <div class="lg:col-span-2 space-y-4">
          <div class="rounded-xl border border-slate-700 bg-slate-800/50 p-4">
            <div class="relative w-full aspect-square max-h-[600px]">
              <WheelComponent ref="wheelRef" :items="items" @rest="handleSpinRest" />
            </div>
          </div>
          <div class="flex gap-3 justify-center">
            <Button size="lg" :disabled="!canSpin" @click="doSpin">Girar!</Button>
            <Button v-if="hasPending" variant="default" size="lg" @click="onConfirm">Confirmar</Button>
            <Button variant="outline" size="lg" @click="onReset">{{ hasPending ? 'Cancelar' : 'Resetear' }}</Button>
          </div>
          <div class="text-center text-xs text-slate-500">
            O apreta <kbd class="px-1 py-0.5 rounded bg-slate-700 text-slate-300 text-[10px]">Space</kbd> o <kbd
              class="px-1 py-0.5 rounded bg-slate-700 text-slate-300 text-[10px]">S</kbd> para girar
          </div>
        </div>

        <!-- Sidebar -->
        <div class="space-y-4">
          <ItemsPanel :items="items" @add="onAddItem" @remove="onRemoveItem" />
          <ResultPanel :winner="winner" />
          <SprintDocPanel :doc="sprintDoc" :loading="sprintLoading" />
          <ConfigPanel />
        </div>
      </div>
    </div>
  </div>
</template>
