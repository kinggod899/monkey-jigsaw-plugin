from one_dragon.base.operation.application.application_config import ApplicationConfig

from . import const

DEFAULT_SPEED_SCALE: float = 0.5
"""默认动作延时倍率。"""
MIN_SPEED_SCALE: float = 0.3
MAX_SPEED_SCALE: float = 3.0


class MonkeyJigsawConfig(ApplicationConfig):

    def __init__(self, instance_idx: int, group_id: str):
        ApplicationConfig.__init__(
            self,
            instance_idx=instance_idx,
            app_id=const.APP_ID,
            group_id=group_id,
        )

    @property
    def speed_scale(self) -> float:
        """动作延时倍率。数值越大每个动作越慢，0.5 是默认速度。"""
        return self.get('speed_scale', DEFAULT_SPEED_SCALE)

    @speed_scale.setter
    def speed_scale(self, new_value: float) -> None:
        self.update('speed_scale', new_value)
