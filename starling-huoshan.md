可以。下面给出一套以 **Starling 作为唯一处理平台**的完整技术路线，目标是：

> 用户上传一部短剧的全部分集，只填写一次表单，系统自动完成字幕提取、字幕翻译、字幕擦除、多角色配音、字幕烧录、成片压制和结果归档。

Starling 已把短剧项目、视频上传、完整翻配任务、AI 流程触发、字幕编辑、角色管理、配音生成、视频压制和产物获取拆成一套 API。产品本身定位就是企业级多语言短剧翻译与配音全链路平台。([火山引擎][1])

---

# 一、最终业务流程

```text
用户创建翻配任务
        │
        ├── 上传第 1～N 集视频
        ├── 选择源语言、目标语言
        ├── 选择字幕擦除等级
        ├── 选择配音模式
        ├── 选择字幕样式
        └── 选择全自动/人工审核模式
                │
                ▼
你的后端创建内部 WorkflowJob
                │
                ▼
创建或复用 Starling Project
                │
                ▼
上传全部分集视频
                │
                ▼
创建 Starling 完整翻配任务
                │
                ▼
Starling 自动执行
    ├── AI 听录/字幕提取
    ├── 术语提取
    ├── 字幕翻译
    ├── 字幕擦除
    ├── 多角色识别
    ├── 多角色目标语言配音
    └── 音频时间轴对齐
                │
                ▼
自动质量检测
                │
        ┌───────┴────────┐
        │                │
      通过             不通过
        │                │
        ▼                ▼
自动确认校对       自动重试/进入人工审核
        │
        ▼
字幕和配音成片压制
        │
        ▼
获取成品视频、音频、字幕、净版视频
        │
        ▼
归档并通知用户
```

---

# 二、核心对象关系

Starling 中至少需要理解四个对象：

```text
Project
    一部短剧的项目容器

Video
    某一集原视频

Task
    一次完整翻配任务，例如中文整剧翻译成英文

SubTask
    某一集 × 某个目标语言的实际处理单元
```

推荐映射：

```text
一个 Starling Project
= 一部短剧

一个 Video
= 一集视频

一个 SubTask
= 一集 × 一种目标语言
```

例如：

```text
Project：总裁的替嫁新娘
├── 第 1 集 → 英语 SubTask
├── 第 2 集 → 英语 SubTask
├── 第 3 集 → 英语 SubTask
├── 第 1 集 → 西班牙语 SubTask
└── 第 2 集 → 西班牙语 SubTask
```

官方也建议按“每部剧”维度创建短剧项目。([火山引擎][2])

---

# 三、用户只填写一次的表单

建议前端表单分为五部分。

## 1. 短剧信息

```text
短剧名称
源语言
分集编号规则
分集视频文件
```

例如：

```text
短剧名称：总裁的替嫁新娘
源语言：中文
视频：
  episode_001.mp4
  episode_002.mp4
  episode_003.mp4
```

## 2. 目标语言

```text
☑ 英语
☐ 西班牙语
☐ 葡萄牙语
☐ 泰语
☐ 印尼语
```

第一版建议一次只选一个目标语言。多语言可以后续复用原项目增加任务，避免调试复杂度。

## 3. 字幕处理

```text
字幕提取：
● Starling AI 自动听录

字幕擦除：
○ 不擦除
● 基础擦除
○ 高级擦除

目标字幕：
☑ 烧录到视频

字幕样式：
默认白字黑边
```

## 4. 配音配置

```text
多角色配音：开启

角色策略：
● 自动识别角色
○ 复用已有整剧角色

配音模式：
● 标准配音
○ 高情感配音

背景声音：
☑ 保留音乐和环境音
```

## 5. 工作流配置

```text
处理模式：
● 全自动成片
○ AI 完成后人工审核

失败自动重试：2 次

质检失败处理：
● 转人工审核
○ 直接标记失败
```

前端最终只调用你自己的一个接口：

```http
POST /api/v1/drama-workflows
```

内部请求可以设计为：

```json
{
  "dramaName": "总裁的替嫁新娘",
  "sourceLanguage": "zh",
  "targetLanguages": ["en"],
  "episodeIds": [
    "episode_001",
    "episode_002",
    "episode_003"
  ],
  "subtitle": {
    "transcriptionMode": "STARLING_AI",
    "removeMode": "BASIC",
    "burnTargetSubtitle": true,
    "styleTemplateId": "white-black-outline-v1"
  },
  "dubbing": {
    "enabled": true,
    "speakerMode": "AUTO_MULTI_SPEAKER",
    "emotionMode": "STANDARD",
    "preserveBackgroundAudio": true
  },
  "workflow": {
    "mode": "FULLY_AUTOMATIC",
    "maxRetryCount": 2,
    "qcFailureAction": "MANUAL_REVIEW"
  }
}
```

这不是 Starling 的参数，而是你自己的稳定业务 DTO。后端再把它转换成 Starling 当前版本的请求参数。

---

# 四、总体技术架构

推荐架构：

```text
┌────────────────────────────┐
│ Vue / React 运营后台       │
└──────────────┬─────────────┘
               │
               ▼
┌────────────────────────────┐
│ API Gateway                │
│ 鉴权、限流、请求校验       │
└──────────────┬─────────────┘
               │
               ▼
┌────────────────────────────┐
│ Drama Workflow Service     │
│                            │
│ 任务创建                   │
│ 配置版本管理               │
│ 状态机                     │
│ 幂等                       │
│ 自动重试                   │
│ 费用预算                   │
└──────────────┬─────────────┘
               │
        ┌──────┴────────┐
        ▼               ▼
┌───────────────┐  ┌────────────────┐
│ Starling      │  │ Quality Worker │
│ Adapter       │  │ 自动质检       │
└───────┬───────┘  └────────┬───────┘
        │                    │
        ▼                    ▼
┌──────────────────────────────────┐
│ Starling OpenAPI                 │
│                                  │
│ Project / Upload / Task          │
│ Subtitle / Speaker / Dubbing     │
│ Suppression / Product            │
└──────────────────────────────────┘

基础设施：
PostgreSQL
Redis
消息队列
对象存储
Webhook Receiver
定时轮询器
日志与指标平台
```

---

# 五、推荐技术栈

按照你已有技术背景，建议：

## 后端

```text
Spring Boot 3
Java 21
PostgreSQL
Redis
Temporal 或消息队列状态机
MyBatis / JPA
```

## 工作流引擎

首选：

```text
Temporal Java SDK
```

原因是整个任务可能持续几分钟到几十分钟，包含：

* 多个外部异步 API；
* 轮询；
* Webhook；
* 超时；
* 重试；
* 分集并行；
* 单集失败补偿；
* 人工审核暂停。

这类任务不适合写成一个普通的 `@Async` 方法。

不使用 Temporal 时，也可以使用：

```text
Spring Boot
+ PostgreSQL 状态表
+ RabbitMQ / Kafka
+ XXL-JOB / Quartz
```

但需要自己处理状态恢复、定时器和重试幂等。

## 文件存储

建议保留自己的对象存储：

```text
原始视频
最终视频
字幕文件
配音音频
任务请求快照
任务响应快照
```

即使 Starling 返回可访问 URL，也不要永久依赖第三方 URL。

## 媒体检测

使用 FFmpeg/FFprobe，但不承担正式翻配：

```text
ffprobe：检查分辨率、时长、轨道
ffmpeg：必要时切片、格式标准化、结果验证
```

---

# 六、Starling API 完整调用路线

官方 API 清单包含项目创建、视频上传、完整短剧任务、任务查询、AI 流程触发、字幕、角色、配音、压制和产物获取。

## 阶段 1：创建或复用短剧项目

调用：

```text
VideoProjectCreate
```

官方固定参数包括：

```text
Action = VideoProjectCreate
Version = 2021-05-21
projectType = 1
```

其中 `projectType=1` 表示短剧项目。([火山引擎][3])

业务逻辑：

```text
查询本地 Drama.starlingProjectId
        │
        ├── 已存在 → 直接复用
        │
        └── 不存在 → 创建 Starling Project
```

请求概念结构：

```json
{
  "name": "总裁的替嫁新娘",
  "comment": "中文短剧英语翻配",
  "projectType": 1
}
```

本地保存：

```text
starling_project_id
```

---

## 阶段 2：上传各集视频

调用：

```text
VideoProjectVideoUpload
```

查询：

```text
VideoProjectGetVideoUploadStatus
```

官方将视频上传与查询上传进度作为两个独立接口。

建议上传流程：

```text
原视频
    ↓
FFprobe 预检查
    ↓
上传或向 Starling 提供文件 URL
    ↓
获得 uploadBatchId / videoId
    ↓
轮询上传状态
    ↓
保存 Starling Video ID
```

上传前验证：

```text
文件可访问
格式正确
有视频轨
有音频轨
时长大于 0
分辨率符合要求
视频文件名和集数对应
```

本地 Episode 表保存：

```text
source_file_key
source_file_hash
starling_video_id
upload_batch_id
upload_status
duration_ms
width
height
```

---

## 阶段 3：创建完整翻配任务

调用：

```text
VideoProjectSerialTaskCreate
```

这是完整短剧任务入口。独立配音任务另有 `VideoProjectSerialDubTaskCreate`，所以完全使用 Starling 时应走前者。([火山引擎][4])

任务参数应覆盖：

```text
Project ID
分集列表
源语言
目标语言
字幕提取
字幕翻译
字幕擦除
多角色配音
术语库
字幕样式或后续压制配置
```

概念结构：

```json
{
  "projectId": 123456,
  "taskName": "总裁的替嫁新娘-en-v1",
  "sourceLanguage": "zh",
  "targetLanguages": ["en"],
  "serialInfo": [
    {
      "episode": 1,
      "videoId": "video_001"
    },
    {
      "episode": 2,
      "videoId": "video_002"
    }
  ],
  "translationConfig": {
    "enableTranscription": true,
    "enableTranslation": true,
    "termBaseId": 123
  },
  "videoConfig": {
    "subtitleRemovalMode": "BASIC"
  },
  "dubbingConfig": {
    "enabled": true,
    "multiSpeaker": true,
    "emotionMode": "STANDARD"
  }
}
```

这只是你内部的参数映射示意。

**生产代码不要手写猜测 Starling 的最终 JSON Schema。**官方文档部分页面依赖动态渲染，建议从当前 OpenAPI 在线调试器或最新官方 SDK 生成请求模型，并把 Starling DTO 封装在独立 Adapter 模块中。

---

## 阶段 4：触发 AI 流程

部分任务创建后会自动运行，部分流程可能需要调用：

```text
VideoProjectTaskBatchStartAIFlow
```

官方提供该接口用于批量触发 AI 翻译流程。([火山引擎][5])

你的编排逻辑不应该简单地：

```text
创建任务
→ 无条件调用 BatchStartAIFlow
```

而应该：

```text
创建任务
    ↓
查询任务详情
    ↓
任务已经运行？
    ├── 是 → 等待
    └── 否且处于可触发状态
            ↓
      BatchStartAIFlow
```

这样可以防止重复触发和重复计费。

---

## 阶段 5：查询任务状态

调用：

```text
VideoProjectTaskDetail
VideoProjectTaskList
```

官方分别提供任务详情和任务列表接口。

外部 Starling 状态不要直接作为你的业务状态。你应转换成内部状态机。

---

# 七、内部状态机设计

建议内部状态：

```text
CREATED

PROJECT_CREATING
PROJECT_READY

VIDEO_UPLOADING
VIDEO_READY

STARLING_TASK_CREATING
STARLING_TASK_READY

AI_FLOW_STARTING
AI_PROCESSING

TRANSCRIPTION_READY
TRANSLATION_READY
CLEAN_VIDEO_READY
DUBBING_READY

AUTOMATIC_QC
WAITING_REVIEW
REVIEW_COMPLETED

SUPPRESSION_STARTING
SUPPRESSING

PRODUCT_FETCHING
ARCHIVING

COMPLETED
FAILED
```

但 Starling 不一定把听录、翻译、擦除和配音分别暴露成完全独立的状态，所以你的状态可以再简化为：

```text
UPLOADING
AI_PROCESSING
QUALITY_CHECKING
SUPPRESSING
COMPLETED
FAILED
```

不要根据预计耗时伪造“正在字幕翻译”等状态。

---

# 八、字幕提取和翻译流程

完整 Starling 方案不再调用阿里云。

Starling 内部生成字幕后，你的后端通过：

```text
VideoEditorListSubtitles
```

获取逐句字幕。

还可以通过：

```text
VideoEditorDownloadSubtitleFileUrl
```

取得字幕文件。官方开放了字幕列表、实时保存、下载、添加和批量添加等接口。

建议把字幕同步到自己的数据库：

```text
SubtitleSegment
├── starling_segment_id
├── start_ms
├── end_ms
├── source_text
├── target_text
├── speaker_id
├── emotion
├── status
└── version
```

自动检查：

```text
源字幕数量 > 0
目标字幕数量 > 0
字幕开始时间 < 结束时间
字幕不超过视频时长
字幕覆盖率在合理范围
目标语言中未翻译源语言字符比例低
```

---

# 九、术语和人名一致性

Starling 的完整翻配任务支持术语相关流程；官方还提供术语库查询、导入和查询导入进度接口。

相关接口：

```text
VideoTermBases
TermBaseTermGroups
TermBaseTermGroupImport
TermBaseTermGroupImportTask
```

推荐在一部短剧正式全量处理前，创建术语库：

```text
顾辰 → Ethan Gu
苏晚 → Sophia Su
陆氏集团 → Lu Group
帝都 → Imperial City
```

技术路线：

```text
创建短剧
    ↓
用户可选上传人物表/术语表
    ↓
导入 Starling 术语库
    ↓
等待术语导入完成
    ↓
创建完整翻配任务并绑定术语库
```

术语库必须版本化：

```text
term_base_version = 1
```

术语改变后，不要默默修改正在运行的任务。

---

# 十、多人角色和跨集一致性

Starling 提供以下角色 API：

```text
VideoEditorGetSpeakers
VideoEditorAddSpeaker
VideoEditorUpdateSpeaker
VideoEditorDeleteSpeaker
VideoEditorSyncSpeakerToSubTask
```

其中明确提供“本剧角色同步至本集”，适合整剧角色复用。

## 全自动角色方案

第一集或首批代表性分集处理完成后：

```text
GetSpeakers
    ↓
获取自动识别的角色
    ↓
保存为本剧角色库
    ↓
后续各集调用 SyncSpeakerToSubTask
```

本地表：

```text
DramaSpeaker
├── id
├── drama_id
├── starling_speaker_id
├── display_name
├── gender
├── voice_config
├── source_episode_id
└── status
```

完全不人工介入时，可以使用：

```text
Speaker 1
Speaker 2
Speaker 3
```

作为内部角色名。

但必须说明：

> “能够全自动执行”不代表模型一定能自动判断跨集中的同一演员身份。

如果你要求男主在 80 集里绝对使用同一声音，最佳方案仍然是首批分集处理后做一次角色确认。系统可以做到只确认一次，而不是每集确认。

---

# 十一、自动角色同步策略

可以设计成两阶段自动工作流。

## 冷启动批次

先处理 1～3 集：

```text
选择角色最丰富的分集
    ↓
AI 识别角色
    ↓
统计角色数量和对白时长
    ↓
生成项目级角色集合
```

## 后续批次

```text
创建新 SubTask
    ↓
同步 Project Speaker 到 SubTask
    ↓
执行配音
    ↓
检测是否出现新增角色
```

自动规则：

```text
若新增角色对白时长 < 3 秒
→ 归为临时角色

若新增角色对白时长 ≥ 3 秒
→ 新增项目角色

若单集角色数量异常增加
→ 标记 NEEDS_REVIEW
```

这些阈值是你的业务规则，不是 Starling 固定参数。

---

# 十二、情绪和单句重新配音

Starling开放：

```text
VideoEditorGetEmotionTags
VideoEditorAddEmotionTag
VideoEditorDeleteEmotionTag
```

以及：

```text
VideoEditorAsyncGenDubbing
VideoEditorQueryAsyncGenDubbingResult
```

因此可以修改某条字幕的情绪并只重新生成该句音频。

全自动模式下，正常流程不会逐句重配。

只有质检发现：

```text
配音为空
配音严重超时
角色缺失
生成失败
```

才自动调用单句重配接口。

单句重试次数建议最多：

```text
2 次
```

超过后进入人工审核，避免无限产生费用。

---

# 十三、字幕擦除路线

用户在表单中只选一次：

```text
NONE
BASIC
ADVANCED
```

保存为内部枚举：

```java
public enum SubtitleRemovalMode {
    NONE,
    BASIC,
    ADVANCED
}
```

创建 Starling 任务时映射到它对应的参数。

自动降级策略：

```text
默认 BASIC
    ↓
任务完成后抽帧检测
    ↓
残留严重？
    ├── 否 → 继续
    └── 是 → 对该集使用 ADVANCED 重做
```

注意不要整部剧全部重做，只重做失败分集。

---

# 十四、自动质量检测

即使用户选择“全自动”，也必须有机器质检门。

## 1. 媒体层检测

使用 FFprobe：

```text
视频轨是否存在
音频轨是否存在
最终时长是否合理
视频是否可完整解码
音频采样率是否正常
文件大小是否异常
```

规则示例：

```text
abs(最终时长 - 原始时长) <= 500ms
```

具体容差需要根据 Starling 实际输出调整。

## 2. 字幕检测

```text
字幕段数量 > 0
目标字幕为空比例 < 1%
字幕越界数量 = 0
字幕严重重叠比例 < 5%
字幕覆盖率合理
```

## 3. 翻译检测

```text
未翻译中文比例
异常重复句比例
人名术语命中率
句子长度异常
非法字符
```

## 4. 配音检测

```text
成品音频存在
音频总有效时长 > 0
长静音比例合理
对白时间段存在能量
响度和峰值正常
左右声道正常
```

## 5. 角色检测

```text
主要角色必须有声音
同一角色 Voice/Speaker 不应频繁变化
角色数量不能突然翻倍
单角色覆盖全部对白时标记异常
```

## 6. 字幕擦除检测

可以每隔 2～3 秒抽一帧：

```text
检测原字幕区域文字残留
检测大面积涂抹
检测新字幕是否越过安全区
```

若不想自己做视觉检测，第一版可以采用抽样人工质检，第二版再加视觉模型。

---

# 十五、自动确认校对

官方提供：

```text
VideoEditorSubmitSubtask
```

用于完成校对。

全自动模式：

```text
AI 处理完成
    ↓
自动质检通过
    ↓
VideoEditorSubmitSubtask
    ↓
进入成片压制
```

人工审核模式：

```text
AI 处理完成
    ↓
状态 WAITING_REVIEW
    ↓
运营人员修改字幕/角色/配音
    ↓
运营点击确认
    ↓
VideoEditorSubmitSubtask
```

---

# 十六、字幕样式处理

官方提供：

```text
VideoEditorUpdateGlobalStyle
VideoEditorBatchUpdateStyle
```

用于更新全局或批量字幕样式。

你的表单不直接暴露几十个 Starling 字段，而是提供样式模板：

```text
white-black-outline-v1
yellow-black-outline-v1
tiktok-safe-v1
```

模板表：

```text
SubtitleStyleTemplate
├── id
├── name
├── font_family
├── font_size
├── font_color
├── outline_color
├── outline_width
├── alignment
├── position_y
├── max_width
└── version
```

提交任务后自动将模板映射成 Starling 样式参数。

---

# 十七、最终成片压制

调用：

```text
VideoProjectSuppressionStart
```

该 API 是独立的视频压制入口。

压制前必须保证：

```text
字幕翻译完成
字幕擦除完成
配音完成
自动或人工校对完成
字幕样式已设置
```

压制目标：

```text
净版视频
+ 目标语言字幕
+ 目标语言配音
+ 背景音乐和环境音
→ 最终成品视频
```

不要在 AI 流程未完成时反复调用压制接口。

压制也要有独立幂等键：

```text
subtaskId
+ subtitleVersion
+ dubbingVersion
+ styleVersion
```

---

# 十八、获取产物

调用：

```text
VideoProjectGetTaskProduct
```

官方产物接口可返回净版视频、成品视频、成品音频等产物类型。([火山引擎][6])

建议归档：

```text
SOURCE_VIDEO
SOURCE_SUBTITLE
TARGET_SUBTITLE
CLEAN_VIDEO
DUBBED_AUDIO
FINAL_VIDEO
COVER
```

流程：

```text
Starling 返回产物 URL
        ↓
你的 Archive Worker 下载
        ↓
上传至自己的对象存储
        ↓
保存永久 URL
        ↓
校验文件 Hash
        ↓
标记 COMPLETED
```

不要让最终用户长期直接使用 Starling 临时 URL。

---

# 十九、Webhook 与轮询

调用：

```text
WebhooksCreate
```

官方 Webhook API 使用 `Version=2021-05-21`，服务为 `i18n_openapi`。([火山引擎][7])

推荐：

```text
Webhook 推动状态
+
轮询兜底
```

Webhook 接收流程：

```text
POST /api/internal/starling/webhook
        ↓
验签
        ↓
保存原始事件
        ↓
根据外部 taskId 查内部 Job
        ↓
幂等更新状态
        ↓
发送 workflow signal
```

轮询策略：

```text
上传阶段：15 秒
AI 处理阶段：30 秒
压制阶段：30 秒
长任务：60 秒
```

加入随机抖动，避免批量任务同时查询。

---

# 二十、数据库设计

## drama

```sql
id
name
source_language
starling_project_id
workflow_config_json
status
created_at
updated_at
```

## episode

```sql
id
drama_id
episode_number
source_storage_key
source_hash
duration_ms
width
height
starling_video_id
upload_batch_id
upload_status
created_at
```

## translation_job

```sql
id
drama_id
target_language
config_version
workflow_mode
starling_task_id
status
current_stage
retry_count
error_code
error_message
request_snapshot
response_snapshot
created_at
updated_at
completed_at
```

## translation_subtask

```sql
id
translation_job_id
episode_id
target_language
starling_subtask_id
status
qc_status
suppression_status
final_video_url
final_audio_url
clean_video_url
error_message
```

## subtitle_segment

```sql
id
subtask_id
starling_segment_id
start_ms
end_ms
source_text
target_text
speaker_id
emotion
subtitle_version
dubbing_version
review_status
```

## drama_speaker

```sql
id
drama_id
starling_speaker_id
display_name
gender
voice_config_json
reference_episode_id
status
```

## workflow_event

```sql
id
job_id
subtask_id
event_type
external_event_id
payload_json
created_at
```

## artifact

```sql
id
subtask_id
artifact_type
starling_url
storage_key
file_hash
file_size
created_at
```

---

# 二十一、工作流伪代码

```java
public void runDramaWorkflow(UUID jobId) {
    WorkflowJob job = jobRepository.getRequired(jobId);

    ensureStarlingProject(job);
    uploadEpisodes(job);
    waitForUploads(job);

    createSerialTranslationTask(job);
    ensureAiFlowStarted(job);
    waitForAiResult(job);

    syncSubtitlesAndSpeakers(job);

    QualityResult quality = runAutomaticQualityChecks(job);

    if (!quality.passed()) {
        handleQualityFailure(job, quality);
        return;
    }

    submitSubtasks(job);
    applySubtitleStyle(job);

    startSuppression(job);
    waitForSuppression(job);

    fetchAndArchiveProducts(job);
    markCompleted(job);
}
```

真正实现时不要用一个线程一直阻塞，而是让工作流引擎在等待外部状态时持久化暂停。

---

# 二十二、Starling Adapter 设计

所有 Starling 调用封装到独立模块：

```java
public interface StarlingClient {

    CreateProjectResult createProject(CreateProjectCommand command);

    UploadVideoResult uploadVideo(UploadVideoCommand command);

    UploadStatus getVideoUploadStatus(String batchId);

    CreateSerialTaskResult createSerialTask(
        CreateSerialTaskCommand command
    );

    TaskDetail getTaskDetail(String taskId);

    void startAiFlow(StartAiFlowCommand command);

    List<SubtitleSegment> listSubtitles(String subtaskId);

    List<Speaker> getSpeakers(String projectId, String subtaskId);

    void syncSpeakers(String projectId, String subtaskId);

    void submitSubtask(String subtaskId);

    SuppressionResult startSuppression(
        SuppressionCommand command
    );

    List<ProductArtifact> getTaskProducts(String taskId);
}
```

业务层永远不要直接依赖火山 JSON 字段。

这样做的好处：

```text
Starling 字段发生变化
→ 只修改 Starling Adapter

业务状态机和数据库
→ 不受影响
```

---

# 二十三、幂等设计

## 创建 Project

```text
UNIQUE(drama_id)
```

## 上传分集

```text
idempotencyKey =
SHA256(projectId + episodeId + sourceFileHash)
```

## 创建翻配任务

```text
idempotencyKey =
SHA256(
  projectId
  + targetLanguage
  + episodeVideoHashes
  + configVersion
)
```

## 单句配音

```text
SHA256(
  segmentId
  + targetText
  + speakerId
  + emotion
  + dubbingVersion
)
```

## 压制任务

```text
SHA256(
  subtaskId
  + subtitleVersion
  + dubbingVersion
  + styleVersion
)
```

数据库唯一约束比“先查询再创建”可靠。

---

# 二十四、重试和补偿策略

## 可自动重试

```text
网络超时
HTTP 5xx
限流
暂时性服务异常
查询任务失败
下载产物失败
```

采用：

```text
指数退避
5s → 15s → 45s → 120s
```

## 不应盲目重试

```text
参数不合法
不支持的语言
文件损坏
无音频轨
权限未开通
余额不足
任务配置冲突
```

这些应直接进入 `FAILED_REQUIRES_ACTION`。

## 单集失败

不要重做全剧：

```text
第 17 集失败
→ 只重新上传/创建第 17 集 SubTask
```

## 配音失败

```text
单句失败
→ 单句生成 API 重试

整集失败
→ 重启该集配音流程

角色映射错误
→ 更新角色后重生成受影响字幕段
```

---

# 二十五、并发策略

不要一次无控制地提交 100 集。

建议：

```text
上传并发：3～5
AI 分集并发：根据 Starling 账户配额
压制并发：2～3
产物下载并发：3～5
```

第一版每批：

```text
5～10 集
```

工作流内部可以并行：

```text
第 1 集上传 ─┐
第 2 集上传 ─┼─→ 全部就绪 → 创建任务
第 3 集上传 ─┘
```

每个目标语言也应设并发限制，避免费用和流量瞬时放大。

---

# 二十六、全自动模式的真实边界

技术上可以实现真正的零人工操作：

```text
上传
→ 自动听录
→ 自动翻译
→ 自动擦除
→ 自动配音
→ 自动校对确认
→ 自动压制
→ 自动归档
```

但不能承诺每部剧都达到可直接发布质量。主要风险：

```text
多人重叠对白
角色识别错误
同一演员跨集映射错误
译文过长导致配音过快
情绪表达不匹配
复杂背景字幕擦除残留
原语言对白未完全消除
```

建议产品提供三档：

```text
FULL_AUTO
全自动完成，失败才人工介入

SAMPLED_REVIEW
自动处理，每部剧抽检 2～3 集

FULL_REVIEW
每集人工确认后压制
```

默认推荐 `SAMPLED_REVIEW`。

---

# 二十七、实施阶段

## 阶段 1：API 连通 POC

实现：

```text
创建 Project
上传一集视频
创建完整任务
查询状态
压制视频
获取产物
```

只测试一集、一个目标语言。

## 阶段 2：全流程自动编排

实现：

```text
一次表单
批量上传
自动状态机
自动压制
结果归档
```

暂时不做角色编辑器。

## 阶段 3：自动质检

加入：

```text
字幕检查
媒体检查
音频检查
擦除抽帧
失败降级
```

## 阶段 4：跨集角色管理

加入：

```text
项目级 Speaker
首批角色识别
后续分集角色同步
异常角色审核
```

## 阶段 5：运营编辑器

加入：

```text
字幕逐句修改
角色切换
情绪标签
单句重配
试听
重新压制
```

---

# 二十八、推荐的最终技术路线

```text
前端：
Vue 3 + Element Plus

业务 API：
Spring Boot 3 + Java 21

工作流：
Temporal Java SDK

数据库：
PostgreSQL

缓存与分布式锁：
Redis

对象存储：
TOS / OSS / S3 兼容存储

媒体检测：
FFmpeg + FFprobe

第三方适配：
独立 Starling Adapter

状态更新：
Webhook + 定时轮询

质量检测：
Java规则引擎
+ FFprobe
+ 音频能量分析
+ 后期视觉模型

部署：
Docker
Kubernetes 或普通云服务器
```

最终业务效果：

> 用户上传短剧、选择一次翻配参数并点击开始；你的系统创建长事务工作流，自动调用 Starling 的项目、上传、翻配、配音、角色、压制和产物 API，最终返回每集目标语言成片。

最重要的工程原则是：

> **把 Starling 当作异步 AI 处理引擎，而不是把它当作你的任务系统。**

项目状态、分集状态、幂等、重试、版本、质检、成本、产物和错误恢复，都必须由你自己的后端掌握。

[1]: https://www.volcengine.com/docs/4640/2122558?utm_source=chatgpt.com "产品介绍--机器翻译"
[2]: https://www.volcengine.com/docs/4640/1963603?utm_source=chatgpt.com "机器翻译- 短剧项目"
[3]: https://www.volcengine.com/docs/4640/2120614?utm_source=chatgpt.com "VideoProjectCreate - 创建短剧项目--机器翻译"
[4]: https://www.volcengine.com/docs/4640/2120615?utm_source=chatgpt.com "VideoProjectSerialTaskCreate - 创建短剧任务--机器翻译"
[5]: https://www.volcengine.com/docs/4640/2276711?utm_source=chatgpt.com "VideoProjectTaskBatchStartAIFlow - 批量触发AI 翻译--机器翻译"
[6]: https://www.volcengine.com/docs/4640/2582209?utm_source=chatgpt.com "VideoProjectGetTaskProduct - 获取任务产物--机器翻译"
[7]: https://www.volcengine.com/docs/4640/2120616?utm_source=chatgpt.com "WebhooksCreate - 创建webhook--机器翻译"

