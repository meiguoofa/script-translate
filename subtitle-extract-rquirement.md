可以做，推荐按这个链路实现：

```text
TOS 原视频
  -> 生成 TOS 临时下载 URL
  -> 调阿里云视频 OCR 提取字幕
  -> 轮询异步任务结果
  -> 下载 SRT 字幕
  -> 可选：翻译字幕文本，保留时间轴
  -> 生成 ASS 字幕文件，设置字体、字号、位置、边距
  -> FFmpeg 把字幕硬嵌入视频
  -> 上传新视频到 TOS
  -> 生成 TOS 临时下载 URL 返回给用户
```

阿里云这个视频 OCR 能识别影视字幕，返回时间戳和文本；接口是异步的，先调用 `RecognizeVideoCastCrewList` 提交任务，再用 `GetAsyncJobResult` 查询结果。字幕模式要传 `Params=[{"Type":"subtitles"}]`，结果里可以拿到 `SubtitlesAllResultsUrl`、`SubtitlesChineseResultsUrl`、`SubtitlesEnglishResultsUrl` 这些标准 SRT 下载地址。([阿里云帮助中心][1])

---

## 一、整体架构建议

### 1. 视频在 TOS，先给阿里云一个可访问 URL

阿里云 OCR 的 `VideoUrl` 必须是它能公网访问的 URL。你的原视频在火山 TOS，如果桶是私有的，就不能直接传 `tos://bucket/key` 或内网地址。

推荐做法是：

```text
后端用 TOS SDK 生成 GET 预签名 URL
 -> 作为 VideoUrl 传给阿里云 OCR
```

TOS 的预签名 URL 本质是在 URL 查询参数中带签名、有效期、资源和操作信息，任何拿到该 URL 的人在有效期内都可以执行对应操作，所以适合给阿里云临时读取视频。([火山引擎][2])

注意：阿里云视频 OCR 文档要求视频 URL 不能包含中文字符，支持 MP4、MOV、AVI、FLV、MKV 等格式，视频不超过 10GB，建议时长不超过 30 分钟，否则容易超时。([阿里云帮助中心][1])

---

## 二、处理流程

### 步骤 1：生成 TOS 原视频下载地址

伪代码：

```java
String inputSignedUrl = tosService.generateGetPresignedUrl(
    bucketName,
    inputObjectKey,
    6 * 3600
);
```

这个 URL 给阿里云 OCR 用。

---

### 步骤 2：调用阿里云视频 OCR 提取字幕

核心入参：

```json
{
  "VideoUrl": "https://xxx.tos-cn-shanghai.volces.com/input/demo.mp4?...签名...",
  "Params": "[{\"Type\":\"subtitles\"}]"
}
```

一定要传：

```json
[{"Type":"subtitles"}]
```

不要传：

```json
[{"Type":"cast"}]
```

`cast` 是演职员表识别，不是普通字幕提取。([阿里云帮助中心][1])

---

### 步骤 3：轮询异步任务

提交后拿到 `RequestId`，然后用它作为 `JobId` 调 `GetAsyncJobResult`。

伪代码：

```java
String jobId = recognizeVideoSubtitle(inputSignedUrl);

while (true) {
    AsyncJobResult result = getAsyncJobResult(jobId);

    if ("PROCESS_SUCCESS".equals(result.getStatus())) {
        break;
    }

    if ("PROCESS_FAILED".equals(result.getStatus()) 
        || "TIMEOUT_FAILED".equals(result.getStatus())) {
        throw new RuntimeException("字幕识别失败");
    }

    Thread.sleep(3000);
}
```

成功后解析 `Data.Result`，取：

```json
{
  "SubtitlesResults": [
    {
      "SubtitlesAllResultsUrl": "...",
      "SubtitlesChineseResultsUrl": "...",
      "SubtitlesEnglishResultsUrl": "..."
    }
  ]
}
```

一般中文短剧用：

```text
SubtitlesChineseResultsUrl
```

中英混合可以用：

```text
SubtitlesAllResultsUrl
```

---

## 三、字幕嵌入位置怎么处理

这里分三种方案。

---

## 方案 A：最简单，固定底部位置

适合：原视频底部没有字幕，或者原字幕位置偏上，新字幕放更靠下不会重叠。

FFmpeg 命令：

```bash
ffmpeg -y \
  -i input.mp4 \
  -vf "subtitles=subtitle.srt:force_style='Fontname=Noto Sans CJK SC,Fontsize=18,Alignment=2,MarginV=24,Outline=2,Shadow=0'" \
  -c:v libx264 \
  -preset veryfast \
  -crf 20 \
  -c:a copy \
  output.mp4
```

说明：

```text
Alignment=2    底部居中
MarginV=24     距离底部 24 像素，数值越小越靠下
Outline=2      字幕描边，避免白底看不清
-c:a copy      音频不重新编码，速度快
```

FFmpeg 的 `subtitles` 滤镜可以把字幕绘制到视频上，底层使用 libass；`force_style` 可以覆盖字幕样式参数。([FFmpeg][3])

这个方案实现快，但缺点是：**不能保证不和原字幕重叠**。

---

## 方案 B：推荐，底部加安全区，字幕放到安全区

适合：原视频已经有内嵌字幕，不想擦除，只想把新字幕放在更下面，避免覆盖原字幕。

思路是给视频底部加一条黑边或半透明区域，把新字幕放在黑边里。

### 不保持原分辨率，直接增加画布高度

```bash
ffmpeg -y \
  -i input.mp4 \
  -vf "pad=iw:ih+140:0:0:black,subtitles=subtitle.srt:force_style='Fontname=Noto Sans CJK SC,Fontsize=20,Alignment=2,MarginV=32,Outline=2'" \
  -c:v libx264 \
  -preset veryfast \
  -crf 20 \
  -c:a copy \
  output.mp4
```

例如原视频是：

```text
720x1280
```

输出会变成：

```text
720x1420
```

优点：不会压缩原画面，字幕基本不会和原字幕重叠。
缺点：输出尺寸变了，部分平台可能会裁剪或显示黑边。

---

### 保持原分辨率，缩小原画面并留底部字幕区

如果短视频必须保持 `720x1280`，可以把原画面稍微缩小，然后底部留黑边：

```bash
ffmpeg -y \
  -i input.mp4 \
  -vf "scale=720:1140,pad=720:1280:0:0:black,subtitles=subtitle.srt:force_style='Fontname=Noto Sans CJK SC,Fontsize=20,Alignment=2,MarginV=32,Outline=2'" \
  -c:v libx264 \
  -preset veryfast \
  -crf 20 \
  -c:a copy \
  output.mp4
```

这个更适合短剧平台，因为最终尺寸仍然是：

```text
720x1280
```

缺点是原画面会被轻微缩小。

---

## 方案 C：高级，动态避让原字幕

适合：你不想加黑边，也不想压缩画面，希望新字幕自动避开原字幕。

阿里云 OCR 结果里不仅有字幕文本，还会返回 OCR 文本框位置，例如 `Boxes=[xmin,ymin,xmax,ymax]`、`Position`、`StartTime`、`EndTime` 等字段。([阿里云帮助中心][1])

你可以用这些框计算原字幕位置，然后生成 ASS 字幕，每条字幕带自己的位置。

逻辑大概是：

```java
for each subtitleLine:
    原字幕框 = 找到同一时间段内、位于画面下半部分的 OCR boxes

    if 原字幕框下面还有空间:
        新字幕放到原字幕下面
    else if 原字幕框上面还有空间:
        新字幕放到原字幕上面
    else:
        放到底部安全区，或者走加黑边方案
```

生成 ASS 示例：

```ass
[Script Info]
ScriptType: v4.00+
PlayResX: 720
PlayResY: 1280

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Noto Sans CJK SC,42,&H00FFFFFF,&H00000000,&H66000000,0,0,0,0,100,100,0,0,1,3,0,2,20,20,30,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.20,0:00:03.80,Default,,0,0,0,,{\an2\pos(360,1220)}你好，欢迎回来
Dialogue: 0,0:00:04.00,0:00:06.50,Default,,0,0,0,,{\an2\pos(360,1080)}这条字幕自动避开原字幕
```

然后用 FFmpeg 嵌入 ASS：

```bash
ffmpeg -y \
  -i input.mp4 \
  -vf "ass=subtitle.ass" \
  -c:v libx264 \
  -preset veryfast \
  -crf 20 \
  -c:a copy \
  output.mp4
```

这个方案效果最好，但开发成本高一些。

---

## 四、上传处理后的视频到 TOS

处理完成后，把 `output.mp4` 上传回 TOS。

普通上传适合小于 5GiB 的文件；TOS Java SDK 支持通过 `putObject` 上传对象，数据流可以用 `ByteArrayInputStream`、`FileInputStream` 等。较大的对象建议走分片上传或断点续传。([火山引擎][4])

伪代码：

```java
try (InputStream in = new FileInputStream(outputFile)) {
    PutObjectInput input = new PutObjectInput()
        .setBucket(bucketName)
        .setKey(outputObjectKey)
        .setContent(in);

    tos.putObject(input);
}
```

上传路径建议这样设计：

```text
原视频：
videos/original/{userId}/{taskId}.mp4

识别字幕：
videos/subtitles/{userId}/{taskId}.srt

嵌入后视频：
videos/result/{userId}/{taskId}.mp4
```

---

## 五、返回给用户下载

上传成功后，再生成一个 TOS GET 预签名 URL：

```java
String downloadUrl = tosService.generateGetPresignedUrl(
    bucketName,
    outputObjectKey,
    24 * 3600
);
```

返回给前端：

```json
{
  "taskId": "xxx",
  "status": "SUCCESS",
  "videoUrl": "https://xxx.tos-cn-shanghai.volces.com/videos/result/xxx.mp4?...签名...",
  "subtitleUrl": "https://xxx.tos-cn-shanghai.volces.com/videos/subtitles/xxx.srt?...签名..."
}
```

---

## 六、推荐落地方案

你的场景是“短剧视频 + 原字幕已内嵌 + 字幕位置要合适”，我建议用这个版本：

```text
1. TOS 生成原视频临时下载 URL
2. 阿里云视频 OCR 提取字幕，拿到 SRT
3. 后端下载原视频和 SRT 到临时目录
4. 可选：翻译 SRT，只改文本，不改时间轴
5. 检测原字幕框位置
6. 优先把新字幕放到原字幕下方
7. 如果原字幕已经贴底，就给底部加字幕安全区
8. FFmpeg 硬嵌字幕
9. 上传新视频到 TOS
10. 返回 TOS 下载链接
```

最稳的 FFmpeg 兜底命令是“保持原分辨率 + 留底部安全区”：

```bash
ffmpeg -y \
  -i input.mp4 \
  -vf "scale=720:1140,pad=720:1280:0:0:black,subtitles=subtitle.srt:force_style='Fontname=Noto Sans CJK SC,Fontsize=20,Alignment=2,MarginV=32,Outline=2,Shadow=0'" \
  -c:v libx264 \
  -preset veryfast \
  -crf 20 \
  -c:a copy \
  output.mp4
```

如果原视频不一定是 `720x1280`，后端先用 `ffprobe` 获取宽高，再动态计算 `scale` 和 `pad` 参数。

---

## 七、后端任务状态设计

建议不要同步阻塞接口等待整个视频处理完成，而是做异步任务：

```text
POST /video/subtitle/burn
```

请求：

```json
{
  "bucket": "your-bucket",
  "objectKey": "videos/original/123.mp4",
  "subtitleType": "chinese",
  "placementMode": "safe_bottom",
  "translateTo": "en"
}
```

返回：

```json
{
  "taskId": "20260627xxxx",
  "status": "PROCESSING"
}
```

查询：

```text
GET /video/subtitle/burn/{taskId}
```

返回：

```json
{
  "taskId": "20260627xxxx",
  "status": "SUCCESS",
  "videoUrl": "https://xxx.tos-cn-shanghai.volces.com/videos/result/xxx.mp4?...",
  "subtitleUrl": "https://xxx.tos-cn-shanghai.volces.com/videos/subtitles/xxx.srt?..."
}
```

任务状态可以这样拆：

```text
PENDING
GENERATING_TOS_URL
OCR_SUBMITTING
OCR_PROCESSING
SRT_DOWNLOADING
TRANSLATING
BURNING_SUBTITLE
UPLOADING_TOS
SUCCESS
FAILED
```

---

## 八、核心注意点

1. **不擦除原字幕就会有双字幕**
   只能通过避让、加黑边、安全区、压缩原画面来避免重叠。

2. **“靠下一点”不是简单调 `MarginV` 就行**
   如果原字幕已经在最底部，继续往下放会超出画面。此时要么加底部安全区，要么擦除原字幕。

3. **建议最终用 ASS，不要只用 SRT**
   SRT 只有时间和文本，位置控制能力弱；ASS 可以控制字体、字号、颜色、描边、边距、每条字幕位置。

4. **FFmpeg 要带 libass**
   否则 `subtitles` / `ass` 滤镜不可用。官方文档也说明 `subtitles` 滤镜依赖 libass。([FFmpeg][3])

5. **跨云会产生流量和耗时**
   视频在 TOS，识别在阿里云，中间会发生火山 TOS 到阿里云的视频读取；后续还要从阿里云结果地址下载 SRT，再本地处理后上传回 TOS。

6. **大视频建议切片处理**
   阿里云文档建议视频不超过 30 分钟；短剧一般没问题，长视频建议先切段，分别识别和合并 SRT。([阿里云帮助中心][1])

[1]: https://help.aliyun.com/zh/viapi/developer-reference/api-video-actor-staff-table-recognition "
    视频OCR RecognizeVideoCastCrewList的语法及示例-视觉智能开放平台(VIAPI)-阿里云帮助中心
  "
[2]: https://www.volcengine.com/docs/6349/173455?lang=zh&utm_source=chatgpt.com "预签名概述（Java SDK）--对象存储-火山引擎"
[3]: https://ffmpeg.org/ffmpeg-filters.html "      FFmpeg Filters Documentation
"
[4]: https://www.volcengine.com/docs/6349/79896?utm_source=chatgpt.com "快速入门（Java SDK）--对象存储-火山引擎"


不复杂，但要分层看：

```text
生成 ASS 文件：简单
设置固定字幕位置：简单
根据原字幕自动避让：中等偏复杂
做到稳定、适配各种短剧视频：偏复杂
```

## 1. 生成 ASS 文件复杂吗？

**不复杂。**

ASS 本质就是一个文本文件，包含三部分：

```text
[Script Info]
[V4+ Styles]
[Events]
```

你只要把阿里云 OCR 返回的 SRT 或字幕时间轴，转换成 ASS 的 `Dialogue` 行即可。

最小可用 ASS 示例：

```ass
[Script Info]
ScriptType: v4.00+
PlayResX: 720
PlayResY: 1280

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Noto Sans CJK SC,42,&H00FFFFFF,&H00000000,&H66000000,0,0,0,0,100,100,0,0,1,3,0,2,20,20,60,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.20,0:00:03.80,Default,,0,0,0,,你好，欢迎回来
Dialogue: 0,0:00:04.00,0:00:06.50,Default,,0,0,0,,这是第二句字幕
```

然后用 FFmpeg 嵌入：

```bash
ffmpeg -y \
  -i input.mp4 \
  -vf "ass=subtitle.ass" \
  -c:v libx264 \
  -preset veryfast \
  -crf 20 \
  -c:a copy \
  output.mp4
```

FFmpeg 官方说明，硬嵌字幕可以用 `subtitles` 或 `ass` 滤镜，底层依赖 `libass`；所以你的服务器 FFmpeg 需要带 `--enable-libass`。([trac.ffmpeg.org][1])

---

## 2. 固定设置字幕位置复杂吗？

**很简单。**

ASS 里有两种常用方式。

### 方式 A：用 Style 的 Alignment + MarginV

例如：

```ass
Style: Default,Noto Sans CJK SC,42,&H00FFFFFF,&H00000000,&H66000000,0,0,0,0,100,100,0,0,1,3,0,2,20,20,60,1
```

关键字段：

```text
Alignment = 2  底部居中
MarginV = 60   距离底部 60 像素
```

这种适合所有字幕都放同一个位置。

### 方式 B：每条字幕用 `\pos(x,y)`

例如：

```ass
Dialogue: 0,0:00:01.20,0:00:03.80,Default,,0,0,0,,{\an2\pos(360,1180)}你好，欢迎回来
```

含义：

```text
\an2        底部居中锚点
\pos(360,1180)   放在 x=360, y=1180 的位置
```

Aegisub 的 ASS 标签说明里也提到，`\pos` 用于控制字幕位置，`\an` / Alignment 决定字幕块的锚点。([Aegisub][2])

如果你只想让字幕固定在底部偏下位置，逻辑大概就是：

```java
int x = videoWidth / 2;
int y = videoHeight - 80;

String line = String.format(
    "Dialogue: 0,%s,%s,Default,,0,0,0,,{\\an2\\pos(%d,%d)}%s",
    startTime,
    endTime,
    x,
    y,
    text
);
```

这个实现难度很低。

---

## 3. 你这个场景真正复杂的是“不要和原字幕重叠”

因为你的视频原本就有内嵌字幕，如果你再把新字幕放到底部，就可能变成这样：

```text
原字幕：你到底想怎么样？
新字幕：What do you want?
```

两行可能重叠。

所以有几种实现难度。

---

# 方案一：固定放底部，开发最简单

适合：

```text
原视频没有字幕
或者原字幕不在底部
或者允许少量重叠风险
```

ASS 生成：

```ass
Dialogue: 0,0:00:01.20,0:00:03.80,Default,,0,0,0,,{\an2\pos(360,1200)}Hello, welcome back
```

复杂度：

```text
低
```

缺点：

```text
无法保证不和原字幕重叠
```

不太推荐给短剧翻译场景作为默认方案。

---

# 方案二：底部安全区，推荐

适合你的场景。

思路是：**不要把新字幕直接画到原画面上，而是给底部留出一块区域专门放新字幕。**

有两种做法。

## 做法 A：增加画布高度

比如原视频是 `720x1280`，输出变成 `720x1420`，下面多出 140 像素黑边，新字幕放黑边里。

FFmpeg：

```bash
ffmpeg -y \
  -i input.mp4 \
  -vf "pad=iw:ih+140:0:0:black,ass=subtitle.ass" \
  -c:v libx264 \
  -preset veryfast \
  -crf 20 \
  -c:a copy \
  output.mp4
```

ASS 里设置：

```ass
PlayResX: 720
PlayResY: 1420
```

字幕位置：

```ass
Dialogue: 0,0:00:01.20,0:00:03.80,Default,,0,0,0,,{\an2\pos(360,1360)}Hello, welcome back
```

优点：

```text
不会遮挡原画面
基本不会和原字幕重叠
实现简单
```

缺点：

```text
输出视频尺寸变了
有些平台可能不喜欢非标准比例
```

---

## 做法 B：保持原分辨率，缩小原画面，底部留黑边

比如原视频是 `720x1280`，保持输出还是 `720x1280`，但把原画面缩小到 `720x1140`，下面留 140 像素给新字幕。

FFmpeg：

```bash
ffmpeg -y \
  -i input.mp4 \
  -vf "scale=720:1140,pad=720:1280:0:0:black,ass=subtitle.ass" \
  -c:v libx264 \
  -preset veryfast \
  -crf 20 \
  -c:a copy \
  output.mp4
```

ASS：

```ass
PlayResX: 720
PlayResY: 1280
```

字幕位置：

```ass
Dialogue: 0,0:00:01.20,0:00:03.80,Default,,0,0,0,,{\an2\pos(360,1220)}Hello, welcome back
```

复杂度：

```text
中低
```

这个方案我最推荐你作为网站默认方案，因为：

```text
不需要复杂识别原字幕位置
基本不会重叠
输出尺寸还能保持 720x1280 / 1080x1920
效果稳定
```

缺点是原视频会被轻微缩小，但短剧场景通常可以接受。

---

# 方案三：根据原字幕位置动态避让

这个是效果最好，但复杂度明显上升。

阿里云视频 OCR 的结果里有文本框坐标，例如：

```json
{
  "StartTime": 1.2,
  "EndTime": 3.8,
  "DetailInfo": [
    {
      "Text": "你到底想怎么样",
      "Boxes": [120, 1080, 600, 1150],
      "Position": [
        {"X": 120, "Y": 1080},
        {"X": 600, "Y": 1080},
        {"X": 600, "Y": 1150},
        {"X": 120, "Y": 1150}
      ]
    }
  ]
}
```

你可以根据 `Boxes` 判断原字幕在哪：

```text
原字幕底部 y = 1150
视频高度 = 1280
底部剩余空间 = 1280 - 1150 = 130
```

然后决定新字幕放哪里。

伪逻辑：

```java
int videoW = 720;
int videoH = 1280;

int subtitleHeight = estimateSubtitleHeight(text, fontSize);
int safeMargin = 30;

Box originalBox = findOriginalSubtitleBox(startTime, endTime);

int x = videoW / 2;
int y;

if (originalBox != null) {
    int spaceBelow = videoH - originalBox.ymax;
    int spaceAbove = originalBox.ymin;

    if (spaceBelow > subtitleHeight + safeMargin) {
        // 原字幕下面还有空间，新字幕放下面
        y = originalBox.ymax + subtitleHeight;
    } else if (spaceAbove > subtitleHeight + safeMargin) {
        // 下面没空间，放原字幕上方
        y = originalBox.ymin - safeMargin;
    } else {
        // 上下都不够，走兜底方案
        y = videoH - 60;
    }
} else {
    // 没识别到原字幕，默认底部
    y = videoH - 80;
}
```

生成 ASS：

```ass
Dialogue: 0,0:00:01.20,0:00:03.80,Default,,0,0,0,,{\an2\pos(360,1020)}Hello, welcome back
```

复杂度：

```text
中等偏高
```

主要难点不是写 ASS，而是这些细节：

```text
1. OCR 框不一定稳定，每一帧位置可能抖动
2. 有些视频有水印、标题、弹幕，不能全当字幕
3. 字幕可能是两行、三行
4. 翻译后文字变长，需要自动换行
5. 不同分辨率、横屏、竖屏都要适配
6. 原字幕可能已经贴底，根本没有空间往下放
7. 字体实际渲染高度不好精确估算
```

所以如果你追求稳定上线，建议不要一开始就做完全动态避让。

---

## 我建议你的实现路线

### 第一版：生成 ASS + 底部安全区

这是最稳的 MVP。

前端给用户选：

```json
{
  "subtitlePosition": "safe_bottom",
  "keepOriginalSubtitle": true,
  "outputResolution": "same_as_source"
}
```

后端做：

```text
1. ffprobe 获取视频宽高
2. 计算底部安全区高度，例如视频高度的 10% ~ 14%
3. 缩小原画面
4. 底部 pad 黑边
5. 生成 ASS，把新字幕放在黑边里
6. FFmpeg 硬嵌
```

动态计算示例：

```java
int w = videoWidth;
int h = videoHeight;

int safeArea = Math.max(120, h / 10);
int contentHeight = h - safeArea;

int subtitleX = w / 2;
int subtitleY = h - safeArea / 2;
```

ASS：

```ass
PlayResX: 720
PlayResY: 1280

Dialogue: 0,0:00:01.20,0:00:03.80,Default,,0,0,0,,{\an2\pos(360,1210)}Hello, welcome back
```

FFmpeg 参数动态生成：

```bash
ffmpeg -y \
  -i input.mp4 \
  -vf "scale=720:1140,pad=720:1280:0:0:black,ass=subtitle.ass" \
  -c:v libx264 \
  -preset veryfast \
  -crf 20 \
  -c:a copy \
  output.mp4
```

这个版本不需要复杂分析原字幕位置，效果可控。

---

### 第二版：支持顶部、底部、自定义位置

在 ASS 里用不同 `\an` 和 `\pos` 即可。

```text
顶部居中：{\an8\pos(w/2, 80)}
中间居中：{\an5\pos(w/2, h/2)}
底部居中：{\an2\pos(w/2, h-80)}
底部安全区：{\an2\pos(w/2, h-safeArea/2)}
```

前端可选项：

```json
{
  "position": "safe_bottom"
}
```

对应：

| position      | ASS 位置                          |
| ------------- | ------------------------------- |
| `top`         | `{\an8\pos(w/2, 80)}`           |
| `center`      | `{\an5\pos(w/2, h/2)}`          |
| `bottom`      | `{\an2\pos(w/2, h-80)}`         |
| `safe_bottom` | `{\an2\pos(w/2, h-safeArea/2)}` |
| `custom`      | `{\an2\pos(x,y)}`               |

这个也不复杂。

---

### 第三版：OCR 框动态避让

等你第一版稳定后再做。

这版要用阿里云返回的 `VideoOcrResults` / `OcrResults` 坐标，判断原字幕区域，再生成每条字幕自己的 `\pos(x,y)`。

推荐不要完全相信每一帧 OCR，而是做聚合：

```text
同一句字幕时间段内：
1. 找到下半屏的 OCR 文本框
2. 过滤掉水印、角标、广告
3. 取 y 坐标中位数
4. 判断原字幕区域
5. 生成新字幕位置
```

这样比逐帧计算稳定。

---

## Java 里生成 ASS 的核心代码大概这样

```java
public class AssSubtitleBuilder {

    public static String buildAss(List<SubtitleLine> lines, int width, int height) {
        int fontSize = Math.max(28, height / 30);
        int outline = Math.max(2, height / 500);
        int marginV = Math.max(40, height / 18);

        StringBuilder sb = new StringBuilder();

        sb.append("[Script Info]\n");
        sb.append("ScriptType: v4.00+\n");
        sb.append("PlayResX: ").append(width).append("\n");
        sb.append("PlayResY: ").append(height).append("\n\n");

        sb.append("[V4+ Styles]\n");
        sb.append("Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, ")
          .append("Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, ")
          .append("BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n");

        sb.append(String.format(
            "Style: Default,Noto Sans CJK SC,%d,&H00FFFFFF,&H00000000,&H66000000," +
            "0,0,0,0,100,100,0,0,1,%d,0,2,20,20,%d,1\n\n",
            fontSize, outline, marginV
        ));

        sb.append("[Events]\n");
        sb.append("Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n");

        int x = width / 2;
        int y = height - marginV;

        for (SubtitleLine line : lines) {
            String text = escapeAssText(line.getText());

            sb.append(String.format(
                "Dialogue: 0,%s,%s,Default,,0,0,0,,{\\an2\\pos(%d,%d)}%s\n",
                toAssTime(line.getStartMs()),
                toAssTime(line.getEndMs()),
                x,
                y,
                text
            ));
        }

        return sb.toString();
    }

    private static String toAssTime(long ms) {
        long cs = ms / 10;
        long hours = cs / 360000;
        cs %= 360000;
        long minutes = cs / 6000;
        cs %= 6000;
        long seconds = cs / 100;
        long centiseconds = cs % 100;

        return String.format("%d:%02d:%02d.%02d", hours, minutes, seconds, centiseconds);
    }

    private static String escapeAssText(String text) {
        if (text == null) {
            return "";
        }

        return text
            .replace("\\", "\\\\")
            .replace("{", "\\{")
            .replace("}", "\\}")
            .replace("\n", "\\N");
    }
}
```

`SubtitleLine` 可以是：

```java
public class SubtitleLine {
    private long startMs;
    private long endMs;
    private String text;

    // getter / setter
}
```

---

## 结论

你要做的两个功能，复杂度大概是：

| 功能           | 复杂度 | 建议             |
| ------------ | --: | -------------- |
| SRT 转 ASS    |   低 | 可以直接做          |
| 统一设置字体、字号、描边 |   低 | 必做             |
| 固定底部位置       |   低 | 可做，但短剧不建议默认    |
| 底部安全区        |  中低 | 最推荐            |
| 保持原分辨率并留安全区  |  中低 | 最适合网站上线        |
| 自动避让原字幕      |  中高 | 第二阶段做          |
| 擦除原字幕再嵌入     |   高 | 需要接视频修复/字幕擦除能力 |

我的建议是：

```text
第一版不要做动态避让。
先做：生成 ASS + 底部安全区 + 保持原分辨率。
```

这样实现难度不高，效果稳定，也最适合你现在“提取字幕 -> 翻译/处理 -> 嵌入视频 -> 上传 TOS -> 给用户下载”的网站流程。

[1]: https://trac.ffmpeg.org/wiki/HowToBurnSubtitlesIntoVideo?utm_source=chatgpt.com "HowToBurnSubtitlesIntoVideo – FFmpeg"
[2]: https://aegisub.org/docs/latest/ass_tags/?utm_source=chatgpt.com "ASS Override Tags - Aegisub"

