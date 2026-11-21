"""拼图：在拼图界面把散落的碎块拖回原位。

面板里亮的是还能拖的碎块，暗的是已经拼好的部分，碎块拖到正确位置会被立刻锁定、变暗。
做法是把某个亮格上的块依次拖到其它亮格：拖对了游戏锁定它，拖错了就是两块互换。

块没有稳定可认的外观（不同块的指纹会撞），所以不靠图像认块，而是让程序自己维护
「位置 -> 块号」的对应关系：每次拖动把两个格子的块号对调，格子变暗就把块号删掉。
哪一块试过哪些位置由 _tried 记录，避免重复试同一对。

拼完的唯一判据是整个面板没有还能拖的亮格。挑不出可试的移动时直接失败，不猜「已就位」——
那样会把没拼完的图当成拼完。
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from cv2.typing import MatLike
from one_dragon.base.controller.drag_timing import DragTiming
from one_dragon.base.geometry.rectangle import Rect
from one_dragon.base.operation.application import application_const
from one_dragon.base.operation.operation_node import operation_node
from one_dragon.base.operation.operation_round_result import OperationRoundResult
from zzz_od.application.zzz_application import ZApplication

from . import const
from .board import (
    PuzzleBoard,
    PuzzleCell,
    analyze_board,
    cell_difference,
    refresh_cells,
)
from .config import (
    DEFAULT_SPEED_SCALE,
    MAX_SPEED_SCALE,
    MIN_SPEED_SCALE,
    MonkeyJigsawConfig,
)

if TYPE_CHECKING:
    from zzz_od.context.zzz_context import ZContext

_SCREEN_NAME: str = '猴王通用拼图'
_AREA_NAME: str = '拼图面板'
_DRAG_TIMING: DragTiming = DragTiming(
    press_wait=0.1, move_duration=0.3, release_wait=0.1
)
"""拖拽时序。按下后必须停一下，游戏才会把这一下当成「抓起一块」。"""
_SETTLE_SECONDS: float = 0.2
"""松手后等碎块落位的时间；被拖的两格没动静就再等一轮。"""
_SETTLE_RETRIES: int = 3
"""落位最多等几轮。"""
_MOVE_THRESHOLD: float = 6.0
"""被拖的那两格平均灰度差超过这个值才算拖动生效。

不用整块面板的平均差：两块互换只占面板面积的两个格，6×6 时只占 1/18，
整块平均差会被摊到 1.6~2.5，低于任何可用阈值，好格子会被误判成拖不动。
"""
_MAX_STEPS: int = 1200
"""最多拖动多少次。"""
_NO_PROGRESS_LIMIT: int = 100
"""连续多少步没有新格子锁定就放弃。"""
_STUCK_LIMIT: int = 3
"""连续多少轮挑不出可试的移动就整盘重来一次。"""
_FULL_RESTART_LIMIT: int = 1
"""整盘重来最多几次。剩的块少时识别容易抖动，重来一遍通常就能过。"""
_DEAD_NEIGHBORS: int = 2
"""同一格跟这么多个不同的对手格都是「重拖一次也不动」，就判定它自己拖不动。"""
_RESET_LIMIT: int = 2
"""「不再试」的记号最多清空几次。"""

CellKey = tuple[int, int]
PairKey = tuple[CellKey, CellKey]


def _pair(a: CellKey, b: CellKey) -> PairKey:
    """无向的一对格子，用来做去重键。"""
    return (a, b) if a <= b else (b, a)


class MonkeyJigsawApp(ZApplication):

    def __init__(self, ctx: ZContext):
        ZApplication.__init__(
            self,
            ctx=ctx,
            app_id=const.APP_ID,
            op_name=const.APP_NAME,
        )
        self.config: MonkeyJigsawConfig = self.ctx.run_context.get_config(
            app_id=const.APP_ID,
            instance_idx=self.ctx.current_instance_idx,
            group_id=application_const.DEFAULT_GROUP_ID,
        )
        self._block_at: dict[CellKey, int] = {}
        """每个亮格上现在放的是哪一块。块号由程序自己分配，跟着拖动一起搬。"""
        self._retired: dict[CellKey, int] = {}
        """被判成暗格的块号暂存，格子重新判成亮格时沿用回来。"""
        self._tried: dict[int, set[CellKey]] = {}
        """块号 -> 已经试过、确认放不进去的位置。"""
        self._next_block_id: int = 0
        self._failed_pairs: set[PairKey] = set()
        """拖过去画面完全没变的格子对，本局不再重试。"""
        self._src_dead: dict[CellKey, set[CellKey]] = {}
        """每格当源格时，跟哪些目标格拖不通。"""
        self._tgt_dead: dict[CellKey, set[CellKey]] = {}
        """每格当目标格时，被哪些源格撞失败过。"""
        self._ghost: set[CellKey] = set()
        """看着是亮格、实际拖不动的格子。源格和目标格都不再用它。"""
        self._pending: PairKey | None = None
        """上一轮拖了没反应的那一对，这一轮原样再拖一次确认。"""
        self._done_sources: set[CellKey] = set()
        """不再拿它当源格的格子：它的其它亮格都试遍了还不锁定，说明它就在原位上。"""
        self._bounced: set[int] = set()
        """已经做过一次「挪走再挪回」的块号，避免反复兜底。"""
        self._size_hint: int | None = None
        """上一轮判出的格数。拼到后期内部线变少，靠它稳定格数。"""
        self._steps: int = 0
        self._last_alive: int = 999
        self._last_progress_step: int = 0
        self._stuck_rounds: int = 0
        self._reset_rounds: int = 0
        self._full_restarts: int = 0
        self._finished_hits: int = 0

    @operation_node(name='拼图', is_start_node=True, node_max_retry_times=_MAX_STEPS)
    def jigsaw(self) -> OperationRoundResult:
        area = self.ctx.screen_loader.get_area(_SCREEN_NAME, _AREA_NAME)
        if area is None:
            return self.round_fail('没有配置拼图面板区域')

        screen = self.screenshot()
        board = analyze_board(screen, area.rect, self._size_hint)
        if board is None:
            return self.round_retry('没识别到拼图面板', wait=0.5)
        self._size_hint = board.size

        if board.is_finished:
            # 连续两轮都判成拼完才算数，避免某一帧识别抖动提前收工
            self._finished_hits += 1
            if self._finished_hits >= 2:
                return self.round_success('拼图完成')
            return self.round_wait('再确认一次', wait=0.2)
        self._finished_hits = 0

        # 有效亮格：剔除掉实测拖不动的格子之后还剩几个
        alive_count = sum(
            1
            for cell in board.movable_cells
            if (cell.row, cell.col) not in self._ghost
        )
        if alive_count < self._last_alive:
            self._last_alive = alive_count
            self._last_progress_step = self._steps
        elif self._steps - self._last_progress_step > _NO_PROGRESS_LIMIT:
            return self.round_fail(
                f'连续 {_NO_PROGRESS_LIMIT} 次拖动没有新格子锁定，还剩 {alive_count} 块'
            )

        self._sync_blocks(board)
        move = self._pick_move(board)
        if move is None:
            if alive_count <= 1:
                # 只剩一块（或一块不剩），其它都锁定了。这一块必然已经在自己的位置上，
                # 游戏也不会再给它换位的机会；被剔除的格子本身多半就是暗格识别错了。
                return self.round_success('拼图完成')
            self._stuck_rounds += 1
            if self._stuck_rounds == 1 and self._reset_rounds < _RESET_LIMIT:
                # 挑不出就先清掉「不再试」的记号，重新轮一遍；清空后能推进就继续。
                # 只清有限的几次，否则会变成「清空 → 重试 → 清空」的循环。
                self._reset_rounds += 1
                self._clear_marks()
            elif self._stuck_rounds >= _STUCK_LIMIT:
                # 挑不出移动多半是剩的块少、识别抖了一下。整盘清空、重新识别再来一遍，
                # 比直接判失败划算 —— 剩几块的时候重来一次通常就过了。
                if self._full_restarts < _FULL_RESTART_LIMIT:
                    self._full_restarts += 1
                    self._reset_all()
                    return self.round_retry('整盘重来', wait=0.5)
                return self.round_fail(
                    f'重来 {_FULL_RESTART_LIMIT} 次仍挑不出可试的移动，还剩 {alive_count} 块'
                )
            return self.round_retry('挑不出可试的移动', wait=0.3)
        self._stuck_rounds = 0

        source, target = move
        self._drag(source, target)
        after_screen = self._settle(
            screen, [source.rect, target.rect], _SETTLE_SECONDS * self._speed_scale
        )
        refresh_cells(after_screen, board, [source, target])
        return self._judge(screen, after_screen, board, source, target)

    def _clear_marks(self) -> None:
        """清掉各种「不再试」的记号，让格子重新参与挑选。"""
        self._done_sources.clear()
        self._failed_pairs.clear()
        self._bounced.clear()
        self._tried.clear()
        self._pending = None

    def _reset_all(self) -> None:
        """整盘重来：块号、格数、所有排除记号全部作废，下一轮当新拼图处理。"""
        self._clear_marks()
        self._block_at.clear()
        self._retired.clear()
        self._next_block_id = 0
        self._src_dead.clear()
        self._tgt_dead.clear()
        self._ghost.clear()
        self._size_hint = None
        self._stuck_rounds = 0
        self._reset_rounds = 0
        self._last_alive = 999
        self._last_progress_step = self._steps
        self._finished_hits = 0

    def _drag(self, source: PuzzleCell, target: PuzzleCell) -> None:
        scale = self._speed_scale
        self.ctx.controller.drag_to(
            start=source.rect.center,
            end=target.rect.center,
            timing=DragTiming(
                press_wait=_DRAG_TIMING.press_wait * scale,
                move_duration=_DRAG_TIMING.move_duration * scale,
                release_wait=_DRAG_TIMING.release_wait * scale,
            ),
        )

    @property
    def _speed_scale(self) -> float:
        """动作延时倍率，每轮现读，改完设置下一张拼图就生效。"""
        try:
            value = float(self.config.speed_scale)
        except (TypeError, ValueError):
            return DEFAULT_SPEED_SCALE
        return min(MAX_SPEED_SCALE, max(MIN_SPEED_SCALE, value))

    def _settle(
        self, before: MatLike, rects: list[Rect], settle: float
    ) -> MatLike:
        """等碎块落位：先等一小会儿，被拖的两格没动静就再等一轮。"""
        time.sleep(settle)
        cur = self.screenshot()
        for _ in range(_SETTLE_RETRIES - 1):
            if any(
                cell_difference(before, cur, rect) > _MOVE_THRESHOLD
                for rect in rects
            ):
                break
            time.sleep(settle)
            cur = self.screenshot()
        return cur

    def _judge(
        self,
        before_screen: MatLike,
        after_screen: MatLike,
        board: PuzzleBoard,
        source: PuzzleCell,
        target: PuzzleCell,
    ) -> OperationRoundResult:
        """看这一次拖拽的结果，更新「位置 -> 块」的对应关系。"""
        self._steps += 1

        src_key: CellKey = (source.row, source.col)
        tgt_key: CellKey = (target.row, target.col)

        moved = (
            cell_difference(before_screen, after_screen, source.rect) > _MOVE_THRESHOLD
            or cell_difference(before_screen, after_screen, target.rect)
            > _MOVE_THRESHOLD
        )
        if not moved:
            return self._handle_no_change(src_key, tgt_key)

        # 拖成功了：拖动本身没问题，这两格都能拖，清掉它们的拖不通记录
        self._pending = None
        self._src_dead.pop(src_key, None)
        self._tgt_dead.pop(tgt_key, None)
        self._src_dead.pop(tgt_key, None)
        self._tgt_dead.pop(src_key, None)

        src_block = self._block_at.get(src_key)
        tgt_block = self._block_at.get(tgt_key)
        if src_block is None or tgt_block is None:
            self._sync_blocks(board)
            return self.round_wait('重建块的记录', wait=0.1)

        # 两块互换：块跟着位置一起换
        self._block_at[src_key] = tgt_block
        self._block_at[tgt_key] = src_block

        # 拖过去的那块在目标格变暗 = 放对了；没变暗 = 它不属于这一格。
        # 被顶回来的那块同理，一次拖拽能确认两个位置。
        src_locked = not target.movable
        tgt_locked = not source.movable
        if src_locked:
            self._tried.pop(src_block, None)
            self._block_at.pop(tgt_key, None)
            self._retired.pop(tgt_key, None)
        else:
            self._tried.setdefault(src_block, set()).add(tgt_key)
        if tgt_locked:
            self._tried.pop(tgt_block, None)
            self._block_at.pop(src_key, None)
            self._retired.pop(src_key, None)
        else:
            self._tried.setdefault(tgt_block, set()).add(src_key)

        if src_locked or tgt_locked:
            # 锁定的格子会影响邻居的边线，交给下一轮的整块重认去处理。
            # 有进展就清掉各种「不再试」的记号，让后面的格子重新参与。
            self._failed_pairs.clear()
            self._done_sources.clear()
            self._bounced.clear()
            return self.round_wait('放对一块', wait=0.15)
        return self.round_wait('两块互换', wait=0.05)

    def _handle_no_change(
        self, src_key: CellKey, tgt_key: CellKey
    ) -> OperationRoundResult:
        """拖过去两格都没变，判断这一对是「没拖动」还是「真不通」。

        一次没反应不能定论：拖动偶尔会不生效（按下早了点、落位还没稳），重拖一次
        通常就好了。同一对连着两次都没反应才算真不通。随机失败两次都失败的概率是
        p²，三成失败率下也只有 9%，而且下一轮清空重来还能纠正。

        真不通时两端都记一笔。一个拖不动的格子换谁当对手都不动，攒够 _DEAD_NEIGHBORS
        个不同的对手就判定它自己拖不动、整个剔掉 —— 这样它最多白撞几次就退出，
        不会像之前那样把 35 个目标格全撞一遍。
        """
        pair = _pair(src_key, tgt_key)
        if self._pending == pair:
            # 连着两次都没反应，这一对真不通
            self._pending = None
            self._failed_pairs.add(pair)
            dead_targets = self._src_dead.setdefault(src_key, set())
            dead_targets.add(tgt_key)
            dead_sources = self._tgt_dead.setdefault(tgt_key, set())
            dead_sources.add(src_key)
            if len(dead_targets) >= _DEAD_NEIGHBORS:
                self._ghost.add(src_key)
                return self.round_wait('这一格拖不动，跳过', wait=0.1)
            if len(dead_sources) >= _DEAD_NEIGHBORS:
                self._ghost.add(tgt_key)
                return self.round_wait('这一格拖不动，跳过', wait=0.1)
            return self.round_wait('这一对真不通，换一个', wait=0.1)

        # 第一次没反应，原样再拖一次确认
        self._pending = pair
        return self.round_wait('重拖一次确认', wait=0.1)

    def _sync_blocks(self, board: PuzzleBoard) -> None:
        """给新出现的亮格分配块号，暗掉的格子把块号暂存起来。"""
        alive: set[CellKey] = {(cell.row, cell.col) for cell in board.movable_cells}
        for key in list(self._block_at.keys()):
            if key not in alive:
                self._retired[key] = self._block_at.pop(key)
        for key in alive:
            if key in self._block_at:
                continue
            if key in self._retired:
                # 相邻格锁定会让这一格的边线跟着变，偶尔一帧判错成暗格。
                # 沿用原来的块号，它试过哪些位置的记录才不会丢。
                self._block_at[key] = self._retired.pop(key)
            else:
                self._block_at[key] = self._next_block_id
                self._next_block_id += 1

    def _pick_move(self, board: PuzzleBoard) -> tuple[PuzzleCell, PuzzleCell] | None:
        """挑一次拖拽：源格选候选最少的那块，目标格取它的第一个候选。"""
        movable = [
            cell
            for cell in board.movable_cells
            if (cell.row, cell.col) not in self._ghost
        ]
        if len(movable) < 2:
            return None

        # 上一轮没确认的那一对优先重拖，别跳过它去挑新的
        pending = self._pending
        if pending is not None:
            for cell in movable:
                if (cell.row, cell.col) == pending[0]:
                    other = board.cells[pending[1][0]][pending[1][1]]
                    if other.movable:
                        return cell, other

        while True:
            best: tuple[int, PuzzleCell, list[PuzzleCell]] | None = None
            for cell in movable:
                key: CellKey = (cell.row, cell.col)
                if key in self._done_sources:
                    continue
                candidates = self._candidates(cell, movable)
                if best is None or len(candidates) < best[0]:
                    best = (len(candidates), cell, candidates)

            if best is None:
                return None
            _, cell, candidates = best
            if candidates:
                return cell, candidates[0]

            # 这一块的其它亮格全试过了还不锁定，说明它就在自己的位置上，只是游戏
            # 没给它落位的机会。先把它挪到别的亮格，下一轮它就只剩原来那一格没试过，
            # 拖回去就会锁定。每个块只兜底一次，兜完还不锁定就跳过，否则会来回打转。
            key = (cell.row, cell.col)
            block = self._block_at.get(key)
            others = [
                other
                for other in movable
                if (other.row, other.col) != key
                and _pair(key, (other.row, other.col)) not in self._failed_pairs
            ]
            if block is None or block in self._bounced or not others:
                self._done_sources.add(key)
                continue
            self._bounced.add(block)
            return cell, others[0]

    def _candidates(
        self, cell: PuzzleCell, movable: list[PuzzleCell]
    ) -> list[PuzzleCell]:
        """这一格上的块还没试过、且拖动确实有反应的目标格。"""
        key: CellKey = (cell.row, cell.col)
        block = self._block_at.get(key)
        tried = self._tried.get(block, set()) if block is not None else set()
        return [
            other
            for other in movable
            if (other.row, other.col) != key
            and (other.row, other.col) not in tried
            and _pair(key, (other.row, other.col)) not in self._failed_pairs
        ]
