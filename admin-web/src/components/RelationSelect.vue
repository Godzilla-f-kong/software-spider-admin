<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { api, type LookupOption } from '../api/client'
import { tr } from '../i18n'

const props = defineProps<{
  modelValue?: number | null
  resource: string
  filters?: Record<string, number | undefined>
  disabled?: boolean
  placeholder?: string
}>()
const emit = defineEmits<{ 'update:modelValue': [value: number | null] }>()
const options = ref<LookupOption[]>([])
const loading = ref(false)
let timer: ReturnType<typeof setTimeout> | undefined
let generation = 0

function mergeOptions(items: LookupOption[]): void {
  const selected = options.value.find(option => option.id === props.modelValue)
  options.value = selected && !items.some(option => option.id === selected.id) ? [selected, ...items] : items
}

async function search(query = ''): Promise<void> {
  const current = ++generation
  loading.value = true
  try {
    const items = await api.lookup(props.resource, { q: query, ...(props.filters ?? {}) })
    if (current === generation) mergeOptions(items)
  } finally {
    if (current === generation) loading.value = false
  }
}

async function loadSelected(value: number): Promise<void> {
  if (options.value.some(option => option.id === value)) return
  const items = await api.lookup(props.resource, { selected_id: value })
  if (props.modelValue === value && items.length) options.value = [...items, ...options.value.filter(option => option.id !== value)]
}

function remoteSearch(query: string): void {
  if (timer) clearTimeout(timer)
  timer = setTimeout(() => { void search(query) }, 250)
}

function change(value: unknown): void {
  emit('update:modelValue', value === '' || value === null || value === undefined ? null : Number(value))
}

function onVisibleChange(visible: boolean): void {
  if (visible) void search()
}

watch(() => JSON.stringify([props.resource, props.filters ?? {}]), () => {
  generation += 1
  options.value = []
  if (props.modelValue != null) void loadSelected(props.modelValue)
})
watch(() => props.modelValue, value => {
  if (value != null) void loadSelected(value)
}, { immediate: true })
onBeforeUnmount(() => { if (timer) clearTimeout(timer) })
</script>
<template>
  <el-select :model-value="modelValue ?? undefined" filterable remote clearable :remote-method="remoteSearch"
    :loading="loading" :disabled="disabled || !resource" :placeholder="placeholder || tr('搜索名称或版本后选择', 'Search by name or version')"
    style="width:100%" @update:model-value="change" @visible-change="onVisibleChange">
    <el-option v-for="option in options" :key="option.id" :label="option.label" :value="option.id" />
  </el-select>
</template>
