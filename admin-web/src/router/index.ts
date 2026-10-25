import { createRouter, createWebHistory } from 'vue-router'
import AdminLayout from '../layouts/AdminLayout.vue'
import DashboardView from '../views/DashboardView.vue'
import ResourceView from '../views/ResourceView.vue'
import SoftwareDetailView from '../views/SoftwareDetailView.vue'
import ArtifactDetailView from '../views/ArtifactDetailView.vue'
import JobDetailView from '../views/JobDetailView.vue'
import SettingsView from '../views/SettingsView.vue'
import PoolScanView from '../views/PoolScanView.vue'
import ShareLinkRegistryView from '../views/ShareLinkRegistryView.vue'

const cachedResourceNames = ['candidates', 'crawl-pools', 'software', 'releases', 'variants', 'artifacts', 'sources', 'links', 'downloads', 'storage', 'content', 'publishing', 'jobs']
const scrollPositions = new Map<string, number>()

const router = createRouter({
  history: createWebHistory(),
  scrollBehavior(to, from, savedPosition) {
    if (savedPosition) return savedPosition
    const position = scrollPositions.get(to.fullPath)
    return { left: 0, top: position ?? 0 }
  },
  routes: [{ path: '/', component: AdminLayout, children: [
    { path: '', component: DashboardView },
    ...cachedResourceNames.map(name => ({ name: `resource-${name}`, path: name, component: ResourceView, props: { name }, meta: { keepAlive: true } })),
    { path: 'crawl-pools/scans/:id', component: PoolScanView },
    { path: 'share-links', component: ShareLinkRegistryView },
    { path: 'software/:id', component: SoftwareDetailView },
    { path: 'artifacts/:id', component: ArtifactDetailView },
    { path: 'jobs/:id', component: JobDetailView },
    { path: 'settings', component: SettingsView },
  ] }],
})

router.beforeEach((_to, from) => {
  if (from.matched.length) scrollPositions.set(from.fullPath, window.scrollY)
})

export default router
