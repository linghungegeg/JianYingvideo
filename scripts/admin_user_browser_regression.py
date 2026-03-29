import json
import sys
import time
import uuid
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright
from werkzeug.security import generate_password_hash

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app import create_app
from app.extensions import db
from app.models.cdk_code import CdkCode
from app.models.user import User
from app.models.user_quota import UserQuota
from app.models.user_token import UserToken
from app.views.api import _ensure_user_ref_code


BASE_URL = "http://127.0.0.1:5000"
EDGE_CDP = "http://127.0.0.1:9222"
_RUN_SUFFIX = uuid.uuid4().hex[:8]
USER_NAME = f"codex_reg_user_{_RUN_SUFFIX}"
USER_PASS = "Codex123!"
ADMIN_NAME = f"codex_reg_admin_{_RUN_SUFFIX}"
ADMIN_PASS = "Codex123!"


def expect(condition, message):
    if not condition:
        raise SystemExit(message)


def ensure_user(username, password, role):
    user = User.query.filter_by(username=username).first()
    if not user:
        user = User(username=username, role=role)
    else:
        user.role = role
    user.password_hash = generate_password_hash(password)
    db.session.add(user)
    db.session.commit()
    _ensure_user_ref_code(user, commit=True)
    return user


def cleanup_accounts_and_codes(codes):
    codes = [code for code in (codes or []) if code]
    if codes:
        CdkCode.query.filter(CdkCode.code.in_(codes)).delete(synchronize_session=False)
    users = User.query.filter(User.username.in_([USER_NAME, ADMIN_NAME])).all()
    if users:
        user_ids = [user.id for user in users]
        UserToken.query.filter(UserToken.user_id.in_(user_ids)).delete(synchronize_session=False)
        UserQuota.query.filter(UserQuota.user_id.in_(user_ids)).delete(synchronize_session=False)
        User.query.filter(User.id.in_(user_ids)).delete(synchronize_session=False)
    if codes or users:
        db.session.commit()


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
    agreement = page.locator("#loginAgreementCheck")
    if agreement.count() and not agreement.is_checked():
        agreement.check()
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
    expect(visible_groups and set(visible_groups) == {group_name}, f"{panel_selector} visible groups mismatch: {visible_groups}")


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
    try:
        page = context.new_page()
        page.goto(f"{BASE_URL}/admin", wait_until="domcontentloaded")
        page.wait_for_load_state("networkidle")
        hidden = login_via_modal(page, USER_NAME, USER_PASS, "adminAuthModal")
        message = (page.locator("#authMsg").text_content() or "").strip()
        result = {"modal_hidden": hidden, "auth_msg": message}
        expect(hidden != "true", "non-admin user should not enter /admin")
        expect(bool(message), "non-admin block message missing")
        return result
    finally:
        context.close()


def check_admin_console(browser):
    context = browser.new_context(viewport={"width": 1440, "height": 1000})
    try:
        page = context.new_page()
        page.goto(f"{BASE_URL}/admin", wait_until="domcontentloaded")
        page.wait_for_load_state("networkidle")
        hidden = login_via_modal(page, ADMIN_NAME, ADMIN_PASS, "adminAuthModal")
        expect(hidden == "true", "admin login did not unlock /admin")

        overview_stats = page.locator("#overviewStats .stat").count()
        overflow = page_overflow(page)

        open_admin_section(page, "site")
        page.locator("#saveSiteBtn").click()
        page.wait_for_timeout(1200)
        site_status = (page.locator("#siteStatus").text_content() or "").strip()

        open_admin_section(page, "license")
        license_value = page.locator("#default_user_quota").input_value()
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
        created_code = ""
        rows = page.locator("#cdkTable tr")
        if rows.count():
            created_code = (rows.first.locator("td").nth(0).text_content() or "").strip()

        open_admin_section(page, "users")
        page.locator("#userSearchInput").fill(ADMIN_NAME)
        page.locator("#userSearchBtn").click()
        page.wait_for_timeout(1200)
        user_search_rows = page.locator("#userSearchTable tr").count()

        result = {
            "overview_stats": overview_stats,
            "overflow": overflow,
            "site_status": site_status,
            "license_status": license_status,
            "license_value": license_value,
            "cdk_hint": cdk_hint,
            "user_search_rows": user_search_rows,
            "created_code": created_code,
        }

        expect(overview_stats >= 1, f"overview stats not rendered: {overview_stats}")
        expect(overflow["pageOverflowX"] <= 1, f"admin page horizontal overflow: {overflow}")
        expect(bool(site_status), f"site save did not respond: {site_status}")
        expect(bool(license_status), f"license save did not respond: {license_status}")
        expect(license_value != "", f"default user quota not rendered: {license_value}")
        expect(bool(cdk_hint), f"cdk create did not respond: {cdk_hint}")
        expect(user_search_rows >= 1, f"user search returned no rows: {user_search_rows}")
        return result
    finally:
        context.close()


def check_user_workspace(browser):
    context = browser.new_context(viewport={"width": 1440, "height": 1000})
    try:
        page = context.new_page()
        page.goto(f"{BASE_URL}/user", wait_until="domcontentloaded")
        page.wait_for_load_state("networkidle")
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

        open_sidebar_group(page, "软件设置")
        open_sidebar_link(page, "AI 账号管理")
        provider_text = wait_text_not_contains(page, "#ai_provider_list", "登录后自动加载可用服务")

        open_sidebar_group(page, "账户中心")
        open_sidebar_link(page, "使用教程")
        tutorial_title = (page.locator("#account-tutorial-section h3").text_content() or "").strip()

        open_sidebar_group(page, "资源互换")
        open_sidebar_link(page, "资源大厅")
        resource_board_text = (page.locator("#resourceExchangeList").text_content() or "").strip()

        result = {
            "overflow": overflow,
            "provider_text": provider_text,
            "tutorial_title": tutorial_title,
            "resource_board_text": resource_board_text,
        }

        expect(overflow["pageOverflowX"] <= 1, f"user page horizontal overflow: {overflow}")
        expect(provider_text and "登录后自动加载可用服务" not in provider_text, f"provider list not loaded: {provider_text}")
        expect("使用教程" in tutorial_title, f"tutorial section missing: {tutorial_title}")
        expect(bool(resource_board_text), "resource exchange board did not render")
        return result
    finally:
        context.close()


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    app = create_app()
    created_codes = []
    with app.app_context():
        ensure_user(USER_NAME, USER_PASS, "user")
        ensure_user(ADMIN_NAME, ADMIN_PASS, "admin")

    report = {}
    try:
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(EDGE_CDP)
            try:
                report["admin_non_admin_gate"] = check_non_admin_block(browser)
                report["admin"] = check_admin_console(browser)
                if report["admin"].get("created_code"):
                    created_codes.append(report["admin"]["created_code"])
                report["user"] = check_user_workspace(browser)
            finally:
                browser.close()
    finally:
        with app.app_context():
            cleanup_accounts_and_codes(created_codes)

    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except PlaywrightTimeoutError as exc:
        raise SystemExit(f"playwright timeout: {exc}")
