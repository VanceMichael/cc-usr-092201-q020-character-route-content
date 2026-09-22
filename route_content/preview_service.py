"""点位预览：按点位还原家庭实际看到的组合内容。

策展人员预览的始终是"当前已发布、未召回"的版本组合，与现场扫码核对
共用同一份钉版数据，避免预览与实物脱节。
"""

from __future__ import annotations

from .catalog import Catalog
from .content_service import license_valid

KIND_LABEL = {
    "glyph": "字形",
    "meaning": "释义",
    "expression": "适龄表达",
    "image": "文物图像",
}


def _resolve_binding(catalog: Catalog, binding: dict, today: str | None) -> dict:
    item = catalog.get("items", binding["item_id"])
    version = catalog.get("versions", binding["version_id"])
    sources = []
    for ref in version["source_refs"]:
        source = catalog.get("sources", ref["source_id"])
        sources.append(
            {
                "title": source["title"],
                "publisher": source["publisher"],
                "year": source["year"],
                "locator": ref.get("locator") or source["locator"],
                "note": ref.get("note", ""),
            }
        )
    resolved = {
        "role": binding["role"],
        "kind": item["kind"],
        "kind_label": KIND_LABEL[item["kind"]],
        "title": item["title"],
        "version_id": version["version_id"],
        "version_no": version["version_no"],
        "payload": version["payload"],
        "sources": sources,
        "expert_review": version.get("review"),
    }
    if item["kind"] == "image":
        licenses = catalog.where("licenses", image_version_id=version["version_id"])
        resolved["license"] = {
            "valid": license_valid(catalog, version["version_id"], today),
            "records": [
                {
                    "license_id": lic["license_id"],
                    "licensor": lic["licensor"],
                    "scope": lic["scope"],
                    "valid_until": lic["valid_until"],
                    "status": lic["status"],
                }
                for lic in licenses
            ],
        }
    return resolved


def preview_point(catalog: Catalog, point_id: str, today: str | None = None) -> dict:
    """汇总点位下每个载体当前有效的完整组合内容。"""
    point = catalog.get("points", point_id)
    carriers_out = []
    for carrier in catalog.where("carriers", point_id=point_id):
        active = catalog.active_carrier_version(carrier["carrier_id"])
        shown = active
        if shown is None:
            versions = catalog.carrier_versions(carrier["carrier_id"])
            shown = versions[-1] if versions else None
        entry = {
            "carrier_id": carrier["carrier_id"],
            "carrier_type": carrier["carrier_type"],
            "title": carrier["title"],
            "audience_note": carrier["audience_note"],
            "status": "无可用版本",
            "version": None,
        }
        if shown is not None:
            if active is not None:
                entry["status"] = "当前有效"
            elif shown.get("recall"):
                entry["status"] = "已撤下"
            else:
                entry["status"] = "旧版留档"
            entry["version"] = {
                "carrier_version_id": shown["carrier_version_id"],
                "version_no": shown["version_no"],
                "fingerprint": shown["fingerprint"],
                "published_at": shown["published_at"],
                "content": [
                    _resolve_binding(catalog, binding, today) for binding in shown["bindings"]
                ],
            }
        carriers_out.append(entry)
    carriers_out.sort(key=lambda c: c["carrier_type"])
    return {
        "point_id": point["point_id"],
        "point_name": point["name"],
        "order": point["order"],
        "active": point["active"],
        "carriers": carriers_out,
    }


def preview_route(catalog: Catalog, today: str | None = None) -> list[dict]:
    """按路线顺序预览全部在用点位。"""
    points = sorted(catalog.where("points", active=True), key=lambda p: p["order"])
    return [preview_point(catalog, point["point_id"], today) for point in points]
