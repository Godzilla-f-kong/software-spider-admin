<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { client } from '../api/client'
import StatusTag from '../components/StatusTag.vue'
import { tr } from '../i18n'
import { formatBeijingTime } from '../utils/time'

interface EditableSettings {
  data_root: string
  spider_enabled: boolean
  spider_user_agent: string
  spider_timeout: number
  spider_max_retries: number
  spider_max_concurrency: number
  spider_request_delay: number
}
interface SettingsResponse extends EditableSettings {
  database: string; database_host: string; database_name: string; local_storage: string
  timezone: string; current_time: string; spider_restart_required: boolean
  downloader: string; ai: string; baidu_pan: string; github_api: string; external_search: string; ai_page_recognition: string
  download_concurrency: number; download_timeout: number; download_max_file_size: number
  cloud_sharelink_api: string; cloud_sharelink_url: string
}
interface StorageAccount { id: number; provider: string; name: string; expires_at: string; status: string }

const settings = ref<SettingsResponse | null>(null)
const baiduAccounts = ref<StorageAccount[]>([])
const selfHostedProvider = ref<{ configured: boolean; base_url: string; category_count: number } | null>(null)
const saving = ref(false)
const form = reactive<EditableSettings>({
  data_root: '', spider_enabled: true, spider_user_agent: '', spider_timeout: 30,
  spider_max_retries: 3, spider_max_concurrency: 1, spider_request_delay: 0.5,
})

function setForm(value: SettingsResponse): void {
  form.data_root = value.data_root
  form.spider_enabled = value.spider_enabled
  form.spider_user_agent = value.spider_user_agent
  form.spider_timeout = value.spider_timeout
  form.spider_max_retries = value.spider_max_retries
  form.spider_max_concurrency = value.spider_max_concurrency
  form.spider_request_delay = value.spider_request_delay
}

async function load(): Promise<void> {
  const value = (await client.get<SettingsResponse>('/settings')).data
  settings.value = value
  setForm(value)
  baiduAccounts.value = (await client.get<{ items: StorageAccount[] }>('/storage/accounts')).data.items.filter(account => account.provider === 'BAIDU')
  const providers = (await client.get<{ items: { provider: string; configured: boolean; base_url?: string; category_count?: number }[] }>('/storage/providers')).data.items
  const cloud = providers.find(provider => provider.provider === 'SELF_HOSTED')
  selfHostedProvider.value = cloud ? { configured: cloud.configured, base_url: cloud.base_url || '', category_count: cloud.category_count || 0 } : null
}

async function connectBaidu(): Promise<void> {
  const popup = window.open('', '_blank')
  if (popup) popup.opener = null
  try {
    const { data } = await client.get<{ authorization_url: string }>('/storage/accounts/baidu/oauth/start')
    if (popup) popup.location.href = data.authorization_url
    else window.location.href = data.authorization_url
    ElMessage.info(tr('完成百度授权后，返回此页刷新状态。', 'Complete Baidu authorization, then refresh this page.'))
  } catch {
    popup?.close()
  }
}

async function save(): Promise<void> {
  saving.value = true
  try {
    const value = (await client.patch<SettingsResponse>('/settings', { ...form })).data
    settings.value = value
    setForm(value)
    ElMessage.success(tr('系统设置已保存', 'Settings saved'))
  } catch {
    // The shared API client displays the validation or network error.
  } finally { saving.value = false }
}

onMounted(() => { void load().catch(() => undefined) })
</script>

<template>
  <h1>{{ tr('系统设置', 'System Settings') }}</h1>
  <div v-if="settings" class="panel">
    <el-descriptions :column="1" border size="small">
      <el-descriptions-item :label="tr('系统时区', 'System time zone')">{{ settings.timezone }} (UTC+8) · {{ formatBeijingTime(settings.current_time) }}</el-descriptions-item>
      <el-descriptions-item :label="tr('MySQL 数据库连接', 'MySQL database')"><StatusTag :value="settings.database" /> {{ settings.database_host }} / {{ settings.database_name }}</el-descriptions-item>
      <el-descriptions-item :label="tr('本地归档实际路径', 'Resolved local archive path')">{{ settings.local_storage }}</el-descriptions-item>
      <el-descriptions-item :label="tr('GitHub API Token', 'GitHub API token')"><StatusTag :value="settings.github_api" /></el-descriptions-item>
      <el-descriptions-item :label="tr('外部站点搜索 API', 'External site search API')"><StatusTag :value="settings.external_search" /></el-descriptions-item>
      <el-descriptions-item :label="tr('AI 辅助页面识别', 'AI-assisted page recognition')"><StatusTag :value="settings.ai_page_recognition" /></el-descriptions-item>
      <el-descriptions-item :label="tr('直接下载器', 'Direct downloader')"><StatusTag :value="settings.downloader" /> · {{ settings.download_concurrency }} {{ tr('并发', 'concurrent') }} · {{ settings.download_timeout }} s · {{ settings.download_max_file_size || tr('无限制', 'unlimited') }} bytes</el-descriptions-item>
      <el-descriptions-item label="AI"><StatusTag :value="settings.ai" /></el-descriptions-item>
      <el-descriptions-item :label="tr('百度网盘', 'Baidu Pan')"><StatusTag :value="settings.baidu_pan" /> <el-button size="small" @click="connectBaidu">{{ tr('连接百度网盘', 'Connect Baidu Pan') }}</el-button> <el-button size="small" @click="load">{{ tr('刷新', 'Refresh') }}</el-button></el-descriptions-item>
      <el-descriptions-item :label="tr('局域网云盘', 'Local cloud drive')"><StatusTag :value="selfHostedProvider?.configured ? 'CONFIGURED' : 'NOT_CONFIGURED'" /> {{ selfHostedProvider?.base_url }} · {{ selfHostedProvider?.category_count || 0 }} {{ tr('个文件类别', 'file categories') }}</el-descriptions-item>
      <el-descriptions-item :label="tr('永久分享登记接口', 'Permanent share registration API')"><StatusTag :value="settings.cloud_sharelink_api" /> {{ settings.cloud_sharelink_url }}</el-descriptions-item>
    </el-descriptions>
    <el-alert type="info" :closable="false" style="margin-top:12px" :title="tr('百度创建分享需企业认证并开通付费分享服务；开放 API 暂无取消分享接口，需在百度网盘手动取消。', 'Baidu share creation requires enterprise approval and paid access. The documented open API has no cancel-share endpoint; cancel shares in Baidu Pan.')" />
    <el-table v-if="baiduAccounts.length" :data="baiduAccounts" border size="small" style="margin-top:12px"><el-table-column prop="name" :label="tr('网盘账号', 'Account')" /><el-table-column :label="tr('状态', 'Status')"><template #default="scope"><StatusTag :value="scope.row.status" /></template></el-table-column><el-table-column :label="tr('令牌到期时间', 'Token expiry')"><template #default="scope">{{ formatBeijingTime(scope.row.expires_at) }}</template></el-table-column></el-table>
  </div>
  <div v-if="settings" class="panel" style="max-width:760px;margin-top:16px">
    <h2>{{ tr('可编辑运行设置', 'Editable runtime settings') }}</h2>
    <el-form label-position="top" @submit.prevent="save">
      <el-form-item :label="tr('本地归档目录', 'Local archive directory')"><el-input v-model="form.data_root" /></el-form-item>
      <el-form-item :label="tr('启用爬虫', 'Enable spider')"><el-switch v-model="form.spider_enabled" /></el-form-item>
      <el-form-item :label="tr('爬虫 User-Agent', 'Spider User-Agent')"><el-input v-model="form.spider_user_agent" /></el-form-item>
      <el-form-item :label="tr('请求超时（秒）', 'Request timeout (seconds)')"><el-input-number v-model="form.spider_timeout" :min="1" :max="120" :step="1" /></el-form-item>
      <el-form-item :label="tr('失败重试次数', 'Retry count')"><el-input-number v-model="form.spider_max_retries" :min="0" :max="10" :step="1" /></el-form-item>
      <el-form-item :label="tr('抓取任务并发数（固定串行）', 'Spider job concurrency (serial)')"><el-input-number v-model="form.spider_max_concurrency" :min="1" :max="1" :step="1" disabled /></el-form-item>
      <el-form-item :label="tr('请求间隔（秒）', 'Request delay (seconds)')"><el-input-number v-model="form.spider_request_delay" :min="0" :max="10" :step="0.1" :precision="1" /></el-form-item>
      <el-alert type="info" :closable="false" :title="tr('后台爬取任务全局串行执行；新增候选或启用 URL 池后会自动排队。', 'Spider jobs run through one global serial queue and are enqueued when candidates or enabled URL pools are added.')" style="margin-bottom:12px" />
      <el-button type="primary" native-type="submit" :loading="saving">{{ tr('保存设置', 'Save settings') }}</el-button>
      <el-button @click="setForm(settings)">{{ tr('撤销未保存修改', 'Discard changes') }}</el-button>
    </el-form>
  </div>
</template>
