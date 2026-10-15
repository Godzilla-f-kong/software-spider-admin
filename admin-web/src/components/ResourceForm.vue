<script setup lang="ts">
import { ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { api, type Row } from '../api/client'
import type { ResourceConfig } from '../types/resources'
import { enumLabel, fieldLabel, resourceTitle, tr } from '../i18n'
import { relationResource } from '../types/relations'
import RelationSelect from './RelationSelect.vue'

const props = defineProps<{ config: ResourceConfig; modelValue: boolean; item?: Row | null; defaults?: Record<string, unknown>; locked?: Record<string, unknown> }>()
const emit = defineEmits<{ 'update:modelValue': [value: boolean]; saved: [] }>()
const form = ref<Record<string, unknown>>({})
const busy = ref(false)
function relationFilters(key: string): Record<string, number | undefined> {
  if ((key === 'release_id' || key === 'generated_content_id') && typeof form.value.software_id === 'number') {
    return { software_id: form.value.software_id }
  }
  return {}
}
function inputLabel(key: string, fallback: string): string {
  const relationLabels: Record<string, [string, string]> = {
    software_id: ['所属已抓取软件', 'Software'],
    release_id: ['关联软件版本', 'Software release'],
    variant_id: ['关联运行环境', 'Release platform'],
    artifact_id: ['关联安装包文件', 'Installer artifact'],
    generated_content_id: ['关联生成内容', 'Generated content'],
    target_id: ['任务目标记录', 'Job target'],
  }
  const label = relationLabels[key]
  return label ? tr(label[0], label[1]) : fieldLabel(key, fallback)
}
function updateRelation(key: string, value: number | null): void {
  if (key === 'software_id' && form.value.software_id !== value) {
    form.value.release_id = null
    form.value.generated_content_id = null
  }
  form.value[key] = value
}
watch(() => [props.modelValue, props.item?.id], () => {
  if (props.modelValue) form.value = { ...(props.defaults ?? {}), ...(props.item ?? {}) }
}, { immediate: true })

async function save() {
  for (const field of props.config.fields) {
    if (field.required && (form.value[field.key] === undefined || form.value[field.key] === null || form.value[field.key] === '')) {
      ElMessage.warning(tr(`请填写${field.label}`, `Please enter ${fieldLabel(field.key, field.label)}`))
      return
    }
  }
  const payload: Record<string, unknown> = {}
  for (const field of props.config.fields) {
    const value = form.value[field.key]
    if (value !== undefined) payload[field.key] = value === '' ? null : value
  }
  busy.value = true
  try {
    if (props.item) await api.update(props.config.path, props.item.id, payload)
    else await api.create(props.config.path, payload)
    ElMessage.success(tr('已保存', 'Saved'))
    emit('update:modelValue', false)
    emit('saved')
  } finally { busy.value = false }
}
</script>
<template>
  <el-dialog :model-value="modelValue" :title="`${item ? tr('编辑', 'Edit ') : tr('新增', 'Add ')}${resourceTitle(config)}`" width="620px" destroy-on-close @update:model-value="emit('update:modelValue', $event)">
    <el-form label-width="120px" size="default" class="resource-form">
      <el-form-item v-for="field in config.fields" :key="field.key" :label="inputLabel(field.key, field.label)" :required="field.required">
        <RelationSelect v-if="relationResource(field.key, form.target_type)" :model-value="typeof form[field.key] === 'number' ? Number(form[field.key]) : null" :resource="relationResource(field.key, form.target_type) || ''" :filters="relationFilters(field.key)" :disabled="locked?.[field.key] !== undefined" @update:model-value="updateRelation(field.key, $event)" />
        <el-select v-else-if="field.key === 'target_id'" disabled :placeholder="tr('先选择任务目标类型', 'Select a target type first')" style="width:100%" />
        <el-select v-else-if="field.type === 'select'" v-model="form[field.key]" :disabled="locked?.[field.key] !== undefined" clearable style="width:100%" @change="field.key === 'target_type' ? form.target_id = null : undefined"><el-option v-for="option in field.options" :key="option" :label="enumLabel(option)" :value="option" /></el-select>
        <el-switch v-else-if="field.type === 'switch'" v-model="form[field.key]" :disabled="locked?.[field.key] !== undefined" />
        <el-input-number v-else-if="field.type === 'number'" v-model="form[field.key]" :disabled="locked?.[field.key] !== undefined" :min="0" :controls="false" style="width:100%" />
        <el-date-picker v-else-if="field.type === 'date'" v-model="form[field.key]" :disabled="locked?.[field.key] !== undefined" type="date" value-format="YYYY-MM-DD" style="width:100%" />
        <el-input v-else v-model="form[field.key]" :disabled="locked?.[field.key] !== undefined" :type="field.type === 'textarea' ? 'textarea' : 'text'" :rows="field.type === 'textarea' ? 4 : 1" />
      </el-form-item>
    </el-form>
    <template #footer><el-button @click="emit('update:modelValue', false)">{{ tr('取消', 'Cancel') }}</el-button><el-button type="primary" :loading="busy" @click="save">{{ tr('保存', 'Save') }}</el-button></template>
  </el-dialog>
</template>
