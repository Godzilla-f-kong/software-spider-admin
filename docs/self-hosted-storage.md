# 局域网云盘对接

管理平台后端通过 `SELF_HOSTED` Provider 将本地已验证 Artifact 上传到云盘服务 `http://192.168.0.100:9000`。浏览器不直接连接云盘。上传由 `UPLOAD_STORAGE` Job 在后台完成。

## 配置

在管理平台 `.env` 设置：

```dotenv
SELF_HOSTED_BASE_URL=http://192.168.0.100:9000
SELF_HOSTED_API_KEY=<与云盘服务端一致的随机密钥>
SELF_HOSTED_USERNAME=<云盘中已初始化的服务账号>
SELF_HOSTED_CHUNK_SIZE=4194304
SELF_HOSTED_TIMEOUT=120
```

在云盘服务端运行环境设置同一密钥 `CLOUD_INTEGRATION_API_KEY`，并设置 `CLOUD_INTEGRATION_USERNAME`。两端密钥必须一致。请通过安全配置渠道生成并保存密钥，不要提交 `.env`。

云盘服务账号必须已经存在，且旧媒体类型 `filetype=5`（其他文件）的计数行已经初始化。`sql/add_file_arch.sql` 会检查列是否已存在，可安全重跑；确认该脚本对实际云盘数据库执行成功后，再重启更新后的云盘服务。

## API 流程

1. Artifact 必须已 `VERIFIED`，管理页面选择 `file_arch` 的 21 个软件类别之一。
2. 管理平台创建一个 `UPLOAD_STORAGE` Job 和 `SELF_HOSTED` 的 `ArtifactStorage` 记录。
3. Provider 按块调用 `POST /integration/file/chunk`，请求头使用 `X-Integration-Key`。旧接口首片返回成功标记，中间片成功时返回空对象，末片返回完成标记和 FastDFS 路径。
4. 最后一块返回 FastDFS 路径后，调用 `POST /integration/file/complete`，云盘端幂等登记 `filelist` 元数据及 `file_arch`。
5. 成功后 `ArtifactStorage.remote_path` 保存 FastDFS 路径，`remote_file_id` 保存云盘文件 ID，`remote_parent_id` 保存类别。

私有云盘归档仅要求 Artifact 已验证；百度网盘上传和公开分享仍按原有再分发许可门槛处理。

## 限制

- 云盘现有文件元数据使用 Java `int filesize`，当前限制为不超过 `2,147,483,647` 字节。
- 云盘旧分片实现不是可恢复分片协议。中断后任务会失败；若服务端留下不完整 FastDFS 文件，需要清理后再重试。
- FastDFS 上传与数据库登记是两个阶段。若上传成功而 complete 请求失败，文件会留在 FastDFS；重试 complete 可按 owner 和 fileindex 防止重复登记。
- 运行环境应限制云盘服务只接受可信局域网来源。集成 API Key 保护新增的 `/integration/file/*` 路由；旧用户路由仍由云盘原有安全边界管理。
- 如果上传任务在第一个分片失败，先检查管理后端到 `SELF_HOSTED_BASE_URL` 的 TCP 连通性及其代理环境，再根据 Job 错误中的 HTTP 状态、连接异常类型或 JSON 错误定位问题。云盘端没有收到请求时，优先排查地址、服务监听和代理；不要通过反复重试掩盖连接故障。
- 如果分片上传到 99% 后元数据登记失败，根据 Job 中 `/complete` 的 HTTP 状态或连接异常定位。云盘端需确认集成账号存在、`filelist.file_arch` 列已创建，且该账号有 `filetype=5` 统计行；分片已写入 FastDFS 时，重试整次上传可能留下未登记文件。

## 上传日志

- 管理端后端控制台会记录失败的 `job_id`、`artifact_id`、Provider、错误码及异常链；Job 页面只显示安全的错误摘要。
- 云盘后端控制台会记录每片的序号、HTTP 状态及结果；`/complete` 会记录 `lookup`、`insert_filelist`、`update_filetype`、`reload_filelist` 中实际失败的阶段。日志不包含集成密钥或文件内容。
- `/complete` 返回 HTTP 409 时，查找云盘日志中的 `Cloud metadata registration blocked stage=update_filetype filetype=5 affectedRows=0`，并核对集成账号在 `filetype` 表中是否有 `filetype=5` 记录。
