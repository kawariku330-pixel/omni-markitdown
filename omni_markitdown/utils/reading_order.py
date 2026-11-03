"""読み順の復元 (再帰 XY-cut)

ページ上の矩形を「全幅の空白帯で上下に切る」「縦の空白帯で段に切る」を
繰り返して分け、段組・縦書きでも自然な読み順に並べる。

- 横書き: 上の帯 → 下の帯、同じ帯の中では 左の段 → 右の段（各段は上から下）
- 縦書き: 右の列 → 左の列、同じ列の中では 上から下
"""

from __future__ import annotations

from typing import Callable, List, Sequence, Tuple, TypeVar

T = TypeVar("T")
BBox = Tuple[float, float, float, float]  # (x0, y0, x1, y1)


def _gaps(intervals: List[Tuple[float, float]], min_gap: float) -> List[Tuple[float, float]]:
    """区間の並びから、min_gap 以上空いている切れ目を (位置, 幅) で返す"""
    if not intervals:
        return []
    intervals = sorted(intervals)
    cuts: List[Tuple[float, float]] = []
    cur_end = intervals[0][1]
    for start, end in intervals[1:]:
        if start - cur_end >= min_gap:
            cuts.append(((cur_end + start) / 2.0, start - cur_end))
        cur_end = max(cur_end, end)
    return cuts


def _split_at(items: List[T], get_bbox: Callable[[T], BBox], axis: int, cuts: List[float]) -> List[List[T]]:
    """axis=1 なら y 方向（上下）、axis=0 なら x 方向（左右）で cuts の位置に分割する"""
    lo, hi = (1, 3) if axis == 1 else (0, 2)
    groups: List[List[T]] = [[] for _ in range(len(cuts) + 1)]
    for it in items:
        b = get_bbox(it)
        center = (b[lo] + b[hi]) / 2.0
        groups[sum(1 for c in cuts if center > c)].append(it)
    return [g for g in groups if g]


def xy_cut_order(
    items: Sequence[T],
    get_bbox: Callable[[T], BBox],
    vertical: bool = False,
    min_gap: float = 3.0,
) -> List[T]:
    """矩形を持つ要素を読み順に並べて返す

    各段階で「上下の空白帯」と「左右の空白帯」のうち幅の大きい方で切る。
    2段組では段の間の溝（左右）が行間（上下）より広いので、先に段で分かれる。
    全幅の見出しの下は見出しが溝をまたぐので、先に上下で分かれる。
    """
    items = list(items)
    if len(items) <= 1:
        return items

    y_cuts = _gaps([(get_bbox(i)[1], get_bbox(i)[3]) for i in items], min_gap)
    x_cuts = _gaps([(get_bbox(i)[0], get_bbox(i)[2]) for i in items], min_gap)
    max_y = max((w for _, w in y_cuts), default=0.0)
    max_x = max((w for _, w in x_cuts), default=0.0)

    if not y_cuts and not x_cuts:
        if vertical:
            return sorted(items, key=lambda i: (-get_bbox(i)[2], get_bbox(i)[1]))
        return sorted(items, key=lambda i: (get_bbox(i)[1], get_bbox(i)[0]))

    # 縦書きは同じ幅なら列（左右）を優先、横書きは帯（上下）を優先
    use_x = max_x > max_y if not vertical else max_x >= max_y
    if use_x:
        # いちばん広い溝だけで切る（細かい溝は再帰の中で判断する）
        pos = max(x_cuts, key=lambda c: c[1])[0]
        groups = _split_at(items, get_bbox, 0, [pos])
        if vertical:
            groups.reverse()  # 右の列から読む
    else:
        pos = max(y_cuts, key=lambda c: c[1])[0]
        groups = _split_at(items, get_bbox, 1, [pos])
    if len(groups) <= 1:
        return sorted(items, key=lambda i: (get_bbox(i)[1], get_bbox(i)[0]))
    return [x for g in groups for x in xy_cut_order(g, get_bbox, vertical, min_gap)]
