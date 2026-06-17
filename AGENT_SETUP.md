# AGENT_SETUP — zhihu-search MCP

> **你现在读到这份文档，是因为用户让你安装、配置或排障 `zhihu-search` MCP 服务器。**
> 按顺序执行，不要跳步。每一步完成后先看「判定」再继续。
>
> 本文档写给 agent。这里的「执行」「判定」「不要继续」都是操作指令。人类用户是你的协作者，不是安装日志的观众。

## 目标

用户能在自己的 MCP 客户端（Claude Code、Cursor 等）里调用 `search`、`ask`、`trending` 三个工具。凭证来自用户在 [https://developer.zhihu.com/personal](https://developer.zhihu.com/personal) 创建的 Access Secret，并保存在用户本机。

## 安全原则

- 不要让用户把 Access Secret 粘贴到聊天里。
- 不要把 Access Secret 写进 `.mcp.json`，除非用户明确要求使用环境变量方式。
- 不要打印完整 Access Secret；只能展示 CLI 已掩码的预览。
- 不要提交、上传、截图或记录凭证明文。

## 执行顺序一览

1. 装包（拿到 `zhihu-search` CLI）
2. 检查凭证状态
3. 没有凭证就引导用户本地保存
4. 验证凭证真能用
5. 决定 MCP 配置文件写在哪
6. 写入 `.mcp.json`
7. 提醒用户重启 MCP 客户端
8. 用一次真实工具调用确认

---

## 第 1 步：装包

**判定**：如果 CLI 不在 PATH 上，后续 `--check-token` / `--save-token` / `--probe` 都不能执行。先把包装上。

执行：

```bash
# 优先：uv，适合已安装 uv 的环境
uv pip install -e .

# 备选：pip
python -m pip install -e .
```

Windows 上如果 `pip` 不在 PATH，用 `py -3 -m pip install -e .`。

**判定**：如果 `uv` 和 `pip` 都没有，告诉用户先装 Python 3.10+：
- macOS / Linux：`brew install python@3.12` 或系统包管理器
- Windows：从 [python.org](https://www.python.org/downloads/) 下载，或 `winget install Python.Python.3.12`

验证：

```bash
zhihu-search --version
```

期望：`zhihu-search 0.1.0`（或当前版本号）。

如果 `zhihu-search --version` 报 `command not found`，通常是脚本目录不在 PATH，或包没有安装到当前 Python 环境。**不要继续**，先定位 `python -m pip show zhihu-search` 和 `python -c "import sys; print(sys.executable)"` 的输出，再帮用户修好。

---

## 第 2 步：检查凭证状态

执行：

```bash
zhihu-search --check-token
```

**判定**：

- 输出 `OK  Access Secret 来源：env` 或 `OK  Access Secret 来源：file` → 进入 **第 4 步**。
- 输出 `FAIL  ...` → 继续 **第 3 步**。

---

## 第 3 步：引导用户本地保存 Access Secret

跟用户说（按用户语言翻译）：

> 「请打开 [https://developer.zhihu.com/personal](https://developer.zhihu.com/personal)。
> 登录后进入个人中心，创建 Access Secret。复制后不要发给我；请只在你本机终端里执行下面的保存命令。」

给用户显示命令模板，让用户自己替换尖括号内容并执行：

```bash
zhihu-search --save-token "<粘贴你的 Access Secret>"
```

如果用户愿意让你操作终端，也只能让用户直接在终端提示处输入 secret。不要通过聊天收集 secret。

保存后执行：

```bash
zhihu-search --check-token
```

**判定**：

- 输出 `OK  Access Secret 来源：file` 或 `OK  Access Secret 来源：env` → 继续 **第 4 步**。
- 命令退出码非 0（一般是 token 长度不对或复制不完整）→ 让用户重新复制并在本地终端再执行保存命令。
- 如果用户说「没账号 / 登录不上」：**停**。把阻塞原因告诉用户，让用户后续重新触发。不要自己重试。

**没确认本机已保存可加载凭证之前不要继续。**

---

## 第 4 步：验证 token 真能用

执行：

```bash
zhihu-search --probe
```

期望：返回配额行和至少 1 条热榜项，例如 `第 1 条：xxx\n链接：xxx`。

**判定**：

| 输出                                                          | 动作                                                |
|---------------------------------------------------------------|-----------------------------------------------------|
| 看到 `第 1 条：...`                                            | 进入 **第 5 步**                                   |
| `[错误] Token 已过期或无效...`                                 | 回 **第 3 步**，告诉用户 token 被拒了，请重新创建    |
| `[错误] 知乎上游暂不可达`                                      | 告诉用户稍后再试                                    |
| 空 / 其他错误                                                  | 捕获 stderr，先排查                                 |

顺手查一下当日配额：

```bash
zhihu-search --quota
```

**判定**：

- `剩余` 正整数 → 进入 **第 5 步**。
- `剩余: 0` → 提醒用户今日配额已用完，建议换 token 或者等明天再装。**停**。

---

## 第 5 步：决定 MCP 配置文件写在哪

**判定**：问用户「装到当前项目还是全局？」，默认项目级。展示即将写入的绝对路径，等用户确认。

参考位置：

| 客户端       | 作用域       | 文件路径                              |
|--------------|--------------|---------------------------------------|
| Claude Code  | 项目         | `<当前目录>/.mcp.json`                |
| Claude Code  | 用户全局     | `~/.claude.json`                      |
| Cursor       | 项目         | `<当前目录>/.cursor/mcp.json`         |
| Cursor       | 用户全局     | `~/.cursor/mcp.json`                  |
| 其他         | 看客户端文档 | —                                     |

未确定路径前不要继续。不要猜用户的客户端类型；如果用户没说，先问。

---

## 第 6 步：写入 MCP 配置

读第 5 步确认的目标文件，不存在则创建。必须保留已有服务器条目，只新增或更新 `zhihu` 这一项。

Claude Code 的 `.mcp.json`：

```json
{
  "mcpServers": {
    "zhihu": {
      "command": "python",
      "args": ["-m", "zhihu_search"],
      "env": {}
    }
  }
}
```

如果项目用 venv，把 `"python"` 换成 venv 的绝对解释器路径。检测方法：

```bash
python -c "import sys; print(sys.executable)"
```

默认使用凭证文件，不在 MCP 配置里写 token。如果用户明确要求用环境变量塞 token，才使用下面形式：

```json
{
  "mcpServers": {
    "zhihu": {
      "command": "python",
      "args": ["-m", "zhihu_search"],
      "env": { "ZHIHU_ACCESS_SECRET": "<用户贴的值>" }
    }
  }
}
```

**判定**：写入前用 JSON 解析和序列化确认目标文件合法。写入后再读一遍，确认：

- JSON 语法合法
- 已有 MCP server 没丢
- `zhihu` 的 `command` 和 `args` 指向可运行的 Python 环境
- 未在配置文件中意外写入 Access Secret

---

## 第 7 步：提醒重启 MCP 客户端

告诉用户（不要自己尝试重启客户端进程）：

> 「重启你的 MCP 客户端（Claude Code / Cursor / ...），让它读到新的服务器。然后回到这里。」

不要执行任何会结束、重启、杀掉客户端进程的命令。

---

## 第 8 步：用一次真实工具调用确认

让用户在 MCP 客户端里试一句，例如：

> 「搜索知乎上『如何评价 2026 高考』」或「问直答什么是 RAG」或「看看现在热榜」。

**判定**：

- 工具调用成功 + 看到末尾那行 `配额：今日已用 X/Y...` → 安装完成，简洁说明已可用。
- 报错 → 查下面的错误目录，回到对应步骤。

---

## 错误目录

| 症状                                                                       | 可能原因                              | 回到第几步 |
|----------------------------------------------------------------------------|---------------------------------------|------------|
| `command not found: zhihu-search`                                           | 装包没成功或 PATH 没设                | 第 1 步    |
| `Token 已过期或无效。请到 https://developer.zhihu.com/personal 重新创建...` | token 被吊销或失效                    | 第 3 步    |
| `知乎上游暂不可达`                                                          | 知乎服务异常                          | 等几分钟后重试 |
| `直答请求超时（>120s）`                                                     | 用户用了 model='agent'（很慢）        | 改 fast 模型重试 |
| `query 长度需在 2-100 字符之间`                                             | 调用方 query 太短 / 太长              | 调整后重试 |
| `count 超出范围`                                                            | 调用方传了超过接口上限的 count        | 调整后重试 |
| 客户端报 `tool not found`                                                   | 客户端没重启或配置文件位置不对        | 第 5 / 7 步 |
| `ImportError: No module named 'zhihu_search'`                               | Python 环境和 MCP 配置里的解释器不一致 | 第 1 / 6 步 |
| 返回内容里 `剩余: 0`                                                       | 今日配额耗尽                          | 等到次日 / 提高上限 |

---

## 配额相关

- 每日上限默认 1000。macOS / Linux 改：`export ZHIHU_DAILY_LIMIT=5000`
- Windows PowerShell 改：`$env:ZHIHU_DAILY_LIMIT=5000`
- 看用量：`zhihu-search --quota`
- 清零今日：`zhihu-search --reset-quota`（仅在调试时使用）

---

## 给 agent 的备注

- **不要**假设用户装了 Python，先检测。
- **不要**未经确认就写到系统级配置。
- **不要**让用户把 Access Secret 发到聊天消息里。
- **不要**把 token 存到凭证文件或 `ZHIHU_ACCESS_SECRET` 环境变量之外的地方。
- **永远**在写入前用 JSON 解析校验一遍。
- **永远**用真实工具调用确认成功再宣布完成。
- 用户要卸载的话：跑 `zhihu-search --clear-token`，再把 `.mcp.json` 里 `zhihu` 条目删掉。