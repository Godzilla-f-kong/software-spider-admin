export type InputType = 'text' | 'textarea' | 'number' | 'date' | 'select' | 'switch'
export interface Field {
  key: string
  label: string
  type?: InputType
  required?: boolean
  options?: readonly string[]
  readonly?: boolean
}
export interface ResourceConfig {
  title: string
  path: string
  fields: Field[]
  columns: string[]
  columnLabels?: Record<string, { zh: string; en: string }>
  search?: boolean
  filters?: string[]
  filterOptions?: Record<string, readonly string[]>
}

const field = (key: string, label: string, type: InputType = 'text', options?: readonly string[], required = false): Field => ({ key, label, type, options, required })
const statuses = {
  candidate: ['DISCOVERED', 'REVIEWING', 'ACCEPTED', 'REJECTED', 'IGNORED'],
  software: ['ACTIVE', 'DISABLED', 'ARCHIVED'],
  source: ['NEW', 'HEALTHY', 'FAILED', 'DISABLED'],
  release: ['DISCOVERED', 'PROCESSING', 'READY', 'PUBLISHED', 'REJECTED'],
  download: ['NOT_DOWNLOADED', 'QUEUED', 'DOWNLOADING', 'DOWNLOADED', 'FAILED'],
  storage: ['PENDING', 'UPLOADING', 'AVAILABLE', 'FAILED', 'EXPIRED'],
  content: ['NOT_GENERATED', 'GENERATING', 'DRAFT', 'REVIEWED', 'APPROVED', 'PUBLISHED'],
  listing: ['DRAFT', 'REVIEW_REQUIRED', 'APPROVED', 'PUBLISHED', 'PAUSED', 'REMOVED'],
  job: ['PENDING', 'RUNNING', 'PAUSED', 'SUCCESS', 'FAILED', 'CANCELLED'],
}

export const resources: Record<string, ResourceConfig> = {
  candidates: { title: '软件候选池', path: 'candidates', search: true, filters: ['status'], columns: ['id', 'name', 'target_version', 'target_os', 'target_architecture', 'category', 'priority_score', 'status', 'automatic_crawl_status', 'software_id', 'created_at'], columnLabels: { id: { zh: '候选记录 ID', en: 'Candidate ID' }, automatic_crawl_status: { zh: '自动抓取任务', en: 'Automatic crawl' }, software_id: { zh: '已收录软件 ID', en: 'Accepted software ID' } }, fields: [
    field('name', '软件名称', 'text', undefined, true), field('category', '软件分类'), field('source_platform', '人工备注平台'), field('source_url', '候选参考 URL（可空）'),
    field('target_version', '目标版本（可空）'), field('target_os', '目标操作系统', 'select', ['WINDOWS', 'LINUX', 'MACOS', 'ANDROID', 'OTHER']),
    field('target_architecture', '目标 CPU 架构', 'select', ['X86', 'X64', 'ARM', 'ARM64', 'UNIVERSAL', 'OTHER']),
    field('sales_signal', '销售线索', 'textarea'), field('search_signal', '搜索线索', 'textarea'), field('competition_signal', '竞争线索', 'textarea'),
    field('commercial_score', '商业评分', 'number'), field('seo_score', 'SEO 评分', 'number'), field('brand_relevance_score', '品牌相关评分', 'number'), field('priority_score', '优先级评分', 'number'),
    field('status', '状态', 'select', statuses.candidate),
  ] },
  software: { title: '已抓取软件', path: 'software', search: true, filters: ['status', 'category', 'origin_region'], columns: ['id', 'name', 'developer', 'category', 'origin_region', 'license', 'status', 'latest_release', 'updated_at'], fields: [
    field('name', '软件名称', 'text', undefined, true), field('slug', '唯一标识 Slug', 'text', undefined, true), field('developer', '开发者 / 维护组织'), field('category', '软件分类'),
    field('origin_region', '国内/国外', 'select', ['DOMESTIC', 'FOREIGN', 'UNKNOWN'], true), field('license', '许可证'), field('official_url', '官网 URL'), field('summary', '摘要', 'textarea'), field('description', '描述', 'textarea'), field('status', '状态', 'select', statuses.software),
  ] },
  'crawl-pools': { title: 'URL 抓取池', path: 'crawl-pools', search: true, filters: ['enabled', 'status'],
    filterOptions: { enabled: ['true', 'false'], status: statuses.source },
    columns: ['id', 'base_url', 'enabled', 'max_pages', 'max_depth', 'last_result_count', 'status', 'last_checked_at', 'last_error'], fields: [
      field('base_url', '网站主页 URL', 'text', undefined, true), field('enabled', '启用', 'switch'),
      field('max_pages', '单次请求预算（可续扫）', 'number'), field('max_depth', '站内最大链接深度', 'number'),
      field('search_path_template', '站内搜索路径模板（{query}）'), field('category_paths', '分类入口路径（每行一个）', 'textarea'),
    ] },
  sources: { title: '已收录软件来源', path: 'sources', filters: ['software_id', 'source_type'], columns: ['id', 'software_name', 'software_id', 'source_type', 'source_url', 'adapter_type', 'priority', 'enabled', 'status', 'automation_status', 'last_checked_at', 'last_success_at', 'last_error'], fields: [
    field('software_id', '所属软件 ID', 'number', undefined, true), field('source_type', '来源类别', 'select', ['OFFICIAL', 'OFFICIAL_DOWNLOAD', 'GITHUB', 'MIRROR', 'OTHER'], true),
    field('source_url', '待抓取页面 URL', 'text', undefined, true), field('adapter_type', '抓取适配器类型', 'select', ['MANUAL', 'GENERIC_HTML', 'GITHUB_RELEASE', 'JSON_API', 'STATIC_URL', 'BROWSER']),
    field('priority', '优先级', 'number'), field('enabled', '启用', 'switch'), field('status', '状态', 'select', statuses.source),
    field('automation_status', '自动访问状态', 'select', ['UNKNOWN', 'ALLOWED', 'MANUAL_REQUIRED', 'DISABLED']),
  ] },
  releases: { title: '软件版本', path: 'releases', search: true, filters: ['software_id', 'status'], columns: ['id', 'software_name', 'software_id', 'version', 'release_date', 'is_latest', 'status', 'created_at'], fields: [
    field('software_id', '所属软件 ID', 'number', undefined, true), field('version', '版本号', 'text', undefined, true), field('release_date', '正式发布日期', 'date'),
    field('release_notes', '版本说明', 'textarea'), field('is_latest', '最新版本', 'switch'), field('status', '状态', 'select', statuses.release),
  ] },
  variants: { title: '版本运行环境', path: 'variants', filters: ['release_id', 'os', 'architecture', 'cpu_family'], columns: ['id', 'software_name', 'release_id', 'os', 'architecture', 'cpu_family', 'edition', 'language', 'min_os_version'], fields: [
    field('release_id', '所属软件版本 ID', 'number', undefined, true), field('os', '目标操作系统', 'select', ['WINDOWS', 'LINUX', 'MACOS', 'ANDROID', 'OTHER', 'UNKNOWN'], true),
    field('architecture', '系统架构', 'select', ['X86', 'X64', 'ARM', 'ARM64', 'UNIVERSAL', 'OTHER', 'UNKNOWN'], true), field('cpu_family', 'CPU 架构族', 'select', ['AMD', 'ARM', 'UNKNOWN'], true), field('edition', '版本类型'),
    field('language', '语言', 'select', ['ZH', 'EN', 'UNKNOWN']), field('min_os_version', '最低 OS 版本'), field('notes', '备注', 'textarea'),
  ] },
  artifacts: { title: '安装包文件', path: 'artifacts', search: true, filters: ['variant_id', 'download_status'],
    filterOptions: { download_status: statuses.download }, columns: ['id', 'software_name', 'variant_id', 'package_type', 'install_type', 'filename', 'md5', 'file_size', 'download_status', 'local_exists'], fields: [
    field('variant_id', '所属运行环境 ID', 'number', undefined, true), field('package_type', '安装包格式', 'select', ['EXE', 'MSI', 'ZIP', 'SEVEN_Z', 'TAR_GZ', 'TAR_XZ', 'DMG', 'PKG', 'DEB', 'RPM', 'APPIMAGE', 'OTHER'], true),
    field('install_type', '免安装/安装包', 'select', ['PORTABLE', 'INSTALLER', 'UNKNOWN'], true), field('filename', '文件名', 'text', undefined, true), field('file_size', '字节大小', 'number'), field('source_url', '下载 URL'),
  ] },
  storage: { title: '文件存储位置', path: 'storage', filters: ['artifact_id', 'provider', 'status'], columns: ['id', 'software_name', 'artifact_id', 'provider', 'remote_path', 'share_url', 'status'], fields: [
    field('artifact_id', '所属安装包 ID', 'number', undefined, true), field('provider', '存储服务提供方', 'select', ['LOCAL', 'BAIDU', 'PAN123', 'SELF_HOSTED', 'S3', 'OTHER'], true),
    field('remote_path', '远程路径'), field('remote_file_id', '远程文件 ID'), field('share_url', '分享链接'), field('share_code', '分享码'), field('status', '状态', 'select', statuses.storage),
  ] },
  content: { title: '生成内容草稿', path: 'content', search: true, filters: ['software_id', 'content_type', 'status'], columns: ['id', 'software_name', 'software_id', 'release_id', 'content_type', 'title', 'status', 'updated_at'], fields: [
    field('software_id', '所属软件 ID', 'number', undefined, true), field('release_id', '关联软件版本 ID', 'number'), field('content_type', '内容用途', 'select', ['WEBSITE', 'XIANYU', 'TAOBAO', 'VERSION_NOTICE'], true),
    field('skill_name', 'Skill 名称'), field('skill_version', 'Skill 版本'), field('title', '标题'), field('content', '正文', 'textarea'), field('status', '状态', 'select', statuses.content),
  ] },
  listings: { title: '电商发布文案', path: 'listings', search: true, filters: ['software_id', 'platform', 'status'], columns: ['id', 'software_name', 'software_id', 'platform', 'title', 'price', 'status', 'published_at'], fields: [
    field('software_id', '所属已抓取软件 ID', 'number', undefined, true), field('release_id', '关联软件版本 ID', 'number'), field('platform', '电商发布渠道', 'select', ['XIANYU', 'TAOBAO'], true),
    field('generated_content_id', '关联内容 ID', 'number'), field('title', '标题', 'text', undefined, true), field('description', '描述', 'textarea'),
    field('price', '价格', 'number'), field('listing_url', '链接'), field('status', '状态', 'select', statuses.listing),
  ] },
  jobs: { title: '后台任务', path: 'jobs', filters: ['job_type', 'status'],
    filterOptions: { status: statuses.job }, columns: ['id', 'job_type', 'target_type', 'target_id', 'status', 'progress', 'bytes_downloaded', 'total_bytes', 'speed_bytes_per_second', 'message', 'created_at', 'started_at', 'finished_at'], fields: [
    field('job_type', '任务类型', 'select', ['CRAWL', 'CHECK_RELEASE', 'DOWNLOAD', 'UPLOAD_STORAGE', 'UPLOAD_BAIDU', 'REGISTER_SHARE_LINK', 'GENERATE_WEBSITE', 'GENERATE_XIANYU', 'GENERATE_TAOBAO', 'PUBLISH_WEBSITE'], true),
    field('target_type', '任务目标类型', 'select', ['candidate', 'software', 'source', 'release', 'variant', 'artifact', 'share_link_submission', 'content', 'listing'], true), field('target_id', '任务目标记录', 'number', undefined, true), field('message', '备注'),
  ] },
}

resources.links = { title: '\u7f51\u76d8\u4e0e\u4e0b\u8f7d\u5165\u53e3', path: 'links', search: true,
  columnLabels: { provider: { zh: '\u7f51\u76d8\u5e73\u53f0', en: 'Link provider' } },
  filters: ['software_id', 'source_id', 'provider', 'review_status'],
  columns: ['id', 'software_name', 'software_id', 'source_id', 'release_id', 'provider', 'link_type', 'link_url', 'access_code', 'review_status'],
  fields: [field('software_id', '\u8f6f\u4ef6 ID', 'number', undefined, true),
    field('source_id', '\u6765\u6e90 ID', 'number', undefined, true),
    field('release_id', '\u7248\u672c ID', 'number'),
    field('provider', '\u7f51\u76d8\u5e73\u53f0', 'select', ['QUARK', 'XUNLEI', 'BAIDU', 'PAN123', 'ALIYUN', 'LANZOU', 'OTHER']),
    field('link_type', '\u94fe\u63a5\u7c7b\u578b', 'select', ['PAN_SHARE', 'DOWNLOAD_PAGE', 'DIRECT_FILE']),
    field('link_url', '\u5206\u4eab\u6216\u4e0b\u8f7d\u94fe\u63a5', 'text', undefined, true),
    field('source_page_url', '\u53d1\u73b0\u9875\u9762 URL'), field('access_code', '\u8bbf\u95ee\u7801'),
    field('label', '\u94fe\u63a5\u6587\u5b57'), field('context_text', '\u9875\u9762\u6587\u6848', 'textarea'),
    field('review_status', '\u5ba1\u6838\u72b6\u6001', 'select', ['DISCOVERED', 'REVIEWED', 'IGNORED'])] }

export const labels: Record<string, string> = Object.fromEntries(Object.values(resources).flatMap(r => r.fields.map(f => [f.key, f.label])))
Object.assign(labels, {
  automation_status: '自动访问状态', last_error: '最近抓取错误', last_checked_at: '最近检查时间', last_success_at: '最近成功时间',
  id: '记录 ID', created_at: '记录创建时间', updated_at: '最近更新时间', latest_release: '最新软件版本号',
  software_name: '软件名称',
  progress: '任务完成进度', started_at: '任务开始时间', finished_at: '任务结束时间',
  sales_signal: '商业销售线索', search_signal: '搜索热度线索',
  competition_signal: '市场竞争线索', commercial_score: '商业价值评分', seo_score: '搜索引擎优化评分',
  brand_relevance_score: '品牌相关度评分', priority_score: '候选优先级评分',
  official_url: '官方网站 URL', summary: '软件简介', description: '详细描述', license: '软件许可证',
  release_notes: '版本更新说明', is_latest: '是否为当前最新版本', edition: '软件发行版 / Edition',
  language: '安装包语言', min_os_version: '最低操作系统版本', file_size: '安装包大小（字节）',
  source_url: '来源页面 / 下载 URL', local_path: '本机归档文件路径', sha256: 'SHA-256 文件校验值',
  md5: 'MD5 文件校验值', remote_path: '存储服务中的文件路径', remote_file_id: '存储服务文件 ID',
  share_url: '网盘分享链接', share_code: '网盘分享提取码', content_type: '文案投放用途',
  skill_name: '内容生成 Skill 名称', skill_version: '内容生成 Skill 版本', generated_content_id: '关联生成文案 ID',
  price: '商品标价', listing_url: '电商商品页面 URL', generated_at: '文案生成时间',
  reviewed_at: '人工审核时间', published_at: '商品发布时间', job_type: '后台任务类型',
  target_type: '任务处理对象类型', target_id: '任务处理对象 ID', error_message: '任务错误详情',
  payload: '任务输入参数', result: '任务执行结果', source_type: '抓取来源类别',
  adapter_type: '抓取适配器类型', priority: '来源优先级', enabled: '是否参与抓取', release_date: '正式发布日期',
  os: '目标操作系统', architecture: '目标 CPU 架构', package_type: '安装包格式', filename: '安装包文件名',
  provider: '文件存储服务', software_id: '关联已抓取软件 ID', release_id: '关联软件版本 ID',
  variant_id: '关联版本运行环境 ID', artifact_id: '关联安装包文件 ID', status: '当前记录状态',
  local_exists: '本机文件存在',
  download_status: '下载状态',
  bytes_downloaded: '已下载字节数', total_bytes: '总字节数', speed_bytes_per_second: '平均下载速度（字节/秒）',
  version: '软件版本号', title: '文案标题', content: '文案正文', platform: '发布平台', message: '任务进度说明',
})
