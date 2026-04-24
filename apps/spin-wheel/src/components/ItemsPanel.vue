<script setup lang="ts">
import { ref } from 'vue';
import type { WheelItem } from '@/types';
import Button from './ui/Button.vue';
import Input from './ui/Input.vue';
import Card from './ui/Card.vue';
import CardHeader from './ui/CardHeader.vue';
import CardTitle from './ui/CardTitle.vue';
import CardContent from './ui/CardContent.vue';
import { NotepadTextDashedIcon } from '@lucide/vue';

const props = defineProps<{
  items: WheelItem[];
}>();

const emit = defineEmits<{
  (e: 'add', label: string): void;
  (e: 'remove', id: string): void;
}>();

const newLabel = ref('');

function onAdd() {
  const label = newLabel.value.trim();
  if (!label) return;
  emit('add', label);
  newLabel.value = '';
}

function onRemove(id: string) {
  emit('remove', id);
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter') onAdd();
}
</script>

<template>
  <Card>
    <CardHeader>
      <CardTitle class="flex items-center gap-6">
        <NotepadTextDashedIcon size="32" /> Items
      </CardTitle>
    </CardHeader>
    <CardContent>
      <div class="space-y-2 max-h-[300px] overflow-y-auto pr-1">
        <div v-for="item in props.items" :key="item.id" :class="[
          'flex items-center justify-between rounded-md px-3 py-2',
          item.checked ? 'bg-slate-700/50 line-through text-slate-500' : 'bg-slate-700'
        ]">
          <span class="text-sm text-slate-200">{{ item.label }}</span>
          <button class="text-slate-400 hover:text-red-400 transition-colors text-lg leading-none px-1"
            @click="onRemove(item.id)" title="Quitar">
            ×
          </button>
        </div>
        <div v-if="props.items.length === 0" class="text-sm text-slate-500 italic">
          No hay items.
        </div>
      </div>
      <div class="mt-3 flex gap-2">
        <Input v-model="newLabel" placeholder="Añadir nueva idea..." class="flex-1" @keydown="onKeydown" />
        <Button size="sm" @click="onAdd">Añadir</Button>
      </div>
    </CardContent>
  </Card>
</template>
