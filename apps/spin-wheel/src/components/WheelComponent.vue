<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch } from 'vue';
import type { WheelItem } from '@/types';
import { initWheel, spinWheel, updateItems, destroyWheel } from '@/wheel';

const props = defineProps<{
  items: WheelItem[];
}>();

const emit = defineEmits<{ (e: 'rest', winnerIndex: number): void }>();

const containerRef = ref<HTMLElement | null>(null);
let initialized = false;

function onRest(index: number) {
  emit('rest', index);
}

onMounted(() => {
  if (containerRef.value) {
    initWheel(containerRef.value, props.items, onRest);
    initialized = true;
  }
});

onUnmounted(() => {
  destroyWheel();
  initialized = false;
});

watch(() => props.items, (newItems) => {
  if (initialized) {
    updateItems(newItems);
  } else if (containerRef.value) {
    initWheel(containerRef.value, newItems, onRest);
    initialized = true;
  }
}, { deep: true });

function doSpin() {
  spinWheel();
}

defineExpose({ spin: doSpin });
</script>

<template>
  <div ref="containerRef" class="w-full h-full min-h-[400px]" />
</template>
