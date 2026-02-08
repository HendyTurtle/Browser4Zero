#!/usr/bin/env python3
"""
Browser4Zero - Lightweight Browser agent
Author: HendyTurtle =)
"""

import os
import sys
import json
import base64
import asyncio
import hashlib
import re
import time
from pathlib import Path
from typing import Dict, List, Optional, Any
from io import BytesIO

try:
    from patchright.async_api import async_playwright, Page, Browser, TimeoutError as PlaywrightTimeout
    from openai import AsyncOpenAI
    from dotenv import load_dotenv
    from PIL import Image
except ImportError:
    print("Error: Missing dependencies, run:")
    print("pip install patchright openai python-dotenv Pillow")
    print("patchright install chromium")
    sys.exit(1)


class Style:
    """极简 ANSI 样式工具"""
    RESET = '\033[0m'
    BOLD = '\033[1m'
    DIM = '\033[2m'
    
    # 前景色
    BLACK = '\033[30m'
    RED = '\033[31m'
    GREEN = '\033[32m'
    YELLOW = '\033[33m'
    BLUE = '\033[34m'
    MAGENTA = '\033[35m'
    CYAN = '\033[36m'
    WHITE = '\033[37m'
    
    # 背景色
    BG_BLACK = '\033[40m'
    BG_RED = '\033[41m'
    BG_GREEN = '\033[42m'
    BG_YELLOW = '\033[43m'
    BG_BLUE = '\033[44m'
    BG_MAGENTA = '\033[45m'
    BG_CYAN = '\033[46m'
    BG_WHITE = '\033[47m'
    
    @classmethod
    def text(cls, s: str, *codes: str) -> str:
        """给文本添加颜色/样式"""
        if not codes:
            return s
        return ''.join(codes) + s + cls.RESET
    
    @classmethod
    def header(cls, s: str, color: str = CYAN) -> str:
        """大标题"""
        return f"\n{cls.text(s, cls.BOLD, color)}"
    
    @classmethod
    def label(cls, text: str, color: str = BLUE) -> str:
        """标签样式，无方括号"""
        return cls.text(text, cls.BOLD, color)
    
    @classmethod
    def dim(cls, s: str) -> str:
        return cls.text(s, cls.DIM)
    
    @classmethod
    def step(cls, current: int) -> str:
        """步骤显示，只显示当前步数"""
        return f"\n{cls.text('Step', cls.BOLD, cls.BLUE)} {cls.text(str(current), cls.BOLD, cls.WHITE)}"
    
    @classmethod
    def action(cls, action_type: str, details: str = "") -> str:
        """操作显示"""
        badge = cls.text(action_type.upper(), cls.BOLD, cls.BLUE)
        if details:
            return f"{badge}  {cls.dim(details)}"
        return badge


class Browser4Zero:

    def __init__(self):
        load_dotenv()
        
        # Config
        self.api_base = os.getenv('OPENAI_API_BASE', 'https://api.openai.com/v1')
        self.api_key = os.getenv('OPENAI_API_KEY')
        self.model = os.getenv('OPENAI_MODEL', 'gpt-4o')
        self.headless = os.getenv('BROWSER_HEADLESS', 'false').lower() == 'true'
        self.max_steps = int(os.getenv('MAX_STEPS', '50'))
        self.screenshot_width = int(os.getenv('SCREENSHOT_WIDTH', '1280'))
        self.navigation_timeout = int(os.getenv('NAVIGATION_TIMEOUT', '30000'))
        self.action_timeout = int(os.getenv('ACTION_TIMEOUT', '10000'))
        
        if not self.api_key:
            raise ValueError("未设置 OPENAI_API_KEY")
        
        self.client = AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.api_base,
            timeout=60
        )
        
        # Runtime
        self.browser: Optional[Browser] = None
        self.page: Optional[Page] = None
        self.playwright = None
        
        # Vision state
        self.vision_enabled = os.getenv('VISION_ENABLED', 'false').lower() == 'true'
        self.vision_fail_count = 0
        self.vision_cooldown_until = 0
        
        # Detect loops
        self.state_hashes: List[str] = []
        
        # Cache
        self.current_elements: List[Dict] = []
        
        # Load helper
        self.helper_js = self._load_helper_js()
    
    def _load_helper_js(self) -> str:
        js_path = Path(__file__).parent / 'page_helper.js'
        if not js_path.exists():
            raise FileNotFoundError(f"Can't find page_helper.js: {js_path}")
        return js_path.read_text(encoding='utf-8')
    
    async def _launch_browser(self):
        """Launches the browser with patchright stealth configuration"""
        self.playwright = await async_playwright().start()

        # launch args
        launch_args = [
            '--no-first-run',
            '--no-default-browser-check',
            '--disable-blink-features=AutomationControlled',
        ]

        try:
            # try to use Chrome, best stealth
            self.browser = await self.playwright.chromium.launch(
                headless=self.headless,
                channel='chrome',
                args=launch_args
            )
        except Exception:
            # Fallback to chromium if not available
            print(f"   {Style.dim('Chrome not found, using Chromium')} (install Chrome for better stealth)")
            self.browser = await self.playwright.chromium.launch(
                headless=self.headless,
                args=launch_args
            )

        context = await self.browser.new_context(
            viewport={'width': self.screenshot_width, 'height': 720},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.0',
            locale='zh-CN',
            timezone_id='Asia/Shanghai',
            permissions=['notifications'],
            color_scheme='light',
            has_touch=False,
        )
        context.set_default_timeout(self.action_timeout)
        context.set_default_navigation_timeout(self.navigation_timeout)

        self.page = await context.new_page()
        
        # 监听新页面打开，自动切换到新标签页
        context.on('page', self._on_new_page)
    
    async def _on_new_page(self, page):
        """当有新标签页打开时，自动切换到新页面"""
        print(f"   {Style.label('New Tab', Style.CYAN)} Auto-switched")
        self.page = page
        await page.wait_for_load_state('domcontentloaded')
        await asyncio.sleep(0.5)
    
    async def _ensure_helper(self) -> bool:
        """Ensure the helper is there every loop"""
        try:
            exists = await self.page.evaluate('typeof window.__AGENT__ !== "undefined"')
            if exists:
                return True
        except:
            pass
        
        # Inject
        for attempt in range(3):
            try:
                await self.page.evaluate(self.helper_js)
                
                # 劫持所有可能打开新标签页的方式，强制在当前页打开
                await self.page.evaluate('''
                    (() => {
                        // 1. 劫持 window.open，强制在当前窗口打开
                        const originalOpen = window.open;
                        window.open = function(url, target, features) {
                            if (url) {
                                window.location.href = url;
                            }
                            return window;
                        };
                        
                        // 2. 劫持所有带 target 的链接，改为在当前页打开
                        function fixTargetElements(root) {
                            // 处理链接
                            root.querySelectorAll && root.querySelectorAll('a[target]').forEach(el => {
                                const original = el.getAttribute('target');
                                if (original && !['_self', '_top'].includes(original)) {
                                    el.removeAttribute('target');
                                    el.setAttribute('data-original-target', original);
                                }
                            });
                            
                            // 处理表单
                            root.querySelectorAll && root.querySelectorAll('form[target]').forEach(el => {
                                const original = el.getAttribute('target');
                                if (original && !['_self', '_top'].includes(original)) {
                                    el.removeAttribute('target');
                                    el.setAttribute('data-original-target', original);
                                }
                            });
                            
                            // 处理 base 标签的 target
                            const base = document.querySelector('base[target]');
                            if (base) {
                                base.removeAttribute('target');
                            }
                        }
                        
                        // 3. 监听点击事件，拦截新窗口打开
                        document.addEventListener('click', (e) => {
                            const el = e.target.closest('a[target]');
                            if (el) {
                                const target = el.getAttribute('target');
                                if (target && !['_self', '_top'].includes(target)) {
                                    e.preventDefault();
                                    const href = el.getAttribute('href');
                                    if (href) {
                                        window.location.href = href;
                                    }
                                }
                            }
                        }, true);
                        
                        // 4. 劫持表单提交，防止新窗口
                        document.addEventListener('submit', (e) => {
                            const form = e.target;
                            const target = form.getAttribute('target');
                            if (target && !['_self', '_top'].includes(target)) {
                                form.removeAttribute('target');
                            }
                        }, true);
                        
                        // 5. 处理当前页面已有的元素
                        fixTargetElements(document);
                        
                        // 6. 监听新添加的元素
                        const observer = new MutationObserver(mutations => {
                            mutations.forEach(mutation => {
                                mutation.addedNodes.forEach(node => {
                                    if (node.nodeType === Node.ELEMENT_NODE) {
                                        fixTargetElements(node);
                                        if (node.tagName === 'BASE' && node.target) {
                                            node.removeAttribute('target');
                                        }
                                    }
                                });
                            });
                        });
                        observer.observe(document.documentElement, { childList: true, subtree: true });
                        
                        // 7. 劫持其他打开新窗口的方式
                        // 防止使用 <area target="...">
                        if (window.HTMLAreaElement) {
                            const areaDesc = Object.getOwnPropertyDescriptor(HTMLAreaElement.prototype, 'target');
                            if (areaDesc) {
                                Object.defineProperty(HTMLAreaElement.prototype, 'target', {
                                    get: areaDesc.get,
                                    set: function(val) {
                                        if (val && !['_self', '_top'].includes(val)) {
                                            val = '_self';
                                        }
                                        return areaDesc.set.call(this, val);
                                    }
                                });
                            }
                        }
                    })();
                ''')
                
                exists = await self.page.evaluate('typeof window.__AGENT__ !== "undefined"')
                if exists:
                    return True
            except Exception as e:
                if attempt < 2:
                    await asyncio.sleep(0.3)
        
        return False
    
    async def _wait_for_stable(self, timeout_ms: int = 2000):
        """Wait until the page is stable"""
        try:
            await self.page.wait_for_load_state('networkidle', timeout=timeout_ms)
        except:
            pass
        await asyncio.sleep(0.3)
    
    async def _safe_goto(self, url: str) -> Dict[str, Any]:
        """Go to page"""
        print(f"   {Style.label('URL', Style.BLUE)} {Style.dim(url[:100])}...")
        
        try:
            await self.page.goto(url, wait_until='domcontentloaded')
            await self._wait_for_stable()
            return {'success': True, 'message': f'已导航到 {url[:50]}'}
        except PlaywrightTimeout:
            # Partially loaded
            await asyncio.sleep(1)
            return {'success': True, 'message': f'导航超时但页面可能已加载: {url[:50]}'}
        except Exception as e:
            return {'success': False, 'message': f'导航失败: {str(e)[:100]}'}
    
    async def _get_page_state(self, mark: bool = True) -> Dict[str, Any]:
        """Get the state of the page"""
        # make sure helper is there
        if not await self._ensure_helper():
            return {
                'url': self.page.url,
                'title': await self.page.title(),
                'elements': [],
                'pageText': '',
                'error': 'Helper 注入失败'
            }
        
        try:
            state = await self.page.evaluate('window.__AGENT__.analyze()')
        except Exception as e:
            return {
                'url': self.page.url,
                'title': await self.page.title(),
                'elements': [],
                'pageText': '',
                'error': f'分析失败: {str(e)[:100]}'
            }
        
        # Cache the elements
        self.current_elements = state.get('elements', [])
        
        # Mark
        if mark and self.current_elements:
            try:
                await self.page.evaluate('window.__AGENT__.mark()')
                await asyncio.sleep(0.2)
            except:
                pass
        
        # Screenshot
        state['screenshot'] = None
        if self.vision_enabled and self.vision_fail_count < 3:
            try:
                state['screenshot'] = await self._take_screenshot()
                self.vision_fail_count = 0
            except Exception as e:
                self.vision_fail_count += 1
                print(f"   {Style.label('Warn', Style.YELLOW)} Screenshot failed ({self.vision_fail_count}/3): {Style.dim(str(e)[:50])}")
        
        # get text
        try:
            state['pageText'] = await self.page.evaluate('window.__AGENT__.getReadableText(5000)')
        except:
            state['pageText'] = ''
        
        # remove mark
        if mark:
            try:
                await self.page.evaluate('window.__AGENT__.unmark()')
            except:
                pass
        
        return state
    
    async def _take_screenshot(self) -> str:
        """Screenshot and zoom"""
        data = await self.page.screenshot(type='jpeg', quality=60)
        img = Image.open(BytesIO(data))
        
        # Zoom
        max_dim = 1024
        if max(img.size) > max_dim:
            ratio = max_dim / max(img.size)
            img = img.resize((int(img.width * ratio), int(img.height * ratio)), Image.Resampling.LANCZOS)
        
        buf = BytesIO()
        img.convert('RGB').save(buf, format='JPEG', quality=50, optimize=True)
        return base64.b64encode(buf.getvalue()).decode()
    
    def _get_element_desc(self, index: int) -> str:
        """Gets a natural element description"""
        if not self.current_elements or index < 1 or index > len(self.current_elements):
            return f"[{index}] (未知元素)"
        
        el = self.current_elements[index - 1]
        tag = el.get('tag', '?')
        text = el.get('text', '')[:30]
        
        desc = f"[{index}] {tag}"
        if text:
            desc += f' "{text}"'
        return desc
    
    async def _get_element_locator(self, index: int):
        """Get element locator with playwright"""
        if index < 1 or index > len(self.current_elements):
            return None
        
        el = self.current_elements[index - 1]
        selector = el.get('selector')
        
        if not selector:
            return None
        
        try:
            locator = self.page.locator(selector).first
            # Check if it actually exists
            if await locator.count() > 0:
                return locator
        except:
            pass
        
        return None
    
    async def _execute_action(self, action: Dict) -> Dict[str, Any]:
        """Execute actions"""
        action_type = action.get('type')
        index = action.get('index')
        value = action.get('value', '')
        
        try:
            # === Nav stuff ===
            if action_type == 'goto':
                url = action.get('url', '')
                if not url:
                    return {'success': False, 'message': '缺少 url 参数'}
                return await self._safe_goto(url)
            
            elif action_type == 'back':
                await self.page.go_back(wait_until='domcontentloaded')
                await self._wait_for_stable()
                return {'success': True, 'message': '已后退'}
            
            elif action_type == 'forward':
                await self.page.go_forward(wait_until='domcontentloaded')
                await self._wait_for_stable()
                return {'success': True, 'message': '已前进'}
            
            elif action_type == 'refresh':
                await self.page.reload(wait_until='domcontentloaded')
                await self._wait_for_stable()
                return {'success': True, 'message': '已刷新'}
            
            elif action_type == 'wait':
                seconds = min(action.get('seconds', 2), 10)
                await asyncio.sleep(seconds)
                return {'success': True, 'message': f'已等待 {seconds} 秒'}
            
            # === Elemnt interactions ===
            elif action_type == 'click':
                locator = await self._get_element_locator(index)
                if not locator:
                    return {'success': False, 'message': f'元素 {index} 不存在'}
                
                await locator.scroll_into_view_if_needed()
                await locator.click(timeout=self.action_timeout)
                await self._wait_for_stable()
                return {'success': True, 'message': f'已点击 {self._get_element_desc(index)}'}
            
            elif action_type == 'fill':
                locator = await self._get_element_locator(index)
                if not locator:
                    return {'success': False, 'message': f'元素 {index} 不存在'}
                
                await locator.scroll_into_view_if_needed()
                await locator.fill(value, timeout=self.action_timeout)
                return {'success': True, 'message': f'已输入到 {self._get_element_desc(index)}'}
            
            elif action_type == 'type':
                # Type one character at a time
                locator = await self._get_element_locator(index)
                if not locator:
                    return {'success': False, 'message': f'元素 {index} 不存在'}
                
                await locator.scroll_into_view_if_needed()
                await locator.click()
                await locator.press_sequentially(value, delay=50)
                return {'success': True, 'message': f'已键入到 {self._get_element_desc(index)}'}
            
            elif action_type == 'clear':
                locator = await self._get_element_locator(index)
                if not locator:
                    return {'success': False, 'message': f'元素 {index} 不存在'}
                
                await locator.clear()
                return {'success': True, 'message': f'已清空 {self._get_element_desc(index)}'}
            
            elif action_type == 'select':
                locator = await self._get_element_locator(index)
                if not locator:
                    return {'success': False, 'message': f'元素 {index} 不存在'}
                
                await locator.select_option(label=value, timeout=self.action_timeout)
                return {'success': True, 'message': f'已选择 "{value}"'}
            
            elif action_type == 'check':
                locator = await self._get_element_locator(index)
                if not locator:
                    return {'success': False, 'message': f'元素 {index} 不存在'}
                
                await locator.check(timeout=self.action_timeout)
                return {'success': True, 'message': f'已勾选 {self._get_element_desc(index)}'}
            
            elif action_type == 'uncheck':
                locator = await self._get_element_locator(index)
                if not locator:
                    return {'success': False, 'message': f'元素 {index} 不存在'}
                
                await locator.uncheck(timeout=self.action_timeout)
                return {'success': True, 'message': f'已取消勾选 {self._get_element_desc(index)}'}
            
            elif action_type == 'hover':
                locator = await self._get_element_locator(index)
                if not locator:
                    return {'success': False, 'message': f'元素 {index} 不存在'}
                
                await locator.hover(timeout=self.action_timeout)
                return {'success': True, 'message': f'已悬停在 {self._get_element_desc(index)}'}
            
            elif action_type == 'focus':
                locator = await self._get_element_locator(index)
                if not locator:
                    return {'success': False, 'message': f'元素 {index} 不存在'}
                
                await locator.focus()
                return {'success': True, 'message': f'已聚焦 {self._get_element_desc(index)}'}
            
            elif action_type == 'scrollTo':
                locator = await self._get_element_locator(index)
                if not locator:
                    return {'success': False, 'message': f'元素 {index} 不存在'}
                
                await locator.scroll_into_view_if_needed()
                return {'success': True, 'message': f'已滚动到 {self._get_element_desc(index)}'}
            
            # === Global actions ===
            elif action_type == 'press':
                key = action.get('key', 'Enter')
                await self.page.keyboard.press(key)
                await self._wait_for_stable()
                return {'success': True, 'message': f'已按 {key}'}
            
            elif action_type == 'scroll':
                direction = action.get('direction', 'down')
                amount = action.get('amount', 500)
                
                if direction == 'down':
                    await self.page.mouse.wheel(0, amount)
                elif direction == 'up':
                    await self.page.mouse.wheel(0, -amount)
                elif direction == 'right':
                    await self.page.mouse.wheel(amount, 0)
                elif direction == 'left':
                    await self.page.mouse.wheel(-amount, 0)
                
                await asyncio.sleep(0.3)
                return {'success': True, 'message': f'已向{direction}滚动'}
            
            elif action_type == 'done':
                result = action.get('result', '任务完成')
                return {'success': True, 'done': True, 'result': result}
            
            else:
                return {'success': False, 'message': f'未知操作: {action_type}'}
        
        except PlaywrightTimeout:
            return {'success': False, 'message': f'操作超时: {action_type}'}
        except Exception as e:
            return {'success': False, 'message': f'操作失败: {str(e)[:100]}'}
    
    def _compute_state_hash(self, state: Dict) -> str:
        """Compute hask for loop detection"""
        key_data = {
            'url': state.get('url', ''),
            'element_count': len(state.get('elements', [])),
            'text_hash': hashlib.md5(state.get('pageText', '')[:500].encode()).hexdigest()[:8]
        }
        return hashlib.md5(json.dumps(key_data).encode()).hexdigest()[:16]
    
    def _detect_loop(self, current_hash: str) -> Optional[str]:
        """Detects loop & reminds the agent"""
        self.state_hashes.append(current_hash)
        
        # Only keep recent ones
        if len(self.state_hashes) > 10:
            self.state_hashes = self.state_hashes[-10:]
        
        # Check for duplicate actions.
        if len(self.state_hashes) >= 5:
            if self.state_hashes[-1] == self.state_hashes[-2] == self.state_hashes[-3]:
                return "LOOP DETECTED: 连续3步页面状态完全相同！你必须尝试本质不同的操作（换URL、换策略、或用done结束）。如果这是误判（例如操作确实需要重复执行），请忽略并继续执行。"
        
        return None
    
    def _format_elements(self, elements: List[Dict]) -> str:
        """Elements list"""
        if not elements:
            return "（无可交互元素）"
        
        lines = []
        for el in elements[:40]:
            idx = el['index']
            tag = el['tag']
            text = el.get('text', '')[:35]
            rect = el.get('rect', {})
            state = el.get('state', {})
            
            line = f"[{idx}] {tag}"
            if text:
                line += f' "{text}"'
            
            # Location
            if rect:
                line += f" @({rect.get('x',0)},{rect.get('y',0)})"
            
            # State
            state_parts = []
            if state.get('value'):
                state_parts.append(f'value="{state["value"][:15]}"')
            if state.get('checked'):
                state_parts.append('[x]')
            if state.get('disabled'):
                state_parts.append('disabled')
            if state_parts:
                line += f" [{', '.join(state_parts)}]"
            
            lines.append(line)
        
        if len(elements) > 100:
            lines.append(f"... 还有 {len(elements) - 100} 个元素")
        
        return '\n'.join(lines)
    
    def _build_system_prompt(self) -> str:
        return """你是一个浏览器自动化代理。你通过元素列表和截图感知网页，通过执行操作与网页交互。

## 操作指令

每步输出一个 JSON（不要 markdown 包裹）：
```
{"thought": "你的思考", "action": {...}}
```

### 元素操作（需要 index）
- 点击: {"type": "click", "index": N}
- 输入（清空后输入）: {"type": "fill", "index": N, "value": "文本"}
- 逐字键入: {"type": "type", "index": N, "value": "文本"}
- 清空: {"type": "clear", "index": N}
- 下拉选择: {"type": "select", "index": N, "value": "选项文本"}
- 勾选/取消: {"type": "check", "index": N} / {"type": "uncheck", "index": N}
- 悬停: {"type": "hover", "index": N}
- 滚动到元素: {"type": "scrollTo", "index": N}

### 全局操作
- 按键: {"type": "press", "key": "Enter"}（支持 Enter/Tab/Escape/ArrowDown 等）
- 滚动: {"type": "scroll", "direction": "down"}（up/down/left/right）
- 导航: {"type": "goto", "url": "https://..."}
- 后退: {"type": "back"}
- 刷新: {"type": "refresh"}
- 等待: {"type": "wait", "seconds": 2}

### 结束
- 完成: {"type": "done", "result": "详细描述结果"}

## 元素列表格式
[index] 标签 "文本" @(x,y) [状态]

## 核心原则

1. **搜索必须按回车**：在搜索框输入后，必须 {"type": "press", "key": "Enter"} 提交

2. **观察变化**：执行操作后观察页面是否真的变了。没变化就换方法。

3. **避免循环**：如果你收到"连续N步无变化"警告，必须：
   - 换一个完全不同的URL
   - 或用 done 结束并说明原因
   - 绝不能继续做相同的事

4. **索引可能变化**：页面更新后元素索引会重新编号，始终参考当前列表。

5. **具体结果**：done 时给出具体信息，不要只说"完成了"。

6. **持久完成**：面对复杂多步骤任务，保持耐心。不要中途轻易放弃，充分尝试可用的路径和方法。

## 常见流程

搜索：goto 搜索引擎 → fill 搜索框 → press Enter → 阅读结果 → click 链接
表单：逐个 fill 字段 → click 提交按钮
弹窗：优先找"关闭""×""接受"按钮点击"""

    def _build_user_message(self, state: Dict, task: str, step: int, loop_warning: Optional[str] = None) -> Any:
        """Build user message"""
        parts = [
            f"## 步骤 {step}",
            f"任务: {task}",
            "",
            f"URL: {state.get('url', 'N/A')}",
            f"标题: {state.get('title', 'N/A')}",
        ]
        
        if loop_warning:
            parts.append("")
            parts.append(loop_warning)
        
        if state.get('error'):
            parts.append(f"\n[Error] {state['error']}")
        
        parts.append(f"\n### 元素列表 ({len(state.get('elements', []))}个)")
        parts.append(self._format_elements(state.get('elements', [])))
        
        parts.append("\n### 页面文本")
        text = state.get('pageText', '')[:800]
        parts.append(text if text else "(无文本)")
        
        parts.append("\n---\n请分析并执行下一步。")
        
        text_content = '\n'.join(parts)
        
        # With screenshot
        if state.get('screenshot'):
            return [
                {'type': 'image_url', 'image_url': {'url': f"data:image/jpeg;base64,{state['screenshot']}", 'detail': 'low'}},
                {'type': 'text', 'text': text_content}
            ]
        return text_content
    
    async def _call_llm(self, messages: List[Dict]) -> Dict:
        """Call LLM"""
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.5,
                max_tokens=600
            )
            
            content = response.choices[0].message.content.strip()
            
            # Decode JSON
            content = re.sub(r'^```json\s*', '', content)
            content = re.sub(r'\s*```$', '', content)
            
            match = re.search(r'\{.*\}', content, re.DOTALL)
            if match:
                content = match.group(0)
            
            data = json.loads(content)
            
            if 'action' not in data:
                raise ValueError("Missing action")
            
            return data
        
        except json.JSONDecodeError as e:
            print(f"   {Style.label('Error', Style.RED)} JSON Decode Error")
            raise
        except Exception as e:
            raise
    
    async def run(self, task: str, start_url: Optional[str] = None) -> str:
        """Run the task"""
        try:
            print(Style.header('Browser4Zero', Style.CYAN))
            print(f"  {Style.dim('Launching browser...')}")
            await self._launch_browser()
            
            if start_url:
                result = await self._safe_goto(start_url)
                print(f"   {result['message']}")
            
            # 任务显示
            print(f"\n{Style.label('Task', Style.MAGENTA)} {task}\n")
            
            # Messages
            messages = [{'role': 'system', 'content': self._build_system_prompt()}]
            
            self.state_hashes = []
            
            for step in range(1, self.max_steps + 1):
                # 步骤显示
                print(Style.step(step))
                
                # Get state
                state = await self._get_page_state()
                
                # 状态栏
                url = state.get('url', 'N/A')[:65]
                elems = len(state.get('elements', []))
                print(f"  {Style.label('URL', Style.BLUE)} {url}")
                print(f"  {Style.label('Elements', Style.GREEN)} {elems}")
                
                # Loop detection
                state_hash = self._compute_state_hash(state)
                loop_warning = self._detect_loop(state_hash)
                if loop_warning:
                    print(f"\n  {Style.label('Warning', Style.YELLOW)} {loop_warning}")
                
                # Build messages
                user_msg = self._build_user_message(state, task, step, loop_warning)
                messages.append({'role': 'user', 'content': user_msg})
                
                # LLM
                try:
                    response = await self._call_llm(messages)
                    thought = response.get('thought', '')
                    action = response.get('action', {})
                    
                    # 思考
                    print(f"\n  {Style.label('Think', Style.MAGENTA)} {Style.dim(thought[:70])}")
                    
                    # 操作
                    action_type = action.get('type', 'unknown')
                    action_json = json.dumps(action, ensure_ascii=False)
                    print(f"  {Style.action(action_type, action_json)}")
                    
                except Exception as e:
                    print(f"\n  {Style.label('Error', Style.RED)} LLM call failed: {e}")
                    # Append model response AND system note
                    messages.append({'role': 'assistant', 'content': response.get('content', "")})
                    messages.append({'role': 'user', 'content': '错误：你的上一次响应不是合法的 JSON 或缺少 "action" 字段，操作未被执行。请重新输出仅包含合法、符合要求的 JSON 回复，不要附加任何多余文本；若反复失败，请换一种方法完成任务。'})
                    continue
                
                messages.append({'role': 'assistant', 'content': json.dumps(response, ensure_ascii=False)})
                
                result = await self._execute_action(action)
                
                # 结果显示
                success = result.get('success', False)
                status_label = Style.label('OK', Style.GREEN) if success else Style.label('Fail', Style.RED)
                msg = result.get('message', 'unknown')
                print(f"  {status_label} {msg}")
                
                result_msg = f"Result: {result.get('message', 'unknown')}"
                if not success:
                    result_msg = f"Failed: {result_msg}"
                messages.append({'role': 'user', 'content': result_msg})
                
                if result.get('done'):
                    final_result = result.get('result', 'Task completed')
                    print(f"\n{Style.label('Done', Style.GREEN)} Step {step}")
                    print(f"{final_result}")
                    return final_result
            
            return f"Max steps reached ({self.max_steps})"
        
        finally:
            if self.browser:
                await self.browser.close()
            if self.playwright:
                await self.playwright.stop()


async def main():
    import argparse
    
    parser = argparse.ArgumentParser()
    parser.add_argument('task', nargs='?')
    parser.add_argument('--url')
    parser.add_argument('-i', '--interactive', action='store_true')
    
    args = parser.parse_args()
    agent = Browser4Zero()
    
    if args.interactive or not args.task:
        # 欢迎界面
        print(Style.header('Browser4Zero', Style.CYAN))
        print(f"  {Style.dim('Lightweight Browser Agent')}")
        print(f"  {Style.dim('by HendyTurtle')}\n")
        print(f"  {Style.dim('Commands: q=quit, <task>=what to do')}")
        
        while True:
            try:
                prompt = f"\n{Style.label('Input', Style.CYAN)} What to do? "
                task = input(prompt).strip()
                if task.lower() in ['q', 'quit', 'exit']:
                    print(f"\n{Style.dim('Goodbye!')}")
                    break
                if not task:
                    continue
                
                url_prompt = f"{Style.label('Input', Style.CYAN)} Start URL (Enter to skip): "
                url = input(url_prompt).strip() or None
                
                result = await agent.run(task, url)
                
            except KeyboardInterrupt:
                print(f"\n\n{Style.dim('Interrupted. Goodbye!')}")
                break
            except Exception as e:
                print(f"\n{Style.label('Error', Style.RED)} {e}")
                import traceback
                traceback.print_exc()
    else:
        result = await agent.run(args.task, args.url)
        print(f"\n{Style.label('Result', Style.GREEN)}\n{result}")


if __name__ == '__main__':
    asyncio.run(main())