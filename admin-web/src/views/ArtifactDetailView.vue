<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api, client, type Row } from '../api/client'
import StatusTag from '../components/StatusTag.vue'
import { enumLabel, tr } from '../i18n'
import { formatBeijingTime } from '../utils/time'

const route = useRoute()
const router = useRouter()
const id = computed(() => Number(route.params.id))
const artifact = ref<Row | null>(null)
const variant = ref<Row | null>(null)
const release = ref<Row | null>(null)
const software = ref<Row | null>(null)
const jobs = ref<Row[]>([])
const storageRows = ref<Row[]>([])
const selfHostedCategories = ref<string[]>([])
const selfHostedDialog = ref(false)
const selfHostedCategory = ref('')
const activeTab = ref('overview')
const busy = ref(false)
let timer: ReturnType<typeof setInterval> | undefined
async function load(): Promise<void> {
  artifact.value = await api.get('artifacts', id.value)
  variant.value = await api.get('variants', Number(artifact.value.variant_id))
  release.value = await api.get('releases', Number(variant.value.release_id))
  software.value = await api.get('software', Number(release.value.software_id))
  jobs.value = (await api.list('jobs', { target_type: 'artifact', target_id: id.value, page_size: 20 })).items
  storageRows.value = (await client.get<{ items: Row[] }>(`/artifacts/${id.value}/storage`)).data.items
}
const activeDownload = computed(() => jobs.value.find(job => job.job_type === 'DOWNLOAD' && ['PENDING', 'RUNNING'].includes(String(job.status))))
const checks = computed(() => (artifact.value?.verification_details as { checks?: { name: string; status: string; message: string }[] } | null)?.checks ?? [])
const warnings = computed(() => (artifact.value?.verification_details as { warnings?: string[] } | null)?.warnings ?? [])
const errors = computed(() => (artifact.value?.verification_details as { errors?: string[] } | null)?.errors ?? [])
async function action(type: 'download' | 'redownload' | 'verify'): Promise<void> {
  busy.value = true
  try {
    if (type === 'redownload') await ElMessageBox.confirm(tr('重新下载会保留原文件；内容变化时需要人工审核。继续？', 'Re-download preserves the old file; changed content requires review. Continue?'), tr('确认重新下载', 'Confirm re-download'))
    const job = await api.action(`/artifacts/${id.value}/${type}`)
    ElMessage.success(tr(`任务 #${job.id} 已创建`, `Job #${job.id} created`))
    await load()
    await router.push(`/jobs/${job.id}`)
  } finally { busy.value = false }
}
async function cancel(): Promise<void> {
  if (!activeDownload.value) return
  await api.action(`/jobs/${activeDownload.value.id}/cancel`)
  ElMessage.success(tr('已请求取消下载', 'Download cancellation requested'))
  await load()
}
async function review(decision: 'approve' | 'reject'): Promise<void> {
  await ElMessageBox.confirm(tr(`确定${decision === 'approve' ? '批准并归档' : '拒绝'}此文件？`, `Are you sure you want to ${decision} this file?`), tr('人工审核确认', 'Confirm manual review'), { type: 'warning' })
  await api.action(`/artifacts/${id.value}/review/${decision}`)
  await load()
}
async function setRedistribution(status: 'ALLOWED' | 'PROHIBITED'): Promise<void> {
  await ElMessageBox.confirm(status === 'ALLOWED' ? tr('请确认你有权再分发此安装包；允许后才能上传百度网盘。', 'Confirm that you have redistribution rights before enabling Baidu upload.') : tr('确定禁止再分发此安装包？', 'Prohibit redistribution of this artifact?'), tr('再分发许可确认', 'Redistribution permission'), { type: 'warning' })
  await client.post(`/artifacts/${id.value}/redistribution`, { status })
  await load()
}
async function uploadBaidu(): Promise<void> {
  await ElMessageBox.confirm(tr('将本地已验证文件上传至已授权的百度网盘账号？', 'Upload this verified local file to the connected Baidu account?'), tr('确认上传', 'Confirm upload'))
  const job = await api.create(`artifacts/${id.value}/upload`, { provider: 'BAIDU' })
  ElMessage.success(tr(`上传任务 #${job.id} 已创建`, `Upload job #${job.id} created`))
  await load()
  await router.push(`/jobs/${job.id}`)
}
async function uploadSelfHosted(): Promise<void> {
  if (!selfHostedCategory.value) return
  await ElMessageBox.confirm(
    tr(`将已验证文件上传到局域网云盘，类别为“${selfHostedCategory.value}”？`, `Upload this verified file to the local cloud drive as “${selfHostedCategory.value}”?`),
    tr('确认上传到局域网云盘', 'Confirm local cloud upload'),
  )
  const job = await api.create(`artifacts/${id.value}/upload`, {
    provider: 'SELF_HOSTED', file_arch: selfHostedCategory.value,
  })
  selfHostedDialog.value = false
  ElMessage.success(tr(`上传任务 #${job.id} 已创建`, `Upload job #${job.id} created`))
  await load()
  await router.push(`/jobs/${job.id}`)
}
async function share(storage: Row): Promise<void> {
  await ElMessageBox.confirm(tr('创建 7 天有效的百度网盘分享链接？', 'Create a Baidu share link valid for 7 days?'), tr('确认分享', 'Confirm share'))
  await client.post(`/storage/${storage.id}/share`, {}, { timeout: 120000 })
  await load()
}
async function copyLink(storage: Row): Promise<void> {
  if (!storage.share_url) return
  await navigator.clipboard.writeText(`${storage.share_url}${storage.share_code ? ` 提取码：${storage.share_code}` : ''}`)
  ElMessage.success(tr('分享链接已复制', 'Share link copied'))
}
onMounted(() => {
  void load()
  void client.get<{ items: string[] }>('/storage/self-hosted/categories').then(({ data }) => { selfHostedCategories.value = data.items })
  timer = setInterval(() => { void load() }, 2000)
})
onUnmounted(() => { if (timer) clearInterval(timer) })
</script>
<template>
  <div class="toolbar"><h1>{{ tr('安装包文件详情', 'Installer artifact') }} #{{ id }}</h1><div class="toolbar-actions">
    <el-button v-if="artifact && !artifact.local_path && !activeDownload" :loading="busy" type="primary" @click="action('download')">{{ tr('下载', 'Download') }}</el-button>
    <el-button v-if="artifact?.local_path && !activeDownload" :loading="busy" @click="action('redownload')">{{ tr('重新下载', 'Re-download') }}</el-button>
    <el-button v-if="activeDownload" type="danger" @click="cancel">{{ tr('取消下载', 'Cancel download') }}</el-button>
    <el-button v-if="artifact?.local_exists || artifact?.download_status === 'DOWNLOADED'" :loading="busy" @click="action('verify')">{{ tr('重新验证', 'Verify') }}</el-button>
    <el-button v-if="artifact?.verification_status === 'MANUAL_REVIEW'" type="success" @click="review('approve')">{{ tr('人工批准', 'Approve') }}</el-button>
    <el-button v-if="artifact?.verification_status === 'MANUAL_REVIEW'" type="danger" @click="review('reject')">{{ tr('人工拒绝', 'Reject') }}</el-button>
  </div></div>
  <el-tabs v-model="activeTab">
  <el-tab-pane :label="tr('文件概览', 'Overview')" name="overview">
  <el-descriptions v-if="artifact" class="panel" :column="2" border>
    <el-descriptions-item :label="tr('已抓取软件', 'Catalog software')">{{ software?.name }}</el-descriptions-item>
    <el-descriptions-item :label="tr('软件版本号', 'Software release')">{{ release?.version }}</el-descriptions-item>
    <el-descriptions-item :label="tr('目标操作系统', 'Target OS')">{{ enumLabel(variant?.os) }}</el-descriptions-item>
    <el-descriptions-item :label="tr('目标 CPU 架构', 'Target architecture')">{{ enumLabel(variant?.architecture) }}</el-descriptions-item>
    <el-descriptions-item :label="tr('安装包格式', 'Package type')">{{ enumLabel(artifact.package_type) }}</el-descriptions-item>
    <el-descriptions-item :label="tr('安装包文件名', 'Filename')">{{ artifact.filename }}</el-descriptions-item>
    <el-descriptions-item :label="tr('文件大小', 'File size')">{{ artifact.file_size ?? '—' }} bytes</el-descriptions-item>
    <el-descriptions-item :label="tr('下载状态', 'Download status')"><StatusTag :value="String(artifact.download_status)" /></el-descriptions-item>
    <el-descriptions-item :label="tr('校验状态', 'Verification status')"><StatusTag :value="String(artifact.verification_status)" /></el-descriptions-item>
    <el-descriptions-item :label="tr('本机文件存在', 'Local file exists')">{{ artifact.local_exists ? tr('是', 'Yes') : tr('否', 'No') }}</el-descriptions-item>
    <el-descriptions-item :label="tr('待审核暂存文件', 'Staged file awaiting review')">{{ artifact.staging_exists ? tr('是', 'Yes') : tr('否', 'No') }}</el-descriptions-item>
    <el-descriptions-item :label="tr('来源 URL', 'Source URL')">{{ artifact.source_url || '—' }}</el-descriptions-item>
    <el-descriptions-item :label="tr('最终下载 URL', 'Resolved URL')">{{ artifact.resolved_url || '—' }}</el-descriptions-item>
    <el-descriptions-item :label="tr('相对归档路径', 'Relative archive path')">{{ artifact.local_path || '—' }}</el-descriptions-item>
    <el-descriptions-item :label="tr('下载时间', 'Downloaded at')">{{ formatBeijingTime(artifact.downloaded_at) }}</el-descriptions-item>
    <el-descriptions-item :label="tr('验证时间', 'Verified at')">{{ formatBeijingTime(artifact.verified_at) }}</el-descriptions-item>
    <el-descriptions-item label="SHA256">{{ artifact.sha256 || '—' }}</el-descriptions-item>
    <el-descriptions-item label="MD5">{{ artifact.md5 || '—' }}</el-descriptions-item>
    <el-descriptions-item :label="tr('再分发许可', 'Redistribution permission')"><StatusTag :value="String(artifact.redistribution_status || 'UNKNOWN')" /></el-descriptions-item>
  </el-descriptions>
  <div v-if="artifact" class="panel"><el-button size="small" @click="setRedistribution('ALLOWED')">{{ tr('确认允许再分发', 'Allow redistribution') }}</el-button><el-button size="small" @click="setRedistribution('PROHIBITED')">{{ tr('禁止再分发', 'Prohibit redistribution') }}</el-button></div>
  <div v-if="artifact?.verification_details" class="panel"><h3>{{ tr('验证详情', 'Verification checks') }}</h3>
    <el-table :data="checks" border size="small"><el-table-column prop="name" :label="tr('检查项', 'Check')" /><el-table-column prop="status" :label="tr('结果', 'Result')" /><el-table-column prop="message" :label="tr('说明', 'Message')" /></el-table>
    <p v-for="warning in warnings" :key="warning">{{ tr('警告', 'Warning') }}: {{ warning }}</p><p v-for="error in errors" :key="error">{{ tr('错误', 'Error') }}: {{ error }}</p>
  </div>
  <div class="panel"><h3>{{ tr('下载与验证任务', 'Download and verification jobs') }}</h3>
    <el-table :data="jobs" border size="small"><el-table-column prop="id" label="ID" /><el-table-column prop="job_type" :label="tr('类型', 'Type')" /><el-table-column :label="tr('状态', 'Status')"><template #default="scope"><StatusTag :value="String(scope.row.status)" /></template></el-table-column><el-table-column :label="tr('进度', 'Progress')"><template #default="scope">{{ scope.row.progress }}% · {{ scope.row.result?.bytes_downloaded ?? '—' }} / {{ scope.row.result?.total_bytes ?? '—' }} bytes</template></el-table-column><el-table-column :label="tr('操作', 'Action')"><template #default="scope"><router-link :to="`/jobs/${scope.row.id}`">{{ tr('查看', 'View') }}</router-link></template></el-table-column></el-table>
  </div>
  </el-tab-pane>
  <el-tab-pane :label="tr('文件存储位置', 'Storage')" name="storage">
    <div class="panel">
      <el-alert v-if="storageRows.some(row => row.share_status === 'CREATED')" type="warning" :closable="false" style="margin-bottom:12px" :title="tr('百度开放 API 暂无取消分享接口。若需要撤销链接，请在百度网盘手动取消；更改再分发许可不会自动撤销现有链接。', 'Baidu Open API has no documented cancel-share endpoint. Cancel the link in Baidu Pan; changing redistribution permission does not revoke existing shares.')" />
      <el-button type="primary" :disabled="artifact?.verification_status !== 'VERIFIED' || artifact?.redistribution_status !== 'ALLOWED' || storageRows.some(row => row.provider === 'BAIDU' && ['PENDING', 'UPLOADING', 'SUCCESS'].includes(String(row.upload_status)))" @click="uploadBaidu">{{ tr('上传百度网盘', 'Upload to Baidu Pan') }}</el-button>
      <p v-if="artifact?.redistribution_status !== 'ALLOWED'">{{ tr('上传前需在文件概览确认再分发许可。', 'Confirm redistribution permission in Overview before upload.') }}</p>
      <el-button :disabled="artifact?.verification_status !== 'VERIFIED' || storageRows.some(row => row.provider === 'SELF_HOSTED' && ['PENDING', 'UPLOADING', 'SUCCESS'].includes(String(row.upload_status)))" @click="selfHostedDialog = true">{{ tr('上传到局域网云盘', 'Upload to local cloud drive') }}</el-button>
      <p v-if="artifact?.verification_status === 'VERIFIED' && artifact?.redistribution_status !== 'ALLOWED'">{{ tr('私有云盘归档只要求文件已验证；公开分享仍需单独确认再分发许可。', 'Private cloud archiving only requires verification; public redistribution still needs separate approval.') }}</p>
      <el-table :data="storageRows" border size="small" style="margin-top:12px">
        <el-table-column prop="provider" :label="tr('存储服务商', 'Provider')" width="120" />
        <el-table-column prop="remote_path" :label="tr('存储路径', 'Storage path')" min-width="240" />
        <el-table-column :label="tr('文件类别', 'File category')" width="120"><template #default="scope">{{ scope.row.provider === 'SELF_HOSTED' ? scope.row.remote_parent_id : '—' }}</template></el-table-column>
        <el-table-column :label="tr('上传状态', 'Upload status')" width="130"><template #default="scope"><StatusTag :value="String(scope.row.upload_status)" /></template></el-table-column>
        <el-table-column :label="tr('分享状态', 'Share status')" width="130"><template #default="scope"><StatusTag :value="String(scope.row.share_status)" /></template></el-table-column>
        <el-table-column prop="share_url" :label="tr('分享链接', 'Share link')" min-width="200" />
        <el-table-column :label="tr('操作', 'Actions')" width="260"><template #default="scope">
          <el-button v-if="scope.row.provider === 'BAIDU' && scope.row.upload_status === 'SUCCESS' && scope.row.share_status !== 'CREATED'" link type="primary" :disabled="artifact?.redistribution_status !== 'ALLOWED' || artifact?.verification_status !== 'VERIFIED'" @click="share(scope.row)">{{ tr('创建分享', 'Create share') }}</el-button>
          <el-button v-if="scope.row.share_status === 'CREATED'" link @click="copyLink(scope.row)">{{ tr('复制链接', 'Copy link') }}</el-button>
          <el-button v-if="scope.row.share_status === 'CREATED'" link disabled>{{ tr('请在百度网盘取消分享', 'Disable in Baidu Pan') }}</el-button>
          <el-button v-if="scope.row.provider === 'LOCAL' && scope.row.local_exists" link @click="api.action(`/storage/${scope.row.id}/open-local-directory`)">{{ tr('打开本地目录', 'Open folder') }}</el-button>
        </template></el-table-column>
      </el-table>
    </div>
  </el-tab-pane>
  </el-tabs>
  <el-dialog v-model="selfHostedDialog" :title="tr('选择云盘文件类别', 'Choose cloud-drive category')" width="420px">
    <el-form label-position="top"><el-form-item :label="tr('文件类别', 'File category')">
      <el-select v-model="selfHostedCategory" filterable style="width:100%" :placeholder="tr('选择类别', 'Select category')">
        <el-option v-for="category in selfHostedCategories" :key="category" :label="category" :value="category" />
      </el-select>
    </el-form-item></el-form>
    <template #footer><el-button @click="selfHostedDialog = false">{{ tr('取消', 'Cancel') }}</el-button><el-button type="primary" :disabled="!selfHostedCategory" @click="uploadSelfHosted">{{ tr('创建上传任务', 'Create upload job') }}</el-button></template>
  </el-dialog>
</template>
