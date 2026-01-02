import asyncio
import json
from pathlib import Path
from playwright.async_api import async_playwright

class BrowserAuth:
    """Handles browser-based authentication for Hinatazaka46 Message."""
    
    @staticmethod
    async def login(headless: bool = False, user_data_dir: str = None, channel: str = None):
        """
        Launches browser for login and captures tokens.
        If user_data_dir is set, uses persistent context to save session.
        If channel is provided (e.g. 'chrome'), uses that browser executable.
        Returns dict with cookies and access_token.
        """
        async with async_playwright() as p:
            print("[*] Launching browser...")
            
            if user_data_dir:
                user_data_path = Path(user_data_dir).absolute()
                user_data_path.mkdir(parents=True, exist_ok=True)
                
                context = await p.chromium.launch_persistent_context(
                    user_data_dir=user_data_path,
                    headless=headless,
                    channel=channel,
                    args=[
                        '--disable-blink-features=AutomationControlled',
                        '--no-sandbox',
                        '--disable-setuid-sandbox',
                        '--disable-infobars',
                        '--disable-gpu',
                        '--disable-dev-shm-usage',
                        '--disable-software-rasterizer',
                    ],
                    viewport={'width': 1280, 'height': 800},
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                )
                page = context.pages[0] if context.pages else await context.new_page()
            else:
                browser = await p.chromium.launch(
                    headless=headless,
                    channel=channel,
                    args=[
                        '--disable-blink-features=AutomationControlled',
                        '--no-sandbox',
                        '--disable-infobars',
                    ]
                )
                context = await browser.new_context(
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    viewport={'width': 1280, 'height': 800}
                )
                page = await context.new_page()
            
            # Stealth script
            await context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
            """)
            
            # Token capture container
            captured_data = {}
            token_future = asyncio.Future()

            async def handle_response(response):
                if token_future.done(): return
                
                request = response.request
                if 'api.message.hinatazaka46.com' in request.url and response.status == 200:
                    headers = request.headers
                    auth = headers.get('authorization') or headers.get('Authorization')
                    
                    if auth and 'Bearer' in auth:
                        token = auth.split('Bearer ')[1]
                        if token:
                            captured_data['access_token'] = token
                            # Capture App ID and UA to impersonate browser perfectly
                            captured_data['x-talk-app-id'] = headers.get('x-talk-app-id') or headers.get('X-Talk-App-ID')
                            captured_data['user-agent'] = headers.get('user-agent') or headers.get('User-Agent')
                            token_future.set_result(True)

            page.on("response", handle_response)
            
            try:
                await page.goto('https://message.hinatazaka46.com/', timeout=60000)
            except Exception as e:
                pass # Nav error
            
            try:
                # Wait for token capture (timeout 5 mins for interactive, 30s for headless/cached)
                timeout = 300 if not headless else 45
                await asyncio.wait_for(token_future, timeout=timeout)
                print("[+] Token captured!")
                
                # Get cookies
                cookies = await context.cookies()
                captured_data['cookies'] = {c['name']: c['value'] for c in cookies}
                
                # Cleanup
                if user_data_dir:
                    await context.close()
                else:
                    await browser.close()
                    
                return captured_data
                
            except asyncio.TimeoutError:
                print("[!] Login timed out.")
                if user_data_dir: await context.close()
                else: await browser.close()
                return None
            except Exception as e:
                print(f"[!] Error: {e}")
                if user_data_dir: await context.close()
                else: await browser.close()
                return None
