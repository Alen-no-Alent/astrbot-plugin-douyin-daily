"""抖音每日分享：在 DeepSeek 峰谷（低价）时段自动刷一轮抖音并推送。

底层复用 NEWJO123/dsh-douyin-scroll 的 MCP server（stdio JSON-RPC）。
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timedelta
from typing import Any

import astrbot.api.message_components as Comp
from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.star import Context, Star, register

try:
    from croniter import croniter
except Exception:  # pragma: no cover
    croniter = None


def _fmt_num(n: Any) -> str:
    try:
        n = int(n)
    except Exception:
        return str(n)
    if n >= 10000:
        return f"{n / 10000:.1f}万"
    return str(n)


class DouyinMcpClient:
    """极简 MCP stdio 客户端：只为调用单个 tool 而存在。"""

    def __init__(self, node_path: str, server_js: str, home: str):
        self.node_path = node_path
        self.server_js = server_js
        self.home = home

    async def call(self, tool: str, arguments: dict[str, Any], timeout: float = 300.0) -> dict[str, Any]:
        requests = [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "astrbot-douyin-daily", "version": "0.1.0"},
                },
            },
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": tool, "arguments": arguments},
            },
        ]
        payload = ("\n".join(json.dumps(r, ensure_ascii=False) for r in requests) + "\n").encode("utf-8")

        env = dict(os.environ)
        env["DOUYIN_HOME"] = self.home
        env["PYTHONIOENCODING"] = "utf-8"

        proc = await asyncio.create_subprocess_exec(
            self.node_path,
            self.server_js,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(payload), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            raise RuntimeError(f"调用 {tool} 超时（>{timeout}s）")

        text = (out or b"").decode("utf-8", "ignore")
        for line in reversed([ln for ln in text.splitlines() if ln.strip()]):
            try:
                msg = json.loads(line)
            except Exception:
                continue
            if msg.get("id") != 2:
                continue
            if "error" in msg:
                raise RuntimeError(f"MCP 错误: {msg['error']}")
            content = (msg.get("result") or {}).get("content") or []
            if not content:
                raise RuntimeError("MCP 返回为空")
            raw = content[0].get("text", "")
            try:
                return json.loads(raw)
            except Exception:
                return {"ok": True, "raw": raw}

        stderr = (err or b"").decode("utf-8", "ignore")[-500:]
        raise RuntimeError(f"MCP 无有效响应: {text[-300:]} / {stderr}")


@register(
    "astrbot_plugin_douyin_daily",
    "汤圆定制",
    "在 DeepSeek 峰谷时段自动刷抖音并分享",
    "v0.1.0",
)
class DouyinDailyPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self._task: asyncio.Task | None = None
        self._stopping = False

    # ------------------------------------------------------------------ #
    # 配置读取
    # ------------------------------------------------------------------ #
    def _c(self, key: str, default: Any = None) -> Any:
        try:
            val = self.config.get(key, default)
        except Exception:
            val = default
        return default if val is None else val

    @property
    def home_dir(self) -> str:
        return os.path.join(str(self._c("plugin_dir")), "data")

    def _client(self) -> DouyinMcpClient:
        return DouyinMcpClient(
            node_path=str(self._c("node_path")),
            server_js=os.path.join(str(self._c("plugin_dir")), "tools", "mcp-server.mjs"),
            home=self.home_dir,
        )

    # ------------------------------------------------------------------ #
    # 生命周期
    # ------------------------------------------------------------------ #
    async def initialize(self):
        if not self._c("enabled", True):
            logger.info("[douyin_daily] 已在配置中关闭")
            return
        if croniter is None:
            logger.warning("[douyin_daily] 未安装 croniter，定时不可用（手动指令仍可用）")
            return
        self._task = asyncio.create_task(self._loop())
        logger.info(f"[douyin_daily] 定时分享已启动，cron={self._c('cron')}")

    async def terminate(self):
        self._stopping = True
        if self._task:
            self._task.cancel()

    async def _loop(self):
        while not self._stopping:
            try:
                expr = str(self._c("cron", "0 3 * * *")).strip() or "0 3 * * *"
                now = datetime.now()
                nxt = croniter(expr, now).get_next(datetime)
                delay = max((nxt - now).total_seconds(), 1)
                logger.info(f"[douyin_daily] 下次刷抖音时间：{nxt:%Y-%m-%d %H:%M}")
                await asyncio.sleep(delay)
                if self._stopping:
                    break
                await self.run_once()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[douyin_daily] 定时循环异常: {type(e).__name__}: {e}")
                await asyncio.sleep(300)

    # ------------------------------------------------------------------ #
    # 核心
    # ------------------------------------------------------------------ #
    async def _fetch_candidates(self) -> list[dict]:
        count = int(self._c("candidate_count", 10) or 10)
        data = await self._client().call("douyin_forward", {"count": count}, timeout=300)
        if not data.get("ok"):
            raise RuntimeError(f"取候选失败: {data}")
        return list(data.get("list") or [])

    @staticmethod
    def _rank(items: list[dict], pick: int) -> list[dict]:
        def score(it: dict) -> float:
            try:
                digg = int(it.get("digg") or 0)
                cmt = int(it.get("comment") or 0)
                share = int(it.get("share") or 0)
                age = float(it.get("age_h") or 48)
                dur = float(it.get("duration_s") or 60)
            except Exception:
                return 0.0
            base = digg + cmt * 6 + share * 3
            fresh = 1.0 + max(0.0, (72 - age)) / 72.0
            length = 1.0 if 20 <= dur <= 600 else 0.7
            return base * fresh * length

        return sorted(items, key=score, reverse=True)[: max(1, pick)]

    async def _llm_intro(self, picked: list[dict]) -> str:
        try:
            provider = None
            pid = str(self._c("provider_id") or "").strip()
            if pid:
                provider = self.context.get_provider_by_id(pid)
            if provider is None:
                provider = self.context.get_using_provider()
            if provider is None:
                return ""
            lines = "\n".join(
                f"- {it.get('author')}：{it.get('desc')}（{_fmt_num(it.get('digg'))}赞）" for it in picked
            )
            prompt = (
                "你是「汤圆」，一个说话软萌、爱撒娇的女孩子，正在给爸爸分享今天刷到的抖音。\n"
                f"这些是今天挑出来的视频：\n{lines}\n\n"
                "请用两三句话开场，口语化、简短、带点小兴奋，说清楚你挑了哪几条、为什么想让他看。"
                "不要用列表，不要复述链接，不要称呼“用户”。"
            )
            resp = await provider.text_chat(prompt=prompt, contexts=[])
            text = (getattr(resp, "completion_text", "") or "").strip()
            return text[:400]
        except Exception as e:
            logger.warning(f"[douyin_daily] 生成推荐语失败: {type(e).__name__}: {e}")
            return ""

    async def run_once(self) -> str:
        """跑一轮并推送，返回摘要文本（供手动指令使用）。"""
        picked = self._rank(await self._fetch_candidates(), int(self._c("pick_count", 3) or 3))
        if not picked:
            return "今天没刷到合适的视频。"

        intro = await self._llm_intro(picked)

        lines: list[str] = []
        if intro:
            lines.append(intro)
            lines.append("")
        lines.append(f"🎬 今日抖音精选（{datetime.now():%m-%d}）")
        for i, it in enumerate(picked, 1):
            desc = str(it.get("desc") or "").strip().replace("\n", " ")
            if len(desc) > 60:
                desc = desc[:60] + "…"
            lines.append(
                f"{i}. {desc}\n"
                f"   @{it.get('author')} ｜ {_fmt_num(it.get('digg'))}赞 ｜ "
                f"{round(float(it.get('duration_s') or 0))}秒\n"
                f"   {it.get('web_url')}"
            )
        text = "\n".join(lines)

        targets = self._c("target_umos") or []
        if isinstance(targets, str):
            targets = [targets]
        for umo in targets:
            umo = str(umo).strip()
            if not umo:
                continue
            try:
                mc = MessageChain()
                mc.chain = [Comp.Plain(text)]
                await self.context.send_message(umo, mc)
            except Exception as e:
                logger.error(f"[douyin_daily] 推送到 {umo} 失败: {type(e).__name__}: {e}")
        return text

    # ------------------------------------------------------------------ #
    # 手动指令
    # ------------------------------------------------------------------ #
    @filter.command("刷抖音")
    async def cmd_douyin(self, event: AstrMessageEvent):
        """手动跑一轮抖音分享。"""
        yield event.plain_result("好，我去刷一会儿，等我一下下～")
        try:
            text = await self.run_once()
            yield event.plain_result(text if len(text) < 1500 else text[:1500] + "…")
        except Exception as e:
            logger.error(f"[douyin_daily] 手动运行失败: {type(e).__name__}: {e}")
            yield event.plain_result(f"刷不动了：{type(e).__name__}: {e}")
