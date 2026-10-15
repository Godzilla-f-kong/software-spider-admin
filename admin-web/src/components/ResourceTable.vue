<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api, type Row } from '../api/client'
import { labels, type ResourceConfig } from '../types/resources'
import StatusTag from './StatusTag.vue'
import ResourceForm from './ResourceForm.vue'
import { enumLabel, fieldLabel, resourceTitle, tr } from '../i18n'
import { relationResource } from '../types/relations'
import RelationSelect from './RelationSelect.vue'
import DiscoveryDialog from './DiscoveryDialog.vue'
import { formatBeijingTime } from '../utils/time'

const props = defineProps<{ config: ResourceConfig; fixed?: Record<string, unknown>; defaults?: Record<string, unknown> }>()
const emit = defineEmits<{ loaded: [rows: Row[]]; imported: [] }>()
const router = useRouter()
const rows = ref<Row[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const search = ref('')
const filters = ref<Record<string, string | number | null>>({})
const loading = ref(false)
const dialog = ref(false)
const editing = ref<Row | null>(null)
const detail = ref<Row | null>(null)
const discovering = ref<Row | null>(null)
const discoveryDialogOpen = computed({ get: () => discovering.value !== null,
  set: (open: boolean) => { if (!open) discovering.value = null } })
const selectedSoftware = ref<Row[]>([])
const title = computed(() => resourceTitle(props.config))
const statusKeys = new Set(['status', 'automation_status', 'automatic_crawl_status', 'download_status', 'verification_status', 'signature_status'])
const enumKeys = computed(() => new Set(props.config.fields.filter(field => field.options).map(field => field.key)))
const filterKeys = computed(() => (props.config.filters ?? []).filter(key => props.fixed?.[key] === undefined))
function columnLabel(key: string): string {
  const custom = props.config.columnLabels?.[key]
  return custom ? tr(custom.zh, custom.en) : fieldLabel(key, labels[key])
}
function updateFilter(key: string, value: number | null): void {
  filters.value[key] = value
  page.value = 1
  void load()
}

async function load() {
  loading.value = true
  try {
    const response = await api.list(props.config.path, { page: page.value, page_size: pageSize.value, search: search.value || undefined, ...filters.value, ...(props.fixed ?? {}) })
    rows.value = response.items
    total.value = response.total
    emit('loaded', response.items)
  } finally { loading.value = false }
}
function edit(row: Row) { editing.value = row; dialog.value = true }
function add() { editing.value = null; dialog.value = true }
function selectionChange(items: Row[]): void { selectedSoftware.value = items }
function softwareSelectable(row: Row): boolean { return row.status === 'ACTIVE' }
function artifactSelectable(row: Row): boolean { return !row.local_exists && ['NOT_DOWNLOADED', 'FAILED'].includes(String(row.download_status)) }
async function artifactAction(row: Row, action: 'download' | 'redownload' | 'verify'): Promise<void> {
  if (action === 'redownload') await ElMessageBox.confirm(tr('重新下载会保留原文件，内容变化将等待人工审核。继续？', 'Re-download keeps the original; changed content requires review. Continue?'), tr('确认重新下载', 'Confirm re-download'))
  const job = await api.action(`/artifacts/${row.id}/${action}`)
  await load()
  await router.push(`/jobs/${job.id}`)
}
async function cancelArtifact(row: Row): Promise<void> {
  const jobs = (await api.list('jobs', { target_type: 'artifact', target_id: row.id, job_type: 'DOWNLOAD', page_size: 10 })).items
  const active = jobs.find(job => ['PENDING', 'RUNNING'].includes(String(job.status)))
  if (active) await api.action(`/jobs/${active.id}/cancel`)
  await load()
}
async function openLocalDirectory(row: Row): Promise<void> {
  await api.action(`/storage/${row.id}/open-local-directory`)
  ElMessage.success(tr('已在后端所在电脑打开本地目录', 'Opened the directory on the backend computer'))
}
async function checkRelease(row: Row): Promise<void> {
  const job = await api.action(`/software/${row.id}/check-release`)
  ElMessage.success(tr(`已创建版本检查任务 #${job.id}`, `Release check job #${job.id} created`))
  await router.push(`/jobs/${job.id}`)
}
async function bulkCheck(): Promise<void> {
  if (selectedSoftware.value.length > 50) {
    ElMessage.warning(tr('一次最多检查 50 个软件', 'Select at most 50 software records'))
    return
  }
  const response = await api.create('software/check-releases', { software_ids: selectedSoftware.value.map(row => row.id) })
  const jobs = response.jobs as Row[]
  ElMessage.success(tr(`已创建 ${jobs.length} 个版本检查任务`, `${jobs.length} release check jobs created`))
  await router.push('/jobs')
}
async function bulkDownload(): Promise<void> {
  const ids = selectedSoftware.value.filter(row => row.download_status === 'NOT_DOWNLOADED' || row.download_status === 'FAILED').map(row => row.id)
  if (!ids.length) return
  const response = await api.create('downloads/bulk', ids)
  const jobs = response.jobs as Row[]
  ElMessage.success(tr(`已创建 ${jobs.length} 个下载任务`, `${jobs.length} download jobs created`))
  await load()
  await router.push('/jobs')
}
function discoveryImported(): void { void load(); emit('imported') }
async function confirmAction(row: Row, action: 'accept' | 'reject' | 'archive') {
  const wording = action === 'accept' ? tr('接受并创建正式软件', 'accept this candidate and create software') : action === 'reject' ? tr('拒绝候选', 'reject this candidate') : tr('归档软件', 'archive this software')
  await ElMessageBox.confirm(tr(`确定${wording}？`, `Are you sure you want to ${wording}?`), tr('确认操作', 'Confirm action'), { type: 'warning' })
  let acceptedSoftwareId: number | null = null
  if (action === 'reject') await api.update('candidates', row.id, { status: 'REJECTED' })
  else {
    const result = await api.action(`/${props.config.path}/${row.id}/${action}`)
    if (action === 'accept') {
      acceptedSoftwareId = result.id
      ElMessage.success(tr(`已创建软件 #${result.id}，正在打开软件档案`, `Software #${result.id} created; opening its record`))
    }
  }
  if (action !== 'accept') ElMessage.success(tr('操作完成', 'Action completed'))
  await load()
  if (acceptedSoftwareId) await router.push(`/software/${acceptedSoftwareId}`)
}
function view(row: Row) {
  if (props.config.path === 'software') router.push(`/software/${row.id}`)
  else if (props.config.path === 'artifacts') router.push(`/artifacts/${row.id}`)
  else if (props.config.path === 'jobs') router.push(`/jobs/${row.id}`)
  else detail.value = row
}
function format(value: unknown): string {
  if (typeof value === 'string' && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(value)) return formatBeijingTime(value)
  if (value === null || value === undefined || value === '') return '—'
  if (typeof value === 'boolean') return value ? tr('是', 'Yes') : tr('否', 'No')
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}
watch(() => props.fixed, () => { page.value = 1; load() }, { deep: true })
let timer: ReturnType<typeof setInterval> | undefined
onMounted(() => { void load(); if (props.config.path === 'jobs' || props.config.path === 'candidates') timer = setInterval(() => { void load() }, 2000) })
onUnmounted(() => { if (timer) clearInterval(timer) })
</script>
<template>
  <section class="resource-surface">
    <el-alert v-if="config.path === 'candidates'" type="info" :closable="false" style="margin-bottom:12px" :title="tr('新增候选后会自动排队。系统按候选优先级逐个扫描全部已启用 URL 池；发现匹配资源后停止该候选并处理下一个。任务和结果可在任务中心查看。', 'New candidates are queued automatically. The system scans enabled URL pools one candidate at a time by priority, then moves to the next candidate after finding a match. View progress and results in Jobs.')" />
    <div class="toolbar"><h2>{{ title }}</h2><div class="toolbar-actions">
      <el-input v-if="config.search" v-model="search" :placeholder="tr('搜索', 'Search')" clearable style="width:190px" @keyup.enter="page = 1; load()" @clear="load" />
      <template v-for="key in filterKeys" :key="key"><RelationSelect v-if="relationResource(key)" :model-value="typeof filters[key] === 'number' ? Number(filters[key]) : null" :resource="relationResource(key) || ''" :placeholder="fieldLabel(key, labels[key])" style="width:210px" @update:model-value="updateFilter(key, $event)" /><el-select v-else-if="config.fields.find(f => f.key === key)?.options" v-model="filters[key]" :placeholder="fieldLabel(key, labels[key])" clearable style="width:150px" @change="page = 1; load()"><el-option v-for="option in config.fields.find(f => f.key === key)?.options" :key="option" :label="enumLabel(option)" :value="option" /></el-select><el-input v-else v-model="filters[key]" :placeholder="fieldLabel(key, labels[key])" clearable style="width:135px" @keyup.enter="page = 1; load()" @clear="load" /></template>
      <el-button @click="page = 1; load()">{{ tr('查询', 'Search') }}</el-button><el-button v-if="config.path === 'software'" :disabled="!selectedSoftware.length" @click="bulkCheck">{{ tr('批量检查版本', 'Bulk check releases') }}</el-button><el-button v-if="config.path === 'artifacts'" :disabled="!selectedSoftware.length" @click="bulkDownload">{{ tr('批量下载', 'Download selected') }}</el-button><el-button type="primary" @click="add">{{ tr('新增', 'Add') }}</el-button>
    </div></div>
    <el-table v-loading="loading" :data="rows" border stripe size="small" style="width:100%" @selection-change="selectionChange">
      <el-table-column v-if="config.path === 'software' || config.path === 'artifacts'" type="selection" :selectable="config.path === 'software' ? softwareSelectable : artifactSelectable" width="45" />
      <el-table-column v-for="key in config.columns" :key="key" :prop="key" :label="columnLabel(key)" :min-width="key === 'id' ? 95 : 110" show-overflow-tooltip>
        <template #default="scope"><router-link v-if="key === 'software_id' && scope.row[key]" :to="`/software/${scope.row[key]}`">#{{ scope.row[key] }}</router-link><span v-else-if="config.path === 'jobs' && key === 'target_id' && scope.row.target_label">{{ scope.row.target_label }} #{{ scope.row[key] }}</span><StatusTag v-else-if="statusKeys.has(key)" :value="scope.row[key]" /><span v-else-if="enumKeys.has(key)">{{ enumLabel(scope.row[key]) }}</span><span v-else>{{ format(scope.row[key]) }}</span></template>
      </el-table-column>
      <el-table-column :label="tr('操作', 'Actions')" fixed="right" min-width="160"><template #default="scope">
        <el-button link type="primary" @click="view(scope.row)">{{ tr('查看', 'View') }}</el-button>
        <el-button v-if="config.path !== 'jobs' && !(config.path === 'candidates' && scope.row.status === 'ACCEPTED')" link type="primary" @click="edit(scope.row)">{{ tr('编辑', 'Edit') }}</el-button>
        <el-button v-if="config.path === 'candidates' && scope.row.status !== 'ACCEPTED'" link type="success" @click="confirmAction(scope.row, 'accept')">{{ tr('接受', 'Accept') }}</el-button>
        <el-button v-if="config.path === 'candidates' && scope.row.status !== 'ACCEPTED' && scope.row.status !== 'REJECTED'" link type="danger" @click="confirmAction(scope.row, 'reject')">{{ tr('拒绝', 'Reject') }}</el-button>
        <el-button v-if="config.path === 'candidates' && scope.row.software_id" link type="primary" @click="router.push(`/software/${scope.row.software_id}`)">{{ tr('进入软件档案', 'Open software') }}</el-button>
        <el-button v-if="config.path === 'candidates' && scope.row.automatic_crawl_job_id" link type="primary" @click="router.push(`/jobs/${scope.row.automatic_crawl_job_id}`)">{{ tr('查看抓取任务', 'View crawl job') }}</el-button>
        <el-button v-if="config.path === 'software' && scope.row.status !== 'ARCHIVED'" link type="warning" @click="confirmAction(scope.row, 'archive')">{{ tr('归档', 'Archive') }}</el-button>
        <el-button v-if="config.path === 'software' && scope.row.status === 'ACTIVE'" link type="primary" @click="checkRelease(scope.row)">{{ tr('检查版本', 'Check release') }}</el-button>
        <el-button v-if="config.path === 'sources' && scope.row.enabled && scope.row.automation_status !== 'MANUAL_REQUIRED'" link type="primary" @click="discovering = scope.row">{{ tr('发现版本', 'Discover') }}</el-button>
        <el-button v-if="config.path === 'artifacts' && artifactSelectable(scope.row)" link type="primary" @click="artifactAction(scope.row, 'download')">{{ tr('下载', 'Download') }}</el-button>
        <el-button v-if="config.path === 'artifacts' && scope.row.local_exists && !['QUEUED', 'DOWNLOADING'].includes(String(scope.row.download_status)) && !(scope.row.staging_exists && scope.row.verification_status === 'MANUAL_REVIEW')" link type="primary" @click="artifactAction(scope.row, 'redownload')">{{ tr('重下', 'Re-download') }}</el-button>
        <el-button v-if="config.path === 'artifacts' && (scope.row.local_exists || scope.row.staging_exists) && scope.row.verification_status !== 'VERIFYING' && !['QUEUED', 'DOWNLOADING'].includes(String(scope.row.download_status))" link type="primary" @click="artifactAction(scope.row, 'verify')">{{ tr('验证', 'Verify') }}</el-button>
        <el-button v-if="config.path === 'artifacts' && ['QUEUED', 'DOWNLOADING'].includes(String(scope.row.download_status))" link type="danger" @click="cancelArtifact(scope.row)">{{ tr('取消', 'Cancel') }}</el-button>
        <el-button v-if="config.path === 'artifacts' && scope.row.verification_status === 'MANUAL_REVIEW'" link type="warning" @click="view(scope.row)">{{ tr('审核', 'Review') }}</el-button>
        <el-button v-if="config.path === 'storage' && scope.row.provider === 'LOCAL'" link type="primary" :disabled="!scope.row.local_exists" @click="openLocalDirectory(scope.row)">{{ tr('打开本地目录', 'Open local directory') }}</el-button>
      </template></el-table-column>
    </el-table>
    <el-pagination class="pagination" v-model:current-page="page" v-model:page-size="pageSize" :total="total" :page-sizes="[10, 20, 50, 100]" layout="total, sizes, prev, pager, next" @current-change="load" @size-change="page = 1; load()" />
    <ResourceForm v-model="dialog" :config="config" :item="editing" :defaults="{ ...(defaults ?? {}), ...(fixed ?? {}) }" :locked="fixed" @saved="load" />
    <DiscoveryDialog v-model="discoveryDialogOpen" :source="discovering" @imported="discoveryImported" />
    <el-dialog :model-value="detail !== null" :title="`${title} ${tr('详情', 'details')}`" width="660px" @update:model-value="detail = null"><el-descriptions v-if="detail" :column="1" border><el-descriptions-item v-for="(value, key) in detail" :key="key" :label="fieldLabel(String(key), labels[String(key)])">{{ enumKeys.has(String(key)) ? enumLabel(value) : format(value) }}</el-descriptions-item></el-descriptions></el-dialog>
  </section>
</template>
