import json
import time
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError


BASE_URL = "http://127.0.0.1:5000"
EDGE_CDP = "http://127.0.0.1:9222"
REGULAR_USER = "codex_reg_user"
REGULAR_PASS = "Codex123!"
ADMIN_USER = "codex_reg_admin"
ADMIN_PASS = "Codex123!"
MATERIALS_DIR = r"E:\JianYingApi\VideoFactory\user_data\stage5_mix_materials"
MANGA_IMAGE = r"E:\JianYingApi\VideoFactory\user_data\dev_drafts\task_024c7651\cover.png"


class Reporter:
    def __init__(self):
        self.results = []
        self.console_errors = []
        self.request_failures = []
        self.generated_user = ""
        self.generated_pass = "Codex123!"

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
        ("用户检索", "users"),
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
        reporter.add("admin-actions", "用户检索", "passed" if (reporter.generated_user in text or REGULAR_USER in text) else "failed", text[:200])
    except Exception as exc:
        reporter.add("admin-actions", "用户检索", "failed", str(exc))

    try:
        page.locator('#adminNav .admin-tab[data-section="logs"]').click()
        page.wait_for_timeout(800)
        hint = safe_text(page.locator("#logsHint"))
        reporter.add("admin-actions", "生成记录刷新", "passed", hint)
    except Exception as exc:
        reporter.add("admin-actions", "生成记录刷新", "failed", str(exc))


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
                test_capture_removed(user_page, reporter)
                test_ai_make(user_page, reporter)
                test_manga(user_page, reporter)
                test_effects_split_clip_export(user_page, reporter)
                test_settings_account(user_page, reporter)
            except Exception as exc:
                reporter.add("user-flow", "常规用户巡检", "failed", str(exc))
            user_context.close()

            admin_context = browser.new_context(viewport={"width": 1440, "height": 1000})
            admin_page = admin_context.new_page()
            reporter.attach_page_watchers(admin_page, "admin")
            test_admin(admin_page, reporter)
            admin_context.close()
        finally:
            browser.close()

    print(json.dumps(summarize(reporter), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
