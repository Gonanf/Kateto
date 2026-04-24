<script setup lang="ts">
import { cn } from '../../lib/utils';

const props = defineProps<{
  class?: string;
  variant?: 'default' | 'outline' | 'ghost' | 'destructive';
  size?: 'default' | 'sm' | 'lg';
  disabled?: boolean;
}>();

const variants = {
  default: 'bg-indigo-600 text-white hover:bg-indigo-700',
  outline: 'border border-slate-600 bg-transparent hover:bg-slate-800 text-slate-200',
  ghost: 'hover:bg-slate-800 text-slate-200',
  destructive: 'bg-red-600 text-white hover:bg-red-700'
};

const sizes = {
  default: 'h-10 px-4 py-2',
  sm: 'h-8 px-3 text-sm',
  lg: 'h-12 px-6 text-lg'
};
</script>

<template>
  <button
    :disabled="props.disabled"
    :class="cn(
      'inline-flex items-center justify-center rounded-md font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 disabled:pointer-events-none disabled:opacity-50',
      variants[props.variant || 'default'],
      sizes[props.size || 'default'],
      props.class
    )"
  >
    <slot />
  </button>
</template>
