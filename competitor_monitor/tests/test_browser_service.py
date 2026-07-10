import sys
import json
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from browser_service import (
    BrowserService,
    PageAuthState,
    build_browser_launch_args,
    build_browser_launch_options,
    build_context_options,
    build_windows_chrome_user_agent,
    detect_page_auth_state,
    random_delay,
)
from credential_service import AccountCredentials


class BrowserServiceConfigTest(unittest.TestCase):
    def test_browser_launch_args_include_standard_stability_flags(self):
        args = build_browser_launch_args()

        self.assertIn("--disable-blink-features=AutomationControlled", args)
        self.assertIn("--no-sandbox", args)
        self.assertIn("--disable-dev-shm-usage", args)

    def test_browser_launch_options_prefer_local_chrome_channel(self):
        options = build_browser_launch_options()

        self.assertEqual(options["channel"], "chrome")
        self.assertIn("--disable-dev-shm-usage", options["args"])

    def test_browser_launch_options_can_fall_back_to_bundled_browser(self):
        options = build_browser_launch_options({"browser_channel": "chrome"}, use_bundled_browser=True)

        self.assertNotIn("channel", options)
        self.assertNotIn("executable_path", options)
        self.assertIn("--no-sandbox", options["args"])

    def test_context_options_include_standard_environment(self):
        options = build_context_options(
            {
                "viewport_width": 1366,
                "viewport_height": 768,
                "user_agent": "Custom UA",
            }
        )

        self.assertEqual(options["viewport"], {"width": 1366, "height": 768})
        self.assertEqual(options["locale"], "zh-CN")
        self.assertEqual(options["timezone_id"], "Asia/Shanghai")
        self.assertEqual(options["geolocation"], {"longitude": 116.4, "latitude": 39.9})
        self.assertEqual(options["permissions"], ["geolocation"])
        self.assertEqual(options["user_agent"], "Custom UA")

    def test_windows_chrome_user_agent_uses_supplied_major_version(self):
        user_agent = build_windows_chrome_user_agent(148)

        self.assertIn("Windows NT 10.0; Win64; x64", user_agent)
        self.assertIn("Chrome/148.0.0.0", user_agent)
        self.assertTrue(user_agent.endswith("Safari/537.36"))

    def test_random_delay_uses_supplied_range_without_real_sleep(self):
        with patch("browser_service.random.uniform", return_value=3.5) as uniform:
            with patch("browser_service.time.sleep") as sleep:
                actual = random_delay(2, 8)

        uniform.assert_called_once_with(2, 8)
        sleep.assert_called_once_with(3.5)
        self.assertEqual(actual, 3.5)

    def test_wait_after_operation_can_be_interrupted_by_stop_request(self):
        stop_event = threading.Event()
        service = BrowserService(
            headless=True,
            timeout_ms=1000,
            context_config={
                "operation_min_delay_seconds": 3,
                "operation_max_delay_seconds": 3,
            },
            stop_event=stop_event,
        )

        def request_stop(_seconds):
            stop_event.set()

        with patch("browser_service.random.uniform", return_value=3.0):
            with patch("browser_service.time.sleep", side_effect=request_stop) as sleep:
                actual = service.wait_after_operation()

        self.assertEqual(actual, 3.0)
        sleep.assert_called_once()
        self.assertLess(sleep.call_args.args[0], 3.0)
        self.assertTrue(stop_event.is_set())

    def test_persistent_context_receives_launch_and_context_options(self):
        fake_module = types.ModuleType("rebrowser_playwright.sync_api")
        captured = {}

        class FakeChromium:
            def launch_persistent_context(self, user_data_dir, **kwargs):
                captured["user_data_dir"] = user_data_dir
                captured["kwargs"] = kwargs
                return FakeContext()

        class FakeContext:
            def close(self):
                captured["closed"] = True

        class FakePlaywright:
            chromium = FakeChromium()

            def stop(self):
                captured["stopped"] = True

        class FakeSyncPlaywright:
            def start(self):
                return FakePlaywright()

        fake_module.sync_playwright = lambda: FakeSyncPlaywright()
        original_modules = dict(sys.modules)
        sys.modules["rebrowser_playwright"] = types.ModuleType("rebrowser_playwright")
        sys.modules["rebrowser_playwright.sync_api"] = fake_module
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                profile_dir = Path(tmpdir) / "profile"
                service = BrowserService(
                    headless=True,
                    timeout_ms=12345,
                    user_data_dir=profile_dir,
                    context_config={"operation_min_delay_seconds": 0, "operation_max_delay_seconds": 0},
                )
                with service:
                    pass
        finally:
            sys.modules.clear()
            sys.modules.update(original_modules)

        self.assertTrue(captured["user_data_dir"].endswith("profile"))
        self.assertTrue(captured["kwargs"]["headless"])
        self.assertEqual(captured["kwargs"]["timeout"], 12345)
        self.assertEqual(captured["kwargs"]["channel"], "chrome")
        self.assertIn("--no-sandbox", captured["kwargs"]["args"])
        self.assertEqual(captured["kwargs"]["viewport"], {"width": 1920, "height": 1080})
        self.assertEqual(captured["kwargs"]["locale"], "zh-CN")

    def test_detects_login_and_manual_verification_states(self):
        self.assertEqual(
            detect_page_auth_state(FakeTextPage("https://login.taobao.com/member/login.jhtml", "登录", "")),
            PageAuthState.LOGIN_REQUIRED,
        )
        self.assertEqual(
            detect_page_auth_state(FakeTextPage("https://detail.tmall.com/item.htm", "商品", "亲，请登录")),
            PageAuthState.LOGIN_REQUIRED,
        )
        self.assertEqual(
            detect_page_auth_state(FakeTextPage("https://detail.tmall.com/item.htm", "安全验证", "请完成滑块验证")),
            PageAuthState.MANUAL_ACTION_REQUIRED,
        )
        self.assertEqual(
            detect_page_auth_state(FakeTextPage("https://passport.taobao.com/", "身份验证", "手机验证 请输入验证码")),
            PageAuthState.MANUAL_ACTION_REQUIRED,
        )
        self.assertEqual(
            detect_page_auth_state(FakeTextPage("https://passport.taobao.com/ac/h5/verify", "", "")),
            PageAuthState.MANUAL_ACTION_REQUIRED,
        )
        self.assertEqual(
            detect_page_auth_state(FakeTextPage("https://detail.tmall.com/item.htm", "商品", "tb39655791 淘宝网首页")),
            PageAuthState.AUTHENTICATED,
        )

    def test_taobao_auto_login_fills_credentials_and_checks_two_boxes(self):
        page = FakeTaobaoLoginPage()
        service = BrowserService(
            headless=True,
            timeout_ms=1000,
            context_config={"operation_min_delay_seconds": 0, "operation_max_delay_seconds": 0},
        )
        service.wait_after_operation = lambda: 0

        service.login_taobao(page, AccountCredentials(username="user1", password="pass1"))

        self.assertEqual(page.filled["input[name='fm-login-id']"], "user1")
        self.assertEqual(page.filled["input[name='fm-login-password']"], "pass1")
        self.assertEqual(page.clicked_texts, ["记住我的登录状态", "我已阅读并同意"])
        self.assertEqual(page.clicked_selectors, ["#fm-agreement-checkbox", "button.fm-submit"])

    def test_taobao_auto_login_opens_login_page_before_filling_from_homepage(self):
        page = FakeTaobaoHomeLoginPromptPage()
        service = BrowserService(
            headless=True,
            timeout_ms=1000,
            context_config={"operation_min_delay_seconds": 0, "operation_max_delay_seconds": 0},
        )
        service.wait_after_operation = lambda: 0

        service.login_taobao(page, AccountCredentials(username="user1", password="pass1"))

        self.assertEqual(page.goto_urls, ["https://login.taobao.com/member/login.jhtml"])
        self.assertEqual(page.filled["input[name='fm-login-id']"], "user1")
        self.assertEqual(page.filled["input[name='fm-login-password']"], "pass1")
        self.assertEqual(page.clicked_selectors, ["#fm-agreement-checkbox", "button.fm-submit"])

    def test_taobao_auto_login_prefers_homepage_login_entry_xpath(self):
        page = FakeTaobaoHomeLoginEntryPage()
        service = BrowserService(
            headless=True,
            timeout_ms=1000,
            context_config={"operation_min_delay_seconds": 0, "operation_max_delay_seconds": 0},
        )
        service.wait_after_operation = lambda: 0

        service.login_taobao(page, AccountCredentials(username="user1", password="pass1"))

        self.assertEqual(page.goto_urls, [])
        self.assertEqual(
            page.clicked_selectors[:1],
            ['xpath=//*[@id="J_SiteNavLogin"]/div[1]/div[1]/a[1]'],
        )
        self.assertEqual(page.filled["input[name='fm-login-id']"], "user1")

    def test_ensure_taobao_login_falls_back_to_login_page_when_home_check_fails(self):
        service = BrowserService(
            headless=True,
            timeout_ms=1000,
            context_config={"operation_min_delay_seconds": 0, "operation_max_delay_seconds": 0},
            taobao_credentials=AccountCredentials(username="user1", password="pass1"),
        )
        service._context = FakeFailingTaobaoHomeContext()
        service.wait_after_operation = lambda: 0

        state = service.ensure_taobao_login()

        page = service._context.page
        self.assertEqual(state, PageAuthState.AUTHENTICATED)
        self.assertEqual(
            page.goto_urls,
            ["https://www.taobao.com/", "https://login.taobao.com/member/login.jhtml"],
        )
        self.assertEqual(page.filled["input[name='fm-login-id']"], "user1")
        self.assertTrue(page.closed)

    def test_taobao_auto_login_supports_new_password_login_form(self):
        page = FakeNewTaobaoPasswordLoginPage()
        service = BrowserService(
            headless=True,
            timeout_ms=1000,
            context_config={"operation_min_delay_seconds": 0, "operation_max_delay_seconds": 0},
        )
        service.wait_after_operation = lambda: 0

        service.login_taobao(page, AccountCredentials(username="user1", password="pass1"))

        self.assertEqual(page.filled["input[placeholder*='账号名']"], "user1")
        self.assertEqual(page.filled["input[placeholder*='登录密码']"], "pass1")
        self.assertEqual(page.clicked_selectors, ["#fm-agreement-checkbox", "button.fm-submit"])

    def test_taobao_auto_login_waits_between_human_sensitive_steps(self):
        page = FakeNewTaobaoPasswordLoginPage()
        service = BrowserService(
            headless=True,
            timeout_ms=1000,
            context_config={"operation_min_delay_seconds": 0, "operation_max_delay_seconds": 0},
        )
        delays = []
        service.wait_after_operation = lambda: delays.append("delay") or 0

        service.login_taobao(page, AccountCredentials(username="user1", password="pass1"))

        self.assertGreaterEqual(len(delays), 4)

    def test_taobao_auto_login_retries_once_when_verification_returns_to_login_page(self):
        page = FakeNewTaobaoPasswordLoginPage()
        page.stay_login_required_after_submit = True
        service = BrowserService(
            headless=True,
            timeout_ms=1000,
            context_config={"operation_min_delay_seconds": 0, "operation_max_delay_seconds": 0},
        )
        service.wait_after_operation = lambda: 0
        pause_messages = []
        service._pause_for_manual_action = lambda _page, message: pause_messages.append(message)

        service.login_taobao(page, AccountCredentials(username="user1", password="pass1"))
        service.login_taobao(page, AccountCredentials(username="user1", password="pass1"))

        self.assertEqual(page.clicked_selectors.count("button.fm-submit"), 2)
        self.assertEqual(page.clicked_selectors.count("#fm-agreement-checkbox"), 2)
        self.assertEqual(page.filled["input[placeholder*='账号名']"], "user1")
        self.assertEqual(page.filled["input[placeholder*='登录密码']"], "pass1")
        self.assertEqual(len(pause_messages), 2)

    def test_taobao_auto_login_caps_retries_when_login_page_keeps_returning(self):
        page = FakeNewTaobaoPasswordLoginPage()
        page.stay_login_required_after_submit = True
        service = BrowserService(
            headless=True,
            timeout_ms=1000,
            context_config={
                "operation_min_delay_seconds": 0,
                "operation_max_delay_seconds": 0,
                "taobao_auto_login_max_attempts": 2,
            },
        )
        service.wait_after_operation = lambda: 0
        pause_messages = []
        service._pause_for_manual_action = lambda _page, message: pause_messages.append(message) or PageAuthState.LOGIN_REQUIRED

        service.login_taobao(page, AccountCredentials(username="user1", password="pass1"))
        service.login_taobao(page, AccountCredentials(username="user1", password="pass1"))
        service.login_taobao(page, AccountCredentials(username="user1", password="pass1"))

        self.assertEqual(page.clicked_selectors.count("button.fm-submit"), 2)
        self.assertEqual(page.clicked_selectors.count("#fm-agreement-checkbox"), 2)
        self.assertEqual(len(pause_messages), 3)

    def test_manual_verification_can_return_to_login_page_for_second_auto_login_attempt(self):
        page = FakeVerificationReturnsToLoginPage()
        service = BrowserService(
            headless=True,
            timeout_ms=1000,
            context_config={
                "operation_min_delay_seconds": 0,
                "operation_max_delay_seconds": 0,
                "manual_action_timeout_seconds": 1,
                "manual_action_poll_seconds": 0,
            },
            taobao_credentials=AccountCredentials(username="user1", password="pass1"),
        )
        service.wait_after_operation = lambda: 0

        state = service.login_taobao(page, AccountCredentials(username="user1", password="pass1"))

        self.assertEqual(state, PageAuthState.AUTHENTICATED)
        self.assertEqual(page.clicked_selectors.count("button.fm-submit"), 2)
        self.assertEqual(page.filled["input[placeholder*='账号名']"], "user1")
        self.assertEqual(page.filled["input[placeholder*='登录密码']"], "pass1")

    def test_recover_page_auth_waits_for_persistent_profile_before_auto_login(self):
        page = FakeDelayedProfileAuthPage()
        service = BrowserService(
            headless=True,
            timeout_ms=1000,
            context_config={
                "operation_min_delay_seconds": 0,
                "operation_max_delay_seconds": 0,
                "taobao_login_state_check_attempts": 2,
                "taobao_login_state_check_seconds": 0,
            },
            taobao_credentials=AccountCredentials(username="user1", password="pass1"),
        )
        service.wait_after_operation = lambda: 0

        with patch("browser_service.time.sleep", side_effect=lambda seconds: page.resolve()):
            state = service._recover_page_auth(page)

        self.assertEqual(state, PageAuthState.AUTHENTICATED)
        self.assertEqual(page.filled, {})
        self.assertNotIn("button.fm-submit", page.clicked_selectors)

    def test_authenticated_state_is_saved_to_storage_state_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            service = BrowserService(
                headless=True,
                timeout_ms=1000,
                user_data_dir=Path(tmpdir) / "profile",
                context_config={"operation_min_delay_seconds": 0, "operation_max_delay_seconds": 0},
            )
            service._context = FakeStorageStateContext()

            service._persist_auth_state_if_authenticated(FakeTextPage("https://www.taobao.com/", "淘宝", "tb39655791"))

            state_path = Path(tmpdir) / "profile" / "storage_state.json"
            self.assertTrue(state_path.exists())
            self.assertEqual(service._context.saved_path, str(state_path))

    def test_storage_state_file_restores_cookies_on_startup(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            profile_dir = Path(tmpdir) / "profile"
            profile_dir.mkdir()
            state_path = profile_dir / "storage_state.json"
            state_path.write_text(
                json.dumps(
                    {
                        "cookies": [
                            {
                                "name": "cookie2",
                                "value": "abc",
                                "domain": ".taobao.com",
                                "path": "/",
                                "expires": -1,
                                "httpOnly": True,
                                "secure": True,
                                "sameSite": "Lax",
                            }
                        ],
                        "origins": [],
                    }
                ),
                encoding="utf-8",
            )
            service = BrowserService(
                headless=True,
                timeout_ms=1000,
                user_data_dir=profile_dir,
                context_config={"operation_min_delay_seconds": 0, "operation_max_delay_seconds": 0},
            )
            context = FakeStorageStateContext()

            service._restore_storage_state(context)

            self.assertEqual(context.added_cookies[0]["name"], "cookie2")
            self.assertEqual(context.added_cookies[0]["domain"], ".taobao.com")

    def test_manual_action_waits_for_browser_resolution_without_stdin(self):
        page = FakeManualResolutionPage()
        service = BrowserService(
            headless=True,
            timeout_ms=1000,
            context_config={
                "manual_action_timeout_seconds": 1,
                "manual_action_poll_seconds": 0,
            },
        )

        with patch("browser_service.sys.stdin.isatty", return_value=False):
            with patch("browser_service.time.sleep", side_effect=lambda seconds: page.resolve()):
                service._pause_for_manual_action(page, "需要人工处理")

        self.assertTrue(page.resolved)

    def test_manual_action_falls_back_to_browser_polling_when_terminal_input_eof(self):
        page = FakeManualResolutionPage()
        service = BrowserService(
            headless=True,
            timeout_ms=1000,
            context_config={
                "manual_action_timeout_seconds": 1,
                "manual_action_poll_seconds": 0,
            },
        )

        with patch("browser_service.sys.stdin.isatty", return_value=True):
            with patch("builtins.input", side_effect=EOFError):
                with patch("browser_service.time.sleep", side_effect=lambda seconds: page.resolve()):
                    service._pause_for_manual_action(page, "需要人工处理")

        self.assertTrue(page.resolved)

    def test_manual_action_uses_browser_polling_without_waiting_for_terminal_enter(self):
        page = FakeManualResolutionPage()
        service = BrowserService(
            headless=True,
            timeout_ms=1000,
            context_config={
                "manual_action_timeout_seconds": 1,
                "manual_action_poll_seconds": 0,
            },
        )

        with patch("browser_service.sys.stdin.isatty", return_value=True):
            with patch("builtins.input") as input_mock:
                with patch("browser_service.time.sleep", side_effect=lambda seconds: page.resolve()):
                    service._pause_for_manual_action(page, "需要人工处理")

        input_mock.assert_not_called()
        self.assertTrue(page.resolved)

    def test_manual_action_does_not_treat_passport_verification_url_as_authenticated(self):
        page = FakePassportVerificationPage()
        service = BrowserService(
            headless=True,
            timeout_ms=1000,
            context_config={
                "manual_action_timeout_seconds": 1,
                "manual_action_poll_seconds": 0,
            },
        )

        with patch("browser_service.time.sleep", side_effect=lambda seconds: page.resolve()):
            service._pause_for_manual_action(page, "需要人工处理")

        self.assertTrue(page.resolved)

    def test_manual_action_wait_stops_when_task_stop_is_requested(self):
        page = FakePassportVerificationPage()
        stop_event = threading.Event()
        service = BrowserService(
            headless=True,
            timeout_ms=1000,
            context_config={
                "manual_action_timeout_seconds": 1,
                "manual_action_poll_seconds": 0,
            },
            stop_event=stop_event,
        )

        def request_stop(_seconds):
            stop_event.set()

        with patch("browser_service.time.sleep", side_effect=request_stop):
            state = service._pause_for_manual_action(page, "需要人工处理")

        self.assertEqual(state, PageAuthState.MANUAL_ACTION_REQUIRED)
        self.assertTrue(stop_event.is_set())


if __name__ == "__main__":
    unittest.main()


class FakeTextPage:
    def __init__(self, url, title, body):
        self.url = url
        self._title = title
        self._body = body

    def title(self):
        return self._title

    def locator(self, selector):
        return FakeBody(self._body)


class FakeBody:
    def __init__(self, text):
        self.text = text

    def inner_text(self, timeout=3000):
        return self.text


class FakeTaobaoLoginPage:
    def __init__(self):
        self.url = "https://login.taobao.com/member/login.jhtml"
        self.body = "账号 密码 登录"
        self.filled = {}
        self.clicked_texts = []
        self.clicked_selectors = []

    def locator(self, selector):
        if selector == "body":
            return FakeBody(self.body)
        return FakeLoginLocator(self, selector)

    def get_by_text(self, text, exact=True):
        return FakeTextClick(self, text)

    def wait_for_load_state(self, state, timeout=0):
        return None

    def wait_for_timeout(self, timeout):
        return None


class FakeTaobaoHomeLoginPromptPage(FakeTaobaoLoginPage):
    def __init__(self):
        super().__init__()
        self.url = "https://www.taobao.com/"
        self.body = "亲，请登录"
        self.goto_urls = []

    def locator(self, selector):
        if selector == "body":
            return FakeBody(self.body)
        if self.url == "https://www.taobao.com/" and (selector.startswith("xpath=") or selector.startswith("text=")):
            return FakeMissingLocator(selector)
        return super().locator(selector)

    def goto(self, url, wait_until="domcontentloaded", timeout=0):
        self.goto_urls.append(url)
        self.url = url
        self.body = "账号 密码 登录"


class FakeTaobaoHomeLoginEntryPage(FakeTaobaoHomeLoginPromptPage):
    LOGIN_ENTRY_SELECTOR = 'xpath=//*[@id="J_SiteNavLogin"]/div[1]/div[1]/a[1]'

    def locator(self, selector):
        if selector == self.LOGIN_ENTRY_SELECTOR:
            return FakeHomeLoginEntryLocator(self, selector)
        return super().locator(selector)


class FakeHomeLoginEntryLocator:
    def __init__(self, page, selector):
        self.page = page
        self.selector = selector

    @property
    def first(self):
        return self

    def click(self, timeout=0):
        self.page.clicked_selectors.append(self.selector)
        self.page.url = "https://login.taobao.com/member/login.jhtml"
        self.page.body = "账号 密码 登录"


class FakeFailingTaobaoHomeContext:
    def __init__(self):
        self.page = FakeFailingTaobaoHomePage()

    def new_page(self):
        return self.page


class FakeFailingTaobaoHomePage(FakeTaobaoLoginPage):
    def __init__(self):
        super().__init__()
        self.url = "about:blank"
        self.body = ""
        self.goto_urls = []
        self.closed = False

    def goto(self, url, wait_until="domcontentloaded", timeout=0):
        self.goto_urls.append(url)
        if url == "https://www.taobao.com/":
            raise RuntimeError("net::ERR_CONNECTION_CLOSED")
        self.url = url
        self.body = "账号 密码 登录"

    def close(self):
        self.closed = True


class FakeNewTaobaoPasswordLoginPage(FakeTaobaoLoginPage):
    SUPPORTED_SELECTORS = {
        "input[placeholder*='账号名']",
        "input[placeholder*='登录密码']",
        "#fm-agreement-checkbox",
        "button.fm-submit",
    }

    def __init__(self):
        super().__init__()
        self.body = "密码登录 短信登录 账号名/邮箱/手机号 请输入登录密码 已阅读并同意以下协议 登录"

    def locator(self, selector):
        if selector == "body":
            return FakeBody(self.body)
        if selector in self.SUPPORTED_SELECTORS:
            return FakeLoginLocator(self, selector)
        return FakeMissingLocator(selector)


class FakeVerificationReturnsToLoginPage(FakeNewTaobaoPasswordLoginPage):
    def __init__(self):
        super().__init__()
        self.state_after_submit = "manual"
        self.manual_polls = 0

    def wait_for_load_state(self, state, timeout=0):
        if self.state_after_submit == "manual":
            self.manual_polls += 1
            if self.manual_polls >= 2:
                self.state_after_submit = "login"
                self.url = "https://login.taobao.com/member/login.jhtml"
                self.body = "密码登录 短信登录 账号名/邮箱/手机号 请输入登录密码 已阅读并同意以下协议 登录"
        return None

    def mark_submitted(self):
        if self.state_after_submit == "manual":
            self.url = "https://passport.taobao.com/ac/h5/verify"
            self.body = "手机验证 请输入验证码"
        elif self.state_after_submit == "login":
            self.url = "https://www.taobao.com/"
            self.body = "tb39655791 淘宝网首页"


class FakeManualResolutionPage(FakeTextPage):
    def __init__(self):
        super().__init__("https://login.taobao.com/member/login.jhtml", "登录", "账号 密码 登录")
        self.resolved = False

    def resolve(self):
        self.url = "https://www.taobao.com/"
        self._title = "淘宝网首页"
        self._body = "tb39655791 淘宝网首页"
        self.resolved = True

    def wait_for_load_state(self, state, timeout=0):
        return None


class FakeDelayedProfileAuthPage(FakeTaobaoLoginPage):
    def __init__(self):
        super().__init__()
        self.url = "https://login.taobao.com/member/login.jhtml"
        self.body = "亲，请登录"
        self.resolved = False

    def resolve(self):
        self.url = "https://www.taobao.com/"
        self.body = "tb39655791 淘宝网首页"
        self.resolved = True


class FakePassportVerificationPage(FakeManualResolutionPage):
    def __init__(self):
        super().__init__()
        self.url = "https://passport.taobao.com/ac/h5/verify"
        self._title = ""
        self._body = ""


class FakeStorageStateContext:
    def __init__(self):
        self.saved_path = None
        self.added_cookies = []

    def storage_state(self, path=None):
        self.saved_path = path
        if path:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_text(json.dumps({"cookies": [], "origins": []}), encoding="utf-8")
        return {"cookies": [], "origins": []}

    def add_cookies(self, cookies):
        self.added_cookies.extend(cookies)


class FakeMissingLocator:
    def __init__(self, selector):
        self.selector = selector

    @property
    def first(self):
        return self

    def click(self, timeout=0):
        raise RuntimeError(f"missing selector: {self.selector}")

    def fill(self, value, timeout=0):
        raise RuntimeError(f"missing selector: {self.selector}")


class FakeLoginLocator:
    def __init__(self, page, selector):
        self.page = page
        self.selector = selector

    @property
    def first(self):
        return self

    def fill(self, value, timeout=0):
        self.page.filled[self.selector] = value

    def click(self, timeout=0):
        self.page.clicked_selectors.append(self.selector)
        if self.selector in {"button[type='submit']", "button.fm-submit"} and hasattr(self.page, "mark_submitted"):
            self.page.mark_submitted()
            return
        if self.selector in {"button[type='submit']", "button.fm-submit"} and not getattr(
            self.page, "stay_login_required_after_submit", False
        ):
            self.page.url = "https://www.taobao.com/"
            self.page.body = "tb39655791 淘宝网首页"


class FakeTextClick:
    def __init__(self, page, text):
        self.page = page
        self.text = text

    @property
    def first(self):
        return self

    def click(self, timeout=0):
        self.page.clicked_texts.append(self.text)
