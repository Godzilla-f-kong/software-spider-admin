# 外部网盘分享链接登记

该流程把爬虫发现的第三方网盘分享地址和提取码登记到局域网云盘的永久分享库。它不传输安装包文件，不依赖 Artifact 是否已下载或验证；本地文件上传仍使用独立的 Artifact Storage 流程。

## 处理流程

1. `DownloadLink` 或候选抓取 Job 结果中的网盘链接进入完整性检查。
2. 完整记录进入 `READY`，缺少必需数据的记录进入 `INCOMPLETE` 并保存问题说明。
3. `REGISTER_SHARE_LINK` Job 在单 worker 后台调用云盘创建接口。
4. 云盘成功响应中的记录 ID、token、永久分享地址和 `reused` 标志回写到登记记录。

提取码必须符合云盘服务当前实现的四位字母或数字格式。外链必须是没有嵌入用户名/密码的绝对 HTTP/HTTPS URL。完整性检查不会访问第三方分享页。

## 配置

在项目根目录 `.env` 中设置：

```ini
SELF_HOSTED_BASE_URL=http://192.168.0.100:9000
CLOUD_INTEGRATION_API_KEY=由云盘后端管理员配置的集成密钥
CLOUD_SHARELINK_PATH=/sharelink/create-online
```

`CLOUD_INTEGRATION_API_KEY` 与文件分片上传使用的 `SELF_HOSTED_API_KEY` 是不同用途的密钥。设置页只显示集成接口是否已配置，不返回密钥内容。修改 `.env` 后需要重启 Backend。

当 `SELF_HOSTED_BASE_URL` 直接指向云盘服务（例如 `http://192.168.0.100:9000`）时，使用 `/sharelink/create-online`。只有经过将 `/api` 转发到该服务的反向代理时，才将路径设为 `/api/sharelink/create-online`。登记请求会绕过当前机器的系统 HTTP 代理，直接访问配置的云盘地址。

云盘服务端还必须配置同一个 `CLOUD_INTEGRATION_API_KEY`。未配置时服务端返回 503，密钥不匹配时返回 401。

## 管理 API

- `GET /api/v1/share-links`：分页查询登记记录，可按 `status` 和 `search` 筛选。
- `POST /api/v1/share-links/check`：扫描已存 `DownloadLink` 和保留的候选/URL 池抓取 Job 结果，记录 READY/INCOMPLETE 状态，不调用云盘。
- `PATCH /api/v1/share-links/{id}`：补全不完整记录的名称、外链和提取码。
- `POST /api/v1/share-links/{id}/register`：登记单条链接。
- `POST /api/v1/share-links/register-ready`：将完整且尚未成功的 READY 记录排入后台任务。

调用云盘时请求包含 `softwareName`、`external_url`、`extractCode` 和 `filetype=5`；文件名、分类、操作系统、架构、MD5、安装方式、文件大小只在有可靠来源时传递。云盘负责固定 owner、在线来源、永久有效期和下载策略。

## 重试与故障处理

网络超时或 Backend 意外退出时，记录状态为 `UNKNOWN`，因为云盘可能已经创建了永久记录。云盘接口按外链、提取码和固定 owner 查询可复用记录；重试时优先获得已有记录。401/503 等确定响应保存为失败状态，可修正配置后重试。

历史 Job 结果只有在数据库中仍保留时才能回填。缺少提取码或格式不完整的分享链接不会提交给云盘。
