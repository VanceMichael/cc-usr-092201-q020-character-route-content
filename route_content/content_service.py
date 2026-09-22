"""内容侧服务：字形、释义、适龄表达与文物图像的版本化发布。

规则要点：
- 所有内容版本必须引用原始依据（来源材料），释义与适龄说明不得无源编写；
- 文字类内容（字形/释义/表达）必须经专家审校才能发布；
- 文物图像不进入文字审校，但必须存在有效授权才能发布，授权单独核验；
- 同一内容条目同一时刻只有一个"当前版本"，旧版本保留为已归档，可留档不可再用于新编排。
"""

from __future__ import annotations

from datetime import date

from .catalog import Catalog
from .errors import NotFoundError, StateError, ValidationError
from .model import EXPERT_REVIEWED_KINDS, LICENSE_SCOPES, content_fingerprint


def _today(today: str | date | None) -> str:
    if today is None:
        return date.today().isoformat()
    return today.isoformat() if isinstance(today, date) else today


def add_source(
    catalog: Catalog,
    source_id: str,
    title: str,
    publisher: str,
    year: int,
    locator: str,
    source_type: str = "文献",
) -> dict:
    """登记一条原始依据（著录、馆藏档案、授权文件等）。"""
    return catalog.add(
        "sources",
        {
            "source_id": source_id,
            "title": title,
            "publisher": publisher,
            "year": year,
            "locator": locator,
            "source_type": source_type,
        },
    )


def create_item(
    catalog: Catalog,
    item_id: str,
    kind: str,
    character: str,
    title: str,
    group: str | None = None,
    note: str = "",
) -> dict:
    """建立内容条目。同一字的不同表达变体用 group 归组（如"走-释义表达"）。"""
    if kind not in {"glyph", "meaning", "expression", "image"}:
        raise ValidationError(f"未知内容类别 {kind}")
    return catalog.add(
        "items",
        {
            "item_id": item_id,
            "kind": kind,
            "character": character,
            "title": title,
            "group": group or f"{character}-{kind}",
            "note": note,
            "current_version_id": None,
        },
    )


def _validate_payload(kind: str, payload: dict) -> None:
    required = {
        "glyph": ["script_form", "period", "glyph_ref"],
        "meaning": ["text"],
        "expression": ["text", "age_band"],
        "image": ["asset_ref", "caption"],
    }[kind]
    missing = [key for key in required if not payload.get(key)]
    if missing:
        raise ValidationError(f"{kind} 内容缺少字段：{'、'.join(missing)}")


def draft_version(
    catalog: Catalog,
    item_id: str,
    payload: dict,
    source_refs: list[dict],
    author: str,
    version_id: str | None = None,
) -> dict:
    """起草新版本。source_refs 形如 [{"source_id": ..., "locator": ..., "note": ...}]。"""
    item = catalog.get("items", item_id)
    kind = item["kind"]
    _validate_payload(kind, payload)
    if not source_refs:
        raise ValidationError("内容版本必须引用原始依据")
    for ref in source_refs:
        try:
            catalog.get("sources", ref["source_id"])
        except NotFoundError:
            raise ValidationError(f"原始依据不存在：{ref['source_id']}") from None

    version_no = catalog.next_version_no("versions", "item_id", item_id)
    record = {
        "version_id": version_id or f"{item_id}-v{version_no}",
        "item_id": item_id,
        "kind": kind,
        "version_no": version_no,
        "payload": payload,
        "source_refs": source_refs,
        "author": author,
        "state": "待编写",
        "review": None,
        "fingerprint": content_fingerprint({**payload, "kind": kind}),
    }
    return catalog.add("versions", record)


def submit_review(catalog: Catalog, version_id: str) -> dict:
    version = catalog.get("versions", version_id)
    if version["state"] != "待编写":
        raise StateError(f"{version_id} 当前为{version['state']}，不能送审")
    version["state"] = "专家审校"
    return version


def expert_approve(catalog: Catalog, version_id: str, reviewer: str, note: str = "") -> dict:
    """专家审校通过。图像类内容不走此闸门。"""
    version = catalog.get("versions", version_id)
    if version["kind"] not in EXPERT_REVIEWED_KINDS:
        raise ValidationError("文物图像以授权为闸门，不进入专家审校")
    if version["state"] != "专家审校":
        raise StateError(f"{version_id} 未处于专家审校")
    version["review"] = {"reviewer": reviewer, "note": note}
    version["state"] = "已发布"
    _promote_if_current(catalog, version)
    return version


def expert_reject(catalog: Catalog, version_id: str, reviewer: str, note: str) -> dict:
    version = catalog.get("versions", version_id)
    if version["state"] != "专家审校":
        raise StateError(f"{version_id} 未处于专家审校")
    version["review"] = {"reviewer": reviewer, "note": note, "rejected": True}
    version["state"] = "待编写"
    return version


def register_license(
    catalog: Catalog,
    license_id: str,
    image_version_id: str,
    licensor: str,
    scope: list[str],
    valid_from: str,
    valid_until: str,
    document_ref: str,
) -> dict:
    """为某个图像内容版本登记授权。授权挂在版本上，撤权只影响该版本。"""
    version = catalog.get("versions", image_version_id)
    if version["kind"] != "image":
        raise ValidationError("授权只能登记在图像内容版本上")
    unknown = set(scope) - set(LICENSE_SCOPES)
    if unknown:
        raise ValidationError(f"未知授权范围：{'、'.join(sorted(unknown))}")
    return catalog.add(
        "licenses",
        {
            "license_id": license_id,
            "image_version_id": image_version_id,
            "licensor": licensor,
            "scope": list(scope),
            "valid_from": valid_from,
            "valid_until": valid_until,
            "document_ref": document_ref,
            "status": "有效",
            "withdrawn": None,
        },
    )


def license_valid(catalog: Catalog, image_version_id: str, today: str | date | None = None) -> bool:
    """该图像版本当前是否持有有效授权。"""
    day = _today(today)
    for license_ in catalog.where("licenses", image_version_id=image_version_id):
        if license_["status"] != "有效":
            continue
        if license_["valid_from"] <= day <= license_["valid_until"]:
            return True
    return False


def approve_image(catalog: Catalog, version_id: str, today: str | date | None = None) -> dict:
    """图像内容凭有效授权发布（第二道闸门，与专家审校并列且缺一不可于各自类别）。"""
    version = catalog.get("versions", version_id)
    if version["kind"] != "image":
        raise ValidationError("approve_image 仅适用于图像内容")
    if version["state"] != "待编写":
        raise StateError(f"{version_id} 当前为{version['state']}，不能授权发布")
    if not license_valid(catalog, version_id, today):
        raise ValidationError(f"{version_id} 缺少有效授权，不能发布")
    version["state"] = "已发布"
    _promote_if_current(catalog, version)
    return version


def _promote_if_current(catalog: Catalog, version: dict) -> None:
    """新版本发布后成为条目当前版本；旧当前版本归档留档。"""
    if version["state"] != "已发布":
        return
    item = catalog.get("items", version["item_id"])
    previous_id = item.get("current_version_id")
    if previous_id and previous_id != version["version_id"]:
        previous = catalog.get("versions", previous_id)
        if previous["state"] == "已发布":
            previous["state"] = "已归档"
    item["current_version_id"] = version["version_id"]


def publish_version(catalog: Catalog, version_id: str, reviewer: str, today: str | date | None = None) -> dict:
    """便捷流程：文字类送审并通过；图像类要求已有有效授权。"""
    version = catalog.get("versions", version_id)
    if version["kind"] == "image":
        return approve_image(catalog, version_id, today)
    if version["state"] == "待编写":
        submit_review(catalog, version_id)
    return expert_approve(catalog, version_id, reviewer)


def current_version(catalog: Catalog, item_id: str) -> dict | None:
    item = catalog.get("items", item_id)
    version_id = item.get("current_version_id")
    return catalog.get("versions", version_id) if version_id else None
