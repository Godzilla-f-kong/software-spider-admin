import { ref } from 'vue'
import type { ResourceConfig } from './types/resources'

export type Language = 'zh-CN' | 'en-US'
const saved = localStorage.getItem('software-spider-language')
export const language = ref<Language>(saved === 'en-US' ? 'en-US' : 'zh-CN')
document.documentElement.lang = language.value

export function setLanguage(next: Language): void {
  language.value = next
  localStorage.setItem('software-spider-language', next)
  document.documentElement.lang = next
}

export function tr(chinese: string, english: string): string {
  return language.value === 'zh-CN' ? chinese : english
}

const titles: Record<string, string> = {
  candidates: 'Software Candidate Pool', software: 'Crawled Software', sources: 'Catalog Software Sources', 'crawl-pools': 'URL Crawl Pool', releases: 'Software Releases',
  links: 'Cloud shares and download links',
  variants: 'Release Platforms', artifacts: 'Installers', storage: 'Artifact Storage', content: 'Generated Content Drafts',
  listings: 'Commerce Publishing Copy', jobs: 'Background Jobs',
}

const fields: Record<string, string> = {
  id: 'ID', name: 'Software name', normalized_name: 'Normalized name', category: 'Software category',
  automation_status: 'Automation policy', last_error: 'Latest discovery error', last_checked_at: 'Last checked', last_success_at: 'Last success',
  source_platform: 'Discovery platform', source_url: 'Source page URL', sales_signal: 'Sales signal',
  base_url: 'Website home URL', max_pages: 'Request budget per run', max_depth: 'Maximum link depth',
  target_version: 'Target version', target_os: 'Target operating system', target_architecture: 'Target CPU architecture',
  search_path_template: 'Site search path template ({query})', category_paths: 'Category paths (one per line)',
  last_result_count: 'Latest candidate matches',
  search_signal: 'Search signal', competition_signal: 'Competition signal',
  automatic_crawl_status: 'Automatic crawl job status',
  commercial_score: 'Commercial score', seo_score: 'SEO score',
  brand_relevance_score: 'Brand relevance', priority_score: 'Priority score',
  status: 'Status', created_at: 'Created at', updated_at: 'Updated at',
  developer: 'Developer / Maintainer', slug: 'Unique slug', license: 'License', official_url: 'Official URL',
  summary: 'Summary', description: 'Description', latest_release: 'Latest release',
  software_id: 'Linked software record ID', source_type: 'Source category', adapter_type: 'Crawl adapter type',
  source_id: 'Source ID', link_type: 'Link type', link_url: 'Share or download URL',
  source_page_url: 'Source page URL', access_code: 'Access code', label: 'Link label',
  context_text: 'Nearby page text', review_status: 'Review status',
  priority: 'Source priority', enabled: 'Enabled', release_id: 'Software release ID', version: 'Version number',
  release_date: 'Official release date', release_notes: 'Release notes', is_latest: 'Latest release',
  os: 'Target operating system', architecture: 'CPU architecture', edition: 'Edition',
  language: 'Language', min_os_version: 'Minimum OS version', notes: 'Notes',
  variant_id: 'Release platform ID', package_type: 'Installer format', filename: 'Filename',
  file_size: 'File size (bytes)', local_path: 'Local path', sha256: 'SHA256', md5: 'MD5',
  signature_status: 'Signature status', download_status: 'Download status',
  verification_status: 'Verification status', artifact_id: 'Installer artifact ID',
  provider: 'Storage service provider', remote_path: 'Remote path', remote_file_id: 'Remote file ID',
  share_url: 'Share URL', share_code: 'Share code', content_type: 'Content type',
  skill_name: 'Skill name', skill_version: 'Skill version', title: 'Title', content: 'Content',
  platform: 'Platform', generated_content_id: 'Generated content ID', price: 'Price',
  listing_url: 'Listing URL', published_at: 'Published at', job_type: 'Job type',
  target_type: 'Target type', target_id: 'Target ID', message: 'Message', progress: 'Progress',
  started_at: 'Started at', finished_at: 'Finished at', error_message: 'Error',
  payload: 'Payload', result: 'Result', reviewed_at: 'Reviewed at', generated_at: 'Generated at',
}

export function fieldLabel(key: string, chinese?: string): string {
  return language.value === 'zh-CN' ? (chinese ?? key) : (fields[key] ?? key)
}

export function resourceTitle(config: ResourceConfig): string {
  if (config.title === '下载任务') return tr('下载任务', 'Download Jobs')
  return language.value === 'zh-CN' ? config.title : (titles[config.path] ?? config.path)
}

const enumZh: Record<string, string> = {
  DISCOVERED: '已发现', REVIEWING: '审核中', ACCEPTED: '已接受', REJECTED: '已拒绝', IGNORED: '已忽略',
  ACTIVE: '启用', DISABLED: '停用', ARCHIVED: '已归档', NEW: '新建', HEALTHY: '正常',
  FAILED: '失败', PROCESSING: '处理中', READY: '就绪', PUBLISHED: '已发布',
  NOT_DOWNLOADED: '未下载', QUEUED: '排队中', DOWNLOADING: '下载中', DOWNLOADED: '已下载',
  PENDING: '待处理', VERIFYING: '验证中', VERIFIED: '已验证', MANUAL_REVIEW: '人工审核',
  UNKNOWN: '未知', VALID: '有效', INVALID: '无效', UNSIGNED: '未签名',
  UPLOADING: '上传中', AVAILABLE: '可用', EXPIRED: '已过期',
  NOT_GENERATED: '未生成', GENERATING: '生成中', DRAFT: '草稿', REVIEWED: '已审核',
  APPROVED: '已批准', REVIEW_REQUIRED: '待审核', PAUSED: '已暂停', MATCHED: '已匹配', REMOVED: '已移除',
  RUNNING: '运行中', SUCCESS: '成功', CANCELLED: '已取消', CONNECTED: '已连接',
  DISCONNECTED: '未连接', NOT_CONFIGURED: '未配置',
  WAITING_FOR_URL_POOL: '等待 URL 抓取池',
  EXISTING: '已存在',
  ALLOWED: '允许', PROHIBITED: '禁止', MANUAL_REQUIRED: '需要人工处理', CONFIGURED: '已配置',
  NONE: '无', CREATING: '创建中', CREATED: '已创建',
  WINDOWS: 'Windows', LINUX: 'Linux', MACOS: 'macOS', ANDROID: 'Android', OTHER: '其他',
  X86: 'x86', X64: 'x64', ARM: 'ARM', ARM64: 'ARM64', UNIVERSAL: '通用',
  OFFICIAL: '官网', OFFICIAL_DOWNLOAD: '官方下载', GITHUB: 'GitHub', MIRROR: '镜像',
  GENERIC_HTML: '通用网页', GITHUB_RELEASE: 'GitHub 版本', JSON_API: 'JSON API',
  STATIC_URL: '固定链接', BROWSER: '浏览器', MANUAL: '手动',
  LOCAL: '本地', BAIDU: '百度网盘', PAN123: '123 云盘', SELF_HOSTED: '自托管', S3: 'S3',
  WEBSITE: '网站', XIANYU: '闲鱼', TAOBAO: '淘宝', VERSION_NOTICE: '版本通知',
  CRAWL: '抓取', CHECK_RELEASE: '检查版本', DOWNLOAD: '下载', VERIFY: '验证',
  UPLOAD_BAIDU: '上传百度网盘', UPLOAD_STORAGE: '上传存储', GENERATE_WEBSITE: '生成网站内容',
  GENERATE_XIANYU: '生成闲鱼内容', GENERATE_TAOBAO: '生成淘宝内容',
  PUBLISH_WEBSITE: '发布网站内容',
  candidate: '候选软件', software: '已抓取软件', source: '已收录软件来源', crawl_pool: 'URL 抓取池', release: '软件版本',
  variant: '版本运行环境', artifact: '安装包文件', content: '生成内容', listing: '电商发布文案',
}

export function enumLabel(value: unknown): string {
  const code = String(value ?? '—')
  if (language.value === 'zh-CN') return enumZh[code] ?? code
  return code.replace(/_/g, ' ').toLowerCase().replace(/\b\w/g, letter => letter.toUpperCase())
}

const errorZh: Record<string, string> = {
  'Candidate not found': '候选软件不存在',
  'Candidate already accepted': '该候选软件已接受',
  'Software not found': '软件不存在',
  'Artifact not found': '文件不存在',
  'Duplicate or referenced record': '记录重复或仍被其他记录引用',
  'Invalid sort field': '无效的排序字段',
  'Use the accept action': '请使用“接受”操作',
  'Use the archive action': '请使用“归档”操作',
  'Accepted candidates are read-only': '已接受的候选软件不可编辑',
  'Jobs are managed by workers': '任务状态由 Worker 管理',
  'Artifact source_url is required for download': '下载前请填写文件来源 URL',
  'Release belongs to another software': '版本不属于该软件',
  'Content belongs to another software': '内容不属于该软件',
  'Field required': '必填',
}

export function apiErrorText(message: unknown): string {
  if (typeof message === 'string') {
    if (language.value === 'en-US') return message
    if (errorZh[message]) return errorZh[message]
    if (message.startsWith('Invalid status transition:')) return `无效的状态转换：${message.split(':').slice(1).join(':').trim()}`
    if (message.startsWith('Software already exists:')) return `软件已存在：${message.split(':').slice(1).join(':').trim()}`
    if (message.endsWith(' does not exist')) return `${fieldLabel(message.slice(0, -15))}不存在`
    return message
  }
  if (Array.isArray(message)) {
    return message.map(item => {
      if (typeof item !== 'object' || item === null) return String(item)
      const value = item as Record<string, unknown>
      const field = String(value.field ?? (Array.isArray(value.loc) ? value.loc[value.loc.length - 1] : '') ?? '')
      const detail = String(value.message ?? value.msg ?? '')
      return `${fieldLabel(field)}: ${language.value === 'zh-CN' ? (errorZh[detail] ?? '输入值无效') : detail}`
    }).join('; ')
  }
  return String(message)
}
