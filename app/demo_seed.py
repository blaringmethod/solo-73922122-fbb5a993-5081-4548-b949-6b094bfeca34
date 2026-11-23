"""Docker Compose 演示用种子数据（可重复执行）。

只在数据库为空时写入：12 个卷号、两份缺报名单、一条“对称差”收录规则。
该规则下两份名单交集每增加 1 卷，入编数变化 2，正好演示“填报数等距/不可达”的复核。
"""

from __future__ import annotations

import os

from .service import CatalogService

DEMO_VOLUMES = [f"V{i:02d}" for i in range(1, 13)]
DEMO_LISTS = [("甲馆", "accept"), ("乙馆", "accept")]
DEMO_RULE = '{"差": [{"并": ["甲馆", "乙馆"]}, {"交": ["甲馆", "乙馆"]}]}'


def seed_demo(service: CatalogService) -> dict:
    """数据库为空时写入演示数据；已有数据则原样保留。"""
    conn = service._conn()
    try:
        volumes = service.volume_count(conn)
        lists = conn.execute("SELECT COUNT(*) FROM list_source").fetchone()[0]
        rule = service.get_rule_text(conn)
    finally:
        conn.close()
    if volumes or lists or rule:
        return {"seeded": False}

    service.replace_volumes(("\n".join(DEMO_VOLUMES) + "\n").encode())
    for name, kind in DEMO_LISTS:
        service.register_list(name, kind)
    service.save_rule(DEMO_RULE)
    return {"seeded": True}


def main() -> None:
    if os.environ.get("DEMO_SEED", "0") != "1":
        return
    db_path = os.environ.get("CATALOG_DB", "/data/catalog.db")
    result = seed_demo(CatalogService(db_path))
    if result["seeded"]:
        print(f"演示数据已写入 {db_path}：结果页可直接使用报数复核。")
    else:
        print("数据库已有数据，跳过演示种子。")


if __name__ == "__main__":
    main()
