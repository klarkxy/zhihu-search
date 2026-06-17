# AGENT_SETUP — zhihu-search MCP

> **你读到这份文档，是因为用户让你安装、配置或排障 `zhihu-search` MCP 服务器。**
>
> 按顺序执行，不要跳步。每步完成后先看「判定」再继续。
> 本文档写给 agent；这里的「执行」「判定」「不要继续」都是操作指令。人类用户是协作者，不是安装日志观众。
>
> 默认安装方式：[uv](https://github.com/astral-sh/uv) 的 `uvx`，按需拉取包到临时 venv，无需用户手动 `pip install`。pip 安装方式见文末「pip 备选方案」。

## 目标

用户能在自己的 MCP 客户端（Claude Code、Cursor 等）里调用 `search`、`ask`、`trending` 三个工具。凭证来自用户在 [developer.zhihu.com/personal](https://developer.zhihu.com/personal) 创建的 Access Secret，保存在本机 `~/.config/zhihu-search/credentials.json`。

## 占位符约定

- `<包来源>`：决定 `uvx` 从哪儿拉包。常见取值：
  - GitHub 源码（默认）：`git+https://github.com/klarkxy/zhihu-search`
  - 锁版本：`git+https://github.com/klarkxy/zhihu-search@v0.1.0`
  - PyPI 上线后：`zhihu-search`（不带 `--from`），或 `zhihu-search==0.1.0`
- `<包来源>` 写入 MCP 配置文件前必须替换成具体值；不要把字面量 `<包来源>` 落进 JSON。

## 安全原则

- 不要让用户把 Access Secret 粘贴到聊天里。
- 不要把 Access Secret 写进 `.mcp.json`，除非用户明确要求使用环境变量方式。
- 不要打印完整 Access Secret；只能展示 CLI 已掩码的预览。
- 不要提交、上传、截图或记录凭证明文。

## 执行顺序一览

1. 安装 uv（拿到 `uvx` 命令）
2. 检查凭证状态
3. 没有凭证就引导用户本地保存（通过 `uvx`）
4. 验证凭证真能用（通过 `uvx`）
5. 决定 MCP 配置文件写在哪
6. 写入 MCP 配置（`uvx` 模式）
7. 提醒用户重启 MCP 客户端
8. 用一次真实工具调用确认

---

## 第 1 步：安装 uv

**判定**：`uvx` 不在 PATH 上时，后续所有 `--check-token` / `--save-token` / `--probe` 都不能跑。先把 uv 装上。

按用户操作系统选一条（如果用户没指定系统，先探测）：

```bash
# 探测当前系统
uname -s 2>/dev/null || echo "Windows"
```

- **macOS / Linux（官方脚本）**：
  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```
- **macOS（Homebrew）**：`brew install uv`
- **Windows（PowerShell）**：
  ```powershell
  powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
  ```
- **Windows（winget）**：`winget install --id Astral.uv -e`
- **其它平台**：从 https://github.com/astral-sh/uv/releases 下载二进制。

装完后验证：

```bash
uvx --version
```

期望：输出类似 `uvx 0.x.y` 的版本号。

**判定**：

- 看到版本号 → 进入 **第 2 步**。
- 报 `command not found` 通常是 PATH 没刷新。让用户重开终端。
- 如果在受限环境（CI 镜像、容器）拿不到外网脚本，回退到 `pip install uv` 或 `pipx install uv`。

---

## 第 2 步：检查凭证状态

执行：

```bash
uvx --from <包来源> zhihu-search --check-token
```

第一次跑会下载包到 `~/.cache/uv`（Windows 在 `%LOCALAPPDATA%\uv`），耗时几秒到几十秒；之后命中缓存立即返回。

**判定**：

- 输出 `OK  Access Secret 来源：env` 或 `OK  Access Secret 来源：file` → 进入 **第 4 步**。
- 输出 `FAIL  ...` → 继续 **第 3 步**。

---

## 第 3 步：引导用户本地保存 Access Secret

跟用户说（按用户语言翻译）：

> 「请打开 [developer.zhihu.com/personal](https://developer.zhihu.com/personal)。登录后进入个人中心，创建 Access Secret。复制后不要发给我；请只在你本机终端里执行下面的保存命令。」

给用户显示命令模板，让用户自己替换尖括号内容并执行：

```bash
uvx --from <包来源> zhihu-search --save-token "<粘贴你的 Access Secret>"
```

如果用户对命令历史敏感（PowerShell / bash history 会留痕），可以让用户走临时变量：

**bash / zsh（输入不回显）**：

```bash
read -s -p "Access Secret: " S && uvx --from <包来源> zhihu-search --save-token "$S" && unset S
```

**PowerShell（用完后清变量）**：

```powershell
$env:ZHIHU_ACCESS_SECRET = "<粘贴你的 Access Secret>"
uvx --from <包来源> zhihu-search --save-token $env:ZHIHU_ACCESS_SECRET
Remove-Item Env:\ZHIHU_ACCESS_SECRET
```

> **注意**：Windows PowerShell 历史文件（`ConsoleHost_history.txt`）仍会记录包含 `$env:ZHIHU_ACCESS_SECRET = "..."` 的那一行。最保险的方式是用上面的 `read -s` 在 WSL / Git Bash 里执行，或粘贴后手动清理历史文件。

不要通过聊天收集 secret。

保存后用 `--check-token` 复核：

```bash
uvx --from <包来源> zhihu-search --check-token
```

**判定**：

- 输出 `OK  Access Secret 来源：file` → 继续 **第 4 步**。
- 退出码非 0（一般是 token 长度不对或复制不完整）→ 让用户重新复制并在本地终端再执行保存命令。
- 如果用户说「没账号 / 登录不上」：**停**。把阻塞原因告诉用户，让用户后续重新触发。不要自己重试。

**没确认本机已保存可加载凭证之前不要继续。**

---

## 第 4 步：验证 token 真能用

执行：

```bash
uvx --from <包来源> zhihu-search --probe
```

期望输出示例：

```
配额：搜索 0/5000 · 热榜 0/100 · 直答 0/100（2026-06-19T00:00:00 刷新）

第 1 条：如何看待 xxx
链接：https://www.zhihu.com/...
```

**判定**：

| 输出                                                   | 动作                                                |
|--------------------------------------------------------|-----------------------------------------------------|
| 看到 `第 1 条：...`                                     | 进入 **第 5 步**                                    |
| `[错误] Token 已过期或无效...`                          | 回 **第 3 步**，告诉用户 token 被拒，请重新创建     |
| `[错误] 知乎上游暂不可达`                               | 告诉用户稍后再试                                    |
| 空 / 其他错误                                           | 捕获 stderr，先排查                                 |

顺手查一下当日配额：

```bash
uvx --from <包来源> zhihu-search --quota
```

**判定**：

- `剩余` 为正整数 → 进入 **第 5 步**。
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

读第 5 步确认的目标文件，不存在则创建。必须保留已有服务器条目，只新增或更新 `zhihu` 这一项。`<包来源>` 占位符必须在写入前替换成具体值。

**uvx 模式（推荐）**：

```json
{
  "mcpServers": {
    "zhihu": {
      "command": "uvx",
      "args": ["--from", "<包来源>", "zhihu-search"],
      "env": {}
    }
  }
}
```

用 pip 装的写法见文末「pip 备选方案」。

默认使用凭证文件，不在 MCP 配置里写 token。如果用户明确要求用环境变量塞 token，才使用下面形式：

```json
{
  "mcpServers": {
    "zhihu": {
      "command": "uvx",
      "args": ["--from", "<包来源>", "zhihu-search"],
      "env": { "ZHIHU_ACCESS_SECRET": "<用户贴的值>" }
    }
  }
}
```

**判定**：写入前用 JSON 解析和序列化确认目标文件合法。写入后再读一遍，确认：

- JSON 语法合法
- 已有 MCP server 没丢
- `zhihu` 的 `command` 是 `uvx` 且可运行（`uvx --version` 不报错）
- `<包来源>` 已经替换成具体值，不是字面量
- 未在配置文件中意外写入 Access Secret（除非用户明确要求 env 模式）

---

## 第 7 步：提醒重启 MCP 客户端

告诉用户（不要自己尝试重启客户端进程）：

> 「重启你的 MCP 客户端（Claude Code / Cursor / ...），让它读到新的服务器。然后回到这里。」

不要执行任何会结束、重启、杀掉客户端进程的命令。

---

## 第 8 步：用一次真实工具调用确认

让用户在 MCP 客户端里试一句，例如：

> 「搜索知乎上『如何评价 2026 高考』」「问直答什么是 RAG」「看看现在热榜」。

**判定**：

- 工具调用成功 + 看到末尾那行 `配额：...` → 安装完成，简洁说明已可用。
- 报错 → 查下面的错误目录，回到对应步骤。

---

## 错误目录

| 症状                                                                       | 可能原因                              | 回到第几步     |
|----------------------------------------------------------------------------|---------------------------------------|----------------|
| `command not found: uvx`                                                    | 没装 uv 或 PATH 没刷新                | 第 1 步        |
| `command not found: zhihu-search`                                           | 用 pip 装但脚本目录没在 PATH          | pip 备选方案   |
| `Token 已过期或无效。请到 https://developer.zhihu.com/personal 重新创建...` | token 被吊销或失效                    | 第 3 步        |
| `知乎上游暂不可达`                                                          | 知乎服务异常                          | 等几分钟后重试 |
| `直答请求超时（>120s）`                                                     | 用户用了 model='agent'（很慢）        | 改 fast 模型重试 |
| `query 长度需在 2-100 字符之间`                                             | 调用方 query 太短 / 太长              | 调整后重试     |
| `count 超出范围`                                                            | 调用方传了超过接口上限的 count        | 调整后重试     |
| 客户端报 `tool not found`                                                   | 客户端没重启或配置文件位置不对        | 第 5 / 7 步    |
| `ImportError: No module named 'zhihu_search'`                               | Python 环境和 MCP 配置里的解释器不一致 | 第 1 / 6 步    |
| 返回内容里 `剩余: 0`                                                       | 今日配额耗尽                          | 等到次日 / 提高上限 |

---

## 配额相关

按接口分桶统计：

| 类别       | 包含接口            | 默认上限 | 覆盖环境变量                 |
|------------|---------------------|----------|------------------------------|
| `search`   | 知乎搜索 / 全网搜索 | 5000     | `ZHIHU_DAILY_LIMIT_SEARCH`   |
| `trending` | 热榜                | 100      | `ZHIHU_DAILY_LIMIT_TRENDING` |
| `ask`      | 直答                | 100      | `ZHIHU_DAILY_LIMIT_ASK`      |

- 旧 `ZHIHU_DAILY_LIMIT` 仍可用：把三个桶同时设为同一个值（向后兼容）
- 看用量：`uvx --from <包来源> zhihu-search --quota`
- 清零今日：`uvx --from <包来源> zhihu-search --reset-quota`（仅在调试时使用）

---

## pip 备选方案

如果用户装不上 uv（老系统、CI 镜像、容器无网络），用 pip 直接装：

```bash
# 源码模式（在项目根目录）
python -m pip install -e .

# Windows 上 pip 不在 PATH 时
py -3 -m pip install -e .
```

装好后，文档里所有 `uvx --from <包来源> zhihu-search ...` 都替换为：

- `zhihu-search ...`：用 `[project.scripts]` 装的脚本
- 或 `python -m zhihu_search ...`：不依赖脚本目录在 PATH

pip 模式需要 Python 3.10+ 已经在系统上，并且 MCP 配置里的解释器路径与用户实际用的 venv 一致。检测方法：

```bash
python -c "import sys; print(sys.executable)"
```

pip 模式的 MCP 配置：

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

如果 venv 路径特殊，把 `command` 换成上面 `sys.executable` 输出的绝对路径，例如 `C:\\Users\\<user>\\.venv\\Scripts\\python.exe`。

项目发到 PyPI 后，`pip install zhihu-search` 可用，配置改为：

```json
{
  "mcpServers": {
    "zhihu": {
      "command": "zhihu-search",
      "args": [],
      "env": {}
    }
  }
}
```

---

## 卸载

如果用户想卸载：

```bash
# 1. 清凭证
uvx --from <包来源> zhihu-search --clear-token
# 或 pip 模式：zhihu-search --clear-token

# 2. 删 MCP 配置里的 zhihu 条目
# 手动编辑第 5 步确认的配置文件，删除 mcpServers.zhihu

# 3. 如不再需要 uv 缓存（可选）
uvx uninstall zhihu-search
```

---

## 给 agent 的备注

- **不要**假设用户装了 Python，先检测。
- **不要**未经确认就写到系统级配置。
- **不要**让用户把 Access Secret 发到聊天消息里。
- **不要**把 token 存到凭证文件或 `ZHIHU_ACCESS_SECRET` 环境变量之外的地方。
- **永远**在写入前用 JSON 解析校验一遍。
- **永远**用真实工具调用确认成功再宣布完成。
- `<包来源>` 写入 JSON 前必须先替换成具体值，不要把字面量落进 MCP 配置。
- 每步执行结果要汇报；遇到阻塞原因先停，不要反复重试。
