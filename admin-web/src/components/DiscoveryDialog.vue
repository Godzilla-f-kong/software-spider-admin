<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { api, type Row } from '../api/client'
import StatusTag from './StatusTag.vue'
import { enumLabel, tr } from '../i18n'

interface ArtifactCandidate {
  filename: string; os: string; architecture: string; package_type: string
  file_size: number | null; download_url: string; status: string
}
interface DownloadLinkCandidate {
  link_url: string; provider: string; link_type: string; access_code: string | null
  context_text: string | null; status: string
}
interface ReleaseCandidate {
  version: string | null; release_date: string | null; is_prerelease: boolean
  status: string; artifacts: ArtifactCandidate[]; links: DownloadLinkCandidate[]
}
interface DiscoveryResult { releases: ReleaseCandidate[]; warnings: string[]; errors: string[] }
const props = defineProps<{ modelValue: boolean; source: Row | null }>()
const emit = defineEmits<{ 'update:modelValue': [value: boolean]; imported: [] }>()
const job = ref<Row | null>(null)
const importing = ref<Row | null>(null)
const discovery = ref<DiscoveryResult | null>(null)
const versionOverrides = ref<Record<number, string>>({})
let timer: ReturnType<typeof setInterval> | undefined
const files = computed(() => discovery.value?.releases.flatMap(release =>
  release.artifacts.map(artifact => ({ ...artifact, version: release.version ?? '—' }))) ?? [])
const links = computed(() => discovery.value?.releases.flatMap(release =>
  (release.links ?? []).map(link => ({ ...link, version: release.version ?? '-' }))) ?? [])
const importable = computed(() => discovery.value?.releases.some((release, index) =>
  (release.links?.length ?? 0) > 0 || !!(release.version || versionOverrides.value[index]?.trim())) ?? false)

function stopPolling(): void { if (timer) clearInterval(timer); timer = undefined }
async function poll(id: number, stage: 'preview' | 'import'): Promise<void> {
  let current: Row
  try { current = await api.get('jobs', id) }
  catch { stopPolling(); return }
  if (stage === 'preview') job.value = current
  else importing.value = current
  if (current.status === 'SUCCESS' || current.status === 'FAILED') {
    stopPolling()
    if (stage === 'preview' && current.status === 'SUCCESS') {
      const result = current.result as { discovery?: DiscoveryResult } | null
      discovery.value = result?.discovery ?? null
    }
    if (stage === 'import' && current.status === 'SUCCESS') {
      ElMessage.success(tr('发现结果已导入', 'Discovery imported'))
      emit('imported')
    }
  }
}
function startPolling(id: number, stage: 'preview' | 'import'): void {
  stopPolling()
  void poll(id, stage)
  timer = setInterval(() => { void poll(id, stage) }, 1200)
}
async function preview(): Promise<void> {
  if (!props.source) return
  discovery.value = null
  versionOverrides.value = {}
  importing.value = null
  try { job.value = await api.action(`/sources/${props.source.id}/discover/preview`) }
  catch { return }
  startPolling(job.value.id, 'preview')
}
async function importAll(): Promise<void> {
  if (!props.source || !job.value) return
  try { importing.value = await api.create(`sources/${props.source.id}/discover/import`, { preview_job_id: job.value.id,
    version_overrides: versionOverrides.value }) }
  catch { return }
  startPolling(importing.value.id, 'import')
}
watch(() => [props.modelValue, props.source?.id], ([open]) => {
  if (open) void preview()
  else stopPolling()
})
onBeforeUnmount(stopPolling)
</script>
<template>
  <el-dialog :model-value="modelValue" :title="tr('来源发现预览', 'Source discovery preview')" width="960px" @update:model-value="emit('update:modelValue', $event)">
    <div v-if="source" style="margin-bottom:12px;word-break:break-all">#{{ source.id }} · {{ source.source_url }} · {{ enumLabel(source.adapter_type) }}</div>
    <div v-if="job" style="margin-bottom:12px">
      <StatusTag :value="String(job.status)" /> {{ job.message }}
      <el-progress :percentage="Number(job.progress)" />
      <el-alert v-if="job.error_message" type="error" :title="String(job.error_message)" show-icon :closable="false" />
    </div>
    <template v-if="discovery">
      <h3>{{ tr('\u7f51\u76d8\u4e0e\u4e0b\u8f7d\u5165\u53e3', 'Cloud shares and download links') }} ({{ links.length }})</h3>
      <el-table :data="links" border size="small" max-height="280">
        <el-table-column prop="version" :label="tr('\u7248\u672c', 'Version')" width="100" />
        <el-table-column prop="provider" :label="tr('\u5e73\u53f0', 'Provider')" width="100" />
        <el-table-column prop="link_url" label="URL" min-width="260" show-overflow-tooltip />
        <el-table-column prop="access_code" :label="tr('\u8bbf\u95ee\u7801', 'Access code')" width="100" />
        <el-table-column prop="context_text" :label="tr('\u9875\u9762\u6587\u6848', 'Page text')" min-width="180" show-overflow-tooltip />
        <el-table-column :label="tr('\u72b6\u6001', 'Status')" width="100"><template #default="scope"><StatusTag :value="scope.row.status" /></template></el-table-column>
      </el-table>
      <el-alert v-if="links.length && !files.length" :title="tr('\u5206\u4eab\u94fe\u63a5\u5df2\u53d1\u73b0\uff1b\u5177\u4f53\u6587\u4ef6\u9700\u4eba\u5de5\u786e\u8ba4\u3002', 'Share links found; installer files need manual review.')" type="info" :closable="false" style="margin:8px 0" />
      <el-alert v-for="warning in discovery.warnings" :key="warning" :title="warning" type="warning" :closable="false" style="margin-bottom:8px" />
      <h3>{{ tr('发现的软件版本', 'Detected releases') }}</h3>
      <el-table :data="discovery.releases" border size="small" max-height="220">
        <el-table-column prop="version" :label="tr('版本号', 'Version')" min-width="170"><template #default="scope"><span v-if="scope.row.version">{{ scope.row.version }}</span><el-input v-else v-model="versionOverrides[scope.$index]" size="small" :placeholder="tr('填写版本后导入', 'Enter version to import')" /></template></el-table-column>
        <el-table-column prop="release_date" :label="tr('发布日期', 'Release date')" min-width="120" />
        <el-table-column :label="tr('预发布', 'Pre-release')" width="100"><template #default="scope">{{ scope.row.is_prerelease ? tr('是', 'Yes') : tr('否', 'No') }}</template></el-table-column>
        <el-table-column :label="tr('状态', 'Status')" width="110"><template #default="scope"><StatusTag :value="scope.row.status" /></template></el-table-column>
        <el-table-column :label="tr('文件数', 'Artifacts')" width="90"><template #default="scope">{{ scope.row.artifacts.length }}</template></el-table-column>
      </el-table>
      <h3>{{ tr('发现的安装包文件', 'Detected artifacts') }}</h3>
      <el-table :data="files" border size="small" max-height="300">
        <el-table-column prop="version" :label="tr('版本', 'Version')" width="110" />
        <el-table-column prop="filename" :label="tr('文件名', 'Filename')" min-width="200" show-overflow-tooltip />
        <el-table-column :label="tr('系统', 'OS')" width="100"><template #default="scope">{{ enumLabel(scope.row.os) }}</template></el-table-column>
        <el-table-column :label="tr('架构', 'Architecture')" width="100"><template #default="scope">{{ enumLabel(scope.row.architecture) }}</template></el-table-column>
        <el-table-column :label="tr('格式', 'Package')" width="90"><template #default="scope">{{ enumLabel(scope.row.package_type) }}</template></el-table-column>
        <el-table-column prop="file_size" :label="tr('字节', 'Bytes')" width="110" />
        <el-table-column :label="tr('状态', 'Status')" width="100"><template #default="scope"><StatusTag :value="scope.row.status" /></template></el-table-column>
        <el-table-column prop="download_url" label="URL" min-width="190" show-overflow-tooltip />
      </el-table>
    </template>
    <div v-if="importing" style="margin-top:12px"><StatusTag :value="String(importing.status)" /> {{ importing.message }}<el-progress :percentage="Number(importing.progress)" /><el-alert v-if="importing.error_message" type="error" :title="String(importing.error_message)" :closable="false" /></div>
    <template #footer>
      <el-button @click="emit('update:modelValue', false)">{{ tr('关闭', 'Close') }}</el-button>
      <el-button v-if="job?.status === 'FAILED'" @click="preview">{{ tr('重试', 'Retry') }}</el-button>
      <el-button type="primary" :disabled="!importable || !!importing" @click="importAll">{{ tr('全部导入', 'Import all') }}</el-button>
    </template>
  </el-dialog>
</template>
