from one_dragon_qt.services.app_setting.app_setting_provider import (
    AppSettingProvider,
    SettingType,
)

from .const import APP_ID


class MonkeyJigsawAppSetting(AppSettingProvider):
    """猴王通用拼图的设置入口。"""

    app_id = APP_ID
    setting_type = SettingType.FLYOUT

    @staticmethod
    def get_setting_cls() -> type:
        from .setting import MonkeyJigsawSettingFlyout

        return MonkeyJigsawSettingFlyout
