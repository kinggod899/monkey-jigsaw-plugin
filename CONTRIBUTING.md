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

```shell
python scripts/validate_plugin.py --strict
```

## 发版

1. 改 `monkey_jigsaw/plugin.json` 的 `version`，`versionCode` 加 1，提交
2. 打 tag 并推送：`git tag v1.0.0 && git push origin v1.0.0`

`Release Plugin` 工作流会自动打包并创建 Release。
