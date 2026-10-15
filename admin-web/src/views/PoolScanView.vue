<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { api, type Row } from '../api/client'
import StatusTag from '../components/StatusTag.vue'
import { tr } from '../i18n'

interface Match {
  candidate_id: number
  candidate_name: string
  page_url: string
  page_title: string
  versions: string[]
  artifact_count: number
  link_count: number
  warnings: string[]
  match_status: string
  page_role: string
  relevance_score: number
  target_version?: string | null
  target_os?: string | null
  target_architecture?: string | null
  artifacts?: { filename: string; url: string; os: string; architecture: string; package_type: string; target_match: boolean }[]
  links?: { url: string; provider: string; access_code: string | null }[]
}
interface ScanResult {
  pool_url: string
  visited_pages: number
  queued_pages: number
  matches: Match[]
  warnings: string[]
  limit_reached: boolean
  stop_reason?: string
  strategies?: Record<string, number>
  page_roles?: Record<string, number>
}

const route = useRoute()
const router = useRouter()
const job = ref<Row | null>(null)
const result = ref<ScanResult | null>(null)
const busy = ref<number | null>(null)
let timer: ReturnType<typeof setInterval> | undefined
function startPolling(): void { if (!timer) timer = setInterval(() => { void load() }, 1500) }

async function load(): Promise<void> {
  job.value = await api.get('jobs', Number(route.params.id))
  result.value = (job.value.result as ScanResult | null) ?? null
  if (['SUCCESS', 'FAILED', 'CANCELLED'].includes(String(job.value.status)) && timer) {
    clearInterval(timer)
    timer = undefined
  }
}

async function createSource(match: Match): Promise<void> {
  if (!job.value) return
  busy.value = match.candidate_id
  try {
    const candidate = await api.get('candidates', match.candidate_id)
    if (candidate.status !== 'ACCEPTED' || !candidate.software_id) {
      ElMessage.warning(tr('请先在软件候选池接受该候选，再建立软件来源', 'Accept this candidate before creating a catalog source'))
      return
    }
    const source = await api.create(`crawl-pools/${job.value.target_id}/scans/${job.value.id}/create-source`, {
      candidate_id: match.candidate_id, page_url: match.page_url,
    })
    ElMessage.success(tr(`已建立软件来源 #${source.id}`, `Catalog source #${source.id} created`))
    await router.push(`/software/${candidate.software_id}?tab=sources`)
  } finally { busy.value = null }
}

async function changeScan(action: 'pause' | 'resume' | 'retry'): Promise<void> {
  if (!job.value) return
  await api.action(`/crawl-pools/scans/${job.value.id}/${action}`)
  await load()
  if (action === 'resume' || action === 'retry') startPolling()
}

onMounted(() => { void load(); startPolling() })
onUnmounted(() => { if (timer) clearInterval(timer) })
</script>

<template>
  <div class="toolbar"><h1>{{ tr('URL 池扫描结果', 'URL pool scan result') }} #{{ route.params.id }}</h1>
    <router-link to="/crawl-pools">{{ tr('返回 URL 抓取池', 'Back to URL crawl pool') }}</router-link></div>
  <div v-if="job" class="panel">
    <StatusTag :value="String(job.status)" /> {{ job.message }}
    <el-button v-if="['PENDING', 'RUNNING'].includes(String(job.status))" size="small" @click="changeScan('pause')">{{ tr('暂停', 'Pause') }}</el-button>
    <el-button v-if="job.status === 'PAUSED'" size="small" type="primary" @click="changeScan('resume')">{{ tr('续扫', 'Resume') }}</el-button>
    <el-button v-if="job.status === 'FAILED'" size="small" type="primary" @click="changeScan('retry')">{{ tr('重试', 'Retry') }}</el-button>
    <el-progress :percentage="Number(job.progress)" />
    <el-alert v-if="job.error_message" type="error" :title="String(job.error_message)" :closable="false" />
  </div>
  <div v-if="result" class="panel">
    <p>{{ tr('站点', 'Website') }}：{{ result.pool_url }} · {{ tr('已访问页面', 'Pages visited') }}：{{ result.visited_pages }} · {{ tr('匹配候选页面', 'Matched candidate pages') }}：{{ result.matches.length }}</p>
    <p>{{ tr('停止原因', 'Stop reason') }}：{{ result.stop_reason || '—' }} · {{ tr('搜索策略', 'Strategies') }}：{{ JSON.stringify(result.strategies || {}) }}</p>
    <el-alert v-if="result.limit_reached" type="info" :title="tr('已达到本轮请求预算；点击“续扫”从断点继续。', 'Request budget reached; click Resume to continue from the checkpoint.')" :closable="false" style="margin-bottom:12px" />
    <el-table :data="result.matches" border stripe size="small">
      <el-table-column type="expand"><template #default="scope">
        <el-table :data="scope.row.artifacts || []" size="small">
          <el-table-column prop="filename" :label="tr('安装包', 'Installer')" min-width="180" />
          <el-table-column prop="os" :label="tr('系统', 'OS')" width="100" />
          <el-table-column prop="architecture" :label="tr('架构', 'Architecture')" width="110" />
          <el-table-column prop="package_type" :label="tr('格式', 'Package')" width="100" />
          <el-table-column :label="tr('目标匹配', 'Target match')" width="110"><template #default="file">{{ file.row.target_match ? tr('是', 'Yes') : tr('待确认', 'Review') }}</template></el-table-column>
          <el-table-column :label="tr('下载来源', 'Download source')" min-width="220"><template #default="file"><a :href="file.row.url" target="_blank" rel="noopener noreferrer">{{ file.row.url }}</a></template></el-table-column>
        </el-table>
        <el-table v-if="scope.row.links?.length" :data="scope.row.links" size="small" style="margin-top:8px">
          <el-table-column prop="provider" :label="tr('网盘 / 入口', 'Provider')" width="120" />
          <el-table-column :label="tr('来源链接', 'Source link')" min-width="240"><template #default="link"><a :href="link.row.url" target="_blank" rel="noopener noreferrer">{{ link.row.url }}</a></template></el-table-column>
          <el-table-column prop="access_code" :label="tr('提取码', 'Access code')" width="110" />
        </el-table>
      </template></el-table-column>
      <el-table-column :label="tr('候选软件', 'Candidate')" min-width="150"><template #default="scope"><router-link :to="`/candidates`">{{ scope.row.candidate_name }} #{{ scope.row.candidate_id }}</router-link></template></el-table-column>
      <el-table-column :label="tr('匹配页面', 'Matched page')" min-width="260" show-overflow-tooltip><template #default="scope"><a :href="scope.row.page_url" target="_blank" rel="noopener noreferrer">{{ scope.row.page_url }}</a></template></el-table-column>
      <el-table-column prop="page_title" :label="tr('页面标题', 'Page title')" min-width="180" show-overflow-tooltip />
      <el-table-column prop="page_role" :label="tr('页面类型', 'Page role')" width="120" />
      <el-table-column :label="tr('匹配状态', 'Match')" width="150"><template #default="scope"><StatusTag :value="scope.row.match_status || 'REVIEW_REQUIRED'" /></template></el-table-column>
      <el-table-column prop="relevance_score" :label="tr('相关性', 'Relevance')" width="90" />
      <el-table-column :label="tr('目标条件', 'Target')" min-width="160"><template #default="scope">{{ [scope.row.target_version, scope.row.target_os, scope.row.target_architecture].filter(Boolean).join(' / ') || '—' }}</template></el-table-column>
      <el-table-column :label="tr('版本', 'Versions')" min-width="100"><template #default="scope">{{ scope.row.versions.join(', ') || '—' }}</template></el-table-column>
      <el-table-column prop="artifact_count" :label="tr('文件数', 'Artifacts')" width="85" />
      <el-table-column prop="link_count" :label="tr('入口数', 'Links')" width="85" />
      <el-table-column :label="tr('操作', 'Actions')" width="170"><template #default="scope"><el-button link type="primary" :disabled="!['SUCCESS', 'PAUSED'].includes(String(job?.status))" :loading="busy === scope.row.candidate_id" @click="createSource(scope.row)">{{ tr('建立软件来源', 'Create catalog source') }}</el-button></template></el-table-column>
    </el-table>
    <el-alert v-for="warning in result.warnings" :key="warning" type="warning" :title="warning" :closable="false" style="margin-top:8px" />
  </div>
</template>
