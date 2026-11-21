"""拼图面板识别。

面板内是 n×n 个等大格子，格子之间用黑色分隔线隔开：
- 可拖动的碎块是独立一块，四条边都有黑线；
- 已经拼好的部分多格连成一片，格与格之间没有黑线。
所以用「这一格四条边里有几条黑线」判断它能不能拖。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np
from cv2.typing import MatLike
from one_dragon.base.geometry.rectangle import Rect

_DARK_GRAY: int = 45
"""判定黑线的灰度上限。"""
_LINE_COVER: float = 0.6
"""黑线沿整条边的最低覆盖比例。"""
_LINE_CONTRAST: float = 12.0
"""黑线与两侧的亮度差基准，差值达到该值才算一条线。"""
_MOVABLE_EDGE_SCORE: float = 3.5
"""四条边的黑线得分之和达到该值才当作可拖动；独立碎块四边齐全，实测都在 4.0。"""
_GRID_SIZES: tuple[int, ...] = (3, 4, 5, 6)
"""游戏里出现过的拼图格数。"""
_REF_WIDTH: int = 1920
"""区域配置使用的基准宽度。"""
_BASE_REACH: int = 8
"""基准分辨率下找黑线时向两侧搜索的像素数。"""
_BASE_INSET: int = 8
"""基准分辨率下判断格子边线时向格内收缩的像素数。"""




@dataclass
class PuzzleCell:
    """面板里的一个格子。"""

    row: int
    col: int
    rect: Rect
    edge_score: float = 0.0
    movable: bool = False


@dataclass
class PuzzleBoard:
    """一次识别出的整个拼图面板。"""

    size: int
    cells: list[list[PuzzleCell]] = field(default_factory=list)
    reach: int = _BASE_REACH
    inset: int = _BASE_INSET

    @property
    def movable_cells(self) -> list[PuzzleCell]:
        """所有还能拖动的格子。"""
        return [cell for line in self.cells for cell in line if cell.movable]

    @property
    def is_finished(self) -> bool:
        """没有任何可拖动的格子就是拼完了。"""
        return len(self.movable_cells) == 0


def _vertical_line_score(
    gray: np.ndarray, x: int, y1: int, y2: int, reach: int
) -> float:
    """x 附近是否有一条竖直黑线，返回 0~1 的得分。"""
    if y2 - y1 < 20:
        return 0.0
    left_edge = max(0, x - reach)
    seg = gray[y1:y2, left_edge : x + reach + 1].astype(np.float32)
    if seg.shape[1] < 6:
        return 0.0
    best = 0.0
    for dx in range(2, seg.shape[1] - 2):
        col = seg[:, dx]
        cover = float((col < _DARK_GRAY).mean())
        if cover < _LINE_COVER:
            continue
        side_left = seg[:, max(0, dx - 3) : dx - 1].mean(axis=1)
        side_right = seg[:, dx + 2 : dx + 4].mean(axis=1)
        contrast = float(((side_left - col).mean() + (side_right - col).mean()) / 2)
        best = max(best, cover * min(1.0, max(0.0, contrast) / _LINE_CONTRAST))
    return best


def _horizontal_line_score(
    gray: np.ndarray, y: int, x1: int, x2: int, reach: int
) -> float:
    """y 附近是否有一条横向黑线，返回 0~1 的得分。"""
    if x2 - x1 < 20:
        return 0.0
    top_edge = max(0, y - reach)
    seg = gray[top_edge : y + reach + 1, x1:x2].astype(np.float32)
    if seg.shape[0] < 6:
        return 0.0
    best = 0.0
    for dy in range(2, seg.shape[0] - 2):
        row = seg[dy, :]
        cover = float((row < _DARK_GRAY).mean())
        if cover < _LINE_COVER:
            continue
        side_up = seg[max(0, dy - 3) : dy - 1, :].mean(axis=0)
        side_down = seg[dy + 2 : dy + 4, :].mean(axis=0)
        contrast = float(((side_up - row).mean() + (side_down - row).mean()) / 2)
        best = max(best, cover * min(1.0, max(0.0, contrast) / _LINE_CONTRAST))
    return best


def _cell_edge_score(
    gray: np.ndarray, cell: PuzzleCell, size: int, reach: int, inset: int
) -> float:
    """算这一格四条边的黑线得分之和。面板外沿的四条边直接算满分。"""
    score = 0.0
    if cell.row > 0:
        score += _horizontal_line_score(
            gray, cell.rect.y1, cell.rect.x1 + inset, cell.rect.x2 - inset, reach
        )
    else:
        score += 1.0
    if cell.row < size - 1:
        score += _horizontal_line_score(
            gray, cell.rect.y2, cell.rect.x1 + inset, cell.rect.x2 - inset, reach
        )
    else:
        score += 1.0
    if cell.col > 0:
        score += _vertical_line_score(
            gray, cell.rect.x1, cell.rect.y1 + inset, cell.rect.y2 - inset, reach
        )
    else:
        score += 1.0
    if cell.col < size - 1:
        score += _vertical_line_score(
            gray, cell.rect.x2, cell.rect.y1 + inset, cell.rect.y2 - inset, reach
        )
    else:
        score += 1.0
    return score


def _score_matrix(
    gray: np.ndarray, area: Rect, size: int, reach: int, inset: int
) -> list[list[float]]:
    """按 size 划分时，每格四条边的黑线得分。"""
    cw = area.width / size
    ch = area.height / size
    matrix: list[list[float]] = []
    for row in range(size):
        line: list[float] = []
        for col in range(size):
            cell = PuzzleCell(
                row=row,
                col=col,
                rect=Rect(
                    area.x1 + col * cw,
                    area.y1 + row * ch,
                    area.x1 + (col + 1) * cw,
                    area.y1 + (row + 1) * ch,
                ),
            )
            line.append(_cell_edge_score(gray, cell, size, reach, inset))
        matrix.append(line)
    return matrix


def _count_movable(matrix: list[list[float]]) -> int:
    """矩阵里有几个四边齐全的独立碎块。"""
    return sum(1 for line in matrix for score in line if score >= _MOVABLE_EDGE_SCORE)


def detect_grid_size(
    gray: np.ndarray, area: Rect, reach: int, inset: int, hint: int | None = None
) -> tuple[int, list[list[float]]]:
    """找出面板是几格，同时返回该格数下每格的边线得分。

    判据是「这个格数划分下，能数出几个四边齐全的独立碎块」。只有格数对了，
    碎块的边才会正好落在划分出来的格线上；格数错了，格线歪掉，四边基本凑不齐。
    实测同一张截图：6 格图按 3/4/5 格划分一个碎块都数不出来，按 6 格数得出 4 个。

    按「内部线平均分」判不行：6 格的分割点里含 3 格的 1/3、2/3，6 格图按 3 格算
    平均分反而更高；拼到后期内部线越来越少，平均分整体掉下来，会把 6 格判成 3 格，
    再往下就是「全是暗格 = 拼完了」的误判。

    一张拼图里的格数从头到尾不会变，所以上一轮判出来就沿用，省掉重复计算。
    只有沿用的格数在当前画面一个亮块都数不出来时，才重新判。

    Args:
        gray: 灰度图。
        area: 面板内区。
        reach: 找黑线时向两侧搜索的像素数。
        inset: 判断格子边线时向格内收缩的像素数。
        hint: 上一轮判出的格数，没有时为 None。

    Returns:
        格数和该格数下每格的边线得分矩阵。
    """
    if hint is not None and hint in _GRID_SIZES:
        matrix = _score_matrix(gray, area, hint, reach, inset)
        hint_count = _count_movable(matrix)
        if hint_count > 0:
            # 格数判错了只会是「把大格数判成小格数」：小格数的格线是大格数格线的
            # 子集，所以一定整除。只跟倍数比一次就够，不用每帧全扫。
            best_size = hint
            best_count = hint_count
            best_matrix = matrix
            for size in _GRID_SIZES:
                if size <= hint or size % hint != 0:
                    continue
                other = _score_matrix(gray, area, size, reach, inset)
                count = _count_movable(other)
                if count > best_count:
                    best_size = size
                    best_count = count
                    best_matrix = other
            return best_size, best_matrix
        # 沿用的格数一个亮块都数不出来，两种可能：真的拼完了，或者沿用的格数本身就
        # 错了（比如上一帧误判）。必须重扫一遍才能分清，不能直接当成拼完。

    best_size: int | None = None
    best_count = 0
    best_matrix: list[list[float]] = []
    # 倒序：数量并列时保留格子多的那个
    for size in sorted(_GRID_SIZES, reverse=True):
        matrix = _score_matrix(gray, area, size, reach, inset)
        count = _count_movable(matrix)
        if count > best_count:
            best_size = size
            best_count = count
            best_matrix = matrix

    if best_size is not None:
        return best_size, best_matrix

    # 一个亮块都数不出来：面板已经拼完，格数不影响结论
    size = _GRID_SIZES[0]
    return size, _score_matrix(gray, area, size, reach, inset)


def analyze_board(
    screen: MatLike, rect: Rect, hint_size: int | None = None
) -> PuzzleBoard | None:
    """识别整个面板。识别不出来返回 None。

    Args:
        screen: 游戏截图，尺寸按实际截图走，内部按基准宽度换算。
        rect: 面板内区，坐标为基准分辨率。
        hint_size: 上一轮判出的格数，用于拼到后期时稳定格数。
    """
    if screen is None or rect is None:
        return None
    if screen.ndim != 3 or screen.shape[0] < 60 or screen.shape[1] < 60:
        return None

    scale = screen.shape[1] / _REF_WIDTH
    area = Rect(rect.x1 * scale, rect.y1 * scale, rect.x2 * scale, rect.y2 * scale)
    if area.width < 90 or area.height < 90:
        return None

    gray = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY).astype(np.float32)
    reach = max(4, round(_BASE_REACH * scale))
    inset = max(4, round(_BASE_INSET * scale))
    size, matrix = detect_grid_size(gray, area, reach, inset, hint_size)

    cw = area.width / size
    ch = area.height / size
    board = PuzzleBoard(size=size, reach=reach, inset=inset)
    for row in range(size):
        line: list[PuzzleCell] = []
        for col in range(size):
            cell = PuzzleCell(
                row=row,
                col=col,
                rect=Rect(
                    area.x1 + col * cw,
                    area.y1 + row * ch,
                    area.x1 + (col + 1) * cw,
                    area.y1 + (row + 1) * ch,
                ),
            )
            cell.edge_score = matrix[row][col]
            cell.movable = cell.edge_score >= _MOVABLE_EDGE_SCORE
            line.append(cell)
        board.cells.append(line)
    return board


def refresh_cells(
    screen: MatLike, board: PuzzleBoard, cells: list[PuzzleCell]
) -> None:
    """只重算指定格子的明暗，其余沿用上一帧的结果。

    拖一次只动两个格子，整块面板重新算一遍太浪费。
    """
    gray = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY).astype(np.float32)
    for cell in cells:
        cell.edge_score = _cell_edge_score(
            gray, cell, board.size, board.reach, board.inset
        )
        cell.movable = cell.edge_score >= _MOVABLE_EDGE_SCORE


def cell_difference(before: MatLike, after: MatLike, rect: Rect) -> float:
    """两帧里同一格的平均灰度差，用来判断这块到底有没有动。"""
    if before is None or after is None:
        return 0.0
    x1 = max(0, rect.x1)
    y1 = max(0, rect.y1)
    x2 = min(after.shape[1], rect.x2, before.shape[1])
    y2 = min(after.shape[0], rect.y2, before.shape[0])
    if x2 - x1 < 8 or y2 - y1 < 8:
        return 0.0
    g1 = cv2.cvtColor(before[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY).astype(np.float32)
    g2 = cv2.cvtColor(after[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY).astype(np.float32)
    return float(np.abs(g1 - g2).mean())
