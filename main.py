"""AstrBot 插件：按时段自动切换 AI 模型 Provider（time-model）

按服务器当前时间，为每次 LLM 请求自动选择不同的 Provider。
AstrBot v4 中，一个 Provider 实例即「服务商 + 模型」的组合，
其 ID 形如 `deepseek/deepseek-v4-flash-vision-exp`（见 WebUI「模型供应商」下拉框）。

典型用法：
  * 白天 / 非高峰期用便宜、快速的模型，省成本；
  * 夜间 / 高峰期切换到更聪明的模型，提升质量；
  * 或者按渠道切换（智谱 / DeepSeek / OpenAI 等）。

【后期可改】时段 → Provider 映射支持两种方式：
  1. AstrBot WebUI → 插件管理 →「时段切换模型」：可视化增删时段、选 Provider（推荐）；
  2. 用管理指令实时增删改（改完自动落盘，无需重启）。

命令前缀默认是 AstrBot 的 ``/``（如果你配置成了别的，按你的来）：
  /schedule                      查看当前配置 + 当前生效 Provider
  /schedule_now                  只看此刻应该用哪个 Provider
  /schedule_add <start> <end> <provider> [name]   新增时段
  /schedule_set <idx> <start> <end> <provider>    修改第 idx 个时段
  /schedule_del <idx>            删除第 idx 个时段
  /schedule_default <provider>   设置默认（无时段命中时使用）
  /schedule_reload               重新从文件加载配置
  /schedule_on  /  /schedule_off     启用 / 停用本插件

说明：
  * provider 填 AstrBot「模型供应商」下拉里的完整 ID（服务商/模型），
    例如 deepseek/deepseek-v4-flash-vision-exp、zhipu/glm-4v-flash。
  * 时段支持跨天，例如 22:00 → 08:00 表示「夜间」。
  * 默认使用服务器本地时间；若服务器不是北京时间，可在配置里加
    "timezone": "Asia/Shanghai" 指定时区。
"""
from __future__ import annotations

import json
import shlex
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, StarTools

try:  # Python 3.9+ 时区支持
    from zoneinfo import ZoneInfo
except ImportError:  # noqa: F401
    ZoneInfo = None


def _build_default_config() -> dict:
    """内置默认配置。用户首次运行时会被写到 schedules.json。"""
    return {
        # 是否启用时段切换
        "enable": True,
        # 按北京时间判断（DeepSeek 错峰优惠是北京时间 00:30-08:30）
        "timezone": "Asia/Shanghai",
        # 时段列表：start/end 为 "HH:MM"，命中即用对应 Provider ID（服务商/模型）
        "schedules": [
            {
                "name": "低谷（DeepSeek 错峰）",
                "start": "00:30",
                "end": "08:30",
                "provider": "deepseek/deepseek-v4-flash-vision-exp",
            },
            {
                "name": "高峰（智谱）",
                "start": "08:30",
                "end": "00:30",
                "provider": "zhipu/glm-4v-flash",
            },
        ],
        # 无任何时段命中时的兜底 Provider（留空表示不干预，用 AstrBot 默认）
        "default_model": {
            "provider": "",
        },
    }


class TimeModel(Star):
    """按时段自动切换 AI 模型 Provider 的插件。"""

    def __init__(self, context: Context, config: Any = None) -> None:
        super().__init__(context)
        self.context = context
        # AstrBot 若检测到 _conf_schema.json，会传入 AstrBotConfig（dict 子类），
        # 此时配置由 WebUI 管理（保存到 data/config/<插件名>_config.json）。
        self._webui_cfg = config if config is not None else None
        self._cfg_path: Optional[Path] = None
        if self._webui_cfg is not None:
            self.cfg = self._normalize(self._webui_cfg)
        else:
            self._cfg_path = self._resolve_cfg_path()
            self._load()

    # ---------- 配置文件路径 ----------

    def _resolve_cfg_path(self) -> Path:
        # 优先用 AstrBot 给插件的数据目录（升级/重装插件不丢配置）
        try:
            data_dir = StarTools.get_data_dir()
            if data_dir:
                d = Path(data_dir)
                d.mkdir(parents=True, exist_ok=True)
                return d / "schedules.json"
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[TimeModel] StarTools.get_data_dir 不可用: {exc}")
        # 回退到插件自身目录
        plugin_dir = Path(__file__).resolve().parent / "data"
        plugin_dir.mkdir(parents=True, exist_ok=True)
        return plugin_dir / "schedules.json"

    # ---------- 配置读写 ----------

    def _load(self) -> None:
        try:
            if self._cfg_path.exists():
                with open(self._cfg_path, encoding="utf-8") as f:
                    cfg = json.load(f)
                self.cfg = self._normalize(cfg)
            else:
                self.cfg = _build_default_config()
                self._save()
        except Exception as exc:  # noqa: BLE001
            logger.error(f"[TimeModel] 读取配置失败，使用默认配置: {exc}")
            self.cfg = _build_default_config()

    @staticmethod
    def _migrate_entry(entry: dict) -> None:
        """把旧版独立的 model 字段合并进 provider（v4 的 provider id = 服务商/模型）。"""
        model = str(entry.pop("model", "") or "").strip()
        provider = str(entry.get("provider", "") or "").strip()
        if not model:
            return
        if provider and "/" not in provider:
            entry["provider"] = f"{provider}/{model}"
        elif not provider:
            entry["provider"] = model
        # 若 provider 已含 "/"（完整 id），保持不变并丢弃 model

    def _normalize(self, cfg: dict) -> dict:
        cfg.setdefault("enable", True)
        cfg.setdefault("timezone", "")
        cfg.setdefault("schedules", [])
        cfg.setdefault("default_model", {})
        # 迁移旧版：把独立的 model 合并进 provider
        for s in cfg.get("schedules", []):
            if isinstance(s, dict):
                self._migrate_entry(s)
        # 兼容旧版 schedules.json 使用的 "default" 兜底模型字段
        old_default = cfg.get("default")
        if isinstance(old_default, dict):
            dm = cfg.setdefault("default_model", {})
            if old_default.get("provider"):
                dm.setdefault("provider", str(old_default.get("provider", "")).strip())
            if old_default.get("model"):
                dm.setdefault("model", str(old_default.get("model", "")).strip())
        dm = cfg.setdefault("default_model", {})
        self._migrate_entry(dm)
        dm.setdefault("provider", "")
        return cfg

    def _save(self) -> None:
        if self._webui_cfg is not None:
            # 写回 AstrBot 的插件配置（data/config/<插件名>_config.json）
            try:
                self._webui_cfg.save_config()
            except Exception as exc:  # noqa: BLE001
                logger.error(f"[TimeModel] 保存 WebUI 配置失败: {exc}")
            return
        try:
            with open(self._cfg_path, "w", encoding="utf-8") as f:
                json.dump(self.cfg, f, ensure_ascii=False, indent=2)
        except Exception as exc:  # noqa: BLE001
            logger.error(f"[TimeModel] 保存配置失败: {exc}")

    # ---------- 时间计算 ----------

    def _now(self) -> datetime:
        tz_cfg = (self.cfg.get("timezone") or "").strip()
        if tz_cfg and ZoneInfo is not None:
            try:
                return datetime.now(ZoneInfo(tz_cfg))
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"[TimeModel] 时区 {tz_cfg} 无效，回退到本地时间: {exc}")
        return datetime.now()

    @staticmethod
    def _to_min(value: str) -> int:
        """把 'HH:MM' 转成当天分钟数；非法返回 -1。"""
        try:
            h, m = value.strip().split(":")
            return int(h) * 60 + int(m)
        except Exception:  # noqa: BLE001
            return -1

    def _match_schedule(self, now_min: int) -> Optional[dict]:
        for s in self.cfg.get("schedules", []):
            start = self._to_min(str(s.get("start", "")))
            end = self._to_min(str(s.get("end", "")))
            if start < 0 or end < 0:
                continue
            if start <= end:
                hit = start <= now_min < end
            else:  # 跨天，如 22:00 -> 08:00
                hit = now_min >= start or now_min < end
            if hit:
                return s
        return None

    def _pick(self) -> tuple[str, str]:
        """返回 (来源说明, provider_id)。provider_id 为 AstrBot v4 完整「服务商/模型」ID。"""
        now = self._now()
        now_min = now.hour * 60 + now.minute
        s = self._match_schedule(now_min)
        if s:
            return (s.get("name") or "未命名", s.get("provider") or "")
        d = self.cfg.get("default_model") or self.cfg.get("default") or {}
        return ("默认", d.get("provider") or "")

    @staticmethod
    def _type_name(part) -> str:
        """从 dict 或 ContentPart 对象里取出 type 值并转小写字符串。"""
        if isinstance(part, dict):
            return str(part.get("type", "") or "").lower()
        t = getattr(part, "type", None)
        if hasattr(t, "value"):  # 枚举类型
            t = t.value
        return str(t or "").lower()

    @staticmethod
    def _event_has_media(event) -> bool:
        """判断当前消息是否含图片/视频等多模态媒体（用于保留视觉模型）。"""
        try:
            msg = getattr(event, "message_obj", None)
            if msg is not None:
                comps = getattr(msg, "message", None) or []
                for comp in comps:
                    if TimeModel._type_name(comp) in {"Image", "Video"}:
                        return True
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[TimeModel] 检测 event 媒体失败: {exc}")
        return False

    # ---------- LLM 请求钩子：切换 Provider ----------

    @filter.on_waiting_llm_request()
    async def on_waiting_llm_request(self, event: AstrMessageEvent) -> None:
        """在 provider 被解析之前写入 selected_provider，以切换模型。

        AstrBot v4 的 provider 在 build_main_agent -> _select_provider 阶段解析，
        而 on_llm_request 钩子在该阶段之后才触发，无法再切换；
        因此必须使用触发更早的 on_waiting_llm_request。
        """
        if not self.cfg.get("enable", True):
            return
        try:
            if self._event_has_media(event):
                logger.info("[TimeModel] 检测到图片/视频媒体，跳过时段模型切换（保留视觉模型）")
                return

            src, provider_id = self._pick()
            if not provider_id:
                return  # 无匹配且无默认，不干预

            # 尊重上层已显式指定的 provider（如 WebChat/OpenAPI 手动选择）
            if event.get_extra("selected_provider"):
                logger.info("[TimeModel] 已存在显式 selected_provider，跳过时段切换")
                return

            event.set_extra("selected_provider", provider_id)
            logger.info(f"[TimeModel] 时段[{src}]切换 Provider: {provider_id}")
        except Exception as exc:  # noqa: BLE001
            logger.error(f"[TimeModel] Provider 切换失败: {exc}")

    # ---------- 管理指令 ----------

    @staticmethod
    def _args(event: AstrMessageEvent, extra_args: tuple) -> list:
        """优先取 AstrBot 注入的 args，取不到则从消息原文解析。"""
        if extra_args and any(extra_args):
            return list(extra_args)
        try:
            text = event.get_message_str() or ""
            parts = shlex.split(text)
            if parts:
                return parts[1:]  # 去掉命令名（如 /schedule_add）
        except Exception:  # noqa: BLE001
            pass
        return []

    @filter.command("schedule", desc="查看当前配置与生效 Provider")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def cmd_help(self, event: AstrMessageEvent):
        yield event.plain_result(self._build_help())

    @filter.command("schedule_now", desc="查看此刻会使用哪个 Provider")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def cmd_now(self, event: AstrMessageEvent):
        now = self._now()
        src, provider_id = self._pick()
        provider_id = provider_id or "(未设置)"
        yield event.plain_result(
            f"当前时间：{now:%Y-%m-%d %H:%M:%S}\n"
            f"命中时段：{src}\n"
            f"将使用：{provider_id}"
        )

    @filter.command("schedule_add", desc="新增时段：<开始> <结束> <provider> [名字]")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def cmd_add(self, event: AstrMessageEvent, *args):
        a = self._args(event, args)
        if len(a) < 3:
            yield event.plain_result("用法：/schedule_add <start> <end> <provider> [name]")
            return
        start, end, provider = a[0], a[1], a[2]
        name = a[3] if len(a) > 3 else f"{start}-{end}"
        item = {"name": name, "start": start, "end": end, "provider": provider}
        self.cfg.setdefault("schedules", []).append(item)
        self._save()
        yield event.plain_result(f"已新增时段「{name}」：{start}-{end} → {provider}")

    @filter.command("schedule_set", desc="修改时段：<序号> <开始> <结束> <provider>")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def cmd_set(self, event: AstrMessageEvent, *args):
        a = self._args(event, args)
        if len(a) < 4:
            yield event.plain_result("用法：/schedule_set <idx> <start> <end> <provider>")
            return
        try:
            idx = int(a[0])
        except ValueError:
            yield event.plain_result("第 1 个参数必须是序号（从 0 开始）。")
            return
        schedules = self.cfg.get("schedules", [])
        if idx < 0 or idx >= len(schedules):
            yield event.plain_result(f"序号超出范围，当前共 {len(schedules)} 个时段。")
            return
        schedules[idx] = {
            "name": schedules[idx].get("name", f"时段{idx}"),
            "start": a[1], "end": a[2], "provider": a[3],
        }
        self._save()
        yield event.plain_result(f"已更新第 {idx} 个时段。")

    @filter.command("schedule_del", desc="删除时段：<序号>")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def cmd_del(self, event: AstrMessageEvent, *args):
        a = self._args(event, args)
        if len(a) < 1:
            yield event.plain_result("用法：/schedule_del <idx>")
            return
        try:
            idx = int(a[0])
        except ValueError:
            yield event.plain_result("参数必须是序号（从 0 开始）。")
            return
        schedules = self.cfg.get("schedules", [])
        if idx < 0 or idx >= len(schedules):
            yield event.plain_result(f"序号超出范围，当前共 {len(schedules)} 个时段。")
            return
        removed = schedules.pop(idx)
        self._save()
        yield event.plain_result(f"已删除时段「{removed.get('name')}」。")

    @filter.command("schedule_default", desc="设置兜底默认 Provider（传 - 清空）")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def cmd_default(self, event: AstrMessageEvent, *args):
        a = self._args(event, args)
        if len(a) < 1:
            yield event.plain_result("用法：/schedule_default <provider>（传 - 可清空）")
            return
        provider = "" if a[0] == "-" else a[0]
        self.cfg["default_model"] = {"provider": provider}
        self._save()
        yield event.plain_result(
            f"默认 Provider 设置为：{provider or '(不干预)'}"
        )

    @filter.command("schedule_reload", desc="重新从文件加载配置")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def cmd_reload(self, event: AstrMessageEvent):
        if self._webui_cfg is not None:
            yield event.plain_result(
                "配置已由 WebUI 管理，在插件管理页保存后自动生效，无需手动 reload。"
            )
            return
        self._load()
        yield event.plain_result("已从文件重新加载配置。")

    @filter.command("schedule_on", desc="启用时段切换模型")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def cmd_on(self, event: AstrMessageEvent):
        self.cfg["enable"] = True
        self._save()
        yield event.plain_result("已启用时段切换模型。")

    @filter.command("schedule_off", desc="停用时段切换模型")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def cmd_off(self, event: AstrMessageEvent):
        self.cfg["enable"] = False
        self._save()
        yield event.plain_result("已停用时段切换模型。")

    # ---------- 帮助文本 ----------

    def _build_help(self) -> str:
        lines = [
            "【时段切换模型 /schedule】",
            "当前启用：" + ("是" if self.cfg.get("enable", True) else "否"),
            "时区：" + (self.cfg.get("timezone") or "服务器本地时间"),
        ]
        scheds = self.cfg.get("schedules", [])
        if scheds:
            lines.append("\n配置的时段：")
            for i, s in enumerate(scheds):
                lines.append(
                    f"[{i}] {s.get('name')}  {s.get('start')}-{s.get('end')} → "
                    f"{s.get('provider') or '(未设置)'}"
                )
        else:
            lines.append("\n暂未配置时段。")
        d = self.cfg.get("default_model") or self.cfg.get("default") or {}
        lines.append(
            f"\n默认：{d.get('provider') or '(未设置)'}"
        )
        lines.append(
            "\n常用指令：\n"
            "/schedule_now\n"
            "/schedule_add <开始> <结束> <provider> [名字]\n"
            "/schedule_set <序号> <开始> <结束> <provider>\n"
            "/schedule_del <序号>\n"
            "/schedule_default <provider>\n"
            "/schedule_reload\n"
            "/schedule_on | /schedule_off"
        )
        if self._webui_cfg is not None:
            lines.append("\n💡 也可在 WebUI「插件管理」里可视化配置时段与 Provider。")
        return "\n".join(lines)
