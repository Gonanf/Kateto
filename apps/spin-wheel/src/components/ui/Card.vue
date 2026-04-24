<script setup lang="ts">
import { cn } from '../../lib/utils';

const props = defineProps<{
  class?: string;
}>();
</script>

<template>
  <div :class="cn('rounded-xl border border-slate-700 bg-slate-800 text-slate-100 shadow', props.class)">
    <slot />
  </div>
</template>
