# DeepSeek Harness

知乎的 DSH 插件已迁到
[dsh-plugins 的 `plugins/dsh-zhihu`](https://github.com/klarkxy/dsh-plugins/tree/main/plugins/dsh-zhihu)。
包名是 `@klarkxy/dsh-zhihu`。本仓库只维护 Python 客户端和 Skill，不再提供
DSH 安装包。

如果你不使用 DSH，请回到[通用安装说明](README.md)，直接安装 Skill。

## 安装

```bash
dsh plugin --profile web add @klarkxy/dsh-zhihu
```

安装后重启目标 profile，在 **Plugins → @klarkxy/dsh-zhihu** 填写 Access Secret。
凭证名是 DSH 的 `ZHIHU_ACCESS_TOKEN`。请使用带 scope 的包名；无 scope 的
`dsh-zhihu` 属于其他维护者。

功能、工具和配置以该插件的说明为准：
<https://github.com/klarkxy/dsh-plugins/tree/main/plugins/dsh-zhihu>

## 卸下本仓库里的旧插件

旧安装包的名称是 `dsh-plugin-zhihu-search`。装上新插件后，从 profile 里移除它：

```bash
dsh plugin --profile web remove dsh-plugin-zhihu-search
```

移除旧安装包不会删除 Python 凭证文件，也不会删除独立安装的 Skill。
