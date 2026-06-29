在当前工程增加一个视频字幕提取-翻译-合并到新的视频的功能:
主要使用的阿里云API参考:https://help.aliyun.com/zh/viapi/developer-reference/api-video-actor-staff-table-recognition?spm=a2cw1.28084037.console-base_help.dexternal.6952143fbs5VFf

需求详细的介绍参考当前目录下的:subtitle-extract-rquirement.md

视频上传和嵌入新的字幕的视频都上传到TOS中

所有历史记录保存，支持查看历史记录

在数据库中设计合理的表相关的记录(不要删除或者清空数据库已有数据，已有数据不允许动，只是新增一张表不需要数据迁移吧，如果需要迁移，将数据库所有数据进行迁移)

要求提取字幕 翻译字幕 翻译后的字幕合并到视频等每个功能都可以根据前端界面选项按需实现

TOS 和 阿里云的API访问 翻译等都参考当前仓库已有的代码功能

实现功能后，使用这个视频测试:https://test-short-drama.tos-cn-beijing.volces.com/uploads/034c1b04-11f7-4f18-ad46-718c3553cd8d/00-1_srt.mp4

