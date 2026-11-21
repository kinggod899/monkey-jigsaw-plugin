from __future__ import annotations

from one_dragon_qt.utils.config_utils import get_prop_adapter
from one_dragon_qt.widgets.app_setting.app_setting_flyout import AppSettingFlyout
from one_dragon_qt.widgets.setting_card.spin_box_setting_card import (
    DoubleSpinBoxSettingCard,
)
from PySide6.QtWidgets import QVBoxLayout

from .config import MAX_SPEED_SCALE, MIN_SPEED_SCALE
from .const import APP_ID


class MonkeyJigsawSettingFlyout(AppSettingFlyout):
    """猴王通用拼图配置弹出框"""

    def _setup_ui(self, layout: QVBoxLayout) -> None:
        self.speed_scale_opt = DoubleSpinBoxSettingCard(
            icon='',
            title='动作延时倍率',
            content=(
                f'可调范围 {MIN_SPEED_SCALE}~{MAX_SPEED_SCALE}，默认 0.5。'
                '数值越大每个动作越慢；出现大量「这一对拖不通」时调大。'
                '强烈建议游戏保持高帧率运行，帧率低时拖动容易失效。'
            ),
            step=0.1,
            minimum=MIN_SPEED_SCALE,
            maximum=MAX_SPEED_SCALE,
            margins=self.card_margins,
        )
        layout.addWidget(self.speed_scale_opt)

    def init_config(self) -> None:
        config = self.ctx.run_context.get_config(
            app_id=APP_ID,
            instance_idx=self.ctx.current_instance_idx,
            group_id=self.group_id,
        )
        self.speed_scale_opt.init_with_adapter(
            get_prop_adapter(config, 'speed_scale')
        )
