# DeepSeek Harness：安装 zhihu-search Skill

DSH 使用一个声明式 bundle，把仓库自带的 `zhihu-search` Skill 挂载到指定
profile。它不会启动 MCP，也不会把知乎凭证写进 DSH 配置；实际查询仍由 Skill
按需执行 `uvx zhihu-search`。

如果你不使用 DSH，请回到[通用安装说明](README.md)，直接安装 Skill。

## 1. 准备 uvx 和凭证

确保启动 DSH 的同一系统用户能够运行：

```powershell
uvx --version
uvx zhihu-search --version
```

在自己的终端保存并验证 Access Secret：

```powershell
uvx zhihu-search --save-token "<Access Secret>"
uvx zhihu-search --probe
```

不要把 Access Secret 写进 `cordis.patch.yml`、profile metadata、聊天、截图或
日志。bundle 只读取现有的 Python 用户级凭证文件。

## 2. 安装 bundle

把 GitHub 仓库安装到实际使用的 profile：

```powershell
dsh plugin --profile web add "github:klarkxy/zhihu-search"
dsh --profile web --dump-config
```

配置结果应包含一个 `zhihu-search-skill` 条目，并满足：

- 使用 `@deepseek-ai/dsh-skill-filesystem`；
- `providerName: zhihu-search-skill`；
- `includeDefaultRoots: false`；
- `bundledSkillDir` 指向包内的 `skills` 目录。

持久安装后停止并重新启动目标 profile。只看到“安装成功”或配置 dump 还不算
端到端验证。

## 3. 验证真实能力

重启后，Skill 目录应出现 `zhihu-search`。发送：

> 帮我查一下最近主流的 RAG 评测方法，返回两条并附来源链接。

验收时确认 Agent 加载了 Skill、按需执行了匹配查询，并返回非空结果和可检查
的链接。不要因为安装了这个 bundle 就再注册常驻知乎 MCP；只有当前会话已经
暴露匹配工具时才复用。

如果项目或用户 Skill 目录里已有同名 Skill，距离更近的副本会覆盖 bundle
版本。需要使用 bundle 版本时，应更新或移除那个独立副本。

## 更新与移除

```powershell
dsh plugin --profile web update dsh-plugin-zhihu-search
dsh plugin --profile web remove dsh-plugin-zhihu-search
```

移除 bundle 只会取消挂载 profile 中的 Skill，不会删除独立安装在用户目录的
Skill，也不会删除 Python 凭证文件。只有用户明确要求删除凭证时才运行：

```powershell
uvx zhihu-search --clear-token
```

## 可复现安装与本地验证

生产或团队环境建议固定到审核过的 Git commit：

```powershell
dsh plugin --profile web add "github:klarkxy/zhihu-search#<commit>"
```

本地 checkout 的冒烟测试可以使用：

```powershell
dsh plugin --profile web add .
```

commit 固定安装不会自动移动到新版本；需要升级时，用新的已审核 SHA 重新添加。

## 发布者说明

bundle 只有 manifest、声明式 patch 和 Skill 文件，没有 `prepare` 或其他安装脚本，
也不需要 npm 发布。Marketplace 和插件搜索通过 GitHub 仓库的 `dsh-plugin`
topic 发现它；`dsh plugin add` 本身不依赖这个 topic。
