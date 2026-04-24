<script setup lang="ts">
import { cn } from '../../lib/utils';

const props = defineProps<{
  class?: string;
}>();
</script>

<template>
  <div :class="cn('animate-pulse rounded-md bg-slate-700', props.class)">
    <slot />
  </div>
</template>
