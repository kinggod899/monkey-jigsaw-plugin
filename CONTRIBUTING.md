# 开发说明

## 目录

```text
monkey_jigsaw/          插件包，目录名 = APP_ID
├── plugin.json         商店元数据
├── const.py            APP_ID / APP_NAME / 运行行为
├── factory.py          应用工厂 + 配置工厂
├── config.py           配置项：动作延时倍率
├── app_setting.py      设置声明
├── setting.py          设置界面（悬浮卡片）
├── app.py              应用主体：单节点自循环状态机 + 穷举策略
├── board.py            面板识别：格数、明暗格、帧差
└── screen_info/        画面区域配置
```

## 本地校验

校验和打包脚本在官方仓 [plugin-tools](https://github.com/OneDragon-Anyone/plugin-tools)，不需要复制进本仓库。本地想少等一轮就克隆到临时目录，版本与 CI 一致：

```shell
git clone --depth 1 --branch v1 https://github.com/OneDragon-Anyone/plugin-tools.git .plugin-tools

python .plugin-tools/scripts/validate_plugin.py --repo . --strict
python .plugin-tools/scripts/build_zip.py --repo .
```

`.plugin-tools/` 已在 `.gitignore` 中忽略。

## 发版

1. 改 `monkey_jigsaw/plugin.json` 的 `version`，`versionCode` 加 1，提交
2. 打 tag 并推送：`git tag v1.0.0 && git push origin v1.0.0`

`Release Plugin` 工作流会校验、打包并创建 Release。

## 工作流版本

两个入口工作流只调用官方可复用工作流，逻辑不在本仓库：

```yaml
uses: OneDragon-Anyone/plugin-tools/.github/workflows/reusable-validate.yml@v1
```

`@v1` 跟随 v1 系列修复，不会有破坏性变化。想锁定就换成 `v1.0.0` 这样的完整 tag 或具体提交 sha。
