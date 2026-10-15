<script setup lang="ts">
import { computed } from 'vue'
import { enumLabel } from '../i18n'
const props = defineProps<{ value: string | number | null | undefined }>()
const tone = computed(() => {
  const value = String(props.value ?? '')
  if (['FAILED', 'REJECTED', 'INVALID', 'REMOVED', 'DISCONNECTED', 'PROHIBITED'].includes(value)) return 'danger'
  if (['ACTIVE', 'READY', 'DIRECT_HTTP_READY', 'VERIFIED', 'AVAILABLE', 'APPROVED', 'PUBLISHED', 'SUCCESS', 'CONNECTED', 'ALLOWED', 'CONFIGURED', 'NEW', 'MATCHED'].includes(value)) return 'success'
  if (['PENDING', 'QUEUED', 'DISCOVERED', 'DRAFT', 'REVIEWING', 'REVIEW_REQUIRED', 'MANUAL_REVIEW', 'MANUAL_REQUIRED', 'PAUSED'].includes(value)) return 'warning'
  return 'info'
})
</script>
<template><el-tag :type="tone" size="small" effect="plain">{{ enumLabel(value) }}</el-tag></template>
