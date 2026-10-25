<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { api, type Row } from '../api/client'
import { resources } from '../types/resources'
import ResourceTable from '../components/ResourceTable.vue'
import StatusTag from '../components/StatusTag.vue'
import { enumLabel, tr } from '../i18n'
const route = useRoute()
const id = computed(() => Number(route.params.id))
const software = ref<Row | null>(null)
const releases = ref<Row[]>([])
const variants = ref<Row[]>([])
const artifacts = ref<Row[]>([])
const selectedRelease = ref<number | null>(null)
const selectedVariant = ref<number | null>(null)
const selectedArtifact = ref<number | null>(null)
const tab = ref(route.query.tab === 'sources' ? 'sources' : 'overview')
const refreshKey = ref(0)
async function onDiscoveryImported() { refreshKey.value += 1; await load() }
async function load() {
  software.value = await api.get('software', id.value)
  releases.value = (await api.list('releases', { software_id: id.value, page_size: 100 })).items
  if (!selectedRelease.value && releases.value.length) selectedRelease.value = releases.value[0].id
}
async function loadVariants() {
  variants.value = selectedRelease.value ? (await api.list('variants', { release_id: selectedRelease.value, page_size: 100 })).items : []
  selectedVariant.value = variants.value[0]?.id ?? null
}
watch(selectedRelease, loadVariants)
watch(selectedVariant, async () => {
  artifacts.value = selectedVariant.value ? (await api.list('artifacts', { variant_id: selectedVariant.value, page_size: 100 })).items : []
  selectedArtifact.value = artifacts.value[0]?.id ?? null
})
onMounted(load)
const sourceDefaults = computed(() => ({ software_id: id.value }))
const releaseDefaults = computed(() => ({ software_id: id.value }))
const catalogOverview = computed(() => software.value?.catalog_overview as Record<string, number> | undefined)
</script>
<template><div class="toolbar"><h1>{{ software?.name ?? tr('已抓取软件档案', 'Crawled software record') }}</h1><router-link to="/software">{{ tr('返回已抓取软件列表', 'Back to crawled software') }}</router-link></div>
  <el-tabs v-model="tab" type="border-card">
    <el-tab-pane :label="tr('软件档案概览', 'Software Overview')" name="overview"><el-descriptions v-if="software" :column="2" border><el-descriptions-item label="ID">{{ software.id }}</el-descriptions-item><el-descriptions-item label="Slug">{{ software.slug }}</el-descriptions-item><el-descriptions-item :label="tr('开发者 / 维护组织', 'Developer / Maintainer')">{{ software.developer || '—' }}</el-descriptions-item><el-descriptions-item :label="tr('软件分类', 'Software category')">{{ software.category || '—' }}</el-descriptions-item><el-descriptions-item :label="tr('收录状态', 'Catalog status')"><StatusTag :value="String(software.status)" /></el-descriptions-item><el-descriptions-item :label="tr('软件许可证', 'Software license')">{{ software.license || '—' }}</el-descriptions-item><el-descriptions-item :label="tr('官方网站 URL', 'Official website URL')">{{ software.official_url || '—' }}</el-descriptions-item><el-descriptions-item :label="tr('软件简介', 'Software summary')">{{ software.summary || '—' }}</el-descriptions-item><el-descriptions-item :label="tr('详细描述', 'Detailed description')">{{ software.description || '—' }}</el-descriptions-item><el-descriptions-item :label="tr('抓取来源', 'Crawl sources')">{{ catalogOverview?.source_count ?? 0 }}</el-descriptions-item><el-descriptions-item :label="tr('已发现版本', 'Discovered releases')">{{ catalogOverview?.release_count ?? 0 }}<span v-if="software.latest_release"> · {{ software.latest_release }}</span></el-descriptions-item><el-descriptions-item :label="tr('安装包文件', 'Installer files')">{{ catalogOverview?.artifact_count ?? 0 }}</el-descriptions-item><el-descriptions-item :label="tr('本地归档文件', 'Local archived files')">{{ catalogOverview?.local_archive_count ?? 0 }}</el-descriptions-item></el-descriptions></el-tab-pane>
    <el-tab-pane :label="tr('软件版本', 'Software Releases')" name="releases"><ResourceTable :key="refreshKey" :config="resources.releases" :fixed="releaseDefaults" :defaults="releaseDefaults" @loaded="releases = $event" /></el-tab-pane>
    <el-tab-pane :label="tr('已收录软件来源', 'Catalog Sources')" name="sources"><ResourceTable :config="resources.sources" :fixed="sourceDefaults" :defaults="sourceDefaults" @imported="onDiscoveryImported" /></el-tab-pane>
    <el-tab-pane :label="tr('版本平台与架构', 'Release Platforms & Architectures')" name="variants"><el-select v-model="selectedRelease" :placeholder="tr('选择软件版本', 'Select software release')" style="width:250px;margin-bottom:12px"><el-option v-for="release in releases" :key="release.id" :label="String(release.version)" :value="release.id" /></el-select><ResourceTable v-if="selectedRelease" :key="selectedRelease" :config="resources.variants" :fixed="{ release_id: selectedRelease }" @loaded="variants = $event" /></el-tab-pane>
    <el-tab-pane :label="tr('安装包文件', 'Installer Packages')" name="files"><div class="toolbar-actions" style="margin-bottom:12px"><el-select v-model="selectedRelease" :placeholder="tr('选择软件版本', 'Select software release')" style="width:220px"><el-option v-for="release in releases" :key="release.id" :label="String(release.version)" :value="release.id" /></el-select><el-select v-model="selectedVariant" :placeholder="tr('选择版本平台与架构', 'Select release platform')" style="width:250px"><el-option v-for="variant in variants" :key="variant.id" :label="`${enumLabel(variant.os)} / ${enumLabel(variant.architecture)} / ${variant.id}`" :value="variant.id" /></el-select></div><ResourceTable v-if="selectedVariant" :key="selectedVariant" :config="resources.artifacts" :fixed="{ variant_id: selectedVariant }" /></el-tab-pane>
    <el-tab-pane :label="tr('安装包存储位置', 'Installer Storage Locations')" name="storage"><div class="toolbar-actions" style="margin-bottom:12px"><el-select v-model="selectedRelease" :placeholder="tr('选择软件版本', 'Select software release')" style="width:180px"><el-option v-for="release in releases" :key="release.id" :label="String(release.version)" :value="release.id" /></el-select><el-select v-model="selectedVariant" :placeholder="tr('选择版本平台与架构', 'Select release platform')" style="width:230px"><el-option v-for="variant in variants" :key="variant.id" :label="`${enumLabel(variant.os)} / ${enumLabel(variant.architecture)} / ${variant.id}`" :value="variant.id" /></el-select><el-select v-model="selectedArtifact" :placeholder="tr('选择安装包文件', 'Select installer package')" style="width:240px"><el-option v-for="artifact in artifacts" :key="artifact.id" :label="String(artifact.filename)" :value="artifact.id" /></el-select></div><ResourceTable v-if="selectedArtifact" :key="selectedArtifact" :config="resources.storage" :fixed="{ artifact_id: selectedArtifact }" /></el-tab-pane>
    <el-tab-pane :label="tr('生成内容草稿', 'Generated Content Drafts')" name="content"><ResourceTable :config="resources.content" :fixed="{ software_id: id }" /></el-tab-pane>
    <el-tab-pane :label="tr('电商发布文案', 'Commerce Publishing Copy')" name="publishing"><ResourceTable :config="resources.listings" :fixed="{ software_id: id }" /></el-tab-pane>
    <el-tab-pane :label="tr('\u7f51\u76d8\u4e0e\u4e0b\u8f7d\u5165\u53e3', 'Cloud shares and download links')" name="links"><ResourceTable :key="refreshKey" :config="resources.links" :fixed="{ software_id: id }" :defaults="{ software_id: id }" /></el-tab-pane>
  </el-tabs>
</template>
