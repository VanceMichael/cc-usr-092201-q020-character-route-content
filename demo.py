"""全流程演示：从"走"字多处释义不一致的乱象，到统一编排后的一次完整治理。

运行：python -m demo
产出：
- output/seed_catalog.json    初始编排资料（可留档、可重新载入）
- output/point-*.html         各点位家庭视角预览
- 控制台                       错字更正、撤权、路线调整、无障碍增补、
                              现场替换、扫码核对、反馈理解度对比的全过程
"""

from __future__ import annotations

import json
from pathlib import Path

from route_content import carrier_service, change_service, content_service, feedback_service
from route_content.catalog import Catalog
from route_content.preview_service import preview_point, preview_route
from route_content.render_html import render_point_html
from route_content.seed import EDITOR, EXPERT, RIGHTS, TODAY, build_seed_catalog

OUTPUT = Path("output")
DAY1 = "2026-09-22"
DAY2 = "2026-09-29"


def hr(title: str) -> None:
    print(f"\n{'=' * 72}\n{title}\n{'=' * 72}")


def show_batch(catalog: Catalog, batch_id: str) -> str:
    b = catalog.get("batches", batch_id)
    return f"{b['batch_id']}：印{b['quantity']} 发{b['distributed']} 召{b['recalled']} [{b['status']}]"


def main() -> None:
    OUTPUT.mkdir(exist_ok=True)
    catalog = build_seed_catalog()
    catalog.validate_integrity()

    hr("① 统一来源：同一“走”字只有一个当前释义版本")
    meaning_v1 = catalog.get("versions", "走-meaning-v1")
    print("当前释义：", meaning_v1["payload"]["text"])
    print("依据：", [r["source_id"] for r in meaning_v1["source_refs"]],
          "审校：", meaning_v1["review"]["reviewer"])
    print("各载体钉版：展签/讲解稿钉释义v1，绘本/路牌/活动钉适龄表达v1")

    catalog.save(OUTPUT / "seed_catalog.json")
    for point in preview_route(catalog, DAY1):
        (OUTPUT / f"point-{point['point_id']}.html").write_text(
            render_point_html(catalog, point["point_id"], DAY1), encoding="utf-8"
        )
    print("初始资料与点位 HTML 已写入 output/")

    hr("② 错字更正：小篆年代标注有误，旧版留档、只召回受影响载体")
    # 专家复核发现小篆释文把“秦”误标为“战国”
    new_meaning, impact = change_service.correct_content(
        catalog,
        "走-glyph-seal-v1",
        {"period": "秦（公元前221年统一后定型）",
         "glyph_ref": "〔小篆：上“夭”下“止”，线条匀圆〕"},
        [{"source_id": "SRC-003", "note": "《说文》成书年代订正"}],
        EDITOR, EXPERT, "小篆年代标注更正", DAY2,
    )
    print("新版本：", new_meaning["version_id"], new_meaning["payload"]["period"])
    print("受影响载体：", [c["carrier_version_id"] for c in impact["carrier_versions"]])
    print("可召回批次：", {b["batch_id"]: b["recallable"] for b in impact["batches"]})

    # 展签与绘本重排新版；展签库存已全发出（无法召库），绘本召回剩余300本
    _, recall_sign = change_service.revise_carrier(
        catalog, "C-SIGN-1", {"走-glyph-seal": new_meaning["version_id"]}, None,
        EDITOR, EXPERT, RIGHTS, "更正小篆年代", "更正", DAY2,
    )
    _, recall_book = change_service.revise_carrier(
        catalog, "C-BOOK-1", {"走-glyph-seal": new_meaning["version_id"]}, None,
        EDITOR, EXPERT, RIGHTS, "更正小篆年代", "更正", DAY2,
    )
    print("展签召回：", recall_sign["recalled_batches"], "（已全部上墙，靠扫码识别旧版）")
    print("绘本召回：", recall_book["recalled_batches"])
    print(show_batch(catalog, "B-BOOK-1"), "← 旧版留档、停止发放")
    # 路牌不含小篆，不受影响
    print(show_batch(catalog, "B-BOARD-1"), "← 路牌未钉小篆，批次不动")

    hr("③ 素材撤权：外聘书法工作室撤回拓印底图授权")
    impact = change_service.withdraw_image(
        catalog, "走-img-rubbing-v1", RIGHTS, "授权方提前终止协议，底图撤权", DAY2
    )
    print("撤权影响载体：", [c["carrier_version_id"] for c in impact["carrier_versions"]])
    print("撤权影响批次：", {b["batch_id"]: b["recallable"] for b in impact["batches"]})

    # 影像部补拍馆内藏简替代图：作为同一图像条目（拓印用图）的新版本，单独取得授权
    catalog.get("items", "走-img-rubbing")["title"] = "拓印活动用图"
    img_jian = content_service.draft_version(
        catalog,
        "走-img-rubbing",
        {"asset_ref": "影像库/JIAN-ZOU-03.png", "caption": "秦简“走”字特写，替代撤权底图"},
        [{"source_id": "SRC-005", "note": "馆藏影像"}],
        EDITOR,
    )
    content_service.register_license(
        catalog, "LIC-003", img_jian["version_id"], "本馆影像部",
        ["互动活动", "展陈印刷", "数字展示"], DAY2, "2028-12-31", "授权协议字第2026-077号",
    )
    content_service.approve_image(catalog, img_jian["version_id"], DAY2)
    new_act, act_recall = change_service.replace_image(
        catalog, "C-ACT-1", "走-img-rubbing-v1", img_jian["version_id"],
        EDITOR, EXPERT, RIGHTS, "撤权图像替换为秦简照片", DAY2,
    )
    print("活动新版：", new_act["carrier_version_id"], "召回旧材料包：", act_recall["recalled_batches"])

    # 撤权图像不得再被任何新载体钉入
    blocked = None
    try:
        carrier_service.draft_carrier_version(
            catalog, "C-BOARD-1",
            [{"item_id": "走-glyph-regular", "version_id": "走-glyph-regular-v1", "role": "字形"},
             {"item_id": "走-img-rubbing", "version_id": "走-img-rubbing-v1", "role": "图像"}],
            EDITOR, "尝试复用撤权图", DAY2,
        )
    except Exception as exc:  # noqa: BLE001 - 演示需要展示拒绝
        blocked = str(exc)
    print("撤权图像再编排被拦截：", blocked)

    hr("④ 现场扫码核对：当前版 / 旧版留档 / 已召回 一扫码即知")
    qr_current = catalog.active_carrier_version("C-ACT-1")["qr"]["payload"]
    qr_old = catalog.get("carrier_versions", "C-ACT-1-cv1")["qr"]["payload"]
    print("扫新材料包：", carrier_service.scan_qr(catalog, qr_current, DAY2)["status"])
    old_scan = carrier_service.scan_qr(catalog, qr_old, DAY2)
    print(f"扫旧材料包：{old_scan['status']} — {old_scan['detail']}")

    hr("⑤ 路线改变：P2 象形步道施工撤点，只召回该点位载体")
    result = change_service.retire_point(catalog, "P2", "赛事运营", "步道施工，P2 撤点", DAY2)
    print("撤点召回：", result)
    print(show_batch(catalog, "B-BOARD-1"), "← 路牌召回；绘本/展签批次不受影响")

    hr("⑥ 无障碍表达增补：为低龄视障家庭加触觉讲解，只升级讲解稿")
    accessible = change_service.add_accessible_expression(
        catalog,
        group="走-释义表达",
        character="走",
        payload={
            "title": "走·触觉讲解版",
            "text": "请伸出手臂：上面像甩开的双臂，下面是一只脚——整个人在奔跑。"
                    "可配合让孩子摸一摸拓片上奔跑的人形。",
            "age_band": "4-6",
        },
        source_refs=[{"source_id": "SRC-006", "note": "触觉通道表达依据"}],
        author=EDITOR, reviewer=EXPERT, license_checker=RIGHTS,
        carrier_ids=["C-SCRIPT-1"], today=DAY2,
    )
    print("新增表达：", accessible["expression_version_id"])
    print("升级载体：", accessible["upgraded_carrier_versions"], "（其他载体不召回、不停发）")
    script_versions = catalog.carrier_versions("C-SCRIPT-1")
    print("讲解稿版本链：", [(v["carrier_version_id"], v["state"]) for v in script_versions])

    hr("⑦ 现场替换：大雨冲花一张展签，现场挂出旧版替补签被扫码识别")
    qr_sign_v1 = catalog.get("carrier_versions", "C-SIGN-1-cv1")["qr"]["payload"]
    scan = carrier_service.scan_qr(catalog, qr_sign_v1, DAY2)
    print(f"扫旧版替补签：{scan['status']} — {scan['detail']}")
    change_service.onsite_replace(
        catalog, "C-SIGN-1-cv1", "现场组长", "雨水损坏现行展签，误用旧版替补，已撤换", DAY2
    )
    scan2 = carrier_service.scan_qr(catalog, qr_sign_v1, DAY2)
    print(f"登记现场替换后再扫：{scan2['status']} — {scan2['detail']}")

    hr("⑧ 反馈闭环：两种适龄表达，哪一种真的让孩子理解了演变？")
    feedbacks = [
        # 故事版（活动新版仍用故事版）
        ("F01", "4-6", "理解", ["奔跑", "象形"]),
        ("F02", "4-6", "理解", ["奔跑"]),
        ("F03", "4-6", "部分理解", ["奔跑"]),
        ("F04", "4-6", "未理解", []),
        ("F05", "4-6", "理解", ["奔跑", "字形演变"]),
        ("F06", "4-6", "部分理解", []),
        # 直白版
        ("F07", "7-9", "理解", ["古今异义", "奔跑"]),
        ("F08", "7-9", "部分理解", ["奔跑"]),
        ("F09", "7-9", "未理解", []),
        ("F10", "7-9", "部分理解", ["奔跑"]),
    ]
    for fid, age, level, concepts in feedbacks[:6]:
        feedback_service.record_feedback(
            catalog, fid, "C-ACT-1-cv2", age, level,
            expression_version_id="走-expr-story-v1", understood_concepts=concepts,
        )
    for fid, age, level, concepts in feedbacks[6:]:
        feedback_service.record_feedback(
            catalog, fid, "C-ACT-1-cv2", age, level,
            expression_version_id="走-expr-plain-v1", understood_concepts=concepts,
        )
    report = feedback_service.understanding_report(catalog)
    for variant in report["variants"]:
        print(f"{variant['version_id']}（{variant['age_band']}岁）："
              f"理解率 {variant['understanding_rate']:.0%}，n={variant['total']}")
    for comparison in report["comparisons"]:
        print(f"同组对比 → 保留 {comparison['best_version_id']}（{comparison['best_rate']:.0%}）")
        print("  排名：", [(r["version_id"], f"{r['rate']:.0%}") for r in comparison["ranking"]])

    hr("⑨ 旧版留档可审计：全部事件与版本仍可查阅")
    for event in catalog.all("events"):
        print(f"{event['at']} {event['type']}：{event['reason']}")
    catalog.save(OUTPUT / "final_catalog.json")
    print("\n最终编排资料已写入 output/final_catalog.json")


if __name__ == "__main__":
    main()
