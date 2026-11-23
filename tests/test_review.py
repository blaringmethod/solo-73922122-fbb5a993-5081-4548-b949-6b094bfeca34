"""报数复核：规则取值、可达集合、示例名单与版本快照。

覆盖：
- 两份名单为并/交/差、重复引用时的 2×2 真值表；
- 可达入编数是 T(s)=C+k·s，k=±2 时只出现同奇偶值（“达不到”的典型情形）；
- 最接近值及等距双列；
- 示例名单严格满足两项报数，并按规则复算得到目标入编数；
- 表单版号校验、受理后被补报/发版仍按受理版本复核。
"""

import io
import json

import pytest

from app.logic import parse_rule
from app.review import (ReviewError, build_math, count_inclusion_over,
                        evaluate_two_lists, intersection_range,
                        nearest_inclusion, sample_membership)


def table_for(rule_doc, names=("甲", "乙")):
    tree = parse_rule(rule_doc, names)
    return tree, evaluate_two_lists(tree, list(names))


# ---------------------------------------------------------------- 规则取值

@pytest.mark.parametrize("rule_doc,expected", [
    ({"并": ["甲", "乙"]}, {(0, 0): 0, (0, 1): 1, (1, 0): 1, (1, 1): 1}),
    ({"交": ["甲", "乙"]}, {(0, 0): 0, (0, 1): 0, (1, 0): 0, (1, 1): 1}),
    ({"差": ["甲", "乙"]}, {(0, 0): 0, (0, 1): 0, (1, 0): 1, (1, 1): 0}),
    # 重复引用：必须按同一变量位取值（各自等价于只引用甲）
    ({"差": ["甲", {"交": ["甲", "乙"]}]},
     {(0, 0): 0, (0, 1): 0, (1, 0): 1, (1, 1): 0}),
    ({"并": ["甲", {"交": ["甲", "乙"]}]},
     {(0, 0): 0, (0, 1): 0, (1, 0): 1, (1, 1): 1}),
    ({"差": ["甲", "甲"]}, {(0, 0): 0, (0, 1): 0, (1, 0): 0, (1, 1): 0}),
])
def test_two_list_truth_table(rule_doc, expected):
    _, table = table_for(rule_doc)
    assert table == expected


def test_repeated_reference_is_not_independent():
    """重复引用按同一变量位取值，等价于只引用一次，而不是引入第二个独立变量。"""
    _, table = table_for({"差": ["甲", {"交": ["甲", "乙"]}]})
    # A − (A∩B) 等价于 A − B
    _, diff = table_for({"差": ["甲", "乙"]})
    assert table == diff
    assert table[(1, 0)] == 1 and table[(0, 1)] == 0

    # 若把并集里的两个“甲”当独立变量，x=0 时仍可能靠第二个“甲”入选；
    # 同一归属下并集必须与单个“甲”完全一致。
    _, doubled = table_for({"并": ["甲", "甲"]})
    _, single = table_for({"并": ["甲"]})
    assert doubled == single
    assert doubled[(0, 1)] == 0


def test_rejects_extra_reference():
    tree = parse_rule({"并": ["甲", "乙", "丙"]}, ["甲", "乙", "丙"])
    with pytest.raises(ReviewError):
        evaluate_two_lists(tree, ["甲", "乙"])


# ---------------------------------------------------------------- 可达集合

def test_union_is_an_interval_with_step_one():
    _, table = table_for({"并": ["甲", "乙"]})
    m = build_math(10, 4, 5, table)
    # T = 9 - s，s∈[0,4] -> 5..9
    assert (m.s_min, m.s_max) == (0, 4)
    assert m.inclusion(0) == 9 and m.inclusion(4) == 5
    assert m.min_inclusion == 5 and m.max_inclusion == 9
    assert all(m.is_achievable(v) for v in range(5, 10))
    assert not m.is_achievable(4) and not m.is_achievable(10)


def test_diff_gives_parity_only():
    """两次引用同一名单的差集会出现步长 2：只能得到同奇偶的入编数。"""
    _, table = table_for({"差": ["甲", {"交": ["甲", "乙"]}]})
    m = build_math(10, 4, 5, table)
    # T = a - s = 4 - s，s∈[0,4] -> 0..4 全部可达
    assert m.step_signed == -1
    assert {m.inclusion(s) for s in range(5)} == {0, 1, 2, 3, 4}

    # 构造 k=±2：规则 A △ B（对称差）的布尔表达为 (A∪B)−(A∩B)，其取值为异或
    _, xor_table = table_for({"差": [{"并": ["甲", "乙"]}, {"交": ["甲", "乙"]}]})
    assert xor_table == {(0, 0): 0, (0, 1): 1, (1, 0): 1, (1, 1): 0}
    mx = build_math(10, 4, 5, xor_table)
    # T = a + b - 2s = 9 - 2s，s∈[0,4] -> 9,7,5,3,1
    assert mx.step_signed == -2
    assert {mx.inclusion(s) for s in range(5)} == {9, 7, 5, 3, 1}
    assert not mx.is_achievable(8) and not mx.is_achievable(0)


def test_nearest_reports_gap_and_tie():
    _, table = table_for({"差": [{"并": ["甲", "乙"]}, {"交": ["甲", "乙"]}]})
    m = build_math(10, 4, 5, table)  # 可达 1,3,5,7,9
    # 填报 8：最近 7 与 9 等距，应都列出
    near = nearest_inclusion(m, 8)
    assert [item["count"] for item in near] == [7, 9]
    assert all(item["distance"] == 1 for item in near)
    # 填报 0：最近 1
    assert [item["count"] for item in nearest_inclusion(m, 0)] == [1]
    # 填报 5：恰好可达
    assert [item["count"] for item in nearest_inclusion(m, 5)] == [5]


def test_reported_out_of_range_rejected():
    _, table = table_for({"并": ["甲", "乙"]})
    m = build_math(10, 4, 5, table)
    with pytest.raises(ReviewError):
        nearest_inclusion(m, 11)
    with pytest.raises(ReviewError):
        build_math(10, 11, 5, table)
    with pytest.raises(ReviewError):
        build_math(0, 0, 0, table)


def test_intersection_range():
    assert intersection_range(10, 4, 5) == (0, 4)
    assert intersection_range(10, 9, 8) == (7, 8)
    assert intersection_range(5, 0, 0) == (0, 0)


# ---------------------------------------------------------------- 示例名单

@pytest.mark.parametrize("rule_doc", [
    {"并": ["甲", "乙"]},
    {"交": ["甲", "乙"]},
    {"差": ["甲", "乙"]},
    {"差": ["甲", {"交": ["甲", "乙"]}]},
    {"差": [{"并": ["甲", "乙"]}, {"交": ["甲", "乙"]}]},
])
def test_sample_lists_are_consistent_and_recompute(rule_doc):
    total, ca, cb = 23, 8, 11
    _, table = table_for(rule_doc)
    m = build_math(total, ca, cb, table)
    volumes = [f"V{i:03d}" for i in range(total)]
    for s in range(m.s_min, m.s_max + 1):
        list_a, list_b = sample_membership(total, ca, cb, s, volumes)
        assert len(list_a) == ca and len(list_b) == cb
        assert len(set(list_a) & set(list_b)) == s
        assert set(list_a) <= set(volumes) and set(list_b) <= set(volumes)
        assert count_inclusion_over(table, volumes, list_a, list_b) == m.inclusion(s)


def test_every_achievable_value_has_witness():
    total, ca, cb = 37, 13, 21
    volumes = [f"V{i:03d}" for i in range(total)]
    for rule_doc in ({"并": ["甲", "乙"]}, {"差": [{"并": ["甲", "乙"]}, {"交": ["甲", "乙"]}]}):
        _, table = table_for(rule_doc)
        m = build_math(total, ca, cb, table)
        seen = set()
        for s in range(m.s_min, m.s_max + 1):
            la, lb = sample_membership(total, ca, cb, s, volumes)
            value = count_inclusion_over(table, volumes, la, lb)
            assert value == m.inclusion(s)
            assert m.is_achievable(value)
            seen.add(value)
        assert seen == {v for v in range(m.min_inclusion, m.max_inclusion + 1)
                        if m.is_achievable(v)}


def test_sample_membership_rejects_bad_intersection():
    volumes = [f"V{i}" for i in range(10)]
    with pytest.raises(ReviewError):
        sample_membership(10, 4, 5, 5, volumes)
    with pytest.raises(ReviewError):
        sample_membership(9, 4, 5, 0, volumes)


# ---------------------------------------------------------------- 端到端

def _setup_two_missing(client):
    data = "\n".join(f"V{i}" for i in range(1, 11)).encode()
    client.post("/volumes/upload", data={"file": (io.BytesIO(data), "v.txt")},
                content_type="multipart/form-data")
    client.post("/lists/register", data={"name": "甲馆", "kind": "accept"})
    client.post("/lists/register", data={"name": "乙馆", "kind": "accept"})
    # 对称差：入编数只能取同奇偶值
    client.post("/rules/save", data={
        "rule": '{"差":[{"并":["甲馆","乙馆"]},{"交":["甲馆","乙馆"]}]}'})


def test_review_page_shows_form_and_gap(client):
    _setup_two_missing(client)
    rv = client.get("/results")
    body = rv.data.decode()
    assert "报数复核" in body
    assert "甲馆" in body and "乙馆" in body
    assert 'name="form_version"' in body

    rv = client.post("/results", data={
        "count_a": "4", "count_b": "5", "reported": "8",
        "form_version": "1", "version_id": "1"})
    body = rv.data.decode()
    assert "等距" in body
    assert "可达入编数 7" in body and "可达入编数 9" in body


def test_review_recomputes_with_sample_lists(client, svc):
    _setup_two_missing(client)
    client.post("/results", data={
        "count_a": "4", "count_b": "5", "reported": "5",
        "form_version": "1", "version_id": "1"})
    conn = svc._conn()
    try:
        ctx = svc.review_page(conn, 1, {"count_a": "4", "count_b": "5",
                                        "reported": "5", "form_version": "1"})
    finally:
        conn.close()
    opt = ctx["result"]["options"][0]
    assert opt["count"] == opt["recomputed"] == 5
    assert len(opt["list_a"]) == 4 and len(opt["list_b"]) == 5
    assert len(set(opt["list_a"]) & set(opt["list_b"])) == opt["s"]


def test_review_rejects_stale_form_version(client):
    _setup_two_missing(client)
    rv = client.post("/results", data={
        "count_a": "4", "count_b": "5", "reported": "5",
        "form_version": "0", "version_id": "0"})
    body = rv.data.decode()
    assert "表单版号与现行版不符" in body
    assert "请重开结果页" in body

    # 旧页面打开后补报产生新版：再次提交仍须提示重开，不得按旧版结果继续
    client.post("/lists/1/upload",
                data={"file": (io.BytesIO(b"V1\n"), "a.txt")},
                content_type="multipart/form-data")
    rv = client.post("/results", data={
        "count_a": "4", "count_b": "5", "reported": "5",
        "form_version": "1", "version_id": "1"})
    assert "表单版号与现行版不符" in rv.data.decode()


def test_review_requires_exactly_two_missing_lists(client):
    client.post("/lists/register", data={"name": "甲馆", "kind": "accept"})
    data = "\n".join(f"V{i}" for i in range(1, 6)).encode()
    client.post("/volumes/upload", data={"file": (io.BytesIO(data), "v.txt")},
                content_type="multipart/form-data")
    # 规则只引用一份名单：不启用复核
    client.post("/rules/save", data={"rule": '{"并":["甲馆"]}'})
    body = client.get("/results").data.decode()
    assert "未启用复核" in body
    assert "当前引用 1 份" in body

    # 规则引用两份，但其中一份已提交：也不启用（复核前提是两份均缺报）
    client.post("/lists/register", data={"name": "乙馆", "kind": "accept"})
    client.post("/rules/save", data={
        "rule": '{"差":[{"并":["甲馆","乙馆"]},{"交":["甲馆","乙馆"]}]}'})
    client.post("/lists/1/upload",
                data={"file": (io.BytesIO(b"V1\n"), "a.txt")},
                content_type="multipart/form-data")
    body = client.get("/results").data.decode()
    assert "未启用复核" in body
    assert "缺报 1 份" in body


def test_legacy_version_without_name_snapshot_is_supported(svc):
    """升级前的历史版本没有名单快照，但规则恰好引用两份且当时缺报数为 2 时可复核。"""
    svc.replace_volumes(b"V1\nV2\nV3\nV4\n")
    svc.register_list("甲馆", "accept")
    svc.register_list("乙馆", "accept")
    svc.save_rule('{"并":["甲馆","乙馆"]}')
    conn = svc._conn()
    try:
        vid = svc.current_version_id(conn)
        # 模拟旧库：清空快照列
        conn.execute("UPDATE result_version SET missing_names_json = '[]' WHERE id = ?",
                     (vid,))
        conn.commit()
        ctx = svc.review_page(conn, vid, {"count_a": "2", "count_b": "3",
                                          "reported": "4", "form_version": str(vid)})
    finally:
        conn.close()
    assert ctx["eligible"] is True
    assert ctx["result"] is not None
    # 并集：T = 5 - s，s∈[1,2] -> 4 或 3；填报 4 恰好可达
    assert ctx["result"]["options"][0]["count"] == 4


def test_review_at_50k_volumes(svc):
    """上限规模：5 万卷的复核与示例名单构造应保持在线可交互。"""
    import time

    svc.replace_volumes(("\n".join(f"V{i:06d}" for i in range(50000)) + "\n").encode())
    svc.register_list("甲馆", "scan")
    svc.register_list("乙馆", "accept")
    svc.save_rule('{"差":[{"并":["甲馆","乙馆"]},{"交":["甲馆","乙馆"]}]}')
    conn = svc._conn()
    try:
        vid = svc.current_version_id(conn)
        t0 = time.perf_counter()
        ctx = svc.review_page(conn, vid, {"count_a": "18000", "count_b": "22000",
                                          "reported": "30051",
                                          "form_version": str(vid)})
        elapsed = time.perf_counter() - t0
    finally:
        conn.close()
    assert ctx["eligible"] is True and ctx["result"] is not None
    # 对称差：T = 40000 - 2s，s∈[0,18000]；30051 等距 30050 与 30052
    assert [opt["count"] for opt in ctx["result"]["options"]] == [30050, 30052]
    for opt in ctx["result"]["options"]:
        assert opt["recomputed"] == opt["count"]
        assert len(opt["list_a"]) == 18000 and len(opt["list_b"]) == 22000
        assert len(set(opt["list_a"]) & set(opt["list_b"])) == opt["s"]
    assert elapsed < 10, f"5 万卷复核过慢：{elapsed:.1f}s"


def test_review_version_snapshot_survives_later_uploads(client, svc):
    """受理后补报/发版照常进行；复核仍读受理版本的规则、缺报与卷序。"""
    _setup_two_missing(client)
    conn = svc._conn()
    try:
        accepted = svc.current_version_id(conn)
    finally:
        conn.close()

    # 之后补交甲馆、产生新版本并改变名单状态
    data = b"V1\nV2\n"
    client.post("/lists/1/upload", data={"file": (io.BytesIO(data), "a.txt")},
                content_type="multipart/form-data")
    conn = svc._conn()
    try:
        latest = svc.current_version_id(conn)
    finally:
        conn.close()
    assert latest > accepted

    # 受理版本的复核上下文不变
    conn = svc._conn()
    try:
        ctx = svc.review_page(conn, accepted, {"count_a": "4", "count_b": "5",
                                               "reported": "5",
                                               "form_version": str(accepted)})
        version = svc.get_version(conn, accepted)
    finally:
        conn.close()
    assert ctx["eligible"] is True
    assert ctx["result"] is not None
    assert version["total"] == 10
    assert set(json.loads(version["missing_names_json"])) == {"甲馆", "乙馆"}
    assert ctx["result"]["options"][0]["recomputed"] == ctx["result"]["options"][0]["count"]


def test_sample_csv_download(client):
    _setup_two_missing(client)
    rv = client.get("/results/review/sample?version_id=1&count_a=4&count_b=5&s=2")
    assert rv.status_code == 200
    text = rv.data.decode("utf-8")
    lines = [ln for ln in text.splitlines() if ln.strip()]
    assert lines[0].lstrip("﻿").startswith("名单")
    assert sum(1 for ln in lines if ln.startswith("甲馆（4 卷）")) == 4
    assert sum(1 for ln in lines if ln.startswith("乙馆（5 卷）")) == 5
