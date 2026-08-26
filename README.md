# ⏰ 时段切换模型（Time Model）

一个 [AstrBot](https://github.com/Soulter/AstrBot) 插件：**按服务器当前时间，自动为每次 LLM 请求切换不同的模型 Provider**。

白天用便宜、快速的模型省钱，夜间或高峰期切换到更聪明的模型保证质量——全程自动，无需手动干预。

> 💡 典型场景：利用 DeepSeek 的**错峰优惠**（北京时间 00:30–08:30 半价），低谷时段自动切到 DeepSeek，白天再切回主力模型。

> 📌 **AstrBot v4 适配说明**：v4 中一个 Provider 实例即「服务商 + 模型」的组合，其 ID 形如 `deepseek/deepseek-v4-flash-vision-exp`。本插件已适配 v4，直接使用完整的 Provider ID（服务商/模型），不再区分「供应商」和「模型」两个字段。

---

## ✨ 功能特性

- 🕐 **按时段自动切换 Provider**，命中即生效
- 🖼️ **多模态保护**：检测到图片 / 视频消息时自动跳过切换，保留视觉模型处理多模态内容
- 🖥️ **WebUI 可视化配置**：在 AstrBot 插件管理页直接增删改时段、选 Provider
- 💬 **命令行指令**：在聊天里用 `/schedule*` 指令实时增删改，无需重启
- 🌙 **支持跨天时段**：如 `22:00 → 08:00` 表示「夜间」
- 🌍 **多时区支持**：基于 `zoneinfo`，可指定 `Asia/Shanghai` 等时区
- 🎯 **兜底模型**：所有时段都不命中时，可回退到指定默认 Provider
- 🔄 **配置持久化 + 热更新**，改完即生效
- 🔁 **自动迁移旧配置**：旧版「`provider` + `model`」分离字段会自动合并为 v4 的完整 Provider ID

---

## 📦 安装

### 方式一：AstrBot WebUI 上传（推荐）

1. 下载本插件并打包为 zip（或在仓库 Releases 中下载 `astrbot_plugin_time_model.zip`）
2. 打开 AstrBot WebUI → **插件管理** → 上传插件
3. 上传成功后，插件会自动加载

### 方式二：手动部署

```bash
cd /path/to/astrbot/data/plugins/
git clone https://github.com/MankindLumi/astrbot_plugin_time_model.git
# 重启 AstrBot
systemctl restart astrbot
```

---

## 🚀 快速开始

插件内置了一套默认配置（可直接用，也可按需修改）：

| 时段（北京时间） | Provider ID |
|---|---|
| `00:30 – 08:30`（低谷·错峰半价） | `deepseek/deepseek-v4-flash-vision-exp` |
| `08:30 – 次日 00:30`（高峰） | `zhipu/glm-5.3` |

两个时段无缝衔接、全天覆盖，时区固定为 `Asia/Shanghai`（北京时间）。

> Provider ID 即你在 AstrBot「模型供应商」页面里每个实例的 ID（`服务商/模型`）。请填真实存在的 ID，例如 `deepseek/deepseek-v4-pro`、`zhipu/glm-4v-flash` 等。

---

## ⚙️ 配置方式

插件同时支持 **WebUI 图形界面** 和 **聊天指令** 两种配置方式，满足不同习惯。

### 1. WebUI 可视化配置（推荐）

打开 **AstrBot WebUI → 插件管理 → 「时段切换模型」**，即可看到可视化表单：

- **启用插件**：开关
- **时区**：下拉选择（默认「中国 UTC+8」）
- **时段规则**：可自由增删改，每项包含：
  - `名称`：仅用于展示，如「夜间低价」
  - `开始时间` / `结束时间`：24 小时制 `HH:MM`，支持跨天
  - `模型 Provider`：下拉选择 AstrBot 里的完整 Provider ID（服务商/模型）
- **默认模型**：无时段命中时的兜底 Provider

改完点**保存**即自动生效，无需重启。

### 2. 命令行指令

在聊天窗口（需是管理员）发送以下指令：

| 指令 | 作用 |
|---|---|
| `/schedule` | 查看当前配置 + 帮助 |
| `/schedule_now` | 查看此刻会使用哪个 Provider |
| `/schedule_add <开始> <结束> <provider> [名字]` | 新增时段 |
| `/schedule_set <序号> <开始> <结束> <provider>` | 修改第 N 个时段 |
| `/schedule_del <序号>` | 删除第 N 个时段 |
| `/schedule_default <provider>` | 设置兜底默认 Provider（传 `-` 清空） |
| `/schedule_reload` | 从文件重新加载配置 |
| `/schedule_on` / `/schedule_off` | 启用 / 停用插件 |

> 序号从 `0` 开始。`provider` 填 AstrBot 里的**完整 Provider ID**（`服务商/模型`），例如 `deepseek/deepseek-v4-flash-vision-exp`。

---

## 🕐 时段匹配规则

1. 按配置列表**顺序**匹配，**第一个命中**的时段生效
2. 时间比较精确到分钟，`[开始, 结束)` 左闭右开
3. 支持**跨天**：当 `开始 > 结束` 时，表示「当天开始 → 次日结束」，如 `22:00 → 08:00` 覆盖整个夜间
4. 无任何时段命中时，回退到「默认模型」；默认模型也为空时，**不干预**，走 AstrBot 自身默认模型
5. 消息含**图片 / 视频**等多模态媒体时，**自动跳过切换**，保留视觉模型

---

## 📄 配置结构（进阶）

WebUI 配置会保存为 `data/config/astrbot_plugin_time_model_config.json`，结构如下：

```json
{
  "enable": true,
  "timezone": "Asia/Shanghai",
  "schedules": [
    {
      "name": "低谷（DeepSeek 错峰）",
      "start": "00:30",
      "end": "08:30",
      "provider": "deepseek/deepseek-v4-flash-vision-exp"
    },
    {
      "name": "高峰（智谱）",
      "start": "08:30",
      "end": "00:30",
      "provider": "zhipu/glm-5.3"
    }
  ],
  "default_model": {
    "provider": ""
  }
}
```

字段说明：

| 字段 | 类型 | 说明 |
|---|---|---|
| `enable` | bool | 是否启用插件 |
| `timezone` | string | 时区，如 `Asia/Shanghai`；留空使用服务器本地时间 |
| `schedules` | list | 时段规则列表 |
| `schedules[].name` | string | 时段名称（仅展示） |
| `schedules[].start` | string | 开始时间 `HH:MM` |
| `schedules[].end` | string | 结束时间 `HH:MM`，可跨天 |
| `schedules[].provider` | string | 完整 Provider ID（`服务商/模型`） |
| `default_model` | object | 兜底 Provider（`provider` 字段） |

> 旧版配置里若还有独立的 `model` 字段，插件会自动将其合并进 `provider`（`服务商/模型`），无需手动修改。

---

## 📁 目录结构

```
astrbot_plugin_time_model/
├── metadata.yaml          # 插件元信息
├── main.py                # 插件核心逻辑
├── _conf_schema.json      # WebUI 配置表单定义
└── README.md              # 本文档
```

---

## ❓ 常见问题

**Q：`provider` 填什么？**
填你在 AstrBot「模型供应商」页面里的**完整 Provider ID**（`服务商/模型`），例如 `deepseek/deepseek-v4-flash-vision-exp`、`zhipu/glm-5.3`，而不是中文名。

**Q：Provider ID 填错了会怎样？**
调用会报「未找到指定的提供商」。务必填写 AstrBot「模型供应商」下拉里**真实存在**的 Provider ID。

**Q：服务器不在中国，时间怎么算？**
把 `timezone` 设为 `Asia/Shanghai` 即可严格按北京时间切换（插件默认已如此设置）。

**Q：改了配置要重启吗？**
不需要。WebUI 保存或 `/schedule*` 指令改完即自动生效。

**Q：发了图片，会误切到文本模型吗？**
不会。插件检测到图片 / 视频消息会自动跳过切换，保留视觉模型处理多模态内容。

**Q：如何临时关闭切换？**
WebUI 关闭「启用插件」开关，或聊天里发 `/schedule_off`。

---

## 📄 许可证

[MIT](./LICENSE) © operit
