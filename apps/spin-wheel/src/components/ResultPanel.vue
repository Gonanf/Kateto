<script setup lang="ts">
import Card from './ui/Card.vue';
import CardHeader from './ui/CardHeader.vue';
import CardTitle from './ui/CardTitle.vue';
import CardContent from './ui/CardContent.vue';
import { CrownIcon, TrophyIcon } from '@lucide/vue';

const props = defineProps<{
  winner: string | null;
}>();
</script>

<template>
  <Card>
    <CardHeader>
      <CardTitle class="flex items-center gap-6">
        <TrophyIcon size="32" /> Resultado
      </CardTitle>
    </CardHeader>
    <CardContent>
      <div v-if="props.winner" class="text-xl font-bold text-indigo-400 flex items-center justify-center gap-6">
        <CrownIcon size="16" /> {{ props.winner }}
      </div>
      <div v-else class="text-sm text-slate-500">
        Gira la rueda para elegir una idea
      </div>
    </CardContent>
  </Card>
</template>
