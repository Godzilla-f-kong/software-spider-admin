<script setup lang="ts">
import { computed } from 'vue'
import ResourceTable from '../components/ResourceTable.vue'
import { resources } from '../types/resources'
defineOptions({ name: 'ResourceView' })
const props = defineProps<{ name: string }>()
const actual = computed(() => props.name === 'publishing' ? 'listings' : props.name === 'downloads' ? 'jobs' : props.name)
const config = computed(() => props.name === 'downloads' ? { ...resources.jobs, title: '下载任务' } : resources[actual.value])
const fixed = computed(() => props.name === 'downloads' ? { job_type: 'DOWNLOAD' } : {})
</script>
<template><ResourceTable v-if="config" :key="name" :config="config" :fixed="fixed" /></template>
