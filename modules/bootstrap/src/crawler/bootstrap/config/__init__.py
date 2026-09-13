"""Settings 的字段分域实现。

``crawler.bootstrap.settings.Settings`` 只负责把这些分域字段类组装成完整配置，
并对齐 config.yaml 的 YAML 数据源；本包内每个模块只承载一个域的字段与本地校验：

- ``base``：仓库根目录常量、相对路径字段清单、通用解析函数
- ``app_fields``：应用与认证、邮件、MCP 网关
- ``infra_fields``：PostgreSQL 与对象存储连接
- ``browser_fields``：浏览器模式、本机/远程槽位与槽位声明模型
- ``douyin_fields``：账号会话、采集风控、互动风控
- ``media_fields``：媒体下载与字幕转写
- ``ui_fields``：前端展示文案
- ``yaml_source``：config.yaml 的读取、深层合并、占位符展开与字段映射表

字段类之间互不依赖，组合顺序不影响取值；新增配置项时先放进对应域文件，再到
``yaml_source._CONFIG_FIELD_MAP`` 登记 YAML 路径（架构测试会检查不漏项）。
"""
