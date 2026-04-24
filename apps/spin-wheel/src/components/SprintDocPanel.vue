<script setup lang="ts">
import Card from './ui/Card.vue';
import CardHeader from './ui/CardHeader.vue';
import CardTitle from './ui/CardTitle.vue';
import CardContent from './ui/CardContent.vue';
import Skeleton from './ui/Skeleton.vue';

const props = defineProps<{
  doc: string;
  loading: boolean;
}>();

</script>

<template>
  <Card>
    <CardHeader>
      <CardTitle>Kateto Product Owner</CardTitle>
    </CardHeader>
    <CardContent>
      <div v-if="props.loading" class="space-y-2">
        <Skeleton class="h-4 w-3/4" />
        <Skeleton class="h-4 w-1/2" />
        <Skeleton class="h-4 w-5/6" />
        <Skeleton class="h-4 w-2/3" />
      </div>
      <div v-else-if="props.doc" class="prose prose-invert max-w-none text-sm text-slate-200" v-html="props.doc" />
      <div v-else class="text-sm text-slate-500">
        Kateto Product Owner creara un documento a partir de la idea
      </div>
    </CardContent>
  </Card>
</template>
