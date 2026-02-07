/**
 * Browser-Use Agent - Page Helper (修复版)
 * 专注于页面分析和元素标注，操作执行交给 Playwright
 */
(function() {
    'use strict';

    // 防止重复注入
    if (window.__AGENT__) {
        return window.__AGENT__;
    }

    // 全局状态
    let elements = [];
    let overlays = new Map();
    let isMarked = false;

    // 颜色池
    const COLORS = [
        '#FF6B6B', '#4ECDC4', '#45B7D1', '#96CEB4', 
        '#FECA57', '#FF9FF3', '#54A0FF', '#5F27CD',
        '#00D2D3', '#FF9F43', '#C44569', '#F8B500',
        '#2ED573', '#FFA502', '#FF6348', '#7BED9F'
    ];

    /**
     * 生成稳定的CSS选择器（优先使用稳定属性）
     */
    function generateSelector(element) {
        // 优先：ID
        if (element.id && !element.id.match(/^[0-9]/) && !element.id.includes(':')) {
            const escaped = CSS.escape(element.id);
            if (document.querySelectorAll(`#${escaped}`).length === 1) {
                return `#${escaped}`;
            }
        }

        // 次优先：name 属性（表单元素）
        const name = element.getAttribute('name');
        if (name) {
            const selector = `${element.tagName.toLowerCase()}[name="${CSS.escape(name)}"]`;
            if (document.querySelectorAll(selector).length === 1) {
                return selector;
            }
        }

        // 次优先：data-testid 等测试属性
        for (const attr of ['data-testid', 'data-test-id', 'data-cy', 'data-test']) {
            const val = element.getAttribute(attr);
            if (val) {
                const selector = `[${attr}="${CSS.escape(val)}"]`;
                if (document.querySelectorAll(selector).length === 1) {
                    return selector;
                }
            }
        }

        // 次优先：aria-label
        const ariaLabel = element.getAttribute('aria-label');
        if (ariaLabel && ariaLabel.length < 50) {
            const selector = `${element.tagName.toLowerCase()}[aria-label="${CSS.escape(ariaLabel)}"]`;
            if (document.querySelectorAll(selector).length === 1) {
                return selector;
            }
        }

        // 后备：路径选择器
        const path = [];
        let current = element;
        let depth = 0;

        while (current && current.nodeType === Node.ELEMENT_NODE && depth < 5) {
            let selector = current.tagName.toLowerCase();
            
            // 添加有意义的类名（过滤动态类）
            if (current.className && typeof current.className === 'string') {
                const classes = current.className.trim().split(/\s+/)
                    .filter(c => c && 
                        !c.match(/^[a-z]{1,2}-/) &&  // 过滤 hash 类名如 sc-xxx
                        !c.match(/^\d/) &&
                        !c.match(/active|hover|focus|selected|open|show|hide/i) &&
                        c.length < 30
                    );
                if (classes.length > 0) {
                    selector += '.' + classes.slice(0, 2).map(c => CSS.escape(c)).join('.');
                }
            }

            // 添加 nth-child
            if (current.parentNode) {
                const siblings = Array.from(current.parentNode.children)
                    .filter(el => el.tagName === current.tagName);
                if (siblings.length > 1) {
                    const index = siblings.indexOf(current) + 1;
                    selector += `:nth-of-type(${index})`;
                }
            }

            path.unshift(selector);
            
            // 如果已经唯一，停止
            const testSelector = path.join(' > ');
            if (document.querySelectorAll(testSelector).length === 1) {
                return testSelector;
            }

            current = current.parentNode;
            depth++;
        }

        return path.join(' > ');
    }

    /**
     * 获取元素类型标识
     */
    function getElementType(element) {
        const tag = element.tagName.toLowerCase();
        const type = element.type ? element.type.toLowerCase() : '';
        const role = element.getAttribute('role');
        
        if (role) return `${tag}[${role}]`;
        if (type && !['submit', 'button'].includes(type)) return `${tag}[${type}]`;
        return tag;
    }

    /**
     * 获取元素标签文本
     */
    function getElementLabel(element) {
        // aria-label
        const ariaLabel = element.getAttribute('aria-label');
        if (ariaLabel) return ariaLabel.trim();

        // aria-labelledby
        const ariaLabelledBy = element.getAttribute('aria-labelledby');
        if (ariaLabelledBy) {
            const labelEl = document.getElementById(ariaLabelledBy);
            if (labelEl) return labelEl.textContent.trim();
        }

        // label[for]
        if (element.id) {
            const label = document.querySelector(`label[for="${CSS.escape(element.id)}"]`);
            if (label) return label.textContent.trim();
        }

        // 常用属性
        for (const attr of ['title', 'alt', 'placeholder', 'value']) {
            const val = element.getAttribute(attr) || element[attr];
            if (val && typeof val === 'string' && val.trim() && val.length < 100) {
                return val.trim();
            }
        }

        // 文本内容
        const text = element.textContent?.trim();
        if (text && text.length < 100) return text;

        return '';
    }

    /**
     * 获取元素可用操作
     */
    function getElementActions(element) {
        const tag = element.tagName.toLowerCase();
        const type = element.type ? element.type.toLowerCase() : '';
        const role = element.getAttribute('role');
        const contentEditable = element.getAttribute('contenteditable');
        
        const actions = ['click'];

        // 文本输入
        if ((tag === 'input' && ['text', 'password', 'email', 'search', 'url', 'tel', 'number', ''].includes(type)) ||
            tag === 'textarea' ||
            contentEditable === 'true' || contentEditable === '') {
            actions.push('fill', 'clear');
        }

        // 选择框
        if (tag === 'select') {
            actions.push('select');
        }

        // 复选框/单选框
        if (type === 'checkbox' || type === 'radio' || role === 'checkbox' || role === 'radio') {
            actions.push('check', 'uncheck');
        }

        // 文件上传
        if (type === 'file') {
            actions.push('upload');
        }

        return actions;
    }

    /**
     * 获取元素状态
     */
    function getElementState(element) {
        const state = {};

        if (element.value !== undefined && element.value !== '') {
            state.value = element.value.substring(0, 100);
        }

        if (element.type === 'checkbox' || element.type === 'radio') {
            state.checked = element.checked;
        }

        if (element.tagName.toLowerCase() === 'select' && element.selectedIndex >= 0) {
            state.selected = element.options[element.selectedIndex]?.text || '';
        }

        const ariaExpanded = element.getAttribute('aria-expanded');
        if (ariaExpanded !== null) {
            state.expanded = ariaExpanded === 'true';
        }

        if (element.disabled || element.getAttribute('aria-disabled') === 'true') {
            state.disabled = true;
        }

        if (element.readOnly) {
            state.readonly = true;
        }

        return state;
    }

    /**
     * 检查元素是否可见且可交互
     */
    function isElementInteractive(element, rect, style) {
        // 零尺寸
        if (rect.width < 5 || rect.height < 5) return false;
        
        // 不可见
        if (style.visibility === 'hidden') return false;
        if (style.display === 'none') return false;
        if (parseFloat(style.opacity) < 0.1) return false;
        
        // 禁用指针事件
        if (style.pointerEvents === 'none') {
            // 但保留某些可能需要展示的元素
            const tag = element.tagName.toLowerCase();
            if (!['input', 'button', 'a', 'select', 'textarea'].includes(tag)) {
                return false;
            }
        }

        // 在视口范围内（带 buffer）
        const buffer = 50;
        if (rect.bottom < -buffer) return false;
        if (rect.top > window.innerHeight + buffer) return false;
        if (rect.right < -buffer) return false;
        if (rect.left > window.innerWidth + buffer) return false;

        return true;
    }

    /**
     * 收集所有交互元素
     */
    function collectInteractiveElements(root = document) {
        const selectors = [
            'a[href]', 
            'button', 
            'input:not([type="hidden"])', 
            'textarea', 
            'select',
            '[onclick]', 
            '[role="button"]', 
            '[role="link"]', 
            '[role="menuitem"]',
            '[role="tab"]', 
            '[role="option"]', 
            '[role="checkbox"]', 
            '[role="radio"]',
            '[role="switch"]',
            '[role="slider"]', 
            '[role="textbox"]', 
            '[role="combobox"]',
            '[role="searchbox"]',
            '[role="listbox"]',
            '[tabindex]:not([tabindex="-1"])',
            '[contenteditable="true"]', 
            '[contenteditable=""]',
            'summary',
            'details',
            'audio[controls]', 
            'video[controls]'
        ];

        const seen = new Set();
        const validElements = [];

        const allElements = root.querySelectorAll(selectors.join(','));

        for (const el of allElements) {
            // 跳过已处理
            if (seen.has(el)) continue;
            seen.add(el);

            // 跳过我们自己的元素
            if (el.classList.contains('__agent_overlay__') || 
                el.classList.contains('__agent_label__')) {
                continue;
            }

            try {
                const rect = el.getBoundingClientRect();
                const style = window.getComputedStyle(el);

                if (!isElementInteractive(el, rect, style)) continue;

                const selector = generateSelector(el);
                
                validElements.push({
                    element: el,
                    selector: selector,
                    rect: {
                        x: Math.round(rect.left),
                        y: Math.round(rect.top),
                        width: Math.round(rect.width),
                        height: Math.round(rect.height)
                    },
                    center: {
                        x: Math.round(rect.left + rect.width / 2),
                        y: Math.round(rect.top + rect.height / 2)
                    },
                    tag: getElementType(el),
                    text: getElementLabel(el),
                    actions: getElementActions(el),
                    state: getElementState(el)
                });
            } catch (e) {
                // 忽略异常元素
            }
        }

        return validElements;
    }

    /**
     * 分析页面
     */
    function analyze() {
        elements = collectInteractiveElements();

        // 按视觉位置排序：从上到下，从左到右
        elements.sort((a, b) => {
            const rowDiff = Math.floor(a.rect.y / 50) - Math.floor(b.rect.y / 50);
            if (rowDiff !== 0) return rowDiff;
            return a.rect.x - b.rect.x;
        });

        const result = {
            url: window.location.href,
            title: document.title,
            viewport: {
                width: window.innerWidth,
                height: window.innerHeight
            },
            scroll: {
                x: Math.round(window.scrollX),
                y: Math.round(window.scrollY),
                maxX: Math.round(document.documentElement.scrollWidth - window.innerWidth),
                maxY: Math.round(document.documentElement.scrollHeight - window.innerHeight)
            },
            elements: elements.map((data, index) => ({
                index: index + 1,
                selector: data.selector,
                tag: data.tag,
                text: data.text.substring(0, 80),
                rect: data.rect,
                center: data.center,
                actions: data.actions,
                state: data.state
            })),
            focusedIndex: null
        };

        // 找焦点元素
        if (document.activeElement && document.activeElement !== document.body) {
            const idx = elements.findIndex(d => d.element === document.activeElement);
            if (idx !== -1) {
                result.focusedIndex = idx + 1;
            }
        }

        return result;
    }

    /**
     * 获取元素选择器（供外部使用）
     */
    function getSelector(index) {
        const data = elements[index - 1];
        return data ? data.selector : null;
    }

    /**
     * 获取页面可读文本
     */
    function getReadableText(maxLength = 5000) {
        const blocks = [];
        const skipTags = new Set(['script', 'style', 'noscript', 'svg', 'path', 'iframe', 'head', 'meta', 'link']);

        function walk(node, depth = 0) {
            if (depth > 20) return; // 防止过深递归

            if (node.nodeType === Node.TEXT_NODE) {
                const text = node.textContent.trim();
                if (text.length >= 2) {
                    blocks.push(text);
                }
                return;
            }

            if (node.nodeType !== Node.ELEMENT_NODE) return;

            const tag = node.tagName.toLowerCase();
            if (skipTags.has(tag)) return;

            // 检查可见性
            try {
                const style = window.getComputedStyle(node);
                if (style.display === 'none' || style.visibility === 'hidden') return;
            } catch (e) {
                return;
            }

            for (const child of node.childNodes) {
                walk(child, depth + 1);
            }
        }

        walk(document.body);

        let text = blocks.join(' ').replace(/\s+/g, ' ').trim();
        
        if (text.length > maxLength) {
            text = text.substring(0, maxLength) + '...';
        }

        return text;
    }

    /**
     * 添加视觉标注
     */
    function mark() {
        if (isMarked) unmark();
        
        elements.forEach((data, index) => {
            const { rect } = data;
            const color = COLORS[index % COLORS.length];
            
            // 创建overlay容器
            const overlay = document.createElement('div');
            overlay.className = '__agent_overlay__';
            overlay.style.cssText = `
                position: fixed;
                left: ${rect.x}px;
                top: ${rect.y}px;
                width: ${rect.width}px;
                height: ${rect.height}px;
                border: 2px solid ${color};
                background: ${color}22;
                pointer-events: none;
                z-index: 2147483646;
                box-sizing: border-box;
            `;

            // 创建标签
            const label = document.createElement('div');
            label.className = '__agent_label__';
            label.textContent = index + 1;
            
            // 标签位置：优先在上方，空间不够则在下方或右侧
            let labelTop = -20;
            let labelLeft = -2;
            
            if (rect.y < 25) {
                labelTop = rect.height + 2;
            }
            if (rect.x < 35) {
                labelLeft = rect.width + 2;
            }

            label.style.cssText = `
                position: absolute;
                top: ${labelTop}px;
                left: ${labelLeft}px;
                background: ${color};
                color: white;
                padding: 1px 6px;
                border-radius: 3px;
                font-size: 11px;
                font-weight: bold;
                font-family: Arial, sans-serif;
                line-height: 1.3;
                white-space: nowrap;
                box-shadow: 0 1px 3px rgba(0,0,0,0.3);
            `;

            overlay.appendChild(label);
            document.body.appendChild(overlay);
            overlays.set(index, overlay);
        });

        isMarked = true;
    }

    /**
     * 移除视觉标注
     */
    function unmark() {
        overlays.forEach(overlay => {
            try { overlay.remove(); } catch (e) {}
        });
        overlays.clear();
        isMarked = false;
    }

    // 暴露 API
    const API = {
        analyze,
        mark,
        unmark,
        getSelector,
        getReadableText
    };

    window.__AGENT__ = API;
    return API;
})();