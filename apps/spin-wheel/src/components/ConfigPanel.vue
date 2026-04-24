<script setup lang="ts">
import { ref, onMounted } from 'vue';
import type { AppConfig } from '@/types';
import { getConfig, setConfig } from '@/api';
import Button from './ui/Button.vue';
import Input from './ui/Input.vue';
import Card from './ui/Card.vue';
import CardHeader from './ui/CardHeader.vue';
import CardTitle from './ui/CardTitle.vue';
import CardContent from './ui/CardContent.vue';
import { CogIcon } from '@lucide/vue';

const availability = ref('');
const teamPersons = ref('');
const saving = ref(false);
const saved = ref(false);

onMounted(async () => {
  try {
    const cfg = await getConfig();
    availability.value = cfg.availability;
    teamPersons.value = cfg.teamPersons.join(', ');
  } catch {
    // ignore
  }
});

async function onSave() {
  saving.value = true;
  saved.value = false;
  try {
    await setConfig({
      availability: availability.value,
      teamPersons: teamPersons.value.split(',').map(s => s.trim()).filter(Boolean)
    });
    saved.value = true;
  } catch {
    // ignore
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <Card>
    <CardHeader>
      <CardTitle class="flex items-center gap-6">
        <CogIcon size="32" />
        Configuracion
      </CardTitle>
    </CardHeader>
    <CardContent>
      <div class="space-y-3">
        <div>
          <label class="block text-xs font-medium text-slate-400 mb-1">Disponibilidad</label>
          <Input v-model="availability" placeholder="ej: full time, part time" />
        </div>
        <div>
          <label class="block text-xs font-medium text-slate-400 mb-1">Equipo (separado por comas)</label>
          <Input v-model="teamPersons" placeholder="ej: Chaos, Kira, Miguel" />
        </div>
        <div class="flex items-center gap-2">
          <Button size="sm" :disabled="saving" @click="onSave">Guardar</Button>
          <span v-if="saved" class="text-xs text-green-400">Guardado!</span>
        </div>
      </div>
    </CardContent>
  </Card>
</template>
