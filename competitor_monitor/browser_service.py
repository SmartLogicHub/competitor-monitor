from __future__ import annotations

from enum import Enum
import json
import random
import sys
import time
from pathlib import Path
from typing import Any

from credential_service import AccountCredentials


DEFAULT_VIEWPORT_WIDTH = 1920
DEFAULT_VIEWPORT_HEIGHT = 1080
DEFAULT_LOCALE = "zh-CN"
DEFAULT_TIMEZONE_ID = "Asia/Shanghai"
DEFAULT_LONGITUDE = 116.4
DEFAULT_LATITUDE = 39.9
DEFAULT_CHROME_MAJOR_VERSION = 149
DEFAULT_OPERATION_MIN_DELAY_SECONDS = 2
DEFAULT_OPERATION_MAX_DELAY_SECONDS = 8
DEFAULT_BROWSER_CHANNEL = "chrome"
STANDARD_LAUNCH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-sandbox",
    "--disable-dev-shm-usage",
]
VERIFY_KEYWORDS = ["验证码", "滑块", "安全验证", "人机验证", "登录", "login.taobao"]
TAOBAO_LOGIN_CHECK_URL = "https://www.taobao.com/"
TAOBAO_LOGIN_URL = "https://login.taobao.com/member/login.jhtml"
LOGIN_URL_MARKERS = ("login.taobao.com", "login.tmall.com")
MERCHANT_WORKBENCH_URL_MARKERS = (
    "qianniu.taobao.com",
    "qn.taobao.com",
    "myseller.taobao.com",
    "seller.taobao.com",
    "sell.taobao.com",
    "work.taobao.com",
)
LOGIN_TEXT_MARKERS = ("亲，请登录", "请登录后", "账号登录", "密码登录")
MANUAL_ACTION_URL_MARKERS = ("passport.taobao.com", "verify", "authcenter")
MANUAL_ACTION_MARKERS = (
    "滑块",
    "安全验证",
    "人机验证",
    "身份验证",
    "手机验证",
    "短信验证",
    "请输入验证码",
    "请输入校验码",
    "验证码",
    "校验码",
    "baxia",
    "punish",
)
TAOBAO_LOGIN_ENTRY_SELECTORS = (
    'xpath=//*[@id="J_SiteNavLogin"]/div[1]/div[1]/a[1]',
    "xpath=/html/body/div[2]/div/ul[1]/li[2]/div[1]/div[1]/a[1]",
    "text=亲，请登录",
)
TAOBAO_USERNAME_SELECTORS = (
    "input[name='fm-login-id']",
    "#fm-login-id",
    "input[placeholder*='账号名']",
    "input[aria-label*='账号名']",
    "input[name='TPL_username']",
    "input[type='text']",
)
TAOBAO_PASSWORD_SELECTORS = (
    "input[name='fm-login-password']",
    "#fm-login-password",
    "input[placeholder*='登录密码']",
    "input[aria-label*='登录密码']",
    "input[name='TPL_password']",
    "input[type='password']",
)
TAOBAO_SUBMIT_SELECTORS = ("button.fm-submit", "button[type='submit']", "#J_SubmitStatic", ".fm-button")
TAOBAO_AGREEMENT_SELECTORS = ("#fm-agreement-checkbox", "input[name='fm-agreement-checkbox']")
TAOBAO_LOGIN_OPTION_TEXTS = ("记住我的登录状态", "我已阅读并同意")


class PageAuthState(str, Enum):
    AUTHENTICATED = "authenticated"
    LOGIN_REQUIRED = "login_required"
    MANUAL_ACTION_REQUIRED = "manual_action_required"


def detect_page_auth_state(page) -> PageAuthState:
    url = str(getattr(page, "url", "") or "")
    title = ""
    text = ""
    try:
        title = str(page.title() or "")
    except Exception:
        pass
    try:
        text = str(page.locator("body").inner_text(timeout=3000) or "")
    except Exception:
        pass

    combined = f"{url}\n{title}\n{text}"
    combined_lower = combined.lower()
    if any(marker in combined_lower for marker in MANUAL_ACTION_URL_MARKERS):
        return PageAuthState.MANUAL_ACTION_REQUIRED
    if any(marker in combined for marker in MANUAL_ACTION_MARKERS) or any(marker in combined_lower for marker in ("baxia", "punish")):
        return PageAuthState.MANUAL_ACTION_REQUIRED
    if any(marker in combined_lower for marker in LOGIN_URL_MARKERS):
        return PageAuthState.LOGIN_REQUIRED
    if "亲，请登录" in combined or "请登录后" in combined:
        return PageAuthState.LOGIN_REQUIRED
    if title.strip() == "登录":
        return PageAuthState.LOGIN_REQUIRED
    if "账号" in combined and "密码" in combined and "登录" in combined:
        return PageAuthState.LOGIN_REQUIRED
    return PageAuthState.AUTHENTICATED


def _is_merchant_workbench_url(url: str) -> bool:
    current_url = str(url or "").lower()
    return any(marker in current_url for marker in MERCHANT_WORKBENCH_URL_MARKERS)


def build_browser_launch_args(extra_args: list[str] | None = None) -> list[str]:
    """Return the standard Chromium flags used by all browser launches."""
    args = list(STANDARD_LAUNCH_ARGS)
    for arg in extra_args or []:
        if arg not in args:
            args.append(arg)
    return args


def build_browser_launch_options(config: dict[str, Any] | None = None, use_bundled_browser: bool = False) -> dict[str, Any]:
    """Build launch options, preferring the local Chrome channel by default."""
    config = config or {}
    options: dict[str, Any] = {
        "args": build_browser_launch_args(config.get("browser_launch_args")),
    }
    if use_bundled_browser:
        return options

    executable_path = config.get("browser_executable_path")
    browser_channel = config.get("browser_channel", DEFAULT_BROWSER_CHANNEL)
    if executable_path:
        options["executable_path"] = str(executable_path)
    elif browser_channel:
        options["channel"] = browser_channel
    return options


def build_windows_chrome_user_agent(chrome_major_version: int | str = DEFAULT_CHROME_MAJOR_VERSION) -> str:
    return (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        f"Chrome/{chrome_major_version}.0.0.0 Safari/537.36"
    )


def build_context_options(config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build stable BrowserContext options with safe defaults."""
    config = config or {}
    viewport_width = int(config.get("viewport_width", DEFAULT_VIEWPORT_WIDTH))
    viewport_height = int(config.get("viewport_height", DEFAULT_VIEWPORT_HEIGHT))
    longitude = float(config.get("longitude", DEFAULT_LONGITUDE))
    latitude = float(config.get("latitude", DEFAULT_LATITUDE))
    chrome_major_version = config.get("chrome_major_version", DEFAULT_CHROME_MAJOR_VERSION)
    user_agent = config.get("user_agent") or build_windows_chrome_user_agent(chrome_major_version)
    return {
        "viewport": {"width": viewport_width, "height": viewport_height},
        "locale": config.get("locale", DEFAULT_LOCALE),
        "timezone_id": config.get("timezone_id", DEFAULT_TIMEZONE_ID),
        "geolocation": {"longitude": longitude, "latitude": latitude},
        "permissions": ["geolocation"],
        "user_agent": user_agent,
    }


def random_delay(min_seconds: float = DEFAULT_OPERATION_MIN_DELAY_SECONDS, max_seconds: float = DEFAULT_OPERATION_MAX_DELAY_SECONDS) -> float:
    """Sleep for a randomized interval and return the actual duration."""
    if max_seconds < min_seconds:
        min_seconds, max_seconds = max_seconds, min_seconds
    delay = random.uniform(min_seconds, max_seconds)
    time.sleep(delay)
    return delay


class BrowserService:
    def __init__(
        self,
        headless: bool,
        timeout_ms: int,
        user_data_dir: Path | str = "browser_profile",
        context_config: dict[str, Any] | None = None,
        taobao_credentials: AccountCredentials | None = None,
        stop_event: Any | None = None,
    ):
        self.headless = headless
        self.timeout_ms = timeout_ms
        self.user_data_dir = Path(user_data_dir)
        self.context_config = context_config or {}
        self.stop_event = stop_event
        self.storage_state_path = Path(
            self.context_config.get("browser_storage_state_path") or self.user_data_dir / "storage_state.json"
        )
        self.taobao_credentials = taobao_credentials
        self.operation_min_delay_seconds = float(
            self.context_config.get("operation_min_delay_seconds", DEFAULT_OPERATION_MIN_DELAY_SECONDS)
        )
        self.operation_max_delay_seconds = float(
            self.context_config.get("operation_max_delay_seconds", DEFAULT_OPERATION_MAX_DELAY_SECONDS)
        )
        self._taobao_auto_login_attempts = 0
        self._playwright = None
        self._context = None

    def __enter__(self):
        try:
            from rebrowser_playwright.sync_api import sync_playwright
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "Missing rebrowser-playwright. Install with: pip install rebrowser-playwright"
            ) from exc
        self.user_data_dir.mkdir(parents=True, exist_ok=True)
        self._playwright = sync_playwright().start()
        self._context = self._launch_persistent_context()
        self._restore_storage_state(self._context)
        return self

    def __exit__(self, exc_type, exc, tb):
        if self._context:
            self._context.close()
        if self._playwright:
            self._playwright.stop()

    def open_page(self, url: str):
        page = self._context.new_page()
        self._attach_manual_action_settings(page)
        page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
        self.wait_after_operation()
        self._recover_page_auth(page)
        return page

    def ensure_taobao_login(self) -> PageAuthState:
        check_url = self.context_config.get("taobao_login_check_url", TAOBAO_LOGIN_CHECK_URL)
        page = self._context.new_page()
        self._attach_manual_action_settings(page)
        try:
            if self._stop_requested():
                return detect_page_auth_state(page)
            try:
                page.goto(check_url, wait_until="domcontentloaded", timeout=self.timeout_ms)
            except Exception:
                if not self.taobao_credentials:
                    raise
                page.goto(
                    self.context_config.get("taobao_login_url", TAOBAO_LOGIN_URL),
                    wait_until="domcontentloaded",
                    timeout=self.timeout_ms,
                )
            self.wait_after_operation()
            if self._stop_requested():
                return detect_page_auth_state(page)
            return self._recover_page_auth(page)
        finally:
            page.close()

    def login_taobao(self, page, credentials: AccountCredentials | None = None) -> PageAuthState:
        self._attach_manual_action_settings(page)
        if self._stop_requested():
            return detect_page_auth_state(page)
        credentials = credentials or self.taobao_credentials
        if not credentials:
            return self._pause_for_manual_action(page, "页面需要登录淘宝/天猫，但未配置账号密码。请在浏览器中手动登录，完成后程序会自动继续...")
        if self._taobao_auto_login_attempts >= self._taobao_auto_login_max_attempts():
            return self._pause_for_manual_action(page, "淘宝登录或验证尚未确认完成。请在浏览器中完成验证，程序会等待登录状态稳定后继续...")

        self._open_taobao_login_page_if_needed(page)
        if self._stop_requested():
            return detect_page_auth_state(page)
        self._fill_first(page, TAOBAO_USERNAME_SELECTORS, credentials.username)
        self.wait_after_operation()
        if self._stop_requested():
            return detect_page_auth_state(page)
        self._fill_first(page, TAOBAO_PASSWORD_SELECTORS, credentials.password)
        self.wait_after_operation()
        if self._stop_requested():
            return detect_page_auth_state(page)
        self._click_taobao_login_options(page)
        self.wait_after_operation()
        if self._stop_requested():
            return detect_page_auth_state(page)
        self._click_first(page, TAOBAO_SUBMIT_SELECTORS)
        self._taobao_auto_login_attempts += 1
        self.wait_after_operation()
        try:
            page.wait_for_load_state("domcontentloaded", timeout=self.timeout_ms)
        except Exception:
            pass
        state = detect_page_auth_state(page)
        if state == PageAuthState.MANUAL_ACTION_REQUIRED:
            state = self._pause_for_manual_action(page, "页面需要人工验证。请在浏览器中处理完成，程序会自动继续...")
            if state == PageAuthState.LOGIN_REQUIRED and self._taobao_auto_login_attempts < self._taobao_auto_login_max_attempts():
                return self.login_taobao(page, credentials)
        elif state == PageAuthState.LOGIN_REQUIRED:
            if self._taobao_auto_login_attempts < self._taobao_auto_login_max_attempts():
                return self.login_taobao(page, credentials)
            state = self._pause_for_manual_action(page, "自动登录未确认成功。请在浏览器中检查并完成登录，程序会自动继续...")
        state = self._confirm_taobao_auth_after_merchant_redirect(page, state)
        return state

    def click(self, page, target, **kwargs):
        if isinstance(target, str):
            result = page.click(target, **kwargs)
        else:
            result = target.click(**kwargs)
        self.wait_after_operation()
        return result

    def wait_after_operation(self) -> float:
        if self._stop_requested():
            return 0.0
        min_seconds = self.operation_min_delay_seconds
        max_seconds = self.operation_max_delay_seconds
        if max_seconds < min_seconds:
            min_seconds, max_seconds = max_seconds, min_seconds
        delay = random.uniform(min_seconds, max_seconds)
        remaining = delay
        poll_seconds = max(0.05, float(self.context_config.get("operation_stop_poll_seconds", 0.25)))
        while remaining > 0:
            if self._stop_requested():
                break
            sleep_seconds = min(poll_seconds, remaining)
            time.sleep(sleep_seconds)
            remaining -= sleep_seconds
        return delay

    def _recover_page_auth(self, page) -> PageAuthState:
        self._attach_manual_action_settings(page)
        state = self._wait_for_auth_state_to_settle(page)
        if self._stop_requested():
            return state
        if state == PageAuthState.LOGIN_REQUIRED:
            state = self.login_taobao(page, self.taobao_credentials)
            state = self._wait_for_auth_state_to_settle(page)
        if self._stop_requested():
            return state
        if state == PageAuthState.MANUAL_ACTION_REQUIRED:
            state = self._pause_for_manual_action(page, "页面需要人工登录或验证。请在浏览器中处理完成，程序会自动继续...")
            if state == PageAuthState.LOGIN_REQUIRED and self.taobao_credentials and self._taobao_auto_login_attempts < self._taobao_auto_login_max_attempts():
                state = self.login_taobao(page, self.taobao_credentials)
            state = self._wait_for_auth_state_to_settle(page)
        state = self._confirm_taobao_auth_after_merchant_redirect(page, state)
        self._persist_auth_state_if_authenticated(page)
        return state

    def _taobao_auto_login_max_attempts(self) -> int:
        return max(1, int(self.context_config.get("taobao_auto_login_max_attempts", 2)))

    def _persist_auth_state_if_authenticated(self, page) -> None:
        if detect_page_auth_state(page) != PageAuthState.AUTHENTICATED or not self._context:
            return
        try:
            self.storage_state_path.parent.mkdir(parents=True, exist_ok=True)
            self._context.storage_state(path=str(self.storage_state_path))
        except Exception:
            pass

    def _restore_storage_state(self, context) -> None:
        try:
            if not self.storage_state_path.exists():
                return
            state = json.loads(self.storage_state_path.read_text(encoding="utf-8"))
            cookies = state.get("cookies") or []
            if cookies:
                context.add_cookies(cookies)
        except Exception:
            pass

    def _confirm_taobao_auth_after_merchant_redirect(self, page, state: PageAuthState) -> PageAuthState:
        if state != PageAuthState.AUTHENTICATED:
            return state
        if not _is_merchant_workbench_url(getattr(page, "url", "")):
            return state
        check_url = self.context_config.get("taobao_login_check_url", TAOBAO_LOGIN_CHECK_URL)
        try:
            page.goto(check_url, wait_until="domcontentloaded", timeout=self.timeout_ms)
            self.wait_after_operation()
            return self._wait_for_auth_state_to_settle(page)
        except Exception:
            return state

    def _wait_for_auth_state_to_settle(self, page) -> PageAuthState:
        attempts = max(1, int(self.context_config.get("taobao_login_state_check_attempts", 3)))
        wait_seconds = max(0.0, float(self.context_config.get("taobao_login_state_check_seconds", 2)))
        state = detect_page_auth_state(page)
        for attempt in range(1, attempts):
            if self._stop_requested():
                return state
            if state in {PageAuthState.AUTHENTICATED, PageAuthState.MANUAL_ACTION_REQUIRED}:
                return state
            try:
                page.wait_for_load_state("domcontentloaded", timeout=2000)
            except Exception:
                pass
            if wait_seconds:
                time.sleep(wait_seconds)
            else:
                time.sleep(0)
            state = detect_page_auth_state(page)
        return state

    @staticmethod
    def _fill_first(page, selectors: tuple[str, ...], value: str) -> None:
        last_error = None
        for selector in selectors:
            try:
                page.locator(selector).first.fill(value, timeout=5000)
                return
            except Exception as exc:
                last_error = exc
        raise RuntimeError(f"未找到可填写的登录输入框：{selectors}") from last_error

    @staticmethod
    def _click_first(page, selectors: tuple[str, ...]) -> None:
        last_error = None
        for selector in selectors:
            try:
                page.locator(selector).first.click(timeout=5000)
                return
            except Exception as exc:
                last_error = exc
        raise RuntimeError(f"未找到可点击的登录按钮：{selectors}") from last_error

    def _click_taobao_login_options(self, page) -> None:
        self._click_visible_unchecked_selectors(page, TAOBAO_AGREEMENT_SELECTORS)
        for text in TAOBAO_LOGIN_OPTION_TEXTS:
            try:
                page.get_by_text(text, exact=False).first.click(timeout=2000)
                self.wait_after_operation()
            except Exception:
                pass
        self._click_visible_unchecked_checkboxes(page)

    def _click_visible_unchecked_selectors(self, page, selectors: tuple[str, ...]) -> None:
        for selector in selectors:
            try:
                target = page.locator(selector).first
                checked = False
                try:
                    checked = target.is_checked(timeout=500)
                except Exception:
                    checked = False
                if not checked:
                    target.click(timeout=1000)
                    self.wait_after_operation()
                return
            except Exception:
                continue

    def _open_taobao_login_page_if_needed(self, page) -> None:
        current_url = str(getattr(page, "url", "") or "").lower()
        if any(marker in current_url for marker in LOGIN_URL_MARKERS):
            return
        if self._click_taobao_login_entry(page):
            current_url = str(getattr(page, "url", "") or "").lower()
            if any(marker in current_url for marker in LOGIN_URL_MARKERS):
                return
        login_url = self.context_config.get("taobao_login_url", TAOBAO_LOGIN_URL)
        page.goto(login_url, wait_until="domcontentloaded", timeout=self.timeout_ms)
        self.wait_after_operation()

    def _click_taobao_login_entry(self, page) -> bool:
        for selector in TAOBAO_LOGIN_ENTRY_SELECTORS:
            try:
                page.locator(selector).first.click(timeout=3000)
                self.wait_after_operation()
                return True
            except Exception:
                continue
        return False

    @staticmethod
    def _click_visible_unchecked_checkboxes(page) -> None:
        try:
            checkboxes = page.locator("input[type='checkbox']")
            count = checkboxes.count()
            for index in range(count):
                checkbox = checkboxes.nth(index)
                if checkbox.is_visible(timeout=500) and not checkbox.is_checked(timeout=500):
                    checkbox.click(timeout=1000)
        except Exception:
            pass

    def _pause_for_manual_action(self, page, message: str) -> PageAuthState:
        self._attach_manual_action_settings(page)
        print(message, flush=True)
        return BrowserService._wait_for_manual_action_resolution(
            page,
            message,
            allow_login_required=bool(self.taobao_credentials),
        )

    def _attach_manual_action_settings(self, page) -> None:
        try:
            setattr(
                page,
                "_manual_action_timeout_seconds",
                int(self.context_config.get("manual_action_timeout_seconds", 180)),
            )
            setattr(
                page,
                "_manual_action_poll_seconds",
                float(self.context_config.get("manual_action_poll_seconds", 2)),
            )
            setattr(page, "_stop_event", self.stop_event)
        except Exception:
            pass

    @staticmethod
    def _wait_for_manual_action_resolution(page, message: str, allow_login_required: bool = False) -> PageAuthState:
        timeout_seconds = int(getattr(page, "_manual_action_timeout_seconds", 180) or 180)
        poll_seconds = float(getattr(page, "_manual_action_poll_seconds", 2) or 2)
        deadline = time.time() + timeout_seconds
        stop_event = getattr(page, "_stop_event", None)

        def stop_requested() -> bool:
            try:
                return bool(stop_event is not None and stop_event.is_set())
            except Exception:
                return False

        state = detect_page_auth_state(page)
        if stop_requested():
            return state
        seen_manual_action = state == PageAuthState.MANUAL_ACTION_REQUIRED
        while time.time() < deadline:
            if stop_requested():
                return detect_page_auth_state(page)
            try:
                page.wait_for_load_state("domcontentloaded", timeout=1000)
            except Exception:
                pass
            state = detect_page_auth_state(page)
            if stop_requested():
                return state
            if state == PageAuthState.AUTHENTICATED:
                return state
            if state == PageAuthState.MANUAL_ACTION_REQUIRED:
                seen_manual_action = True
            if allow_login_required and seen_manual_action and state == PageAuthState.LOGIN_REQUIRED:
                return state
            time.sleep(poll_seconds)
        raise RuntimeError(f"{message} 等待人工处理超时，请完成验证后重新运行")

    def _stop_requested(self) -> bool:
        try:
            return bool(self.stop_event is not None and self.stop_event.is_set())
        except Exception:
            return False

    def _launch_persistent_context(self):
        launch_options = {
            "headless": self.headless,
            "timeout": self.timeout_ms,
            **build_browser_launch_options(self.context_config),
            **build_context_options(self.context_config),
        }
        try:
            return self._playwright.chromium.launch_persistent_context(str(self.user_data_dir), **launch_options)
        except Exception:
            if not self.context_config.get("fallback_to_bundled_browser", True):
                raise
            fallback_options = {
                "headless": self.headless,
                "timeout": self.timeout_ms,
                **build_browser_launch_options(self.context_config, use_bundled_browser=True),
                **build_context_options(self.context_config),
            }
            return self._playwright.chromium.launch_persistent_context(str(self.user_data_dir), **fallback_options)

    def _pause_if_manual_action_required(self, page) -> None:
        if detect_page_auth_state(page) in {PageAuthState.LOGIN_REQUIRED, PageAuthState.MANUAL_ACTION_REQUIRED}:
            self._pause_for_manual_action(page, "页面需要人工登录或验证。请在浏览器中处理完成，程序会自动继续...")
