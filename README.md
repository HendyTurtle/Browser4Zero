# Browser4Zero

两个文件实现的浏览器 agent。

<img width="720" alt="Browser4Zero Screenshot" src="https://github.com/user-attachments/assets/544464d8-b344-48e5-afad-6e34383aab7f" />

给 Zero。

它很简单，就是 Playwright 加一个 LLM。

你告诉它要干嘛（“搜一下从成都飞上海最便宜的机票”、"帮我把这个表单填了"、"看看 Hacker News 今天头条是啥"），它会打开一个真实的浏览器，自己看页面上有什么，然后点点点、打打字，把事情办了。

## 原理

整个项目大概就是个底层引擎加一个注入页面的 JS 辅助脚本，以及一点点反检测工作。

1. JS 脚本扫描页面上所有可交互的元素（按钮、链接、输入框等），给每个元素生成稳定的 CSS 选择器，编成一个带编号的列表。
2. 这个列表连同页面文本一起发给 LLM。
3. LLM 返回一个 JSON 动作，比如 `{"type": "click", "index": 3}` 或者 `{"type": "fill", "index": 5, "value": "你好"}`。
4. Playwright 执行这个动作，然后回到第 1 步。

另外还有循环检测，如果连续 3 步页面状态没变化，会提醒 LLM 换个思路。
支持截图，可以配合视觉模型使用，但是成本会更高，而且对不少任务**未必效果更好**。
默认状态下，视觉模式是关闭的，也就意味着 LLM 只能通过元素列表和文本来理解页面。
对于大多数任务来说，这样反而能让它更专注，但是如果你的任务大多数是视觉上才能完成的，请考虑打开视觉模式。

## 如何使用？

管理员权限跑：

```bash
pip install patchright openai python-dotenv Pillow
patchright install chrome
```

把 `.env.example` 复制成 `.env`，填上你的 API key。
所有 OpenAI 格式的接口都能用。

```bash
cp .env.example .env
```

> **关于 Patchright**:我们用了 Patchright 替代原生 Playwright，提高反检测能力。


## 用法

交互模式：

```bash
python agent.py
```

自动化执行：

```bash
python agent.py "查一下成都现在的天气"
python agent.py "搜索最新的 Claude 版本是啥" --url https://google.com
```

`--url` 指定起始页面。不传的话 agent 会自己导航。

## 配置

都在 `.env` 里。主要的几个：

| 变量 | 作用 |
|---|---|
| `OPENAI_API_KEY` | API 密钥 |
| `OPENAI_MODEL` | 使用的模型 |
| `OPENAI_API_BASE` | API 地址 |
| `BROWSER_HEADLESS` | 隐藏浏览器窗口 |
| `VISION_ENABLED` | 开启视觉模式（截图发给 LLM），默认 `false` |
| `MAX_STEPS` | 最大步数 |

建议保持 `BROWSER_HEADLESS=false`，这样能看到它在做什么。Patchright 的无头模式比普通 Playwright 更难被检测，但还是建议在有头模式下运行来获得最好的反检测效果。

## 能干什么

基本上你在浏览器里手动能做的事，它都能试着做：

- 搜索（自己打开搜索引擎、输入关键词、按回车、读结果）
- 填表单
- 多步骤流程的点击操作
- 读取页面内容并汇报
- 处理弹窗和 Cookie 横幅

LLM 很重要！别配个7b的小模型然后想让它把事做好事、。

## 局限

- 不支持多标签页，只在单个页面里操作。
- 不处理文件下载。
- 特别密集的页面可能会丢元素。
- Agent 成本较高（尤其视觉开启时）
- 容易被提示词注入。

## License

Apache 2.0 License，详情见 LICENSE 文件。
