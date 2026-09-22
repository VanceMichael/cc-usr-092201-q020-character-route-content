"""种子数据：亲子健走"走"字赛道的完整初始编排。

围绕"走"字组织甲骨文、金文、小篆、楷书四种字形，古义"奔跑"的释义，
两种适龄表达变体，以及两件文物图像（一件后续会被撤权）。
所有标识均为虚构样例，不含真实馆藏编号、个人资料或授权文书。
"""

from __future__ import annotations

from . import carrier_service, content_service
from .catalog import Catalog

TODAY = "2026-09-22"
EDITOR = "内容组"
EXPERT = "外聘文字学专家"
RIGHTS = "版权联络人"

# 点位
POINTS = [
    ("P1", "启程·奔跑的起点", 1),
    ("P2", "象形步道", 2),
    ("P3", "城终留名", 3),
    ("P4", "终点互动区", 4),
]


def build_seed_catalog() -> Catalog:
    catalog = Catalog()

    # ---- 原始依据 ------------------------------------------------------
    content_service.add_source(
        catalog, "SRC-001", "甲骨文合集（摹本著录）", "中华书局", 1982, "第三册·走字条", "著录"
    )
    content_service.add_source(
        catalog, "SRC-002", "殷周金文集成（释文）", "中华书局", 1994, "卷五·走字器铭", "著录"
    )
    content_service.add_source(
        catalog, "SRC-003", "说文解字", "中华书局", 1963, "走部：走，趋也", "字书"
    )
    content_service.add_source(
        catalog, "SRC-004", "通用规范汉字字典", "商务印书馆", 2013, "走字条", "字书"
    )
    content_service.add_source(
        catalog, "SRC-005", "馆藏文物图像档案", "本馆影像部", 2024, "影像库·青铜器类", "图像档案"
    )
    content_service.add_source(
        catalog, "SRC-006", "儿童汉字认知发展研究综述", "学前教育研究", 2019, "第4期·表意文字教学", "研究文献"
    )

    # ---- 字形（甲骨文/金文/小篆/楷书） ---------------------------------
    glyphs = [
        ("走-glyph-oracle", "甲骨文", "商代晚期", "〔甲骨文：像人摆臂奔跑之形〕", "SRC-001"),
        ("走-glyph-bronze", "金文", "西周", "〔金文：人形下增“止”（脚），强调奔跑〕", "SRC-002"),
        ("走-glyph-seal", "小篆", "秦", "〔小篆：上“夭”下“止”，线条匀圆〕", "SRC-003"),
        ("走-glyph-regular", "楷书", "汉魏以降", "走", "SRC-004"),
    ]
    for item_id, script, period, glyph_ref, src in glyphs:
        content_service.create_item(
            catalog, item_id, "glyph", "走", f"走·{script}", group="走-字形"
        )
        version = content_service.draft_version(
            catalog,
            item_id,
            {"script_form": script, "period": period, "glyph_ref": glyph_ref},
            [{"source_id": src, "note": f"{script}字形出处"}],
            EDITOR,
        )
        content_service.publish_version(catalog, version["version_id"], EXPERT, TODAY)

    # ---- 释义：古义"奔跑" ----------------------------------------------
    content_service.create_item(catalog, "走-meaning", "meaning", "走", "走·古义", group="走-释义")
    meaning = content_service.draft_version(
        catalog,
        "走-meaning",
        {"text": "古汉语中“走”的本义是跑、奔跑，如“走马观花”；今义“步行”是后起的。"},
        [
            {"source_id": "SRC-003", "note": "《说文》：走，趋也"},
            {"source_id": "SRC-004", "note": "今义对照"},
        ],
        EDITOR,
    )
    content_service.publish_version(catalog, meaning["version_id"], EXPERT, TODAY)

    # ---- 适龄表达：同一释义的两种说法（用于效果对比） -------------------
    content_service.create_item(
        catalog, "走-expr-plain", "expression", "走", "走·直白版", group="走-释义表达"
    )
    expr_plain = content_service.draft_version(
        catalog,
        "走-expr-plain",
        {
            "text": "三千年前，“走”是奔跑的意思。古人看到快跑的人，就画下了这个字。",
            "age_band": "7-9",
        },
        [
            {"source_id": "SRC-003", "note": "释义依据"},
            {"source_id": "SRC-006", "note": "适龄改写依据"},
        ],
        EDITOR,
    )
    content_service.publish_version(catalog, expr_plain["version_id"], EXPERT, TODAY)

    content_service.create_item(
        catalog, "走-expr-story", "expression", "走", "走·故事版", group="走-释义表达"
    )
    expr_story = content_service.draft_version(
        catalog,
        "走-expr-story",
        {
            "text": "看这个字，像不像一个人甩开手臂大步跑？古时候“走”就是“快跑”哦！",
            "age_band": "4-6",
        },
        [
            {"source_id": "SRC-001", "note": "字形描述依据"},
            {"source_id": "SRC-006", "note": "适龄改写依据"},
        ],
        EDITOR,
    )
    content_service.publish_version(catalog, expr_story["version_id"], EXPERT, TODAY)

    # ---- 文物图像（权利单独核验） ---------------------------------------
    content_service.create_item(
        catalog, "走-img-ding", "image", "走", "青铜鼎铭文照片", group="走-文物图像"
    )
    img_ding = content_service.draft_version(
        catalog,
        "走-img-ding",
        {"asset_ref": "影像库/DING-ZOU-01.tif", "caption": "西周青铜鼎铭文中的“走”字（金文）"},
        [{"source_id": "SRC-005", "note": "馆藏影像"}],
        EDITOR,
    )
    content_service.register_license(
        catalog,
        "LIC-001",
        img_ding["version_id"],
        "本馆影像部",
        ["展陈印刷", "出版物", "互动活动", "数字展示"],
        "2026-01-01",
        "2027-12-31",
        "授权协议字第2026-017号",
    )
    content_service.approve_image(catalog, img_ding["version_id"], TODAY)

    content_service.create_item(
        catalog, "走-img-rubbing", "image", "走", "拓印模板底图", group="走-拓印素材"
    )
    img_rubbing = content_service.draft_version(
        catalog,
        "走-img-rubbing",
        {"asset_ref": "影像库/RUB-ZOU-02.png", "caption": "拓印体验用“走”字金文底图"},
        [{"source_id": "SRC-005", "note": "馆藏影像"}],
        EDITOR,
    )
    content_service.register_license(
        catalog,
        "LIC-002",
        img_rubbing["version_id"],
        "外聘书法工作室",
        ["互动活动"],
        "2026-03-01",
        "2026-12-31",
        "授权协议字第2026-042号",
    )
    content_service.approve_image(catalog, img_rubbing["version_id"], TODAY)

    # ---- 点位与载体 -----------------------------------------------------
    for point_id, name, order in POINTS:
        carrier_service.add_point(catalog, point_id, name, order)

    carrier_service.create_carrier(
        catalog, "C-SIGN-1", "P1", "展签", "起点主展签·走字演变", "亲子家庭"
    )
    carrier_service.create_carrier(catalog, "C-BOARD-1", "P2", "路牌", "步道指示路牌", "亲子家庭")
    carrier_service.create_carrier(catalog, "C-BOOK-1", "P3", "绘本", "《跟着汉字去跑步》打卡绘本", "4-9岁")
    carrier_service.create_carrier(
        catalog, "C-SCRIPT-1", "P1", "讲解稿", "讲解员手持讲稿", "讲解员"
    )
    carrier_service.create_carrier(
        catalog, "C-ACT-1", "P4", "互动活动", "终点拓印体验", "亲子家庭"
    )

    def bind(*entries):
        return [
            {"item_id": item_id, "version_id": f"{item_id}-v1", "role": role}
            for item_id, role in entries
        ]

    def release(carrier_id, bindings, note=""):
        draft = carrier_service.draft_carrier_version(
            catalog, carrier_id, bindings, EDITOR, note, TODAY
        )
        carrier_service.submit_carrier_review(catalog, draft["carrier_version_id"])
        carrier_service.expert_approve_carrier(catalog, draft["carrier_version_id"], EXPERT, note)
        carrier_service.verify_carrier_licenses(
            catalog, draft["carrier_version_id"], RIGHTS, TODAY
        )
        return carrier_service.release_carrier_version(catalog, draft["carrier_version_id"], TODAY)

    # 展签：完整字形链 + 释义 + 直白版表达 + 鼎铭照片
    release(
        "C-SIGN-1",
        bind(
            ("走-glyph-oracle", "字形"),
            ("走-glyph-bronze", "字形"),
            ("走-glyph-seal", "字形"),
            ("走-glyph-regular", "字形"),
            ("走-meaning", "释义"),
            ("走-expr-plain", "适龄表达"),
            ("走-img-ding", "文物图像"),
        ),
        "起点主展签首版",
    )
    # 路牌：仅楷书与故事版表达（远处可读）
    release("C-BOARD-1", bind(("走-glyph-regular", "字形"), ("走-expr-story", "适龄表达")), "路牌首版")
    # 绘本：字形链 + 故事版表达 + 鼎铭照片
    release(
        "C-BOOK-1",
        bind(
            ("走-glyph-oracle", "字形"),
            ("走-glyph-bronze", "字形"),
            ("走-glyph-seal", "字形"),
            ("走-glyph-regular", "字形"),
            ("走-expr-story", "适龄表达"),
            ("走-img-ding", "文物图像"),
        ),
        "绘本首版",
    )
    # 讲解稿：释义 + 直白版表达（无图像，无需授权范围外核验）
    release(
        "C-SCRIPT-1",
        bind(("走-meaning", "释义"), ("走-expr-plain", "适龄表达")),
        "讲解稿首版",
    )
    # 互动活动：拓印底图 + 故事版表达
    release(
        "C-ACT-1",
        bind(("走-img-rubbing", "文物图像"), ("走-expr-story", "适龄表达")),
        "拓印活动首版",
    )

    # ---- 印刷批次 -------------------------------------------------------
    carrier_service.print_batch(catalog, "B-SIGN-1", "C-SIGN-1-cv1", 40, "起点展签·首印", TODAY)
    carrier_service.print_batch(catalog, "B-BOARD-1", "C-BOARD-1-cv1", 60, "路牌·首印", TODAY)
    carrier_service.print_batch(catalog, "B-BOOK-1", "C-BOOK-1-cv1", 800, "绘本·首印", TODAY)
    carrier_service.print_batch(catalog, "B-ACT-1", "C-ACT-1-cv1", 300, "拓印材料包·首印", TODAY)

    carrier_service.distribute_batch(catalog, "B-SIGN-1", 40)
    carrier_service.distribute_batch(catalog, "B-BOARD-1", 60)
    carrier_service.distribute_batch(catalog, "B-BOOK-1", 500)
    carrier_service.distribute_batch(catalog, "B-ACT-1", 200)

    return catalog
