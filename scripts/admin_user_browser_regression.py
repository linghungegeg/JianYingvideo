import json
import re
import sys
import time

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


BASE_URL = "http://127.0.0.1:5000"
EDGE_CDP = "http://127.0.0.1:9222"
USER_NAME = "codex_reg_user"
USER_PASS = "Codex123!"
ADMIN_NAME = "codex_reg_admin"
ADMIN_PASS = "Codex123!"


def expect(condition, message):
    if not condition:
        raise SystemExit(message)


def visible(locator):
    try:
        return locator.is_visible()
    except Exception:
        return False


def page_overflow(page):
    return page.evaluate(
        """() => ({
            pageOverflowX: document.documentElement.scrollWidth - document.documentElement.clientWidth,
            pageOverflowY: document.documentElement.scrollHeight - document.documentElement.clientHeight
        })"""
    )


def login_via_modal(page, username, password, modal_id):
    page.locator("#loginAccount").fill(username)
    page.locator("#loginPassword").fill(password)
    page.locator("#loginForm button[type='submit']").click()
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(600)
    return page.locator(f"#{modal_id}").get_attribute("aria-hidden")


def open_admin_section(page, section):
    page.locator(f"#adminNav .admin-tab[data-section='{section}']").click()
    page.wait_for_timeout(700)


def open_sidebar_group(page, label):
    button = page.locator(".sidebar-parent", has_text=label).first
    expect(button.count(), f"missing sidebar group: {label}")
    button.click()
    page.wait_for_timeout(250)


def open_sidebar_link(page, label):
    link = page.locator(".sidebar-link", has_text=label).first
    expect(link.count(), f"missing sidebar link: {label}")
    if not visible(link):
        parent = link.locator("xpath=ancestor::div[contains(@class,'sidebar-group')]").locator(".sidebar-parent")
        if parent.count():
            parent.first.click()
            page.wait_for_timeout(250)
    link.click()
    page.wait_for_timeout(450)


def assert_only_group_visible(page, panel_selector, group_name):
    visible_groups = page.evaluate(
        """(panelSelector) => {
            const panel = document.querySelector(panelSelector);
            if (!panel) return [];
            return Array.from(panel.querySelectorAll('[data-subtab-group]'))
                .filter((node) => getComputedStyle(node).display !== 'none')
                .map((node) => node.getAttribute('data-subtab-group') || '');
        }""",
        panel_selector,
    )
    expect(
        visible_groups and set(visible_groups) == {group_name},
        f"{panel_selector} visible groups mismatch: {visible_groups}",
    )


def wait_text_not_contains(page, selector, bad_text, timeout_ms=10000):
    end = time.time() + timeout_ms / 1000
    while time.time() < end:
        text = (page.locator(selector).text_content() or "").strip()
        if text and bad_text not in text:
            return text
        time.sleep(0.2)
    return (page.locator(selector).text_content() or "").strip()


def check_non_admin_block(browser):
    context = browser.new_context(viewport={"width": 1440, "height": 1000})
    page = context.new_page()
    page.goto(f"{BASE_URL}/admin", wait_until="domcontentloaded")
    page.wait_for_load_state("networkidle")
    hidden = login_via_modal(page, USER_NAME, USER_PASS, "adminAuthModal")
    message = (page.locator("#authMsg").text_content() or "").strip()
    result = {
        "modal_hidden": hidden,
        "auth_msg": message,
    }
    expect(hidden != "true", "non-admin user should not enter /admin")
    expect("管理员" in message or "当前账号不是管理员" in message, "non-admin block message missing")
    context.close()
    return result


def check_admin_console(browser):
    context = browser.new_context(viewport={"width": 1440, "height": 1000})
    page = context.new_page()
    page.goto(f"{BASE_URL}/admin", wait_until="domcontentloaded")
    page.wait_for_load_state("networkidle")
    auth_tabs = page.locator("#adminAuthModal .auth-tab").count()
    register_form_count = page.locator("#registerForm").count()
    hidden = login_via_modal(page, ADMIN_NAME, ADMIN_PASS, "adminAuthModal")
    expect(hidden == "true", "admin login did not unlock /admin")

    overview_stats = page.locator("#overviewStats .stat").count()
    action_buttons = page.locator(".admin-actions .btn").all_text_contents()
    overflow = page_overflow(page)
    layout_metrics = page.evaluate(
        """() => {
            const container = document.querySelector('.admin-body .container');
            const layout = document.querySelector('.admin-layout');
            const sidebar = document.querySelector('.admin-sidebar');
            const pagebar = document.querySelector('.admin-pagebar');
            return {
                viewportWidth: document.documentElement.clientWidth,
                containerWidth: Math.round(container?.getBoundingClientRect().width || 0),
                layoutGap: parseFloat(getComputedStyle(layout).gap || '0'),
                sidebarWidth: Math.round(sidebar?.getBoundingClientRect().width || 0),
                pagebarHeight: Math.round(pagebar?.getBoundingClientRect().height || 0)
            };
        }"""
    )

    open_admin_section(page, "site")
    site_fields = [
        "site_name",
        "site_title",
        "site_keywords",
        "site_description",
        "workspace_title",
        "workspace_subtitle",
        "login_title",
        "login_subtitle",
        "locked_title",
        "locked_subtitle",
        "admin_title",
        "admin_subtitle",
    ]
    original_site = {field: page.locator(f"#{field}").input_value() for field in site_fields}
    page.locator("#saveSiteBtn").click()
    page.wait_for_timeout(1200)
    site_status = (page.locator("#siteStatus").text_content() or "").strip()
    preview_count = page.locator("#sitePreviewGrid .site-preview-item").count()

    open_admin_section(page, "license")
    license_values = {
        field: page.locator(f"#{field}").input_value()
        for field in [
            "license_offline_hours",
            "license_transfer_cooldown_hours",
            "license_code_length",
            "license_points_ratio",
            "manga_generate_cost",
            "daily_checkin_reward",
        ]
    }
    page.locator("#saveLicenseBtn").click()
    page.wait_for_timeout(1200)
    license_status = (page.locator("#licenseStatus").text_content() or "").strip()

    open_admin_section(page, "cdk")
    test_card_type = f"QA-{int(time.time())}"
    page.locator("#cdk_card_type").fill(test_card_type)
    page.locator("#cdk_duration_days").fill("1")
    page.locator("#cdk_quantity").fill("1")
    page.locator("#cdk_bonus_points").fill("0")
    page.locator("#cdk_device_limit").fill("1")
    page.locator("#cdk_transfer_times").fill("0")
    page.locator("#cdk_redeem_days").fill("0")
    page.locator("#cdkCreateBtn").click()
    page.wait_for_timeout(1800)
    cdk_hint = (page.locator("#cdkCreateHint").text_content() or "").strip()
    batch_match = re.search(r"批次\\s+([0-9a-fA-F]+)", cdk_hint)
    created_batch = batch_match.group(1) if batch_match else ""
    if created_batch:
        page.locator("#cdk_filter_batch").fill(created_batch)
        page.locator("#cdkRefreshBtn").click()
        page.wait_for_timeout(1200)
    cdk_rows = page.locator("#cdkTable tr").count()
    first_code = ""
    if cdk_rows:
        first_code = (page.locator("#cdkTable tr").first.locator("td").nth(0).text_content() or "").strip()
    if first_code:
        page.locator("#cdkTable tr").first.locator("button").click()
        page.wait_for_timeout(1200)

    open_admin_section(page, "bindings")
    bindings_rows = page.locator("#bindingsTable tr").count()

    open_admin_section(page, "users")
    page.locator("#userSearchInput").fill(ADMIN_NAME)
    page.locator("#userSearchBtn").click()
    page.wait_for_timeout(1200)
    user_search_rows = page.locator("#userSearchTable tr").count()
    user_search_hint = (page.locator("#userSearchHint").text_content() or "").strip()

    open_admin_section(page, "logs")
    logs_rows = page.locator("#logsTable tr").count()
    logs_hint = (page.locator("#logsHint").text_content() or "").strip()

    result = {
        "overview_stats": overview_stats,
        "action_buttons": action_buttons,
        "overflow": overflow,
        "layout_metrics": layout_metrics,
        "auth_tabs": auth_tabs,
        "register_form_count": register_form_count,
        "site_status": site_status,
        "preview_count": preview_count,
        "license_values": license_values,
        "license_status": license_status,
        "cdk_hint": cdk_hint,
        "cdk_rows": cdk_rows,
        "created_batch": created_batch,
        "bindings_rows": bindings_rows,
        "user_search_rows": user_search_rows,
        "user_search_hint": user_search_hint,
        "logs_rows": logs_rows,
        "logs_hint": logs_hint,
        "site_labels": page.locator("#section-site label").all_text_contents(),
        "nav_labels": page.locator("#adminNav .admin-tab").all_text_contents(),
    }

    expect(overview_stats >= 4, f"overview stats not rendered: {overview_stats}")
    expect(action_buttons == ["退出后台"], f"unexpected admin actions: {action_buttons}")
    expect(overflow["pageOverflowX"] <= 1, f"admin page horizontal overflow: {overflow}")
    expect(auth_tabs == 0, f"admin auth modal should not expose tabs: {auth_tabs}")
    expect(register_form_count == 0, f"admin auth modal should not expose register form: {register_form_count}")
    expect(layout_metrics["containerWidth"] >= 1390, f"admin container still too narrow: {layout_metrics}")
    expect(layout_metrics["sidebarWidth"] >= 300, f"admin sidebar still too narrow: {layout_metrics}")
    expect(layout_metrics["pagebarHeight"] >= 150, f"admin pagebar still too compressed: {layout_metrics}")
    expect("保存" in site_status, f"site save did not succeed: {site_status}")
    expect(preview_count == 4, f"site preview count mismatch: {preview_count}")
    expect("保存" in license_status, f"license save did not succeed: {license_status}")
    expect("成功" in cdk_hint, f"cdk create did not succeed: {cdk_hint}")
    expect(user_search_rows >= 1, f"user search returned no rows: {user_search_hint}")
    expect(logs_rows >= 1, "logs section returned no rows")

    context.close()
    return result


def check_user_workspace(browser):
    context = browser.new_context(viewport={"width": 1440, "height": 1000})
    page = context.new_page()
    page.goto(f"{BASE_URL}/user", wait_until="domcontentloaded")
    page.wait_for_load_state("networkidle")
    before_login = page.evaluate(
        """() => ({
            title: document.title,
            lockedTitle: document.getElementById('lockedTitle')?.innerText || '',
            loginTitle: document.getElementById('loginBrandTitle')?.innerText || ''
        })"""
    )
    hidden = login_via_modal(page, USER_NAME, USER_PASS, "authModal")
    expect(hidden == "true", "user login did not unlock /user")

    overflow = page_overflow(page)
    open_sidebar_group(page, "批量导出")
    assert_only_group_visible(page, "#panel-export", "export-settings")
    open_sidebar_link(page, "批量导出")
    assert_only_group_visible(page, "#panel-export", "export-batch")
    open_sidebar_link(page, "片段导出")
    assert_only_group_visible(page, "#panel-export", "export-segments")

    open_sidebar_group(page, "批量分割")
    assert_only_group_visible(page, "#panel-split", "split-file")
    open_sidebar_link(page, "草稿处理")
    assert_only_group_visible(page, "#panel-split", "split-draft")
    open_sidebar_link(page, "批量查看")
    assert_only_group_visible(page, "#panel-split", "split-batch")

    open_sidebar_group(page, "片段微调")
    assert_only_group_visible(page, "#clipToolsGrid", "clip-ai")
    open_sidebar_link(page, "节奏变速")
    assert_only_group_visible(page, "#clipToolsGrid", "clip-rhythm")
    open_sidebar_link(page, "画面校正")
    assert_only_group_visible(page, "#clipToolsGrid", "clip-transform")
    open_sidebar_link(page, "摇晃关键帧")
    assert_only_group_visible(page, "#clipToolsGrid", "clip-shake")

    open_sidebar_group(page, "软件设置")
    open_sidebar_link(page, "AI 账号管理")
    provider_text = wait_text_not_contains(page, "#ai_provider_list", "登录后自动加载可用服务。")
    provider_options = page.locator("#ai_provider_select option").all_text_contents()

    result = {
        "before_login": before_login,
        "overflow": overflow,
        "provider_text": provider_text,
        "provider_options": provider_options,
        "workspace_title": (page.locator("#workspaceTitle").text_content() or "").strip(),
        "workspace_subtitle": (page.locator("#workspaceSubtitle").text_content() or "").strip(),
    }

    expect(overflow["pageOverflowX"] <= 1, f"user page horizontal overflow: {overflow}")
    expect(provider_text and "登录后自动加载可用服务。" not in provider_text, f"provider list not loaded: {provider_text}")
    expect(provider_options and provider_options[0].strip(), f"provider select not loaded: {provider_options}")

    context.close()
    return result


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    report = {}
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(EDGE_CDP)
        try:
            report["admin_non_admin_gate"] = check_non_admin_block(browser)
            report["admin"] = check_admin_console(browser)
            report["user"] = check_user_workspace(browser)
        finally:
            browser.close()
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except PlaywrightTimeoutError as exc:
        raise SystemExit(f"playwright timeout: {exc}")
