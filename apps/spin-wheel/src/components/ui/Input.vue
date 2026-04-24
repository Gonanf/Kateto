<script setup lang="ts">
import { cn } from '../../lib/utils';

const props = defineProps<{
  class?: string;
  modelValue?: string;
  placeholder?: string;
  type?: string;
}>();

const emit = defineEmits<{ (e: 'update:modelValue', value: string): void }>();

function onInput(event: Event) {
  emit('update:modelValue', (event.target as HTMLInputElement).value);
}
</script>

<template>
  <input
    :type="props.type || 'text'"
    :value="props.modelValue"
    :placeholder="props.placeholder"
    @input="onInput"
    :class="cn(
      'flex h-10 w-full rounded-md border border-slate-600 bg-slate-800 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500 disabled:cursor-not-allowed disabled:opacity-50',
      props.class
    )"
  />
</template>
