from __future__ import annotations

from typing import TYPE_CHECKING

from one_dragon.base.operation.application.application_config import ApplicationConfig
from one_dragon.base.operation.application.application_factory import (
    ApplicationFactory,
)
from one_dragon.base.operation.application_base import Application

from . import const
from .app import MonkeyJigsawApp
from .config import MonkeyJigsawConfig

if TYPE_CHECKING:
    from zzz_od.context.zzz_context import ZContext


class MonkeyJigsawFactory(ApplicationFactory):

    def __init__(self, ctx: ZContext):
        ApplicationFactory.__init__(self, const)
        self.ctx: ZContext = ctx

    def create_application(self, instance_idx: int, group_id: str) -> Application:
        return MonkeyJigsawApp(self.ctx)

    def create_config(
        self, instance_idx: int, group_id: str
    ) -> ApplicationConfig:
        return MonkeyJigsawConfig(instance_idx=instance_idx, group_id=group_id)
