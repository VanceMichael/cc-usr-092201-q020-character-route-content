"""参与反馈与理解度分析。

互动活动（拓印、简牍书写等）回收的反馈挂在"活动载体版本 + 适龄表达版本"上，
因此可以比较不同表达变体对孩子理解汉字演变的实际效果，用证据决定保留哪种说法。
"""

from __future__ import annotations

from .catalog import Catalog
from .errors import ValidationError
from .model import AGE_BANDS, UNDERSTANDING_LEVELS


def record_feedback(
    catalog: Catalog,
    feedback_id: str,
    activity_carrier_version_id: str,
    age_band: str,
    understanding: str,
    expression_version_id: str | None = None,
    understood_concepts: list[str] | None = None,
    comment: str = "",
) -> dict:
    if age_band not in AGE_BANDS:
        raise ValidationError(f"适龄段须为 {'/'.join(AGE_BANDS)}")
    if understanding not in UNDERSTANDING_LEVELS:
        raise ValidationError(f"理解度须为 {'/'.join(UNDERSTANDING_LEVELS)}")
    activity = catalog.get("carrier_versions", activity_carrier_version_id)
    carrier = catalog.get("carriers", activity["carrier_id"])
    if carrier["carrier_type"] != "互动活动":
        raise ValidationError("反馈只能登记在互动活动载体上")
    if expression_version_id:
        version = catalog.get("versions", expression_version_id)
        if version["kind"] != "expression":
            raise ValidationError("反馈引用的内容版本须为适龄表达")
    return catalog.add(
        "feedback",
        {
            "feedback_id": feedback_id,
            "activity_carrier_version_id": activity_carrier_version_id,
            "expression_version_id": expression_version_id,
            "age_band": age_band,
            "understanding": understanding,
            "understood_concepts": understood_concepts or [],
            "comment": comment,
        },
    )


def _expression_groups(catalog: Catalog) -> dict[str, list[str]]:
    """同组适龄表达（同一释义的不同说法）归在一起比较。"""
    groups: dict[str, list[str]] = {}
    for item in catalog.all("items"):
        if item["kind"] != "expression":
            continue
        groups.setdefault(item["group"], []).append(item["item_id"])
    return groups


def understanding_report(catalog: Catalog) -> dict:
    """按表达变体汇总理解度，并在同组变体之间对比。"""
    feedback = catalog.all("feedback")
    per_version: dict[str, dict] = {}

    for note in feedback:
        key = note.get("expression_version_id")
        if not key:
            continue
        bucket = per_version.setdefault(
            key,
            {"total": 0, "by_level": {level: 0 for level in UNDERSTANDING_LEVELS},
             "by_age_band": {band: {"total": 0, "理解": 0} for band in AGE_BANDS},
             "concepts": {}},
        )
        bucket["total"] += 1
        bucket["by_level"][note["understanding"]] += 1
        age = bucket["by_age_band"][note["age_band"]]
        age["total"] += 1
        if note["understanding"] == "理解":
            age["理解"] += 1
        for concept in note["understood_concepts"]:
            bucket["concepts"][concept] = bucket["concepts"].get(concept, 0) + 1

    variants = []
    for version_id, stats in per_version.items():
        version = catalog.get("versions", version_id)
        item = catalog.get("items", version["item_id"])
        understood = stats["by_level"]["理解"]
        variants.append(
            {
                "group": item["group"],
                "item_id": item["item_id"],
                "version_id": version_id,
                "text": version["payload"]["text"],
                "age_band": version["payload"].get("age_band"),
                "total": stats["total"],
                "understood": understood,
                "understanding_rate": round(understood / stats["total"], 3) if stats["total"] else None,
                "partial": stats["by_level"]["部分理解"],
                "not_understood": stats["by_level"]["未理解"],
                "by_age_band": stats["by_age_band"],
                "top_concepts": sorted(stats["concepts"].items(), key=lambda kv: -kv[1])[:5],
            }
        )

    # 同组对比：哪一种说法理解率最高
    comparisons = []
    for group, item_ids in _expression_groups(catalog).items():
        group_variants = [v for v in variants if v["item_id"] in item_ids and v["total"] > 0]
        if len(group_variants) < 2:
            continue
        ranked = sorted(
            group_variants,
            key=lambda v: (v["understanding_rate"] if v["understanding_rate"] is not None else -1),
            reverse=True,
        )
        comparisons.append(
            {
                "group": group,
                "best_version_id": ranked[0]["version_id"],
                "best_rate": ranked[0]["understanding_rate"],
                "ranking": [
                    {"version_id": v["version_id"], "rate": v["understanding_rate"], "n": v["total"]}
                    for v in ranked
                ],
            }
        )

    return {"variants": variants, "comparisons": comparisons, "feedback_count": len(feedback)}
