下面按你确定的链路梳理：

> **字幕 OCR 提取 → 字幕擦除基础版 / 高级版 → 字幕翻译 → 视频导出**

---

# 一、推荐完整流程

## 总流程

```text
本地视频
  ↓
上传 OSS
  ↓
并行执行：
  A. CaptionExtraction 提取原硬字幕 SRT
  B. VideoDetext 擦除原字幕，输出 clean.mp4
  ↓
清洗 / 校对 SRT
  ↓
SubmitVideoTranslationJob：
  clean.mp4 + cleaned.zh.srt
  → 翻译字幕
  → 压制新字幕
  → 导出目标语言视频
  ↓
输出：
  translated.srt
  translated.mp4
```

关键点：

**字幕提取必须在原视频上做，不能在擦除后的视频上做。**
擦除后视频只用于最终合成。

---

# 二、每一步用到的 API

## Step 0：开通与授权

你需要先开通 IMS，并完成 OSS / VOD / MPS / MNS 等关联授权。阿里云开通文档说明，开通后需要进行服务授权，完成对象存储 OSS、点播 VOD、媒体处理 MPS、消息队列 MNS 的账号授权。([AlibabaCloud][1])

文档：

* **开通智能媒体服务 IMS**：([AlibabaCloud][1])

---

## Step 1：上传视频到 OSS

小文件可以用 `PutObject`；如果单个视频比较大，建议用 OSS 分片上传。

| 用途         | API                                                                  |
| ---------- | -------------------------------------------------------------------- |
| 普通上传       | `PutObject`                                                          |
| 大文件/批量稳定上传 | `InitiateMultipartUpload` → `UploadPart` → `CompleteMultipartUpload` |

`PutObject` 单次上传限制为 5GB，超过 5GB 需要使用分片上传。([AlibabaCloud][2])

文档：

* **OSS PutObject**：([AlibabaCloud][2])
* **OSS MultipartUpload 分片上传**：([AlibabaCloud][3])

建议 OSS 路径：

```text
oss://bucket/shortdrama/input/ep001.mp4
oss://bucket/shortdrama/source_srt/ep001.zh.srt
oss://bucket/shortdrama/source_srt_clean/ep001.zh.clean.srt
oss://bucket/shortdrama/clean_video/ep001.clean.mp4
oss://bucket/shortdrama/output_video/ep001.en.mp4
```

---

# 三、字幕提取：CaptionExtraction

## API

```text
SubmitIProductionJob
FunctionName = CaptionExtraction
```

查询：

```text
QueryIProductionJob
```

阿里云文档明确写到，字幕提取通过 `SubmitIProductionJob` 异步提交，`FunctionName` 填 `CaptionExtraction`，输入支持 OSS，输出为 SRT 文件；`fps` 默认 5，范围 2–10；`roi` 可指定字幕区域，不填默认识别视频底部 1/4 区域。([AlibabaCloud][4])

## 请求示例

```json
{
  "Name": "ep001_caption_extraction",
  "FunctionName": "CaptionExtraction",
  "Input": {
    "Type": "OSS",
    "Media": "oss://bucket/shortdrama/input/ep001.mp4"
  },
  "Output": {
    "Type": "OSS",
    "Media": "oss://bucket/shortdrama/source_srt/ep001.zh.srt"
  },
  "JobParams": "{\"fps\":5,\"roi\":[[0.65,1],[0,1]],\"sep\":false,\"lang\":\"ch_ml\",\"track\":\"main\"}"
}
```

## 参数建议

| 参数      |                建议值 | 说明           |
| ------- | -----------------: | ------------ |
| `fps`   |                  5 | 常规短剧字幕够用     |
| `fps`   |                 10 | 字幕变化快、花字多时使用 |
| `roi`   | `[[0.65,1],[0,1]]` | 竖屏短剧底部 35%   |
| `lang`  |            `ch_ml` | 中英混合识别       |
| `track` |             `main` | 只提取主字幕       |
| `sep`   |            `false` | 不拆分中英文两个 SRT |

注意：`CaptionExtraction` 的 `roi` 格式是：

```text
[[top, bottom], [left, right]]
```

---

# 四、字幕擦除：VideoDetext 基础版 / 高级版

## API

```text
SubmitIProductionJob
FunctionName = VideoDetext
```

查询：

```text
QueryIProductionJob
```

`SubmitIProductionJob` 文档中明确列出 `VideoDetext` 是视频去字幕，`CaptionExtraction` 是字幕提取；`VideoDetext` 输入一个视频文件，输出擦除字幕后的视频，格式为 MP4。文档还说明 `ModelId=algo-video-detext-new` 是效果更好的字幕擦除算法，速度更慢、费用更高。([AlibabaCloud][5])

---

## 4.1 基础版字幕擦除

不传 `ModelId`，使用默认模型。

```json
{
  "Name": "ep001_detext_basic",
  "FunctionName": "VideoDetext",
  "Input": {
    "Type": "OSS",
    "Media": "oss://bucket/shortdrama/input/ep001.mp4"
  },
  "Output": {
    "Type": "OSS",
    "Media": "oss://bucket/shortdrama/clean_video/ep001.clean.mp4"
  },
  "JobParams": "{\"LimitRegion\":[[0,0.65,1,0.35]]}"
}
```

---

## 4.2 高级版字幕擦除

传：

```json
"ModelId": "algo-video-detext-new"
```

完整示例：

```json
{
  "Name": "ep001_detext_advanced",
  "FunctionName": "VideoDetext",
  "ModelId": "algo-video-detext-new",
  "Input": {
    "Type": "OSS",
    "Media": "oss://bucket/shortdrama/input/ep001.mp4"
  },
  "Output": {
    "Type": "OSS",
    "Media": "oss://bucket/shortdrama/clean_video/ep001.clean.mp4"
  },
  "JobParams": "{\"LimitRegion\":[[0,0.65,1,0.35]]}"
}
```

`LimitRegion` 格式是：

```text
[x, y, width, height]
```

所以：

```json
[[0, 0.65, 1, 0.35]]
```

代表擦除底部 35% 区域。

---

# 五、查询字幕提取 / 擦除任务

## API

```text
QueryIProductionJob
```

用途：

```text
查询 CaptionExtraction 任务
查询 VideoDetext 任务
```

提交智能生产任务是异步接口，`SubmitIProductionJob` 返回 `JobId` 后，可以通过 `QueryIProductionJob` 查询任务状态。([AlibabaCloud][5])

文档：

* **SubmitIProductionJob - 提交智能生产任务**：([AlibabaCloud][5])
* **QueryIProductionJob - 查询智能生产任务**：([AlibabaCloud][6])
* **字幕提取实践文档**：([AlibabaCloud][4])

---

# 六、SRT 清洗

这一步不是阿里云 API，但强烈建议加。

原因是你不走 ASR，字幕翻译质量完全依赖 OCR 提取出来的 SRT。

建议本地做：

```text
下载 ep001.zh.srt
→ 去重
→ 删除水印、角标、广告词
→ 合并重复字幕
→ 修正明显 OCR 错字
→ 检查时间轴
→ 上传 ep001.zh.clean.srt
```

上传清洗后的 SRT 仍然用 OSS `PutObject`。

---

# 七、字幕翻译 + 视频导出

## API

```text
SubmitVideoTranslationJob
```

查询：

```text
GetSmartHandleJob
```

`SubmitVideoTranslationJob` 用于提交视频翻译任务，支持字幕级翻译、语音级翻译和面容级翻译；该接口是异步接口，提交后返回 `JobId`，后续可通过 `GetSmartHandleJob` 主动查询任务状态和结果。([AlibabaCloud][7])

视频翻译参数文档说明，字幕级翻译需要：

```text
NeedSpeechTranslate = false
NeedFaceTranslate = false
对应配置：SubtitleTranslate
```

并且视频翻译参数文档列出了字幕级翻译支持的地域。([AlibabaCloud][8])

## 推荐调用方式

使用：

```text
clean.mp4 + cleaned.zh.srt
```

也就是不要让它重新 OCR / ASR，而是直接使用前面提取并清洗好的 SRT。

```json
{
  "InputConfig": {
    "Type": "Video",
    "Video": "oss://bucket/shortdrama/clean_video/ep001.clean.mp4",
    "Subtitle": "oss://bucket/shortdrama/source_srt_clean/ep001.zh.clean.srt"
  },
  "EditingConfig": {
    "SourceLanguage": "zh",
    "TargetLanguage": "en",
    "TextSource": "SubtitleFile",
    "BilingualSubtitle": false,
    "NeedSpeechTranslate": false,
    "NeedFaceTranslate": false,
    "SubtitleTranslate": {
      "SubtitleConfig": {
        "Type": "Text",
        "FontSize": 72,
        "FontColor": "#FFFFFF",
        "FontColorOpacity": 1,
        "X": 0.5,
        "Y": 0.82,
        "TextWidth": 0.9,
        "Alignment": "Center",
        "BorderStyle": 1,
        "Outline": 2
      }
    },
    "SupportEditing": true
  },
  "OutputConfig": {
    "OutputTarget": "OSS",
    "MediaURL": "oss://bucket/shortdrama/output_video/ep001.en.mp4"
  },
  "Title": "ep001_en"
}
```

文档：

* **SubmitVideoTranslationJob - 提交视频翻译任务**：([AlibabaCloud][7])
* **视频翻译参数介绍与示例**：([AlibabaCloud][8])
* **GetSmartHandleJob - 获取智能任务结果**：([阿里云][9])

---

# 八、任务编排建议

## 推荐并行流程

```text
1. OSS 上传原视频

2. 并行提交两个任务：
   A. SubmitIProductionJob(CaptionExtraction)
      输出 ep001.zh.srt

   B. SubmitIProductionJob(VideoDetext)
      输出 ep001.clean.mp4

3. QueryIProductionJob 查询 A、B 任务

4. 下载 ep001.zh.srt，本地清洗，上传 ep001.zh.clean.srt

5. SubmitVideoTranslationJob：
   输入 clean.mp4 + zh.clean.srt
   NeedSpeechTranslate=false
   NeedFaceTranslate=false

6. GetSmartHandleJob 查询最终结果

7. 输出：
   ep001.en.mp4
   翻译后字幕文件 URL
```

---


# 十一、所有相关文档清单

## 开通 / 授权

| 文档                                   | 用途                           |
| ------------------------------------ | ---------------------------- |
| **开通智能媒体服务 IMS** ([AlibabaCloud][1]) | 开通 IMS、完成 OSS/VOD/MPS/MNS 授权 |

## OSS 上传

| 文档                                               | 用途         |
| ------------------------------------------------ | ---------- |
| **OSS PutObject** ([AlibabaCloud][2])            | 上传视频 / SRT |
| **OSS MultipartUpload 分片上传** ([AlibabaCloud][3]) | 大文件视频上传    |

## 字幕提取 / 字幕擦除

| 文档                                                      | 用途                                     |
| ------------------------------------------------------- | -------------------------------------- |
| **SubmitIProductionJob - 提交智能生产任务** ([AlibabaCloud][5]) | 提交 `CaptionExtraction` / `VideoDetext` |
| **QueryIProductionJob - 查询智能生产任务** ([AlibabaCloud][6])  | 查询字幕提取 / 字幕擦除结果                        |
| **字幕提取实践文档** ([AlibabaCloud][4])                        | `CaptionExtraction` 参数示例               |
| **智能生产计费** ([AlibabaCloud][10])                         | 字幕擦除基础版 / 高级版价格                        |

## 字幕翻译 / 视频导出

| 文档                                                           | 用途                                                                            |
| ------------------------------------------------------------ | ----------------------------------------------------------------------------- |
| **SubmitVideoTranslationJob - 提交视频翻译任务** ([AlibabaCloud][7]) | 提交字幕级翻译任务                                                                     |
| **视频翻译参数介绍与示例** ([AlibabaCloud][8])                          | `NeedSpeechTranslate=false`、`SubtitleTranslate`、`TextSource=SubtitleFile` 等参数 |
| **GetSmartHandleJob - 获取智能任务结果** ([阿里云][9])                  | 查询字幕翻译 / 导出结果                                                                 |

---

# 十二、最终推荐配置

正式跑短剧，我建议：

```text
字幕提取：
CaptionExtraction
fps=5 或 10
roi=[[0.65,1],[0,1]]
lang=ch_ml
track=main

字幕擦除：
VideoDetext
ModelId=algo-video-detext-new
LimitRegion=[[0,0.65,1,0.35]]

字幕翻译：
SubmitVideoTranslationJob
TextSource=SubtitleFile
NeedSpeechTranslate=false
NeedFaceTranslate=false

输出：
OSS MediaURL
```


[1]: https://www.alibabacloud.com/help/zh/ims/getting-started/opening-service?utm_source=chatgpt.com "开通智能媒体服务 - 智能媒体服务 - 阿里云"
[2]: https://www.alibabacloud.com/help/zh/oss/developer-reference/putobject?utm_source=chatgpt.com "对象存储PutObject接口 - 对象存储 OSS - 阿里云 - Alibaba Cloud"
[3]: https://www.alibabacloud.com/help/zh/oss/developer-reference/multipart-upload-11?utm_source=chatgpt.com "如何在OSS中实现分片上传 - 对象存储 OSS - 阿里云"
[4]: https://www.alibabacloud.com/help/zh/vod/use-cases/subtitle-extraction "
 字幕提取 - 视频点播 - 阿里云

"
[5]: https://www.alibabacloud.com/help/zh/ims/developer-reference/api-ice-2020-11-09-submitiproductionjob "
 SubmitIProductionJob - 提交智能生产任务 - 智能媒体服务 - 阿里云

"
[6]: https://www.alibabacloud.com/help/zh/ims/developer-reference/api-ice-2020-11-09-queryiproductionjob?utm_source=chatgpt.com "QueryIProductionJob - 查询智能生产任务 - 智能媒体服务 ..."
[7]: https://www.alibabacloud.com/help/zh/ims/developer-reference/api-ice-2020-11-09-submitvideotranslationjob "
 SubmitVideoTranslationJob - 提交视频翻译任务 - 智能媒体服务 - 阿里云

"
[8]: https://www.alibabacloud.com/help/zh/ims/use-cases/introduction-and-examples-of-video-translation-parameters "
 视频翻译参数介绍与示例 - 智能媒体服务 - 阿里云

"
[9]: https://api.aliyun.com/document/ICE/2020-11-09/GetSmartHandleJob "GetSmartHandleJob_智能媒体生产_API文档-阿里云OpenAPI开发者门户"
[10]: https://www.alibabacloud.com/help/zh/ims/intelligent-production-billing "
 智能生产计费 - 智能媒体服务 - 阿里云

"

