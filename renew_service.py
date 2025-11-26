import os
import time
import sys
import random
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
# 引入反指纹插件
from playwright_stealth import stealth_sync

# --- 全局配置 ---
HIDENCLOUD_COOKIE = os.environ.get('HIDENCLOUD_COOKIE')
HIDENCLOUD_EMAIL = os.environ.get('HIDENCLOUD_EMAIL')
HIDENCLOUD_PASSWORD = os.environ.get('HIDENCLOUD_PASSWORD')

BASE_URL = "https://dash.hidencloud.com"
LOGIN_URL = f"{BASE_URL}/auth/login"
SERVICE_URL = f"{BASE_URL}/service/71879/manage"
COOKIE_NAME = "remember_web_59ba36addc2b2f9401580f014c7f58ea4e30989d"

def log(message):
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}", flush=True)

def handle_cloudflare(page):
    """
    终极版 Cloudflare 处理逻辑：
    结合了 XVFB 环境，我们可以更自信地等待验证通过。
    """
    iframe_selector = 'iframe[src*="challenges.cloudflare.com"]'
    
    # 检测是否存在验证框
    if page.locator(iframe_selector).count() == 0:
        return True

    log("⚠️ 检测到 Cloudflare 验证，开始对抗...")
    start_time = time.time()
    
    while time.time() - start_time < 45:
        try:
            # 再次检查是否已经通过（iframe 消失）
            if page.locator(iframe_selector).count() == 0:
                log("✅ Cloudflare 验证已通过！")
                return True

            frame = page.frame_locator(iframe_selector)
            checkbox = frame.locator('input[type="checkbox"]')
            
            # 如果复选框可见，则执行拟人化点击
            if checkbox.is_visible():
                box = checkbox.bounding_box()
                if box:
                    log("定位到验证框，执行拟人移动点击...")
                    # 移动鼠标稍微随机一点
                    x = box['x'] + box['width'] / 2 + random.uniform(-10, 10)
                    y = box['y'] + box['height'] / 2 + random.uniform(-10, 10)
                    page.mouse.move(x, y, steps=20)
                    time.sleep(random.uniform(0.2, 0.5))
                    page.mouse.down()
                    time.sleep(random.uniform(0.1, 0.2))
                    page.mouse.up()
                else:
                    checkbox.click()
                
                # 点击后，给一点时间让它转圈
                log("已点击，等待验证反应...")
                time.sleep(5)
            else:
                # 有时候复选框不可见是在加载中，或者已经是在转圈了
                log("验证框存在但复选框不可见，可能正在验证中，等待...")
                time.sleep(2)

        except Exception as e:
            pass # 忽略过程中的小错误，持续尝试
            
        time.sleep(1)

    log("❌ Cloudflare 验证长时间未通过。")
    return False

def login(page):
    log("开始登录流程...")
    
    if HIDENCLOUD_COOKIE:
        log("尝试 Cookie 登录...")
        try:
            page.context.add_cookies([{
                'name': COOKIE_NAME, 'value': HIDENCLOUD_COOKIE,
                'domain': 'dash.hidencloud.com', 'path': '/',
                'expires': int(time.time()) + 3600 * 24 * 365,
                'httpOnly': True, 'secure': True, 'sameSite': 'Lax'
            }])
            page.goto(SERVICE_URL, wait_until="domcontentloaded", timeout=60000)
            handle_cloudflare(page)
            
            if "auth/login" not in page.url:
                log("✅ Cookie 登录成功！")
                return True
            log("Cookie 失效，转为密码登录。")
            page.context.clear_cookies()
        except:
            pass

    if not HIDENCLOUD_EMAIL or not HIDENCLOUD_PASSWORD:
        return False

    log("尝试账号密码登录...")
    try:
        page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
        handle_cloudflare(page)
        
        page.fill('input[name="email"]', HIDENCLOUD_EMAIL)
        page.fill('input[name="password"]', HIDENCLOUD_PASSWORD)
        
        handle_cloudflare(page)
        page.click('button[type="submit"]:has-text("Sign in to your account")')
        
        # 登录后可能强制验证
        time.sleep(2)
        handle_cloudflare(page)
        
        page.wait_for_url(f"{BASE_URL}/dashboard", timeout=60000)
        log("✅ 账号密码登录成功！")
        return True
    except Exception as e:
        log(f"❌ 登录失败: {e}")
        page.screenshot(path="login_fail.png")
        return False

def renew_service(page):
    try:
        log("开始续费...")
        if page.url != SERVICE_URL:
            page.goto(SERVICE_URL, wait_until="domcontentloaded", timeout=60000)
        
        handle_cloudflare(page)

        log("点击 'Renew'...")
        page.locator('button:has-text("Renew")').click()
        time.sleep(2) # 稍作等待

        log("点击 'Create Invoice'...")
        # 这里是关键点，点击后 Cloudflare 可能会拦截
        create_btn = page.locator('button:has-text("Create Invoice")')
        create_btn.wait_for(state="visible", timeout=10000)
        create_btn.click()
        
        # --- 监控发票生成 & 拦截 ---
        log("等待发票生成 (含 Cloudflare 监控)...")
        new_invoice_url = None
        
        # 定义一个简单的重试循环
        for i in range(40):
            # 1. 检查 URL 是否变化（成功跳转）
            if "/payment/invoice/" in page.url:
                new_invoice_url = page.url
                log(f"🎉 页面跳转成功: {new_invoice_url}")
                break
            
            # 2. 检查是否出现 Cloudflare 拦截
            # 在点击 Create Invoice 后，如果页面没动，很可能弹出了验证码
            handle_cloudflare(page)
            
            time.sleep(1)
            
        if not new_invoice_url:
            log("❌ 未能获取发票 URL，可能被拦截或超时。")
            page.screenshot(path="renew_stuck.png")
            return False

        # 如果 URL 变了但没跳转（极少情况），手动跳
        if page.url != new_invoice_url:
            page.goto(new_invoice_url)

        log("点击 'Pay'...")
        pay_btn = page.locator('a:has-text("Pay"):visible, button:has-text("Pay"):visible').first
        pay_btn.wait_for(state="visible", timeout=30000)
        pay_btn.click()
        
        log("✅ 续费动作完成。")
        time.sleep(5)
        return True

    except Exception as e:
        log(f"❌ 续费异常: {e}")
        page.screenshot(path="renew_error.png")
        return False

def main():
    if not HIDENCLOUD_COOKIE and not (HIDENCLOUD_EMAIL and HIDENCLOUD_PASSWORD):
        sys.exit(1)

    with sync_playwright() as p:
        try:
            log("启动浏览器 (Headless=False + XVFB)...")
            # 关键：这里设置为 headless=False，因为我们有 XVFB
            browser = p.chromium.launch(
                headless=False, 
                args=['--no-sandbox', '--disable-blink-features=AutomationControlled']
            )
            context = browser.new_context(viewport={'width': 1280, 'height': 960})
            page = context.new_page()
            
            # 激活隐身模式插件
            stealth_sync(page)

            if not login(page):
                sys.exit(1)

            if not renew_service(page):
                sys.exit(1)

            log("🎉 任务全部完成！")
        except Exception as e:
            log(f"💥 严重错误: {e}")
            sys.exit(1)
        finally:
            if 'browser' in locals() and browser:
                browser.close()

if __name__ == "__main__":
    main()
