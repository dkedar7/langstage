"""Browser automation state and streaming via Playwright + CDP screencast.

Provides BrowserState (persistent per-session, lazy-init) and
BrowserStreamManager (routes CDP frames to WebSocket connections).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Callable, Awaitable

logger = logging.getLogger(__name__)

try:
    from playwright.async_api import async_playwright, Browser, BrowserContext, Page
    _HAS_PLAYWRIGHT = True
except ImportError:
    _HAS_PLAYWRIGHT = False


@dataclass
class BrowserFrame:
    """A single screencast frame from CDP."""

    data: str  # base64-encoded JPEG
    session_id: int  # CDP frame session ID for ack
    width: int
    height: int
    timestamp: float


class BrowserState:
    """Persistent browser state for a session.

    Follows the NotebookState pattern: lazy initialization on first tool call,
    global instance + per-session instances.
    """

    def __init__(self, ws_session_id: str | None = None) -> None:
        self._ws_session_id = ws_session_id
        self._playwright: Any = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._cdp_session: Any = None
        self._is_running = False
        self._current_url = ""
        self._frame_callback: Callable[[BrowserFrame], Awaitable[None]] | None = None
        self._screencast_active = False

    @property
    def is_running(self) -> bool:
        return self._is_running

    @property
    def current_url(self) -> str:
        return self._current_url

    async def ensure_browser(self) -> Page:
        """Lazy-initialize browser on first use."""
        if not _HAS_PLAYWRIGHT:
            raise RuntimeError(
                "Playwright is not installed. "
                "Install with: pip install 'cowork-dash[browser]' && playwright install chromium"
            )

        if self._page is not None:
            return self._page

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-gpu"],
        )
        self._context = await self._browser.new_context(
            viewport={"width": 1280, "height": 720},
        )
        self._page = await self._context.new_page()
        self._is_running = True

        await self._start_screencast()
        return self._page

    async def _start_screencast(self) -> None:
        """Start CDP screencast for live frame streaming."""
        if not self._page or self._screencast_active:
            return

        self._cdp_session = await self._page.context.new_cdp_session(self._page)
        self._cdp_session.on("Page.screencastFrame", self._on_frame)

        await self._cdp_session.send("Page.startScreencast", {
            "format": "jpeg",
            "quality": 60,
            "maxWidth": 1280,
            "maxHeight": 720,
            "everyNthFrame": 1,
        })
        self._screencast_active = True

    async def _on_frame(self, params: dict) -> None:
        """Handle incoming CDP screencast frame."""
        await self._cdp_session.send("Page.screencastFrameAck", {
            "sessionId": params["sessionId"],
        })

        if self._frame_callback:
            metadata = params.get("metadata", {})
            try:
                await self._frame_callback(BrowserFrame(
                    data=params["data"],
                    session_id=params["sessionId"],
                    width=int(metadata.get("deviceWidth", 1280)),
                    height=int(metadata.get("deviceHeight", 720)),
                    timestamp=metadata.get("timestamp", 0),
                ))
            except Exception:
                logger.debug("Frame callback error", exc_info=True)

    def set_frame_callback(
        self, callback: Callable[[BrowserFrame], Awaitable[None]] | None
    ) -> None:
        """Register async callback for frame forwarding."""
        self._frame_callback = callback

    async def navigate(self, url: str) -> dict[str, Any]:
        """Navigate to a URL."""
        page = await self.ensure_browser()
        try:
            response = await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            self._current_url = page.url
            return {
                "status": "success",
                "url": page.url,
                "title": await page.title(),
                "status_code": response.status if response else None,
            }
        except Exception as e:
            self._current_url = page.url
            return {"status": "error", "error": str(e), "url": page.url}

    async def click(self, selector: str) -> dict[str, Any]:
        """Click an element."""
        page = await self.ensure_browser()
        try:
            await page.click(selector, timeout=10_000)
            self._current_url = page.url
            return {"status": "success", "clicked": selector, "url": page.url}
        except Exception as e:
            return {"status": "error", "error": str(e), "selector": selector}

    async def type_text(self, selector: str, text: str) -> dict[str, Any]:
        """Type text into an element."""
        page = await self.ensure_browser()
        try:
            await page.fill(selector, text, timeout=10_000)
            return {"status": "success", "typed": text, "into": selector}
        except Exception as e:
            return {"status": "error", "error": str(e), "selector": selector}

    async def screenshot(self) -> bytes:
        """Take a full screenshot (PNG) for agent vision."""
        page = await self.ensure_browser()
        return await page.screenshot(type="png", full_page=False)

    async def get_text(self, selector: str | None = None) -> str:
        """Get text content from the page or a specific element."""
        page = await self.ensure_browser()
        try:
            if selector:
                el = await page.query_selector(selector)
                if el:
                    return await el.text_content() or ""
                return f"Element not found: {selector}"
            return await page.inner_text("body")
        except Exception as e:
            return f"Error: {e}"

    async def scroll(self, direction: str = "down", amount: int = 500) -> dict[str, Any]:
        """Scroll the page."""
        page = await self.ensure_browser()
        delta = amount if direction == "down" else -amount
        await page.evaluate(f"window.scrollBy(0, {delta})")
        return {"status": "success", "direction": direction, "amount": amount}

    async def close(self) -> dict[str, Any]:
        """Close the browser and clean up."""
        if self._screencast_active and self._cdp_session:
            try:
                await self._cdp_session.send("Page.stopScreencast")
            except Exception:
                pass
            try:
                await self._cdp_session.detach()
            except Exception:
                pass
            self._screencast_active = False
            self._cdp_session = None

        if self._browser:
            await self._browser.close()
            self._browser = None
            self._context = None
            self._page = None

        if self._playwright:
            await self._playwright.stop()
            self._playwright = None

        self._is_running = False
        self._current_url = ""
        return {"status": "closed"}

    async def reset(self) -> None:
        """Full cleanup for session reset."""
        await self.close()


# ---------------------------------------------------------------------------
# BrowserStreamManager — routes frames to WebSocket connections
# ---------------------------------------------------------------------------

class BrowserStreamManager:
    """Routes browser frames from BrowserState instances to WebSocket connections."""

    _instance: BrowserStreamManager | None = None

    def __init__(self) -> None:
        self._connections: dict[str, Any] = {}  # session_id → WebSocket

    @classmethod
    def get_instance(cls) -> BrowserStreamManager:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def register(self, session_id: str, websocket: Any) -> None:
        self._connections[session_id] = websocket

    def unregister(self, session_id: str) -> None:
        self._connections.pop(session_id, None)

    async def send_frame(self, session_id: str, frame: BrowserFrame) -> None:
        ws = self._connections.get(session_id)
        if ws:
            try:
                await ws.send_json({
                    "type": "browser_frame",
                    "data": frame.data,
                    "width": frame.width,
                    "height": frame.height,
                })
            except Exception:
                pass

    async def send_status(self, session_id: str, status: str) -> None:
        ws = self._connections.get(session_id)
        if ws:
            try:
                await ws.send_json({
                    "type": "browser_status",
                    "status": status,
                })
            except Exception:
                pass

    async def send_url(self, session_id: str, url: str) -> None:
        ws = self._connections.get(session_id)
        if ws:
            try:
                await ws.send_json({
                    "type": "browser_url",
                    "url": url,
                })
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Module-level state (follows NotebookState pattern)
# ---------------------------------------------------------------------------

_browser_state: BrowserState | None = None
_session_browser_states: dict[str, BrowserState] = {}


def get_browser_state(session_id: str | None = None) -> BrowserState:
    """Get (or create) the BrowserState for a session."""
    global _browser_state

    if not session_id:
        if _browser_state is None:
            _browser_state = BrowserState()
        return _browser_state

    if session_id not in _session_browser_states:
        _session_browser_states[session_id] = BrowserState(ws_session_id=session_id)
    return _session_browser_states[session_id]


async def cleanup_browser_state(session_id: str) -> None:
    """Close and remove browser state for a session."""
    state = _session_browser_states.pop(session_id, None)
    if state:
        await state.close()
