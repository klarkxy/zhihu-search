# dsh-plugin-zhihu-search

这是给 DeepSeek Harness 使用的 `zhihu-search` Skill 安装包。它只负责把同一份
Skill 挂进目标 profile：不启动 MCP，也不在 DSH 配置中保存知乎凭证。

## 三步开始

### 1. 在自己的终端准备凭证

```powershell
uvx zhihu-search --save-token "<Access Secret>"
uvx zhihu-search --probe
```

### 2. 安装到实际使用的 profile

```powershell
dsh plugin --profile web add "github:klarkxy/zhihu-search"
dsh --profile web --dump-config
```

### 3. 重启并做一次真实查询

重启 profile 后，Skill 目录应出现 `zhihu-search`。让 Agent 查询一条中文社区
资料，并确认返回非空结果和来源链接。仅有安装成功提示或配置 dump 不算完整
验证。

查询仍按需执行 `uvx zhihu-search`。只有当前会话已经提供匹配的知乎 MCP 工具
时才直接复用；不要因为安装了 bundle 就再注册常驻 MCP。

完整的配置检查和故障说明见 [DSH 安装指南](../setup/dsh.md)。

## 更新与移除

```powershell
dsh plugin --profile web update dsh-plugin-zhihu-search
dsh plugin --profile web remove dsh-plugin-zhihu-search
```

移除 bundle 不会删除独立安装的同名 Skill，也不会删除 Python 凭证文件。只有
明确需要删除凭证时才运行 `uvx zhihu-search --clear-token`。

如果项目或用户 Skill 目录中已有同名副本，距离更近的副本会优先于 bundle
版本。更新或移除那个副本后，bundle 版本才会生效。

## 可复现安装与本地验证

固定到审核过的 Git commit：

```powershell
dsh plugin --profile web add "github:klarkxy/zhihu-search#<commit>"
```

从本地 checkout 验证：

```powershell
dsh plugin --profile web add .
```

## 安全边界

- bundle 不包含 Access Secret，也不会通过命令参数转发密钥；
- CLI 读取 `--save-token` 创建的用户级凭证文件；
- 不要把 Access Secret、OAuth app key 或 OAuth token 发到聊天；
- 本机 PDF/知识库上传和 OAuth token 交换只允许从 CLI/Python 执行。

发布者请保留 GitHub 仓库的 `dsh-plugin` topic，供 Marketplace 和插件搜索发现。
