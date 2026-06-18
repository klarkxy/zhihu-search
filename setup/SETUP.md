# 通用准备（所有终端都需执行）

## 1. 获取 Access Secret

打开 [developer.zhihu.com/personal](https://developer.zhihu.com/personal)，登录后创建 Access Secret。

**安全提醒**：不要把它粘贴到聊天记录、截图或公开仓库。只在本地终端执行保存命令。

## 2. 保存凭证（本地终端执行）

```bash
# 先安装（任选一种）
# 方式 A：uvx（推荐，无需克隆）
uvx zhihu-search --save-token "<你的 Access Secret>"

# 方式 B：pip 从 PyPI
pip install zhihu-search
zhihu-search --save-token "<你的 Access Secret>"

# 方式 C：本地源码（开发者模式）
cd /path/to/zhihu-search
pip install -e .
zhihu-search --save-token "<你的 Access Secret>"
```

验证凭证已存好：

```bash
zhihu-search --check-token
# 期望输出：OK  Access Secret 来源：file
```

## 3. 验证端到端连通性

```bash
zhihu-search --probe
# 期望输出：配额信息和热榜第一条
```

凭证验证通过后，再去看你对应客户端的指南，写入配置并重启。

## 4. 常用 CLI 命令

```bash
zhihu-search --check-token      # 检查凭证
zhihu-search --probe            # 端到端验证
zhihu-search --quota            # 查看今日配额
zhihu-search --reset-quota      # 清零今日计数（调试用）
zhihu-search --clear-token      # 删除本地凭证
zhihu-search --version          # 查看版本
```

## 5. 排障

| 症状 | 排查 |
|---|---|
| `command not found: uvx` | 安装 uv |
| `command not found: zhihu-search` | 确认 pip/uvx 安装成功，或写绝对路径 |
| `Token 已过期或无效` | 回 developer.zhihu.com/personal 重新创建 |
| `知乎上游暂不可达` | 等几分钟后重试 |
| 客户端报 `tool not found` | 确认已重启客户端；检查配置文件位置/格式 |
| `ImportError: No module named 'zhihu_search'` | Python 环境和 MCP 配置里的解释器不一致 |
| 返回内容里 `剩余: 0` | 今日配额耗尽，等次日或提高上限 |
