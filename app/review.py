"""结果页“报数复核”。

适用前提（与页面条件一致）：
- 总册非空；
- 受理时的结果版本里，收录规则恰好引用两份名单，且这两份名单当时均为缺报。

此时两份名单各自在总册内的卷数 a、b 已由分馆确认，但具体卷号未知。
对任一整数 s（两份名单的交集卷数，取值范围见 :func:`intersection_range`），
四类归属的卷数完全由 a、b、s 决定：

    A∩B           = s
    A 且非 B      = a - s
    非 A 且 B     = b - s
    两者皆非      = N - a - b + s

规则只依赖这两份名单，因此同一归属的卷号入编结论相同。记 f(x, y) 为
“在 A 中 = x、在 B 中 = y”时的规则取值，则入编数为

    T(s) = f(0,0)·(N-a-b) + f(0,1)·b + f(1,0)·a
           + s·(f(0,0) - f(0,1) - f(1,0) + f(1,1))

即 T(s) = C + k·s。k ∈ {-2,-1,0,1,2}，所以可达入编数是一条等差序列：
k = ±2 时只出现同奇偶的值，这就是“填报数看似接近、实际达不到”的常见原因。

规则中重复引用同一名单时，求值始终按同一变量位取值，同一卷的归属天然一致。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

# 两份名单的四种归属，按 (在 A 中, 在 B 中) 索引
ASSIGNMENTS = ((0, 0), (0, 1), (1, 0), (1, 1))


class ReviewError(ValueError):
    """复核输入或前提不满足。"""


# ---------------------------------------------------------------- 规则取值

def collect_ref_names(doc) -> set[str]:
    """收集规则 JSON 中引用的全部名单名（不校验名单是否登记）。"""
    names: set[str] = set()

    def walk(node):
        if isinstance(node, str):
            if node.strip():
                names.add(node.strip())
            return
        if isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(doc)
    return names


def evaluate_two_lists(tree: dict, names: list[str]) -> dict[tuple[int, int], int]:
    """把只引用两份名单的规范化规则树求成 2×2 真值表。

    名单名按 names 的顺序绑定变量位；重复引用读同一位，因此同一卷的归属始终一致。
    两份名单之外出现任何引用都属前提不满足，直接抛 ReviewError。
    """
    position = {name: i for i, name in enumerate(names)}

    def walk(node, values: tuple[int, ...]) -> int:
        if node["type"] == "ref":
            idx = position.get(node["name"])
            if idx is None:
                raise ReviewError(f"规则引用了名单《{node['name']}》，不是本次复核的两份缺报名单")
            return values[idx]
        children = node["children"]
        if node["op"] == "union":
            return 1 if any(walk(child, values) for child in children) else 0
        if node["op"] == "intersect":
            return 1 if all(walk(child, values) for child in children) else 0
        return 1 if (walk(children[0], values) and not walk(children[1], values)) else 0

    return {
        assignment: walk(tree, assignment)
        for assignment in ASSIGNMENTS
    }


# ---------------------------------------------------------------- 可达入编数

def intersection_range(total: int, count_a: int, count_b: int) -> tuple[int, int]:
    """两份名单交集卷数的所有可能取值（闭区间）。"""
    return max(0, count_a + count_b - total), min(count_a, count_b)


@dataclass(frozen=True)
class ReviewMath:
    total: int
    count_a: int
    count_b: int
    table: dict[tuple[int, int], int]
    base: int          # T(s) = base + step_signed * s
    step_signed: int   # k
    s_min: int
    s_max: int

    @property
    def step(self) -> int:
        return abs(self.step_signed)

    @property
    def constant(self) -> bool:
        return self.step_signed == 0

    def inclusion(self, s: int) -> int:
        return self.base + self.step_signed * s

    @property
    def min_inclusion(self) -> int:
        return min(self.inclusion(self.s_min), self.inclusion(self.s_max))

    @property
    def max_inclusion(self) -> int:
        return max(self.inclusion(self.s_min), self.inclusion(self.s_max))

    def is_achievable(self, value: int) -> bool:
        if not (self.min_inclusion <= value <= self.max_inclusion):
            return False
        if self.step_signed == 0:
            return value == self.base
        return (value - self.base) % self.step_signed == 0 and \
            self.s_min <= (value - self.base) // self.step_signed <= self.s_max


def build_math(total: int, count_a: int, count_b: int,
               table: dict[tuple[int, int], int]) -> ReviewMath:
    if total <= 0:
        raise ReviewError("总册为空，无法复核")
    for value, label in ((count_a, "名单一"), (count_b, "名单二")):
        if not isinstance(value, int) or isinstance(value, bool):
            raise ReviewError(f"{label}卷数必须是整数")
        if not 0 <= value <= total:
            raise ReviewError(f"{label}卷数必须在 0 到总册卷数 {total} 之间")

    s_min, s_max = intersection_range(total, count_a, count_b)
    base = (table[(0, 0)] * (total - count_a - count_b)
            + table[(0, 1)] * count_b
            + table[(1, 0)] * count_a)
    step = (table[(0, 0)] - table[(0, 1)]
            - table[(1, 0)] + table[(1, 1)])
    return ReviewMath(total, count_a, count_b, table, base, step, s_min, s_max)


def nearest_inclusion(math: ReviewMath, reported: int) -> list[dict]:
    """返回与填报值最接近的可达入编数；两侧等距时同时返回两个。

    每个元素含 count（入编数）、distance、s（用于构造示例名单的交集卷数）。
    """
    if not isinstance(reported, int) or isinstance(reported, bool):
        raise ReviewError("待复核的入编数必须是整数")
    if not 0 <= reported <= math.total:
        raise ReviewError(f"待复核的入编数必须在 0 到总册卷数 {math.total} 之间")

    if math.constant:
        return [{"count": math.base, "distance": abs(math.base - reported),
                 "s": math.s_min}]

    k = math.step_signed
    # k·s = reported - base；只需比较夹住目标的两个整数 s（再受可行区间约束）
    floor_s = (reported - math.base) // k
    candidates: dict[int, int] = {}
    for s in (floor_s - 1, floor_s, floor_s + 1, floor_s + 2,
              math.s_min, math.s_max):
        s = max(math.s_min, min(math.s_max, s))
        candidates[math.inclusion(s)] = s

    best = min(abs(value - reported) for value in candidates)
    out = [{"count": value, "distance": abs(value - reported), "s": s}
           for value, s in candidates.items() if abs(value - reported) == best]
    out.sort(key=lambda item: item["count"])
    return out


# ---------------------------------------------------------------- 示例名单

def sample_membership(total: int, count_a: int, count_b: int, intersection: int,
                      volumes: list[str]) -> tuple[list[str], list[str]]:
    """构造一对满足两项报数、交集为 intersection 的示例名单。

    卷号取自受理版本的卷序（result_item 的写入顺序），只需保证两列表长度与交集正确。
    A = 前 a 个卷号；B = 前 s 个（交集）+ A 之后的 b-s 个。重复引用不影响归属一致性。
    """
    if len(volumes) != total:
        raise ReviewError("版本卷号数量与版本记录不一致，无法生成示例名单")
    lo, hi = intersection_range(total, count_a, count_b)
    if not lo <= intersection <= hi:
        raise ReviewError(f"交集卷数必须在 {lo} 到 {hi} 之间")
    if count_a + (count_b - intersection) > total:
        raise ReviewError("报数与交集组合超出总册范围")

    list_a = list(volumes[:count_a])
    list_b = list(volumes[:intersection]) + list(volumes[count_a:count_a + count_b - intersection])
    if len(list_a) != count_a or len(list_b) != count_b:
        raise ReviewError("示例名单长度与报数不一致")
    return list_a, list_b


def count_inclusion_over(rule_values: dict[tuple[int, int], int],
                         volumes: Iterable[str], list_a: Iterable[str],
                         list_b: Iterable[str]) -> int:
    """在完整总册卷序上按规则复算入编数。"""
    in_a = set(list_a)
    in_b = set(list_b)
    return sum(rule_values[(1 if volume in in_a else 0,
                            1 if volume in in_b else 0)]
               for volume in volumes)


def format_inclusion_formula(math: ReviewMath) -> str:
    """把 T(s) 展示成便于手算的式子。"""
    sign = "+" if math.step_signed >= 0 else "−"
    step = abs(math.step_signed)
    if step == 0:
        return f"入编数恒为 {math.base}"
    if step == 1:
        tail = f"{sign} s"
    else:
        tail = f"{sign} {step}·s"
    return (f"入编数 = {math.base} {tail}，s 为两份名单的交集卷数，"
            f"取值范围 {math.s_min}–{math.s_max}")
