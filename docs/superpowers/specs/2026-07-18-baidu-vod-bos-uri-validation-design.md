# 百度 VOD BOS URI 校验修复设计

## 背景

百度 VOD 页面先把视频上传到百度 BOS，上传结果使用 `bos://bucket/key`。创建任务接口仍复用了阿里云 OSS 的 `oss://` 校验，导致已成功上传的 BOS 对象在 `POST /api/baidu-vod` 阶段被错误返回 400。

## 目标

- 创建百度 VOD 任务时接受 `bos://` 输入并拒绝 `oss://` 输入。
- 保持请求字段 `oss_uri` 和现有 `items_json` 兼容，不进行数据库迁移。
- 将上传结果同步保存到 `input_bos_key` 和 `input_bos_uri`，供详情与后续扩展使用。
- 不改变 runner 的拉取方式；runner 继续使用已验证可公网访问的 `input_public_url`。

## 方案

在 `create_baidu_vod_job` 中把 URI 前缀校验从 `oss://` 改为 `bos://`。构造 item 时保留 `input_oss_uri=spec.oss_uri` 作为兼容字段，同时设置 `input_bos_key=spec.key` 和 `input_bos_uri=spec.oss_uri`。不重命名 API 类型或数据库 JSON 字段，避免扩大改动范围。

## 错误处理

非 `bos://` URI 返回 400，错误信息使用 `非法的视频 bos_uri`，让调用方能够直接识别协议要求。其他创建任务校验与后台执行行为保持不变。

## 测试

- 回归测试：携带 `bos://` item 创建任务返回 201，并断言响应保存正确的 `input_bos_key/input_bos_uri`。
- 反向测试：携带 `oss://` item 返回 400。
- 运行完整后端测试集和前端生产构建。
- 按仓库要求将后端变更部署到本机生产目录并重启服务，再验证健康接口。
