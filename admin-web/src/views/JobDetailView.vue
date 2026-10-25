<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { api, type Row } from '../api/client'
import StatusTag from '../components/StatusTag.vue'
import { enumLabel, tr } from '../i18n'
import { formatBeijingTime } from '../utils/time'
const route = useRoute()
const job = ref<Row | null>(null)
const downloadJobs = ref<Row[]>([])
const id = computed(() => Number(route.params.id))
const automaticResult = computed(() => {
  const result = job.value?.result as Record<string, unknown> | null
  return result?.workflow === 'automatic_candidate_search' ? result : null
})
let timer: ReturnType<typeof setInterval> | undefined
async function load() {
  job.value = await api.get('jobs', id.value)
  if (job.value?.target_type === 'candidate_auto_search') {
    downloadJobs.value = (await api.list('jobs', { target_type: 'crawl_link_download', target_id: id.value, page_size: 100 })).items
  }
  const downloadsActive = downloadJobs.value.some(item => ['PENDING', 'RUNNING'].includes(String(item.status)))
  if (job.value && ['SUCCESS', 'FAILED', 'CANCELLED'].includes(String(job.value.status)) && !downloadsActive && timer) {
    clearInterval(timer)
    timer = undefined
  }
}
async function controlAutomaticSearch(action: 'pause' | 'resume' | 'retry'): Promise<void> {
  await api.action(`/crawl-pools/scans/${id.value}/${action}`)
  await load()
  if (action !== 'pause' && !timer) timer = setInterval(() => { void load() }, 1500)
  ElMessage.success(tr('任务状态已更新', 'Job updated'))
}
onMounted(() => { void load(); timer = setInterval(() => { void load() }, 1500) })
onUnmounted(() => { if (timer) clearInterval(timer) })
</script>
<template><div class="toolbar"><h1>{{ tr('后台任务', 'Background Job') }} #{{ id }}</h1><router-link to="/jobs">{{ tr('返回任务中心', 'Back to jobs') }}</router-link></div><div v-if="job" class="panel"><el-descriptions :column="2" border><el-descriptions-item :label="tr('类型', 'Type')">{{ enumLabel(job.job_type) }}</el-descriptions-item><el-descriptions-item :label="tr('状态', 'Status')"><StatusTag :value="String(job.status)" /></el-descriptions-item><el-descriptions-item :label="tr('目标', 'Target')">{{ job.target_label || job.target_type }} #{{ job.target_id }}</el-descriptions-item><el-descriptions-item :label="tr('进度', 'Progress')"><el-progress :percentage="Number(job.progress)" /></el-descriptions-item><el-descriptions-item :label="tr('已传输 / 总字节', 'Transferred / total bytes')">{{ job.bytes_downloaded ?? (job.result as Record<string, unknown> | null)?.bytes_uploaded ?? '—' }} / {{ job.total_bytes ?? '—' }}</el-descriptions-item><el-descriptions-item :label="tr('下载速度', 'Download speed')">{{ job.speed_bytes_per_second ?? '—' }} bytes/s</el-descriptions-item><el-descriptions-item :label="tr('消息', 'Message')">{{ job.message || '—' }}</el-descriptions-item><el-descriptions-item :label="tr('错误', 'Error')">{{ job.error_message || '—' }}</el-descriptions-item><el-descriptions-item :label="tr('创建', 'Created')">{{ formatBeijingTime(job.created_at) }}</el-descriptions-item><el-descriptions-item :label="tr('开始', 'Started')">{{ formatBeijingTime(job.started_at) }}</el-descriptions-item><el-descriptions-item :label="tr('完成', 'Finished')">{{ formatBeijingTime(job.finished_at) }}</el-descriptions-item></el-descriptions>
    <div v-if="job.target_type === 'candidate_auto_search'" style="margin-top:12px">
      <el-button v-if="['PENDING', 'RUNNING'].includes(String(job.status))" size="small" @click="controlAutomaticSearch('pause')">{{ tr('暂停任务', 'Pause job') }}</el-button>
      <el-button v-if="job.status === 'PAUSED'" size="small" type="primary" @click="controlAutomaticSearch('resume')">{{ tr('继续任务', 'Resume job') }}</el-button>
      <el-button v-if="job.status === 'FAILED'" size="small" type="primary" @click="controlAutomaticSearch('retry')">{{ tr('从断点重试', 'Retry from checkpoint') }}</el-button>
    </div>
    <template v-if="automaticResult">
      <h2>{{ tr('自动定向抓取结果', 'Automatic focused crawl results') }} · {{ automaticResult.candidate_name }}</h2>
      <el-alert v-if="automaticResult.current_pool" type="info" :closable="false" style="margin-bottom:12px" :title="`${tr('当前 URL 池', 'Current URL pool')} ${Number(automaticResult.current_pool_index) + 1}: ${automaticResult.current_pool}`" />
      <el-alert v-if="job.auto_download_processed" type="success" :closable="false" style="margin-bottom:12px" :title="`${tr('自动下载队列已处理', 'Automatic download queue processed')} · ${downloadJobs.length} ${tr('个链接任务', 'link jobs')}`" />
      <el-table v-if="downloadJobs.length" :data="downloadJobs" border stripe size="small" style="margin-bottom:12px">
        <el-table-column prop="id" label="ID" width="80" />
        <el-table-column :label="tr('发现链接', 'Discovered link')" min-width="240"><template #default="scope"><a :href="String((scope.row.payload as Record<string, unknown>)?.url || '')" target="_blank" rel="noopener noreferrer">{{ (scope.row.payload as Record<string, unknown>)?.url || '—' }}</a></template></el-table-column>
        <el-table-column prop="status" :label="tr('下载状态', 'Download status')" width="130"><template #default="scope"><StatusTag :value="String(scope.row.status)" /></template></el-table-column>
        <el-table-column :label="tr('进度', 'Progress')" width="160"><template #default="scope"><el-progress :percentage="Number(scope.row.progress || 0)" /></template></el-table-column>
        <el-table-column prop="message" :label="tr('结果', 'Result')" min-width="200" />
        <el-table-column prop="error_message" :label="tr('错误', 'Error')" min-width="200" />
        <el-table-column :label="tr('详情', 'Details')" width="90"><template #default="scope"><router-link :to="`/jobs/${scope.row.id}`">{{ tr('打开', 'Open') }}</router-link></template></el-table-column>
      </el-table>
      <el-table :data="(automaticResult.pool_results as Record<string, unknown>[] || [])" border stripe size="small">
        <el-table-column prop="pool_url" :label="tr('URL 抓取池', 'URL pool')" min-width="240" />
        <el-table-column prop="visited_pages" :label="tr('访问页面数', 'Pages visited')" width="110" />
        <el-table-column :label="tr('匹配结果', 'Matches')" width="100"><template #default="scope">{{ (scope.row.matches as unknown[] || []).length }}</template></el-table-column>
        <el-table-column prop="stop_reason" :label="tr('扫描结果', 'Scan outcome')" width="190" />
        <el-table-column prop="error" :label="tr('错误', 'Error')" min-width="180" />
      </el-table>
      <el-table v-if="(automaticResult.matches as Record<string, unknown>[] || []).length" :data="automaticResult.matches as Record<string, unknown>[]" border stripe size="small" style="margin-top:12px">
        <el-table-column type="expand"><template #default="scope">
          <el-table :data="(scope.row.artifacts as Record<string, unknown>[] || [])" size="small">
            <el-table-column prop="filename" :label="tr('文件名', 'Filename')" min-width="160" />
            <el-table-column prop="os" :label="tr('系统', 'OS')" width="100" />
            <el-table-column prop="architecture" :label="tr('架构', 'Architecture')" width="110" />
            <el-table-column prop="package_type" :label="tr('格式', 'Package')" width="100" />
            <el-table-column :label="tr('下载 URL', 'Download URL')" min-width="240"><template #default="file"><a :href="String(file.row.url)" target="_blank" rel="noopener noreferrer">{{ file.row.url }}</a></template></el-table-column>
          </el-table>
          <el-table v-if="(scope.row.links as Record<string, unknown>[] || []).length" :data="scope.row.links as Record<string, unknown>[]" size="small" style="margin-top:8px">
            <el-table-column prop="provider" :label="tr('网盘平台', 'Provider')" width="120" />
            <el-table-column :label="tr('分享链接', 'Share URL')" min-width="240"><template #default="link"><a :href="String(link.row.url)" target="_blank" rel="noopener noreferrer">{{ link.row.url }}</a></template></el-table-column>
            <el-table-column prop="access_code" :label="tr('提取码', 'Access code')" width="110" />
          </el-table>
        </template></el-table-column>
        <el-table-column prop="candidate_name" :label="tr('候选软件', 'Candidate')" width="160" />
        <el-table-column prop="page_title" :label="tr('发现页面', 'Discovered page')" min-width="180" />
        <el-table-column :label="tr('页面 URL', 'Page URL')" min-width="240"><template #default="scope"><a :href="String(scope.row.page_url)" target="_blank" rel="noopener noreferrer">{{ scope.row.page_url }}</a></template></el-table-column>
        <el-table-column :label="tr('版本', 'Versions')" width="130"><template #default="scope">{{ (scope.row.versions as string[] || []).join(', ') || '—' }}</template></el-table-column>
        <el-table-column prop="artifact_count" :label="tr('安装包候选', 'Artifact candidates')" width="130" />
        <el-table-column :label="tr('网盘链接', 'Share links')" width="100"><template #default="scope">{{ (scope.row.links as unknown[] || []).length }}</template></el-table-column>
        <el-table-column prop="match_status" :label="tr('匹配状态', 'Match status')" width="150"><template #default="scope"><StatusTag :value="String(scope.row.match_status)" /></template></el-table-column>
      </el-table>
      <el-alert v-if="automaticResult.stop_reason" type="info" :closable="false" style="margin-top:12px" :title="String(automaticResult.stop_reason)" />
    </template>
    <el-descriptions :column="1" border style="margin-top:12px"><el-descriptions-item label="Payload"><pre>{{ JSON.stringify(job.payload, null, 2) }}</pre></el-descriptions-item><el-descriptions-item label="Result"><pre>{{ JSON.stringify(job.result, null, 2) }}</pre></el-descriptions-item></el-descriptions>
  </div></template>
