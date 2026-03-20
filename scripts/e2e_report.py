import json
import time
from pathlib import Path
import sys

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from werkzeug.security import generate_password_hash

from app import create_app
from app.extensions import db
from app.models.user import User
from app.services.user_quota_service import adjust_quota, get_or_create_quota
from app.views.api import _ensure_user_ref_code


BASE_URL = "http://127.0.0.1:5000"
EDGE_CDP = "http://127.0.0.1:9222"
REGULAR_USER = "codex_reg_user"
REGULAR_PASS = "Codex123!"
ADMIN_USER = "codex_reg_admin"
ADMIN_PASS = "Codex123!"
MATERIALS_DIR = r"E:\JianYingApi\VideoFactory\user_data\stage5_mix_materials"
MANGA_IMAGE = r"E:\JianYingApi\VideoFactory\user_data\dev_drafts\task_024c7651\cover.png"


def ensure_browser_regression_accounts():
    app = create_app()
    with app.app_context():
        regular = User.query.filter_by(username=REGULAR_USER).first()
        if not regular:
            regular = User(username=REGULAR_USER, role="user")
        else:
            regular.role = "user"
        regular.password_hash = generate_password_hash(REGULAR_PASS)
        db.session.add(regular)
        db.session.commit()
        _ensure_user_ref_code(regular, commit=True)
        quota = get_or_create_quota(regular.id)
        if quota.remaining < 5:
            adjust_quota(regular.id, remaining=5)

        admin = User.query.filter_by(username=ADMIN_USER).first()
        if not admin:
            admin = User(username=ADMIN_USER, role="admin")
        else:
            admin.role = "admin"
        admin.password_hash = generate_password_hash(ADMIN_PASS)
        db.session.add(admin)
        db.session.commit()
        _ensure_user_ref_code(admin, commit=True)


class Reporter:
    def __init__(self):
        self.results = []
        self.console_errors = []
        self.request_failures = []
        self.generated_user = ""
        self.generated_pass = "Codex123!"
        self.resource_post_name = ""

    def add(self, area, step, status, detail):
        self.results.append(
            {
                "area": area,
                "step": step,
                "status": status,
                "detail": detail,
            }
        )

    def attach_page_watchers(self, page, area):
        page.on(
            "console",
            lambda msg: self.console_errors.append(
                {
                    "area": area,
                    "type": msg.type,
                    "text": msg.text,
                }
            )
            if msg.type == "error"
            else None,
        )
        page.on(
            "requestfailed",
            lambda req: self.request_failures.append(
                {
                    "area": area,
                    "url": req.url,
                    "method": req.method,
                    "error": req.failure,
                }
            ),
        )


def safe_text(locator):
    try:
        return (locator.text_content() or "").strip()
    except Exception:
        return ""


def safe_value(locator):
    try:
        return (locator.input_value() or "").strip()
    except Exception:
        return ""


def visible(locator):
    try:
        return locator.is_visible()
    except Exception:
        return False


def open_group(page, label):
    page.locator(".sidebar-parent", has_text=label).first.click()
    page.wait_for_timeout(250)


def open_link(page, label):
    link = page.locator(".sidebar-link", has_text=label).first
    if not visible(link):
        group = link.get_attribute("data-nav-group") or ""
        if group:
            page.locator(f'[data-group-toggle="{group}"]').click()
            page.wait_for_timeout(250)
    link.click()
    page.wait_for_timeout(300)


def wait_modal_hidden(page, modal_id, timeout=15000):
    page.wait_for_function(
        """(modalId) => {
            const node = document.getElementById(modalId);
            return !!node && node.getAttribute('aria-hidden') === 'true';
        }""",
        arg=modal_id,
        timeout=timeout,
    )


def try_wait_modal_hidden(page, modal_id, timeout=15000):
    try:
        wait_modal_hidden(page, modal_id, timeout=timeout)
        return True
    except PlaywrightTimeoutError:
        return False


def wait_panel_active(page, panel_id, timeout=8000):
    page.wait_for_function(
        """(id) => {
            const node = document.getElementById(id);
            return !!node && node.classList.contains('active');
        }""",
        arg=panel_id,
        timeout=timeout,
    )


def horizontal_overflow(page):
    return page.evaluate(
        """() => ({
            scrollWidth: document.documentElement.scrollWidth,
            clientWidth: document.documentElement.clientWidth,
            overflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 2
        })"""
    )


def visible_control_count(page, root_selector):
    return page.locator(
        f"{root_selector} input:visible, {root_selector} button:visible, {root_selector} select:visible, {root_selector} textarea:visible"
    ).count()


def open_assistant(page):
    open_group(page, "智能助手")
    open_link(page, "命令中心")
    wait_panel_active(page, "panel-assistant")


def wait_text_contains(page, selector, snippets, timeout=10000):
    page.wait_for_function(
        """({selector, snippets}) => {
            const node = document.querySelector(selector);
            if (!node) return false;
            const text = node.innerText || node.textContent || '';
            return snippets.every((item) => text.includes(item));
        }""",
        arg={"selector": selector, "snippets": snippets},
        timeout=timeout,
    )


def preview_assistant(page, command, expected_snippets):
    open_assistant(page)
    page.locator("#assistantCommandInput").fill(command)
    page.locator("#assistantPreviewBtn").click()
    wait_text_contains(page, "#assistantPreviewBox", expected_snippets)
    return safe_text(page.locator("#assistantPreviewBox"))


def register_user(page, reporter):
    reporter.generated_user = f"e2e_{int(time.time())}"
    page.goto(f"{BASE_URL}/user", wait_until="domcontentloaded")
    page.wait_for_load_state("networkidle")
    page.locator('.auth-tab[data-tab="register"]').click()
    page.locator("#registerUsername").fill(reporter.generated_user)
    page.locator("#registerPassword").fill(reporter.generated_pass)
    page.locator("#registerForm button[type='submit']").click()
    if not try_wait_modal_hidden(page, "authModal"):
        msg = safe_text(page.locator("#authMsg"))
        state = page.locator("#authModal").get_attribute("aria-hidden")
        reporter.add("user-auth", "注册并自动登录", "failed", f"注册后弹窗未关闭，aria-hidden={state}，提示={msg}")
        return
    open_group(page, "账户中心")
    open_link(page, "账户信息")
    username = safe_text(page.locator("#userName"))
    if username == reporter.generated_user:
        reporter.add("user-auth", "注册并自动登录", "passed", f"注册用户 {reporter.generated_user} 成功")
    else:
        reporter.add("user-auth", "注册并自动登录", "failed", f"注册后账户信息未显示新用户，当前值：{username}")


def logout_user(page, reporter):
    open_group(page, "账户中心")
    open_link(page, "账户信息")
    page.locator("#logoutBtn").click()
    page.wait_for_function(
        """() => {
            const node = document.getElementById('authModal');
            return !!node && node.getAttribute('aria-hidden') === 'false';
        }""",
        timeout=10000,
    )
    reporter.add("user-auth", "退出登录", "passed", "退出后登录弹窗重新显示")


def login_user(page, username, password, area, reporter):
    page.locator('.auth-tab[data-tab="login"]').click()
    page.locator("#loginAccount").fill(username)
    page.locator("#loginPassword").fill(password)
    page.locator("#loginForm button[type='submit']").click()
    wait_modal_hidden(page, "authModal")
    reporter.add(area, f"登录 {username}", "passed", "登录成功")


def login_admin(page, reporter):
    page.goto(f"{BASE_URL}/admin", wait_until="domcontentloaded")
    page.wait_for_load_state("networkidle")
    page.locator("#loginAccount").fill(ADMIN_USER)
    page.locator("#loginPassword").fill(ADMIN_PASS)
    page.locator("#loginForm button[type='submit']").click()
    wait_modal_hidden(page, "adminAuthModal")
    reporter.add("admin-auth", "管理员登录", "passed", "管理员登录成功")


def check_user_navigation(page, reporter):
    navs = [
        ("批量混剪", "按组精准替换", "panel-materials"),
        ("批量混剪", "混剪裂变替换", "panel-materials"),
        ("批量混剪", "分区混剪裂变", "panel-materials"),
        ("AI 智做", "AI 成片", "panel-ai-make"),
        ("AI 智做", "AI 漫剧", "panel-ai-manga"),
        ("批量效果", "效果配置", "panel-effects"),
        ("批量效果", "资源库", "panel-effects"),
        ("批量效果", "Duo 资源", "panel-effects"),
        ("批量分割", "文件分割", "panel-split"),
        ("批量分割", "草稿处理", "panel-split"),
        ("批量分割", "批量查看", "panel-split"),
        ("片段微调", "AI 灵感", "panel-clip"),
        ("片段微调", "节奏变速", "panel-clip"),
        ("片段微调", "画面校正", "panel-clip"),
        ("片段微调", "摇晃关键帧", "panel-clip"),
        ("批量导出", "导出设置", "panel-export"),
        ("批量导出", "批量导出", "panel-export"),
        ("批量导出", "片段导出", "panel-export"),
        ("软件设置", "工作台设置", "panel-settings"),
        ("软件设置", "路径与目录", "panel-settings"),
        ("软件设置", "AI 漫剧服务", "panel-settings"),
        ("软件设置", "AI 账号管理", "panel-settings"),
        ("账户中心", "账户信息", "panel-account"),
        ("账户中心", "授权激活", "panel-account"),
    ]
    for group, item, panel in navs:
        try:
            open_group(page, group)
            open_link(page, item)
            wait_panel_active(page, panel)
            metrics = horizontal_overflow(page)
            count = visible_control_count(page, f"#{panel}")
            status = "passed"
            detail = f"{item} 打开成功，可见控件 {count} 个，横向溢出={metrics['overflow']}"
            if metrics["overflow"]:
                status = "warning"
            reporter.add("user-navigation", f"{group} -> {item}", status, detail)
        except Exception as exc:
            reporter.add("user-navigation", f"{group} -> {item}", "failed", str(exc))


def test_mix_generate(page, reporter):
    try:
        open_group(page, "批量混剪")
        open_link(page, "按组精准替换")
        page.wait_for_timeout(1200)
        draft_items = page.locator("#draftDiscoveryList .draft-item")
        if not draft_items.count():
            reporter.add("mix-generate", "选择草稿", "failed", "未发现可选草稿")
            return
        target_draft = None
        for idx in range(draft_items.count()):
            node = draft_items.nth(idx)
            text = safe_text(node)
            if "mcp_" in text:
                continue
            target_draft = node
            break
        if target_draft is None:
            target_draft = draft_items.first
        target_draft.click()
        page.wait_for_timeout(1800)
        draft_path = page.locator("#draft_path").input_value().strip()
        if not draft_path:
            reporter.add("mix-generate", "选择草稿", "failed", "点击草稿后当前草稿仍为空")
            return
        page.locator("#folder_path").fill(MATERIALS_DIR)
        page.locator("#batch_count").fill("1")
        if page.locator("#replace_materials").is_checked() is False:
            page.locator("#replace_materials").check()
        page.locator("#submitBtn").click()
        page.wait_for_timeout(1500)
        page.wait_for_function(
            """() => {
                const t = (document.getElementById('progress-text')?.innerText || '');
                return t.includes('任务已提交') || t.includes('生成完成') || t.includes('生成失败') || t.includes('提交失败');
            }""",
            timeout=120000,
        )
        progress = safe_text(page.locator("#progress-text"))
        status = "passed" if ("任务已提交" in progress or "生成完成" in progress) else "failed"
        reporter.add("mix-generate", "素材替换生成", status, progress)
    except Exception as exc:
        reporter.add("mix-generate", "素材替换生成", "failed", str(exc))


def test_capture_removed(page, reporter):
    try:
        removal_state = page.evaluate(
            """() => ({
                hasGroup: Array.from(document.querySelectorAll('.sidebar-parent')).some((node) => (node.innerText || '').includes('素材获得')),
                hasLink: Array.from(document.querySelectorAll('.sidebar-link')).some((node) => (node.innerText || '').includes('素材获得')),
                hasPanel: !!document.getElementById('panel-material-capture')
            })"""
        )
        api_state = page.evaluate(
            """async() => {
                const res = await fetch('/api/net-assets/start', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: '{}'
                });
                let data = {};
                try { data = await res.json(); } catch (err) {}
                return {status: res.status, data};
            }"""
        )
        message = json.dumps(api_state.get("data") or {}, ensure_ascii=False)
        if any(removal_state.values()):
            reporter.add("capture-removed", "第三方采集已下线", "failed", json.dumps(removal_state, ensure_ascii=False))
        elif api_state.get("status") != 410 or "已下线" not in message:
            reporter.add("capture-removed", "第三方采集已下线", "failed", f"{api_state.get('status')} | {message}")
        else:
            reporter.add("capture-removed", "第三方采集已下线", "passed", f"nav={json.dumps(removal_state, ensure_ascii=False)} api={message}")
    except Exception as exc:
        reporter.add("capture-removed", "第三方采集已下线", "failed", str(exc))


def test_assistant(page, reporter):
    layout_root = PROJECT_ROOT / "user_data" / "assistant_e2e_layouts" / f"run_{int(time.time())}"

    commands = [
        {
            "step": "assistant preview group mix",
            "command": "帮我按组混剪",
            "expected": ["类型：navigate", "目标模式：group", "目标面板：panel-materials"],
        },
        {
            "step": "assistant preview export draft",
            "command": "帮我导出当前草稿",
            "expected": ["类型：navigate", "目标面板：panel-export"],
        },
        {
            "step": "assistant preview inspect draft slots",
            "command": "帮我检查草稿槽位",
            "expected": ["类型：navigate", "目标面板：panel-split"],
        },
        {
            "step": "assistant preview text template",
            "command": "帮我生成文字替换模板",
            "expected": ["类型：fill_text_template"],
        },
        {
            "step": "assistant preview create material layout",
            "command": "帮我创建素材目录",
            "expected": ["类型：create_material_layout", "确认：需要"],
        },
        {
            "step": "assistant preview partition mix",
            "command": "帮我分区一段视频",
            "expected": ["类型：navigate", "目标模式：partition", "目标面板：panel-materials"],
        },
    ]
    for item in commands:
        try:
            preview_text = preview_assistant(page, item["command"], item["expected"])
            reporter.add("assistant", item["step"], "passed", preview_text)
        except Exception as exc:
            reporter.add("assistant", item["step"], "failed", str(exc))

    try:
        preview_assistant(page, "帮我按组混剪", ["类型：navigate", "目标模式：group"])
        page.locator("#assistantExecuteBtn").click()
        wait_panel_active(page, "panel-materials")
        page.wait_for_function(
            """() => {
                const node = document.getElementById('mixModeStatusTitle');
                return !!node && (node.innerText || '').includes('按组精准替换');
            }""",
            timeout=10000,
        )
        reporter.add("assistant", "assistant execute group mix", "passed", safe_text(page.locator("#mixModeStatusTitle")))
    except Exception as exc:
        reporter.add("assistant", "assistant execute group mix", "failed", str(exc))

    try:
        open_group(page, "批量混剪")
        open_link(page, "按组精准替换")
        wait_panel_active(page, "panel-materials")
        page.locator("#folder_path").fill(str(layout_root))
        preview_assistant(page, "帮我创建素材目录", ["类型：create_material_layout", "确认：需要"])
        page.once("dialog", lambda dialog: dialog.accept())
        page.locator("#assistantExecuteBtn").click()
        page.wait_for_function(
            """() => {
                const text = document.getElementById('materialLayoutStatus')?.innerText || '';
                return text.includes('已创建：');
            }""",
            timeout=15000,
        )
        created_root = safe_value(page.locator("#folder_path"))
        exists = bool(created_root) and Path(created_root).exists()
        detail = safe_text(page.locator("#materialLayoutStatus")) or created_root
        reporter.add("assistant", "assistant execute create material layout", "passed" if exists else "failed", detail)
    except Exception as exc:
        reporter.add("assistant", "assistant execute create material layout", "failed", str(exc))

    try:
        preview_assistant(page, "帮我生成文字替换模板", ["类型：fill_text_template"])
        page.locator("#assistantExecuteBtn").click()
        page.wait_for_function(
            """() => {
                const box = document.getElementById('text_batch_input');
                return !!box && !!(box.value || '').trim();
            }""",
            timeout=10000,
        )
        value = safe_value(page.locator("#text_batch_input"))
        line_count = len([line for line in value.splitlines() if line.strip()])
        reporter.add("assistant", "assistant execute fill text template", "passed" if line_count > 0 else "failed", f"lines={line_count}")
    except Exception as exc:
        reporter.add("assistant", "assistant execute fill text template", "failed", str(exc))

    try:
        preview_assistant(page, "帮我导出当前草稿", ["类型：navigate", "目标面板：panel-export"])
        page.locator("#assistantExecuteBtn").click()
        wait_panel_active(page, "panel-export")
        export_visible = visible(page.locator("#export_dir"))
        reporter.add("assistant", "assistant execute export draft", "passed" if export_visible else "failed", f"export_dir_visible={export_visible}")
    except Exception as exc:
        reporter.add("assistant", "assistant execute export draft", "failed", str(exc))

    try:
        preview_assistant(page, "帮我检查草稿槽位", ["类型：navigate", "目标面板：panel-split"])
        page.locator("#assistantExecuteBtn").click()
        wait_panel_active(page, "panel-split")
        split_visible = visible(page.locator("#split_draft_result"))
        reporter.add("assistant", "assistant execute inspect draft slots", "passed" if split_visible else "failed", f"split_draft_result_visible={split_visible}")
    except Exception as exc:
        reporter.add("assistant", "assistant execute inspect draft slots", "failed", str(exc))

    try:
        preview_assistant(page, "帮我分区一段视频", ["类型：navigate", "目标模式：partition", "目标面板：panel-materials"])
        page.locator("#assistantExecuteBtn").click()
        wait_panel_active(page, "panel-materials")
        page.wait_for_function(
            """() => {
                const node = document.getElementById('mixModeStatusTitle');
                return !!node && (node.innerText || '').includes('分区混剪裂变');
            }""",
            timeout=10000,
        )
        reporter.add("assistant", "assistant execute partition mix", "passed", safe_text(page.locator("#mixModeStatusTitle")))
    except Exception as exc:
        reporter.add("assistant", "assistant execute partition mix", "failed", str(exc))

    try:
        open_assistant(page)
        page.locator("#assistantRefreshLogsBtn").click()
        page.wait_for_timeout(800)
        log_text = safe_text(page.locator("#assistantLogList"))
        required_logs = ["帮我按组混剪", "帮我创建素材目录", "帮我导出当前草稿"]
        ok = all(item in log_text for item in required_logs)
        reporter.add("assistant", "assistant logs", "passed" if ok else "failed", log_text[:400])
    except Exception as exc:
        reporter.add("assistant", "assistant logs", "failed", str(exc))


def test_ai_make(page, reporter):
    try:
        open_group(page, "AI 智做")
        open_link(page, "AI 成片")
        selects = {
            "即梦": page.locator("#ai_jimeng_key option").all_text_contents(),
            "火山": page.locator("#ai_volc_key option").all_text_contents(),
            "OpenAI": page.locator("#ai_openai_key option").all_text_contents(),
        }
        populated = any(any(opt.strip() and opt.strip() != "请选择" for opt in values) for values in selects.values())
        if populated:
            reporter.add("ai-make", "AI 成片账号准备", "passed", json.dumps(selects, ensure_ascii=False))
        else:
            reporter.add("ai-make", "AI 成片账号准备", "blocked", f"未发现已配置可用 AI 账号：{json.dumps(selects, ensure_ascii=False)}")
    except Exception as exc:
        reporter.add("ai-make", "AI 成片账号准备", "failed", str(exc))


def test_manga(page, reporter):
    try:
        open_group(page, "软件设置")
        open_link(page, "AI 漫剧服务")
        page.locator("#testOpenclawSettingsBtn").click()
        page.wait_for_timeout(2500)
        conn_text = safe_text(page.locator("#openclawSettingsStatus"))
        if not conn_text:
            conn_text = safe_text(page.locator("#globalToast"))
        if "成功" not in conn_text:
            reporter.add("ai-manga", "OpenClaw 连接", "blocked", conn_text or "未返回连接结果")
            return
        reporter.add("ai-manga", "OpenClaw 连接", "passed", conn_text)
        open_group(page, "AI 智做")
        open_link(page, "AI 漫剧")
        page.locator("#manga_character_file").set_input_files(MANGA_IMAGE)
        page.locator("#manga_script").fill("1. 女主走进咖啡店，镜头推进\n2. 店员递上咖啡，特写杯口热气")
        page.locator("#manga_generate_btn").click()
        page.wait_for_timeout(3000)
        page.wait_for_function(
            """() => {
                const t = (document.getElementById('manga_status')?.innerText || '');
                return !!t && t !== '完成脚本、角色图和服务配置后即可开始。';
            }""",
            timeout=120000,
        )
        status = safe_text(page.locator("#manga_status"))
        if any(key in status for key in ["完成", "成功", "处理中", "生成中"]):
            reporter.add("ai-manga", "AI 漫剧生成", "passed", status)
        else:
            reporter.add("ai-manga", "AI 漫剧生成", "failed", status)
    except Exception as exc:
        reporter.add("ai-manga", "AI 漫剧生成", "failed", str(exc))


def test_ai_blocked_guidance(page, reporter):
    try:
        open_group(page, "AI 智做")
        open_link(page, "AI 成片")
        intro_text = safe_text(page.locator("#panel-ai-make .module-sub")) + "\n" + safe_text(page.locator("#panel-ai-make .tool-result").first)
        intro_ok = "AI账号管理" in intro_text
        reporter.add("ai-make", "AI 成片账号引导文案", "passed" if intro_ok else "failed", intro_text[:200])

        selects = {
            "jimeng": page.locator("#ai_jimeng_key option").all_text_contents(),
            "volc": page.locator("#ai_volc_key option").all_text_contents(),
            "openai": page.locator("#ai_openai_key option").all_text_contents(),
        }
        populated = any(any(opt.strip() and opt.strip() != "请选择" for opt in values) for values in selects.values())
        if not populated:
            page.locator("#ai_jimeng_prompt").fill("e2e no-account prompt")
            page.locator("#ai_jimeng_action").fill("VideoGeneration")
            page.locator("#ai_jimeng_version").fill("2024-01-01")
            page.locator('#panel-ai-make button:has-text("开始生成")').first.click()
            page.wait_for_timeout(500)
            status_text = safe_text(page.locator("#ai_jimeng_status"))
            guidance_ok = "AI账号管理" in status_text
            reporter.add("ai-make", "AI 成片无账号弱提示", "passed" if guidance_ok else "failed", status_text)
        else:
            reporter.add("ai-make", "AI 成片无账号弱提示", "passed", "当前环境已存在可用 AI 账号，跳过无账号提示校验")
    except Exception as exc:
        reporter.add("ai-make", "AI 成片弱提示一致性", "failed", str(exc))

    try:
        open_group(page, "AI 智做")
        open_link(page, "AI 漫剧")
        intro_text = safe_text(page.locator("#panel-ai-manga .module-sub")) + "\n" + safe_text(page.locator(".manga-intro-card"))
        intro_ok = ("素材" in intro_text and "历史" in intro_text and "草稿" in intro_text)
        reporter.add("ai-manga", "AI 漫剧定位文案", "passed" if intro_ok else "failed", intro_text[:240])

        page.locator("#manga_script").fill("1. e2e blocked probe")
        page.locator("#manga_generate_btn").click()
        page.wait_for_timeout(800)
        status_text = safe_text(page.locator("#manga_status"))
        settings_active = page.evaluate(
            """() => {
                const panel = document.getElementById('panel-settings');
                const section = document.getElementById('settings-service-section');
                return !!panel?.classList.contains('active') && !!section && section.style.display !== 'none';
            }"""
        )
        if "服务地址" in status_text or "AI 漫剧服务" in status_text:
            reporter.add("ai-manga", "AI 漫剧缺服务弱提示", "passed" if settings_active else "failed", f"{status_text} | settings_active={settings_active}")
        else:
            reporter.add("ai-manga", "AI 漫剧缺服务弱提示", "passed", f"当前环境未命中缺服务提示：{status_text}")
    except Exception as exc:
        reporter.add("ai-manga", "AI 漫剧缺服务弱提示", "failed", str(exc))


def test_ai_guidance_copy(page, reporter):
    try:
        open_group(page, "AI 智做")
        open_link(page, "AI 成片")
        intro_text = safe_text(page.locator("#panel-ai-make .module-sub")) + "\n" + safe_text(page.locator("#panel-ai-make .tool-result").first)
        intro_ok = "AI账号管理" in intro_text
        reporter.add("ai-make", "AI 成片账号引导文案", "passed" if intro_ok else "failed", intro_text[:200])

        selects = {
            "jimeng": page.locator("#ai_jimeng_key option").all_text_contents(),
            "volc": page.locator("#ai_volc_key option").all_text_contents(),
            "openai": page.locator("#ai_openai_key option").all_text_contents(),
        }
        populated = any(any(opt.strip() and opt.strip() != "请选择" for opt in values) for values in selects.values())
        if not populated:
            page.locator("#ai_jimeng_prompt").fill("e2e no-account prompt")
            page.locator("#ai_jimeng_action").fill("VideoGeneration")
            page.locator("#ai_jimeng_version").fill("2024-01-01")
            page.locator('#panel-ai-make button:has-text("开始生成")').first.click()
            page.wait_for_timeout(500)
            status_text = safe_text(page.locator("#ai_jimeng_status"))
            guidance_ok = "AI账号管理" in status_text
            reporter.add("ai-make", "AI 成片无账号弱提示", "passed" if guidance_ok else "failed", status_text)
        else:
            reporter.add("ai-make", "AI 成片无账号弱提示", "passed", "当前环境已存在可用 AI 账号，跳过无账号提示校验")
    except Exception as exc:
        reporter.add("ai-make", "AI 成片弱提示一致性", "failed", str(exc))

    try:
        open_group(page, "AI 智做")
        open_link(page, "AI 漫剧")
        intro_text = safe_text(page.locator("#panel-ai-manga .module-sub")) + "\n" + safe_text(page.locator(".manga-intro-card"))
        intro_ok = ("素材" in intro_text and "历史" in intro_text and "草稿" in intro_text)
        reporter.add("ai-manga", "AI 漫剧定位文案", "passed" if intro_ok else "failed", intro_text[:240])

        page.locator('#panel-ai-manga button:has-text("打开服务设置")').click()
        page.wait_for_timeout(500)
        settings_active = page.evaluate(
            """() => {
                const panel = document.getElementById('panel-settings');
                const section = document.getElementById('settings-service-section');
                return !!panel?.classList.contains('active') && !!section && section.style.display !== 'none';
            }"""
        )
        reporter.add("ai-manga", "AI 漫剧服务设置跳转", "passed" if settings_active else "failed", f"settings_active={settings_active}")
    except Exception as exc:
        reporter.add("ai-manga", "AI 漫剧弱提示一致性", "failed", str(exc))


def test_effects_split_clip_export(page, reporter):
    try:
        open_group(page, "批量效果")
        open_link(page, "资源库")
        page.wait_for_timeout(1000)
        if page.locator("#effect_type option").count():
            page.locator('button:has-text("搜索资源")').click()
            page.wait_for_timeout(1500)
            reporter.add("effects", "资源库搜索", "passed", safe_text(page.locator("#resource_results"))[:200])
        else:
            reporter.add("effects", "资源库搜索", "failed", "未加载资源类型")
    except Exception as exc:
        reporter.add("effects", "资源库搜索", "failed", str(exc))

    try:
        open_group(page, "批量效果")
        open_link(page, "Duo 资源")
        page.wait_for_timeout(1500)
        page.locator('button:has-text("搜索 Duo 资源")').click()
        page.wait_for_timeout(1500)
        reporter.add("effects", "Duo 资源搜索", "passed", safe_text(page.locator("#duo_results"))[:200])
    except Exception as exc:
        reporter.add("effects", "Duo 资源搜索", "failed", str(exc))

    try:
        open_group(page, "批量分割")
        open_link(page, "文件分割")
        page.locator("#split_mode").select_option("silence")
        page.wait_for_timeout(300)
        silence_visible = visible(page.locator("#split_silence_db"))
        page.locator("#split_mode").select_option("subtitle")
        page.wait_for_timeout(300)
        subtitle_visible = visible(page.locator("#split_subtitle_path"))
        status = "passed" if silence_visible and subtitle_visible else "failed"
        reporter.add("split", "分割模式显隐", status, f"silence={silence_visible}, subtitle={subtitle_visible}")
    except Exception as exc:
        reporter.add("split", "分割模式显隐", "failed", str(exc))

    try:
        open_group(page, "片段微调")
        open_link(page, "节奏变速")
        page.locator('button:has-text("生成建议")').click()
        page.wait_for_timeout(1200)
        reporter.add("clip", "节奏变速建议", "passed", safe_text(page.locator("#clip_result"))[:200])
    except Exception as exc:
        reporter.add("clip", "节奏变速建议", "failed", str(exc))

    try:
        open_group(page, "批量导出")
        open_link(page, "导出设置")
        page.locator('button:has-text("生成导出计划")').click()
        page.wait_for_timeout(600)
        plan_text = safe_text(page.locator("#export_result"))
        reporter.add("export", "导出计划", "passed" if plan_text else "failed", plan_text[:200] or "未生成导出计划")
        open_link(page, "批量导出")
        page.locator('button:has-text("加入当前草稿")').click()
        page.wait_for_timeout(500)
        summary = safe_text(page.locator("#export_queue_summary"))
        reporter.add("export", "加入导出队列", "passed" if "已加入" in summary else "failed", summary)
    except Exception as exc:
        reporter.add("export", "导出能力", "failed", str(exc))


def test_settings_account(page, reporter):
    try:
        open_group(page, "软件设置")
        open_link(page, "工作台设置")
        page.locator("#saveSettingsBtn").click()
        page.wait_for_timeout(600)
        reporter.add("settings", "保存工作台设置", "passed", safe_text(page.locator("#settingsSaveMsg")) or safe_text(page.locator("#globalToast")))
    except Exception as exc:
        reporter.add("settings", "保存工作台设置", "failed", str(exc))

    try:
        open_link(page, "路径与目录")
        page.locator("#savePathSettingsBtn").click()
        page.wait_for_timeout(600)
        reporter.add("settings", "保存路径设置", "passed", safe_text(page.locator("#pathSettingsSaveMsg")) or safe_text(page.locator("#globalToast")))
    except Exception as exc:
        reporter.add("settings", "保存路径设置", "failed", str(exc))

    try:
        open_link(page, "AI 账号管理")
        page.wait_for_timeout(1000)
        provider_text = safe_text(page.locator("#ai_provider_list"))
        reporter.add("settings", "AI 账号管理服务加载", "passed" if provider_text and "登录后自动加载可用服务" not in provider_text else "failed", provider_text)
    except Exception as exc:
        reporter.add("settings", "AI 账号管理服务加载", "failed", str(exc))

    try:
        open_group(page, "账户中心")
        open_link(page, "账户信息")
        checkin_btn = page.locator("#dailyCheckinBtn")
        if checkin_btn.is_disabled():
            text = safe_text(checkin_btn) or safe_text(page.locator("#checkinActionMsg")) or "今天已签到"
            reporter.add("account", "每日签到", "passed", text)
        else:
            checkin_btn.click()
            page.wait_for_timeout(1200)
            msg = safe_text(page.locator("#checkinActionMsg")) or safe_text(page.locator("#globalToast"))
            reporter.add("account", "每日签到", "passed" if msg else "failed", msg or "未返回签到结果")
    except Exception as exc:
        reporter.add("account", "每日签到", "failed", str(exc))

    try:
        open_group(page, "账户中心")
        open_link(page, "授权激活")
        label = safe_text(page.locator('.sidebar-link[data-hard-section="account-license-section"]'))
        title = safe_text(page.locator("#account-license-section h3"))
        if label and title and label != title:
            reporter.add("account", "授权文案一致性", "warning", f"侧栏文案为“{label}”，正文标题为“{title}”")
        else:
            reporter.add("account", "授权文案一致性", "passed", f"{label} / {title}")
    except Exception as exc:
        reporter.add("account", "授权文案一致性", "failed", str(exc))


def test_admin(page, reporter):
    try:
        login_admin(page, reporter)
    except Exception as exc:
        reporter.add("admin-auth", "管理员登录", "failed", str(exc))
        return

    try:
        metrics = horizontal_overflow(page)
        reporter.add("admin-layout", "后台总览布局", "warning" if metrics["overflow"] else "passed", json.dumps(metrics, ensure_ascii=False))
    except Exception as exc:
        reporter.add("admin-layout", "后台总览布局", "failed", str(exc))

    sections = [
        ("站点管理", "site"),
        ("授权激活", "license"),
        ("CDK 管理", "cdk"),
        ("设备绑定", "bindings"),
        ("用户列表", "users"),
        ("生成记录", "logs"),
    ]
    for label, sec in sections:
        try:
            page.locator(f'#adminNav .admin-tab[data-section="{sec}"]').click()
            page.wait_for_timeout(800)
            reporter.add("admin-navigation", label, "passed", safe_text(page.locator(f"#section-{sec}"))[:200])
        except Exception as exc:
            reporter.add("admin-navigation", label, "failed", str(exc))

    try:
        page.locator('#adminNav .admin-tab[data-section="site"]').click()
        page.wait_for_timeout(500)
        page.locator("#saveSiteBtn").click()
        page.wait_for_timeout(800)
        reporter.add("admin-actions", "保存站点配置", "passed", safe_text(page.locator("#siteStatus")))
    except Exception as exc:
        reporter.add("admin-actions", "保存站点配置", "failed", str(exc))

    try:
        page.locator('#adminNav .admin-tab[data-section="license"]').click()
        page.wait_for_timeout(500)
        page.locator("#saveLicenseBtn").click()
        page.wait_for_timeout(800)
        reporter.add("admin-actions", "保存授权激活规则", "passed", safe_text(page.locator("#licenseStatus")))
    except Exception as exc:
        reporter.add("admin-actions", "保存授权激活规则", "failed", str(exc))

    try:
        page.locator('#adminNav .admin-tab[data-section="cdk"]').click()
        page.wait_for_timeout(800)
        page.locator("#cdk_card_type").fill("E2E测试卡")
        page.locator("#cdk_duration_days").fill("1")
        page.locator("#cdk_quantity").fill("1")
        page.locator("#cdkCreateBtn").click()
        page.wait_for_timeout(1200)
        hint = safe_text(page.locator("#cdkCreateHint"))
        reporter.add("admin-actions", "生成 CDK", "passed" if "成功" in hint or "批次" in hint else "failed", hint)
    except Exception as exc:
        reporter.add("admin-actions", "生成 CDK", "failed", str(exc))

    try:
        page.locator('#adminNav .admin-tab[data-section="users"]').click()
        page.wait_for_timeout(500)
        page.locator("#userSearchInput").fill(reporter.generated_user or REGULAR_USER)
        page.locator("#userSearchBtn").click()
        page.wait_for_timeout(1000)
        text = safe_text(page.locator("#userSearchTable"))
        reporter.add("admin-actions", "用户列表", "passed" if (reporter.generated_user in text or REGULAR_USER in text) else "failed", text[:200])
    except Exception as exc:
        reporter.add("admin-actions", "用户列表", "failed", str(exc))

    try:
        page.locator('#adminNav .admin-tab[data-section="logs"]').click()
        page.wait_for_timeout(800)
        hint = safe_text(page.locator("#logsHint"))
        reporter.add("admin-actions", "生成记录刷新", "passed", hint)
    except Exception as exc:
        reporter.add("admin-actions", "生成记录刷新", "failed", str(exc))


def check_user_navigation(page, reporter):
    navs = [
        ("智能助手", "命令中心", "panel-assistant"),
        ("批量混剪", "按组精准替换", "panel-materials"),
        ("批量混剪", "混剪裂变替换", "panel-materials"),
        ("批量混剪", "分区混剪裂变", "panel-materials"),
        ("AI 智做", "AI 成片", "panel-ai-make"),
        ("AI 智做", "AI 漫剧", "panel-ai-manga"),
        ("批量效果", "效果配置", "panel-effects"),
        ("批量效果", "资源库", "panel-effects"),
        ("批量效果", "Duo 资源", "panel-effects"),
        ("批量分割", "文件分割", "panel-split"),
        ("批量分割", "草稿处理", "panel-split"),
        ("批量分割", "批量查看", "panel-split"),
        ("片段微调", "AI 灵感", "panel-clip"),
        ("片段微调", "节奏变速", "panel-clip"),
        ("片段微调", "画面校正", "panel-clip"),
        ("片段微调", "摇晃关键帧", "panel-clip"),
        ("批量导出", "导出设置", "panel-export"),
        ("批量导出", "批量导出", "panel-export"),
        ("批量导出", "片段导出", "panel-export"),
        ("账户中心", "账户信息", "panel-account"),
        ("账户中心", "授权激活", "panel-account"),
        ("账户中心", "使用教程", "panel-account"),
        ("资源互换", "资源大厅", "panel-resource-exchange"),
        ("资源互换", "互换发布", "panel-resource-exchange"),
        ("软件设置", "工作台设置", "panel-settings"),
        ("软件设置", "路径与目录", "panel-settings"),
        ("软件设置", "AI 账号管理", "panel-settings"),
    ]
    for group, item, panel in navs:
        try:
            open_group(page, group)
            open_link(page, item)
            wait_panel_active(page, panel)
            metrics = horizontal_overflow(page)
            count = visible_control_count(page, f"#{panel}")
            reporter.add("user-navigation", f"{group} -> {item}", "warning" if metrics["overflow"] else "passed", f"{item} 打开成功，可见控件 {count} 个，横向溢出={metrics['overflow']}")
        except Exception as exc:
            reporter.add("user-navigation", f"{group} -> {item}", "failed", str(exc))


def test_manga(page, reporter):
    try:
        open_group(page, "AI 智做")
        open_link(page, "AI 漫剧")
        page.locator("#manga_project_name").fill(f"漫剧{int(time.time())}")
        page.locator("#manga_script").fill("1. 女主推门进入咖啡店\n2. 店员递上咖啡\n3. 女主停顿微笑看向窗外")
        page.locator("#manga_scene_duration").fill("2")
        page.locator("#manga_generate_btn").click()
        page.wait_for_function(
            """() => {
                const status = document.getElementById('manga_status')?.innerText || '';
                const result = document.getElementById('mangaDraftResult')?.innerText || '';
                return result.includes('草稿路径：') || status.includes('生成失败') || status.includes('已取消');
            }""",
            timeout=120000,
        )
        status = safe_text(page.locator("#manga_status"))
        result = safe_text(page.locator("#mangaDraftResult"))
        ok = "草稿路径" in result and ("已生成" in status or "场景目录" in result)
        reporter.add("ai-manga", "AI 漫剧生成", "passed" if ok else "failed", f"{status}\n{result[:260]}")
    except Exception as exc:
        reporter.add("ai-manga", "AI 漫剧生成", "failed", str(exc))


def test_ai_guidance_copy(page, reporter):
    try:
        open_group(page, "AI 智做")
        open_link(page, "AI 成片")
        intro_text = safe_text(page.locator("#panel-ai-make .module-sub")) + "\n" + safe_text(page.locator("#panel-ai-make .tool-result").first)
        intro_ok = "AI账号管理" in intro_text or "AI 账号管理" in intro_text
        reporter.add("ai-make", "AI 成片账号引导文案", "passed" if intro_ok else "failed", intro_text[:220])
    except Exception as exc:
        reporter.add("ai-make", "AI 成片弱提示一致性", "failed", str(exc))

    try:
        open_group(page, "AI 智做")
        open_link(page, "AI 漫剧")
        intro_text = safe_text(page.locator("#panel-ai-manga .module-sub")) + "\n" + safe_text(page.locator(".manga-intro-card"))
        intro_ok = ("剪映草稿" in intro_text and "场景" in intro_text and "素材目录" in intro_text)
        reporter.add("ai-manga", "AI 漫剧定位文案", "passed" if intro_ok else "failed", intro_text[:260])
        page.locator("#manga_script").fill("")
        page.locator("#manga_generate_btn").click()
        page.wait_for_timeout(500)
        status_text = safe_text(page.locator("#manga_status"))
        guidance_ok = "请先填写分镜脚本" in status_text
        reporter.add("ai-manga", "AI 漫剧弱提示一致性", "passed" if guidance_ok else "failed", status_text)
    except Exception as exc:
        reporter.add("ai-manga", "AI 漫剧弱提示一致性", "failed", str(exc))


def test_account_tutorial(page, reporter):
    try:
        open_group(page, "账户中心")
        open_link(page, "使用教程")
        page.locator("#accountTutorialSearch").fill("资源互换")
        page.wait_for_timeout(400)
        text = safe_text(page.locator("#accountTutorialList"))
        ok = "资源互换" in text and "免费功能" in text
        reporter.add("account", "使用教程搜索", "passed" if ok else "failed", text[:240])
    except Exception as exc:
        reporter.add("account", "使用教程搜索", "failed", str(exc))


def test_resource_exchange(page, reporter):
    try:
        open_group(page, "资源互换")
        open_link(page, "资源大厅")
        wait_panel_active(page, "panel-resource-exchange")
        board_text = safe_text(page.locator("#resourceExchangeList"))
        reporter.add("resource-exchange", "资源大厅打开", "passed", board_text[:220] or "资源大厅已打开")
    except Exception as exc:
        reporter.add("resource-exchange", "资源大厅打开", "failed", str(exc))
        return

    try:
        open_group(page, "资源互换")
        open_link(page, "互换发布")
        project_name = f"互换{int(time.time())}"[:15]
        reporter.resource_post_name = project_name
        page.locator("#resourceProjectName").fill(project_name)
        page.locator("#resourceProjectIntro").fill("剪映项目资源互换")
        page.locator("#resourceContact").fill(f"vx_{int(time.time())}")
        page.locator("#resourcePublishBtn").click()
        page.wait_for_timeout(1200)
        status_text = safe_text(page.locator("#resourcePublishStatus"))
        posts_text = safe_text(page.locator("#resourceMyPostsList"))
        ok = ("发布成功" in status_text) or (project_name in posts_text) or ("每天" in status_text)
        reporter.add("resource-exchange", "互换发布", "passed" if ok else "failed", f"{status_text}\n{posts_text[:220]}")
    except Exception as exc:
        reporter.add("resource-exchange", "互换发布", "failed", str(exc))


def test_admin_resource_review(page, reporter):
    try:
        page.locator('#adminNav .admin-tab[data-section="resource-review"]').click()
        page.wait_for_timeout(800)
        if reporter.resource_post_name:
            page.locator("#resourceReviewKeyword").fill(reporter.resource_post_name)
        elif reporter.generated_user:
            page.locator("#resourceReviewKeyword").fill(reporter.generated_user)
        page.locator("#resourceReviewSearchBtn").click()
        page.wait_for_timeout(1200)
        table_text = safe_text(page.locator("#resourceReviewTable"))
        matched = reporter.resource_post_name and reporter.resource_post_name in table_text
        if matched:
            buttons = page.locator('#resourceReviewTable button:has-text("通过")')
            if buttons.count():
                buttons.first.click()
                page.wait_for_timeout(1200)
                table_text = safe_text(page.locator("#resourceReviewTable"))
        ok = matched or (reporter.generated_user and reporter.generated_user in table_text)
        reporter.add("admin-actions", "审核发布", "passed" if ok else "failed", table_text[:260])
    except Exception as exc:
        reporter.add("admin-actions", "审核发布", "failed", str(exc))


def summarize(reporter):
    by_status = {}
    for item in reporter.results:
        by_status[item["status"]] = by_status.get(item["status"], 0) + 1
    return {
        "summary": by_status,
        "generated_user": reporter.generated_user,
        "results": reporter.results,
        "console_errors": reporter.console_errors[:50],
        "request_failures": reporter.request_failures[:50],
    }


def main():
    ensure_browser_regression_accounts()
    reporter = Reporter()
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(EDGE_CDP)
        try:
            user_context = browser.new_context(viewport={"width": 1440, "height": 1000})
            user_page = user_context.new_page()
            reporter.attach_page_watchers(user_page, "user")
            try:
                register_user(user_page, reporter)
            except Exception as exc:
                reporter.add("user-auth", "注册并自动登录", "failed", str(exc))
            try:
                if user_page.locator("#logoutBtn").count() and visible(user_page.locator("#logoutBtn")):
                    logout_user(user_page, reporter)
            except Exception as exc:
                reporter.add("user-auth", "退出登录", "failed", str(exc))
            try:
                login_user(user_page, REGULAR_USER, REGULAR_PASS, "user-auth", reporter)
                check_user_navigation(user_page, reporter)
                test_mix_generate(user_page, reporter)
                test_assistant(user_page, reporter)
                test_capture_removed(user_page, reporter)
                test_ai_make(user_page, reporter)
                test_manga(user_page, reporter)
                test_ai_guidance_copy(user_page, reporter)
                test_effects_split_clip_export(user_page, reporter)
                test_settings_account(user_page, reporter)
            except Exception as exc:
                reporter.add("user-flow", "常规用户巡检", "failed", str(exc))

            try:
                if user_page.locator("#logoutBtn").count() and visible(user_page.locator("#logoutBtn")):
                    logout_user(user_page, reporter)
                if reporter.generated_user:
                    user_page.evaluate(
                        """() => {
                            try { localStorage.removeItem('vf_token'); } catch (err) {}
                            try { sessionStorage.removeItem('vf_token'); } catch (err) {}
                        }"""
                    )
                    user_page.goto(f"{BASE_URL}/user", wait_until="domcontentloaded")
                    user_page.wait_for_load_state("networkidle")
                    login_user(user_page, reporter.generated_user, reporter.generated_pass, "user-auth", reporter)
                    test_account_tutorial(user_page, reporter)
                    test_resource_exchange(user_page, reporter)
                else:
                    reporter.add("user-flow", "新增用户资源互换巡检", "failed", "缺少新注册用户，无法继续资源互换链路")
            except Exception as exc:
                reporter.add("user-flow", "新增用户资源互换巡检", "failed", str(exc))
            user_context.close()

            admin_context = browser.new_context(viewport={"width": 1440, "height": 1000})
            admin_page = admin_context.new_page()
            reporter.attach_page_watchers(admin_page, "admin")
            test_admin(admin_page, reporter)
            test_admin_resource_review(admin_page, reporter)
            admin_context.close()
        finally:
            browser.close()

    print(json.dumps(summarize(reporter), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
