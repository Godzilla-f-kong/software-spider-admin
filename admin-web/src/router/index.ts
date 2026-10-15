import { createRouter, createWebHistory } from 'vue-router'
import AdminLayout from '../layouts/AdminLayout.vue'
import DashboardView from '../views/DashboardView.vue'
import ResourceView from '../views/ResourceView.vue'
import SoftwareDetailView from '../views/SoftwareDetailView.vue'
import ArtifactDetailView from '../views/ArtifactDetailView.vue'
import JobDetailView from '../views/JobDetailView.vue'
import SettingsView from '../views/SettingsView.vue'
import PoolScanView from '../views/PoolScanView.vue'

export default createRouter({
  history: createWebHistory(),
  routes: [{ path: '/', component: AdminLayout, children: [
    { path: '', component: DashboardView },
    ...['candidates', 'crawl-pools', 'software', 'releases', 'variants', 'artifacts', 'sources', 'links', 'downloads', 'storage', 'content', 'publishing', 'jobs'].map(name => ({ path: name, component: ResourceView, props: { name } })),
    { path: 'crawl-pools/scans/:id', component: PoolScanView },
    { path: 'software/:id', component: SoftwareDetailView },
    { path: 'artifacts/:id', component: ArtifactDetailView },
    { path: 'jobs/:id', component: JobDetailView },
    { path: 'settings', component: SettingsView },
  ] }],
})
