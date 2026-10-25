<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { client } from '../api/client'
import { tr } from '../i18n'
import { formatBeijingTime } from '../utils/time'

interface Submission {
  id: number; software_name: string; provider: string | null; external_url: string; extract_code: string | null
  status: string; validation_errors: string[]; cloud_link: string | null; cloud_record_id: number | null
  cloud_reused: boolean | null; error_message: string | null; created_at: string | null
}
interface Page { items: Submission[]; total: number; page: number; page_size: number }

const rows = ref<Submission[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 20
const status = ref('')
const search = ref('')
const loading = ref(false)
const checking = ref(false)
const registering = ref(false)
const activeId = ref<number | null>(null)
const editVisible = ref(false)
const editingId = ref<number | null>(null)
const editForm = reactive({ software_name: '', external_url: '', extract_code: '' })
const statusLabels: Record<string, [string, string]> = {
  INCOMPLETE: ['信息不完整', 'Incomplete'], READY: ['可登记', 'Ready'], QUEUED: ['排队中', 'Queued'],
  RUNNING: ['登记中', 'Registering'], SUCCESS: ['已登记', 'Registered'], FAILED: ['登记失败', 'Failed'],
  UNKNOWN: ['结果待核对', 'Outcome unknown'],
}
function statusLabel(value: string): string {
  const labels = statusLabels[value] || [value, value]
  return tr(labels[0], labels[1])
}
function statusTone(value: string): 'success' | 'warning' | 'danger' | 'info' {
  if (value === 'SUCCESS') return 'success'
  if (value === 'FAILED') return 'danger'
  if (['INCOMPLETE', 'QUEUED', 'RUNNING', 'UNKNOWN'].includes(value)) return 'warning'
  return 'info'
}

async function load(): Promise<void> {
  loading.value = true
  try {
    const params: Record<string, string | number> = { page: page.value, page_size: pageSize }
    if (status.value) params.status = status.value
    if (search.value.trim()) params.search = search.value.trim()
    const result = (await client.get<Page>('/share-links', { params })).data
    rows.value = result.items
    total.value = result.total
  } finally { loading.value = false }
}

async function checkExisting(): Promise<void> {
  checking.value = true
  try {
    const result = (await client.post<{ scanned: number; ready: number; incomplete: number }>('/share-links/check')).data
    ElMessage.success(tr(`检查完成：扫描 ${result.scanned} 条，可登记 ${result.ready} 条，信息不完整 ${result.incomplete} 条`,
      `Check complete: ${result.scanned} scanned, ${result.ready} ready, ${result.incomplete} incomplete`))
    page.value = 1
    await load()
  } finally { checking.value = false }
}

async function registerReady(): Promise<void> {
  try {
    await ElMessageBox.confirm(tr('将完整的分享链接登记到局域网云盘，并创建永久分享记录。继续吗？',
      'Register complete share links in the local cloud drive as permanent shares?'),
    tr('确认登记', 'Confirm registration'), { type: 'warning' })
  } catch { return }
  registering.value = true
  try {
    const result = (await client.post<{ queued: number }>('/share-links/register-ready')).data
    ElMessage.success(tr(`已创建 ${result.queued} 个后台登记任务`, `${result.queued} registration jobs queued`))
    await load()
  } finally { registering.value = false }
}

async function registerOne(row: Submission): Promise<void> {
  activeId.value = row.id
  try {
    await client.post(`/share-links/${row.id}/register`)
    ElMessage.success(tr('登记任务已加入后台队列', 'Registration job queued'))
    await load()
  } finally { activeId.value = null }
}

function edit(row: Submission): void {
  editingId.value = row.id
  editForm.software_name = row.software_name
  editForm.external_url = row.external_url
  editForm.extract_code = row.extract_code || ''
  editVisible.value = true
}

async function saveEdit(): Promise<void> {
  if (editingId.value === null) return
  await client.patch(`/share-links/${editingId.value}`, { ...editForm })
  editVisible.value = false
  ElMessage.success(tr('链接信息已更新，请重新检查后登记', 'Link details saved. Recheck before registration.'))
  await load()
}

async function copy(value: string): Promise<void> {
  await navigator.clipboard.writeText(value)
  ElMessage.success(tr('已复制分享链接', 'Share URL copied'))
}

onMounted(() => { void load() })
</script>

<template>
  <div class="page-heading">
    <div><h1>{{ tr('云盘分享链接登记', 'Cloud share link registry') }}</h1>
      <p>{{ tr('把爬虫发现的网盘外链和提取码登记为局域网云盘永久分享记录；不会上传文件本体。', 'Register discovered cloud URLs and extraction codes as permanent local cloud shares. No file bytes are uploaded.') }}</p></div>
    <div class="toolbar">
      <el-button :loading="checking" @click="checkExisting">{{ tr('检查历史链接', 'Check historical links') }}</el-button>
      <el-button type="primary" :loading="registering" @click="registerReady">{{ tr('登记所有完整链接', 'Register all complete links') }}</el-button>
    </div>
  </div>
  <div class="panel">
    <div class="filters">
      <el-input v-model="search" clearable :placeholder="tr('搜索软件名或外链', 'Search software or URL')" @keyup.enter="page = 1; load()" />
      <el-select v-model="status" clearable :placeholder="tr('全部登记状态', 'All registration states')" @change="page = 1; load()">
        <el-option v-for="value in ['INCOMPLETE', 'READY', 'QUEUED', 'RUNNING', 'SUCCESS', 'FAILED', 'UNKNOWN']" :key="value" :label="statusLabel(value)" :value="value" />
      </el-select>
      <el-button @click="page = 1; load()">{{ tr('查询', 'Search') }}</el-button>
    </div>
    <el-table v-loading="loading" :data="rows" border stripe size="small">
      <el-table-column prop="software_name" :label="tr('软件名称', 'Software')" min-width="150" />
      <el-table-column prop="provider" :label="tr('原网盘', 'Source provider')" width="105" />
      <el-table-column :label="tr('原分享链接', 'Original share URL')" min-width="260"><template #default="scope"><a :href="scope.row.external_url" target="_blank" rel="noreferrer">{{ scope.row.external_url }}</a></template></el-table-column>
      <el-table-column prop="extract_code" :label="tr('提取码', 'Code')" width="90" />
      <el-table-column :label="tr('完整性 / 登记状态', 'Validation / status')" min-width="175"><template #default="scope"><el-tag :type="statusTone(scope.row.status)" size="small" effect="plain">{{ statusLabel(scope.row.status) }}</el-tag><div v-if="scope.row.validation_errors.length" class="error-hint">{{ scope.row.validation_errors.join('；') }}</div><div v-else-if="scope.row.error_message" class="error-hint">{{ scope.row.error_message }}</div></template></el-table-column>
      <el-table-column :label="tr('云盘生成的永久链接', 'Cloud permanent URL')" min-width="190"><template #default="scope"><template v-if="scope.row.cloud_link"><a :href="scope.row.cloud_link" target="_blank" rel="noreferrer">{{ scope.row.cloud_link }}</a><el-button link size="small" @click="copy(scope.row.cloud_link)">{{ tr('复制', 'Copy') }}</el-button><small v-if="scope.row.cloud_reused">{{ tr('复用了已有记录', 'Existing record reused') }}</small></template><span v-else>—</span></template></el-table-column>
      <el-table-column prop="created_at" :label="tr('登记时间', 'Created')" width="155"><template #default="scope">{{ scope.row.created_at ? formatBeijingTime(scope.row.created_at) : '—' }}</template></el-table-column>
      <el-table-column fixed="right" :label="tr('操作', 'Actions')" width="140"><template #default="scope"><el-button v-if="scope.row.status === 'INCOMPLETE'" link @click="edit(scope.row)">{{ tr('补全信息', 'Complete') }}</el-button><el-button v-if="['READY', 'FAILED', 'UNKNOWN'].includes(scope.row.status)" link type="primary" :loading="activeId === scope.row.id" @click="registerOne(scope.row)">{{ scope.row.status === 'READY' ? tr('登记', 'Register') : tr('重试', 'Retry') }}</el-button></template></el-table-column>
      <template #empty><el-empty :description="tr('暂无登记记录，请先检查历史抓取结果', 'No records. Check historical crawl results first.')" /></template>
    </el-table>
    <el-pagination v-model:current-page="page" :page-size="pageSize" :total="total" layout="total, prev, pager, next" style="justify-content:flex-end;margin-top:14px" @current-change="load" />
  </div>
  <el-dialog v-model="editVisible" :title="tr('补全网盘分享信息', 'Complete share link details')" width="560px">
    <el-form label-position="top">
      <el-form-item :label="tr('软件名称', 'Software name')"><el-input v-model="editForm.software_name" maxlength="255" /></el-form-item>
      <el-form-item :label="tr('外部网盘链接', 'External share URL')"><el-input v-model="editForm.external_url" maxlength="2048" /></el-form-item>
      <el-form-item :label="tr('四位分享码', 'Four-character share code')"><el-input v-model="editForm.extract_code" maxlength="64" /></el-form-item>
    </el-form>
    <template #footer><el-button @click="editVisible = false">{{ tr('取消', 'Cancel') }}</el-button><el-button type="primary" @click="saveEdit">{{ tr('保存', 'Save') }}</el-button></template>
  </el-dialog>
</template>

<style scoped>
.page-heading{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;margin-bottom:16px}.page-heading h1{margin:0}.page-heading p{margin:6px 0 0;color:var(--muted,#697586)}.toolbar,.filters{display:flex;align-items:center;gap:8px}.filters{margin-bottom:12px}.filters .el-input{max-width:320px}.filters .el-select{width:190px}.error-hint{font-size:12px;color:#b54708;margin-top:4px}.el-table a{word-break:break-all}.el-table small{display:block;color:var(--muted,#697586)}
</style>
