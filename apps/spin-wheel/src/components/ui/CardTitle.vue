<script setup lang="ts">
import { cn } from '../../lib/utils';

const props = defineProps<{
  class?: string;
}>();
</script>

<template>
  <h3 :class="cn('text-lg font-semibold leading-none tracking-tight text-slate-100', props.class)">
    <slot />
  </h3>
</template>
