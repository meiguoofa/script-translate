对。下面是基于百度 VOD 视频翻译 API 的**完整、正确、可落地流程**。

先明确三个核心对象：

```text
Project：一部短剧的翻译任务容器
Media：上传到百度 VOD 媒资库中的某一集原视频
Translation Task：某一集视频翻译成某一种目标语言的实际处理任务
```

它们的关系是：

```text
一部短剧 Project
├── 第 1 集英文翻译 Task
├── 第 2 集英文翻译 Task
├── 第 3 集英文翻译 Task
├── 第 1 集西班牙语翻译 Task
└── 第 2 集西班牙语翻译 Task
```

**Project 不直接存视频，也不保存永久生效的翻译参数。**视频独立存放在 VOD 媒资库；每次创建 Translation Task 时，才传入源语言、目标语言、字幕识别、字幕擦除、声音复刻和字幕烧录参数。百度官方将 Project 定义为“一组视频翻译任务的集合”。([百度智能云][1])

---

# 一、完整流程总览

```text
你的业务系统创建一部短剧
        ↓
在百度 VOD 创建一个翻译 Project
        ↓
逐集上传视频到百度 VOD 媒资库
        ↓
每集得到一个 mediaId
        ↓
选取 1～2 集创建翻译测试任务
        ↓
检查字幕识别、翻译、擦除、声音复刻和成片
        ↓
参数确认
        ↓
按批次提交整部剧的翻译任务
        ↓
百度为每一集分别创建 Translation Task
        ↓
轮询每个 taskId 的状态
        ↓
获取最终译制视频和中间结果
        ↓
自动质检 + 人工抽检
        ↓
归档、发布或单集重试
```

百度控制台给出的产品流程也是“上传视频素材 → 配置翻译任务 → 生成翻译结果 → 编辑”。([百度智能云][2])

---

# 二、阶段 0：开通和接入准备

百度 VOD 的 `/v2/...` 接口需要在你的**服务端**调用。

推荐准备：

```text
百度智能云账号
VOD 服务
Access Key
Secret Key
服务端 BCE AK/SK 签名模块
你自己的数据库
你自己的任务调度器
```

不要让前端直接持有 AK/SK。前端只向你的服务端提交“创建短剧”“上传视频”“开始翻译”等业务请求，由服务端调用百度。

你自己的系统至少保存：

```text
短剧
剧集
百度 Project ID
百度 Media ID
百度 Translation Task ID
翻译配置
任务状态
最终结果 URL
错误信息
```

---

# 三、阶段 1：创建短剧翻译 Project

一部短剧创建一个百度翻译项目。

接口：

```http
POST https://vod.bj.baidubce.com/v2/translation/project
```

请求：

```json
{
  "name": "霸道总裁爱上我",
  "description": "中文短剧英文译制",
  "type": "ShortSeries"
}
```

返回：

```json
{
  "projectId": "pjt-fjvtg03paqrfvgcq"
}
```

官方支持的项目类型包括：

```text
ShortSeries：短剧
Ecommerce：电商
```

创建翻译任务前，必须先创建项目。([百度智能云][1])

## 你自己的数据库记录

```text
Drama
├── id
├── name
├── baidu_project_id
├── source_language
├── status
└── created_at
```

例如：

```text
id = drama_1001
name = 霸道总裁爱上我
baidu_project_id = pjt-fjvtg03paqrfvgcq
```

Project 一般只创建一次。以后新增剧集，继续使用原 `projectId`。

---

# 四、阶段 2：逐集上传到百度 VOD 媒资库

视频不是直接上传到 Project，而是先上传到百度 VOD 的公共媒资库。

假设一部短剧有 50 集：

```text
第 1 集 → 百度媒资 mda-001
第 2 集 → 百度媒资 mda-002
第 3 集 → 百度媒资 mda-003
...
第 50 集 → 百度媒资 mda-050
```

## 方案 A：已有公网视频 URL

使用拉取上传接口：

```http
POST https://vod.bj.baidubce.com/v2/medias/fetch
```

请求：

```json
{
  "url": "https://your-cdn.example.com/drama/episode-001.mp4",
  "name": "霸道总裁爱上我-第001集",
  "deleteAfterSeconds": 2592000
}
```

返回：

```json
{
  "taskId": "tsk-upload-001"
}
```

注意，此时返回的是**上传任务 ID**，还不是 `mediaId`。

拉取上传完成后，再查询上传任务，才能拿到：

```text
mediaId = mda-xxxx
```

百度拉取上传接口支持网络音视频进入 VOD，单个文件上限为 5GB；还可以通过 `deleteAfterSeconds` 设置 1 小时到 180 天的自动过期时间。([百度智能云][3])

## 方案 B：本地文件上传

本地文件可以使用百度 VOD 上传接口或上传 SDK：

```text
本地 episode-001.mp4
        ↓
申请上传地址和凭证
        ↓
文件直传百度 VOD
        ↓
完成上传
        ↓
获得 mediaId
```

生产环境通常建议客户端或上传服务直传百度，避免所有视频先经过你的业务服务器。

## 上传后的数据库映射

```text
Episode
├── id
├── drama_id
├── episode_no
├── source_url
├── baidu_upload_task_id
├── baidu_media_id
├── duration_ms
├── width
├── height
└── status
```

例如：

```text
第001集
baidu_upload_task_id = tsk-upload-001
baidu_media_id = mda-001
```

此时视频仍然没有自动进入 Project，也不会自动开始翻译。

---

# 五、阶段 3：确定统一翻译配置

翻译配置应保存在**你自己的系统中**，而不是期待设置到百度 Project 上。

例如为这部短剧建立一份配置模板：

```json
{
  "sourceLanguage": "zh-CN",
  "targetLanguage": "en-US",
  "translationTypes": [
    "subtitle",
    "speech"
  ],
  "voiceMode": "VOICE_CLONE",
  "recognitionType": "OCR",
  "removeOriginalSubtitle": true,
  "desubtitleModel": "v4",
  "desubtitleType": "dialog",
  "composeTargetSubtitle": true
}
```

这个模板表达：

```text
源语言：中文
目标语言：英文
生成目标语言字幕
生成目标语言配音
自动复刻不同角色音色
从画面 OCR 提取原字幕
擦除中文字幕
烧录英文字幕
```

创建任务接口支持同时选择：

```text
subtitle：字幕翻译
speech：语音翻译
```

配音模式支持：

```text
VOICE_CLONE：声音复刻
AI_DUB：系统 AI 音色
```

其中 AI_DUB 当前只能配置一个音色，不适合多角色短剧；VOICE_CLONE 会走声音复刻。([百度智能云][4])

---

# 六、阶段 4：先提交 1～2 集 POC

不要第一次就提交整部 50 集。

先选：

```text
第 1 集
第 2 集
```

要求测试素材尽量包含：

```text
多个男女角色
快速对白
情绪激烈对白
背景音乐
字幕位置变化
两人交替说话
少量声音重叠
```

调用核心翻译任务接口：

```http
POST https://vod.bj.baidubce.com/v2/translation/tasks
```

## 推荐逻辑请求

```json
{
  "projectId": "pjt-fjvtg03paqrfvgcq",
  "mediaIdList": [
    "mda-001",
    "mda-002"
  ],
  "translationConfig": {
    "sourceLanguage": "zh-CN",
    "targetLanguage": "en-US",
    "translationTypeList": [
      "subtitle",
      "speech"
    ],
    "ttsConfig": {
      "type": "VOICE_CLONE"
    }
  },
  "subtitleConfig": {
    "recognitionType": "OCR",
    "ocrConfig": {
      "areaList": [
        {
          "x": 40,
          "y": 1300,
          "width": 1000,
          "height": 450,
          "start": 0
        }
      ],
      "regionIOU": 0
    },
    "textTypeList": [
      "dialog"
    ],
    "targetSubtitleCompose": true,
    "desubtitleConfig": {
      "modelType": "v4",
      "desubtitleType": "dialog"
    },
    "fontConfig": {
      "dialog": {
        "padding": 8,
        "color": "#00000000",
        "font": {
          "family": "Hei",
          "alignment": "center",
          "size": 48,
          "bold": false,
          "color": "#FFFFFFFF",
          "outlineThickness": 2,
          "outlineColor": "#000000FF"
        }
      }
    }
  }
}
```

## 重要：百度文档字段存在不一致

目前官方参数表将擦除配置写成：

```json
{
  "desubtitleConfig": {
    "modelType": "v4",
    "desubtitleType": "dialog"
  }
}
```

但官方请求示例又把：

```json
{
  "desubtitleType": "global"
}
```

直接放在 `subtitleConfig` 下；同时，参数表把 `targetSubtitleCompose` 标记为字符串，示例则传布尔值。([百度智能云][4])

因此正式开发时应当：

1. 先使用百度 VOD API 在线调试器；
2. 输入真实参数；
3. 生成 Java、Python 或 cURL 示例；
4. 以在线调试器实际接受的 Schema 为准；
5. 再固化到你的生产代码中。

不要仅依据文档页面手写擦除字段结构后直接全量提交。

---

# 七、百度收到任务后内部做什么

对每一个 `mediaId`，百度会分别创建一条翻译任务。

每一集内部执行：

```text
1. 读取原视频
2. OCR 或 ASR 提取原语言台词
3. 生成原语言字幕时间轴
4. 将字幕翻译成目标语言
5. 识别不同说话人
6. 复刻不同角色的原始音色
7. 生成目标语言配音
8. 擦除原画面硬字幕
9. 烧录目标语言字幕
10. 合成目标语言配音和背景音
11. 输出最终译制视频
```

使用 `VOICE_CLONE` 时，产品说明是自动识别视频中的不同说话人，并复刻每个人物的原始音色。([百度智能云][2])

注意，声音复刻目前支持的目标语言范围小于纯字幕翻译；官方表格显示声音复刻主要支持中文、英语、日语、韩语、德语、法语、俄语和西班牙语。([百度智能云][4])

---

# 八、一次传多个 mediaId，不等于一个总任务

提交：

```json
{
  "mediaIdList": [
    "mda-001",
    "mda-002",
    "mda-003"
  ]
}
```

百度不会只创建一个总 Task，而是创建三条任务：

```text
mda-001 → tsk-translation-001
mda-002 → tsk-translation-002
mda-003 → tsk-translation-003
```

响应：

```json
{
  "total": 3,
  "translationTaskCreateResultList": [
    {
      "taskId": "tsk-translation-001",
      "mediaId": "mda-001"
    },
    {
      "taskId": "tsk-translation-002",
      "mediaId": "mda-002"
    },
    {
      "taskId": "tsk-translation-003",
      "mediaId": "mda-003"
    }
  ]
}
```

百度明确说明 `mediaIdList` 用于按同一翻译配置创建多个任务，并为每个媒资返回对应的 `taskId`。([百度智能云][4])

你的数据库应当逐条保存映射：

```text
episode_001 + en-US → tsk-translation-001
episode_002 + en-US → tsk-translation-002
episode_003 + en-US → tsk-translation-003
```

---

# 九、阶段 5：查询每一集任务状态

查询项目下的翻译任务：

```http
GET https://vod.bj.baidubce.com/v2/translation/project/{projectId}/tasks
```

可以按 `taskId` 查询：

```http
GET /v2/translation/project/pjt-xxxx/tasks?taskId=tsk-xxxx
```

也可以按 `mediaId` 查询：

```http
GET /v2/translation/project/pjt-xxxx/tasks?mediaId=mda-xxxx
```

状态包括：

```text
READY：已创建，等待执行
RUNNING：处理中
FAILED：失败
SUCCESS：成功
```

任务成功后，列表接口可返回：

```text
url：最终译制视频
coverUrl：最终视频封面
desubtitleUrl：字幕擦除后的视频
```

任务失败时返回 `errMsg`。([百度智能云][4])

## 推荐轮询方式

```text
创建后 0～2 分钟：每 10 秒查询
2～10 分钟：每 30 秒查询
10 分钟以上：每 60 秒查询
```

应为每条 `taskId` 单独维护状态，不能只给整个 Project 一个总状态。

---

# 十、阶段 6：获取中间结果

项目任务列表主要用于获取任务状态和最终视频。

还可以查询具体工作流任务详情，获得中间结果，包括：

```text
原语言字幕 SRT
翻译后的字幕 SRT
字幕擦除后视频
最终合成视频
各处理节点状态
```

百度官方明确说明，视频翻译任务是一个包含多个子节点的工作流任务，任务详情可以获取源字幕、译文字幕、擦除后视频和最终结果。([百度智能云][4])

建议成功后立即归档：

```text
原始视频 Media ID
源字幕 SRT
目标字幕 SRT
去字幕视频
最终译制视频
任务请求参数
任务响应参数
```

不要只保存最终成片 URL，否则后续出现翻译或字幕问题时，很难定位具体环节。

---

# 十一、阶段 7：质检 POC 结果

在全量提交之前，至少检查：

## 字幕提取

```text
OCR 是否漏字
是否误识别人名或画面招牌
字幕时间轴是否准确
是否存在重复字幕
```

## 字幕擦除

```text
中文字幕是否仍有残留
人物脸部和衣服是否被误擦
字幕区域是否出现明显涂抹
不同场景字幕位置是否都覆盖
```

## 翻译字幕

```text
人名是否一致
代词是否正确
上下文是否连贯
英文字幕是否过长
字幕是否超出屏幕
```

## 声音复刻

```text
男女角色是否串音
同一角色前后音色是否一致
翻译语音是否过快
多人交替时是否错角色
背景音乐是否保留
原中文对白是否仍然明显存在
```

## 最终成片

```text
视频时长是否与原视频接近
音画是否同步
是否存在无声区间
音频是否爆音
英文字幕是否与英文配音基本一致
```

只有测试集通过后，再提交整部短剧。

---

# 十二、阶段 8：批量提交整部剧

参数确认后，把剩余剧集按批次提交。

推荐：

```text
每批 5～10 集
```

例如：

```text
批次 1：第 3～10 集
批次 2：第 11～20 集
批次 3：第 21～30 集
批次 4：第 31～40 集
批次 5：第 41～50 集
```

每批调用一次：

```http
POST /v2/translation/tasks
```

每次使用：

```text
同一个 projectId
一批不同的 mediaId
同一份 translationConfig
同一份 subtitleConfig
```

之所以建议分批，而不是一次提交全部，是为了：

```text
控制并发
降低错误配置造成的重复计费
单集失败容易重试
方便观察处理效果
便于统计每集成本
```

---

# 十三、多目标语言的处理方式

一条 Translation Task 只配置一个 `targetLanguage`。

如果同一部剧需要：

```text
英文
西班牙语
日语
```

可以继续使用同一个 Project，但需要分别创建三批任务。

```text
Project：霸道总裁爱上我
├── 第 1 集 → en-US
├── 第 1 集 → es-ES
├── 第 1 集 → ja-JP
├── 第 2 集 → en-US
├── 第 2 集 → es-ES
└── 第 2 集 → ja-JP
```

调用逻辑：

```text
第 1 次：
targetLanguage = en-US
mediaIdList = 全部剧集

第 2 次：
targetLanguage = es-ES
mediaIdList = 全部剧集

第 3 次：
targetLanguage = ja-JP
mediaIdList = 全部剧集
```

数据库唯一键建议设计为：

```text
drama_id + episode_id + target_language
```

避免同一集、同一语言被重复提交。

---

# 十四、新增剧集不会自动翻译

假设原本已经翻译了 50 集，后来新增第 51 集：

```text
上传第 51 集
    ↓
获得 mda-051
```

它不会因为属于同一部短剧就自动开始翻译。

还需要再次调用：

```http
POST /v2/translation/tasks
```

传入：

```json
{
  "projectId": "原来的 projectId",
  "mediaIdList": [
    "mda-051"
  ],
  "translationConfig": {
    "...": "原配置"
  },
  "subtitleConfig": {
    "...": "原配置"
  }
}
```

因此，“自动继承整部剧配置”要由你的业务系统实现：

```text
新增剧集
  ↓
读取短剧默认翻译模板
  ↓
创建百度翻译任务
```

百度 Project 本身不会自动触发。

---

# 十五、失败和重试策略

如果任务失败，不要重新提交整个 Project，也不要重做所有集数。

正确方式是：

```text
找到失败的 taskId
    ↓
读取 errMsg
    ↓
判断是配置、媒资还是服务错误
    ↓
只为失败的 mediaId 创建新任务
```

例如：

```json
{
  "projectId": "pjt-xxxx",
  "mediaIdList": [
    "mda-017"
  ],
  "translationConfig": {
    "...": "修正后的配置"
  },
  "subtitleConfig": {
    "...": "修正后的配置"
  }
}
```

常见调整：

```text
OCR 漏字 → 缩小或修改 OCR 区域，或者改用 ASR
字幕误擦 → dialog 改为 manual
擦除残留 → v3 改为 v4
字幕位置错误 → 修改字体和区域配置
语言不支持声音复刻 → 改用 AI_DUB 或取消 speech
```

---

# 十六、结果导出与人工返修

任务成功后，还可以导出剪映工程：

```http
POST /v2/translation/task/{taskId}/export_project
```

返回：

```json
{
  "downloadUrl": "剪映工程 ZIP 下载地址"
}
```

目前只支持成功任务导出，下载链接有效期为 24 小时。([百度智能云][4])

适合处理：

```text
个别字幕翻译错误
字幕位置需要微调
音量需要调整
局部配音效果不好
需要人工剪辑
```

---

# 十七、建议的数据库模型

## ShortDrama

```text
id
name
baidu_project_id
source_language
default_translation_config
status
```

## Episode

```text
id
drama_id
episode_no
source_url
baidu_media_id
upload_task_id
duration_ms
status
```

## TranslationJob

```text
id
episode_id
target_language
baidu_task_id
status
translation_config
subtitle_config
error_message
final_video_url
desubtitle_video_url
created_at
completed_at
```

## TranslationArtifact

```text
id
translation_job_id
type
url
storage_key
```

其中 `type`：

```text
SOURCE_SRT
TARGET_SRT
DESUBTITLE_VIDEO
FINAL_VIDEO
COVER
JIAN_YING_PROJECT
```

---

# 十八、最终正确流程，一句话版

```text
一部短剧创建一个百度翻译 Project；
每一集先上传到百度 VOD 媒资库并取得 mediaId；
你的系统保存一份统一翻译配置；
调用 /v2/translation/tasks，将 projectId、若干 mediaId 和翻译配置一起提交；
百度为每集分别创建任务，内部完成字幕提取、翻译、擦除、多角色声音复刻、字幕烧录和成片合成；
你的系统逐条轮询 taskId，保存结果、质检，并对失败的单集单独重试。
```

最关键的关系是：

```text
Project ≠ 视频存储目录
Project ≠ 自动翻译模板
Project = 翻译任务的管理容器

Media = 原始剧集视频
Task = 一集视频 × 一种目标语言 × 一套翻译配置
```

[1]: https://cloud.baidu.com/doc/VOD/s/Dmh0j7ldd "项目管理 - 音视频点播VOD_视频点播_ 视频转码_视频上传_百度智能云"
[2]: https://cloud.baidu.com/doc/VOD/s/ymfxfxrmw "视频翻译 - 音视频点播VOD_视频点播_ 视频转码_视频上传_百度智能云"
[3]: https://cloud.baidu.com/doc/VOD/s/Am4j8w1t0 "拉取上传 - 音视频点播VOD_视频点播_ 视频转码_视频上传_百度智能云"
[4]: https://cloud.baidu.com/doc/VOD/s/ymh0j93u8 "任务管理 - 音视频点播VOD_视频点播_ 视频转码_视频上传_百度智能云"
