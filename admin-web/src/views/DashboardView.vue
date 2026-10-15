<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { client, type Row } from '../api/client'
import StatusTag from '../components/StatusTag.vue'
import { enumLabel, tr } from '../i18n'
import { formatBeijingTime } from '../utils/time'
import illustration from '../assets/dashboard-illustration.svg'

interface Dashboard {
  candidates: number; software: number; releases: number; artifacts: number
  pending_downloads: number; failed_jobs: number; pending_review_content: number; recent_jobs: Row[]
}
type MetricKey = Exclude<keyof Dashboard, 'recent_jobs'>
const dashboard = ref<Dashboard | null>(null)
const loading = ref(true)
const metrics: { key: MetricKey; zh: string; en: string; short: string; href: string; tone: string }[] = [
  { key: 'candidates', zh: '待评估候选软件', en: 'Candidates to review', short: '01', href: '/candidates', tone: 'blue' },
  { key: 'software', zh: '已抓取软件', en: 'Crawled software', short: '02', href: '/software', tone: 'coral' },
  { key: 'releases', zh: '已发现软件版本', en: 'Discovered releases', short: '03', href: '/releases', tone: 'yellow' },
  { key: 'artifacts', zh: '软件安装包文件', en: 'Installer packages', short: '04', href: '/artifacts', tone: 'mint' },
  { key: 'pending_downloads', zh: '待下载文件', en: 'Pending downloads', short: '05', href: '/downloads', tone: 'mint' },
  { key: 'failed_jobs', zh: '失败任务', en: 'Failed jobs', short: '06', href: '/jobs', tone: 'coral' },
  { key: 'pending_review_content', zh: '待审核内容', en: 'Content awaiting review', short: '07', href: '/content', tone: 'blue' },
]

onMounted(async () => {
  try { dashboard.value = (await client.get<Dashboard>('/dashboard')).data }
  finally { loading.value = false }
})
</script>

<template>
  <div class="dashboard-page">
    <section class="dashboard-hero">
      <div class="hero-copy"><span class="section-kicker">SOFTWARE RESOURCE STUDIO · 01</span>
        <h1>{{ tr('把软件资源，整理得井井有条。', 'A clearer view of every software resource.') }}</h1>
        <p>{{ tr('从发现来源、整理版本到验证安装包，所有工作都从这里开始。', 'Discover sources, organize releases, and verify installers from one workspace.') }}</p>
        <div class="hero-actions"><router-link class="hero-primary" to="/software">{{ tr('查看已抓取软件', 'Explore software') }} <span aria-hidden="true">↗</span></router-link>
          <router-link class="hero-secondary" to="/sources">{{ tr('管理抓取池来源', 'Manage sources') }} <span aria-hidden="true">→</span></router-link></div>
      </div>
      <img class="hero-illustration" :src="illustration" :alt="tr('软件来源、版本和文件的抽象插画', 'Illustration of software sources, releases and files')" />
    </section>

    <div class="section-heading"><div><span class="section-kicker">WORKSPACE AT A GLANCE</span><h2>{{ tr('资源与任务概况', 'Resources and activity') }}</h2></div>
      <span class="section-hint">{{ tr('数据来自当前数据库', 'Live counts from the database') }}</span></div>
    <div v-loading="loading" class="stat-grid">
      <router-link v-for="metric in metrics" :key="metric.key" :to="metric.href" class="stat" :class="`stat-${metric.tone}`">
        <span class="stat-top"><span class="stat-index">{{ metric.short }}</span><span aria-hidden="true" class="stat-arrow">↗</span></span>
        <strong>{{ dashboard?.[metric.key] ?? '—' }}</strong><span class="stat-label">{{ tr(metric.zh, metric.en) }}</span>
      </router-link>
    </div>

    <section class="panel dashboard-jobs"><div class="section-heading"><div><span class="section-kicker">ACTIVITY LOG</span><h2>{{ tr('最近任务', 'Recent jobs') }}</h2></div>
      <router-link to="/jobs" class="text-link">{{ tr('进入任务中心', 'Open job center') }} →</router-link></div>
      <el-table :data="dashboard?.recent_jobs ?? []" size="small" :empty-text="tr('暂无任务记录', 'No jobs yet')">
        <el-table-column prop="id" label="ID" width="76" />
        <el-table-column :label="tr('任务类型', 'Type')" min-width="130"><template #default="scope">{{ enumLabel(scope.row.job_type) }}</template></el-table-column>
        <el-table-column prop="target_type" :label="tr('目标类型', 'Target')" min-width="115" />
        <el-table-column prop="target_id" :label="tr('目标 ID', 'Target ID')" min-width="95" />
        <el-table-column :label="tr('状态', 'Status')" min-width="110"><template #default="scope"><StatusTag :value="scope.row.status" /></template></el-table-column>
        <el-table-column prop="progress" :label="tr('进度', 'Progress')" min-width="90" />
        <el-table-column :label="tr('创建时间', 'Created at')" min-width="165"><template #default="scope">{{ formatBeijingTime(scope.row.created_at) }}</template></el-table-column>
        <el-table-column :label="tr('操作', 'Action')" width="88"><template #default="scope"><router-link :to="`/jobs/${scope.row.id}`" class="text-link">{{ tr('查看', 'View') }}</router-link></template></el-table-column>
      </el-table>
    </section>
  </div>
</template>
