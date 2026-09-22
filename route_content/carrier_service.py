"""载体侧服务：点位、展签/路牌/绘本/讲解稿/互动活动的版本钉版与发放。

规则要点：
- 每个载体版本把"哪个条目的哪个内容版本"逐条钉死（pin），改稿产生新版本，
  已发布版本内容与指纹不可变；
- 载体版本发布需同时具备专家审校记录与图像授权核验记录，缺一不可；
- 发布时固化二维码指纹；现场扫码拿当前版本比对，旧版/召回/被换均可识别；
- 印刷批次记录印量与召回量，召回只处理仍在场的实物。
"""

from __future__ import annotations

import json
from datetime import date

from .catalog import Catalog
from .content_service import license_valid
from .errors import StateError, ValidationError
from .model import binding_fingerprint

# 载体类别对应的图像授权范围
CARRIER_SCOPE = {
    "展签": "展陈印刷",
    "路牌": "展陈印刷",
    "绘本": "出版物",
    "互动活动": "互动活动",
    "讲解稿": "数字展示",
}


def _today(today: str | date | None) -> str:
    if today is None:
        return date.today().isoformat()
    return today.isoformat() if isinstance(today, date) else today


# ---- 点位与载体 ---------------------------------------------------------


def add_point(catalog: Catalog, point_id: str, name: str, order: int, note: str = "") -> dict:
    return catalog.add(
        "points",
        {"point_id": point_id, "name": name, "order": order, "note": note, "active": True},
    )


def create_carrier(
    catalog: Catalog,
    carrier_id: str,
    point_id: str,
    carrier_type: str,
    title: str,
    audience_note: str = "",
) -> dict:
    catalog.get("points", point_id)
    return catalog.add(
        "carriers",
        {
            "carrier_id": carrier_id,
            "point_id": point_id,
            "carrier_type": carrier_type,
            "title": title,
            "audience_note": audience_note,
        },
    )


# ---- 载体版本 -----------------------------------------------------------


def draft_carrier_version(
    catalog: Catalog,
    carrier_id: str,
    bindings: list[dict],
    author: str,
    note: str = "",
    today: str | date | None = None,
) -> dict:
    """起草载体版本。bindings: [{item_id, version_id, role}]，逐条钉版。"""
    carrier = catalog.get("carriers", carrier_id)
    if not bindings:
        raise ValidationError("载体版本至少包含一项内容绑定")

    normalized: list[dict] = []
    seen_items: set[str] = set()
    for binding in bindings:
        item = catalog.get("items", binding["item_id"])
        version = catalog.get("versions", binding["version_id"])
        if version["item_id"] != item["item_id"]:
            raise ValidationError(f"绑定 {binding['version_id']} 不属于 {item['item_id']}")
        if version["state"] != "已发布":
            raise ValidationError(
                f"只能钉入已发布的内容版本：{binding['version_id']} 当前为{version['state']}"
            )
        if item["kind"] == "image" and not license_valid(catalog, version["version_id"], today):
            raise ValidationError(f"图像 {binding['version_id']} 授权缺失或已失效，不能编入载体")
        if item["item_id"] in seen_items:
            raise ValidationError(f"同一载体中条目 {item['item_id']} 重复绑定")
        seen_items.add(item["item_id"])
        normalized.append(
            {
                "item_id": item["item_id"],
                "version_id": version["version_id"],
                "role": binding.get("role", "正文"),
            }
        )

    normalized.sort(key=lambda b: (b["role"], b["item_id"]))
    version_no = catalog.next_version_no("carrier_versions", "carrier_id", carrier_id)
    record = {
        "carrier_version_id": f"{carrier_id}-cv{version_no}",
        "carrier_id": carrier_id,
        "version_no": version_no,
        "bindings": normalized,
        "author": author,
        "note": note,
        "state": "待编写",
        "review": None,
        "license_check": None,
        "fingerprint": binding_fingerprint(
            {"carrier_id": carrier_id, "version_no": version_no, "bindings": normalized}
        ),
        "qr": None,
        "recall": None,
        "superseded": False,
        "published_at": None,
    }
    return catalog.add("carrier_versions", record)


def submit_carrier_review(catalog: Catalog, carrier_version_id: str) -> dict:
    record = catalog.get("carrier_versions", carrier_version_id)
    if record["state"] != "待编写":
        raise StateError(f"{carrier_version_id} 当前为{record['state']}，不能送审")
    record["state"] = "专家审校"
    return record


def expert_approve_carrier(
    catalog: Catalog, carrier_version_id: str, reviewer: str, note: str = ""
) -> dict:
    record = catalog.get("carrier_versions", carrier_version_id)
    if record["state"] != "专家审校":
        raise StateError(f"{carrier_version_id} 未处于专家审校")
    record["review"] = {"reviewer": reviewer, "note": note}
    record["state"] = "待授权"
    return record


def verify_carrier_licenses(
    catalog: Catalog, carrier_version_id: str, checker: str, today: str | date | None = None
) -> dict:
    """核验载体中每件文物图像的授权是否有效且范围覆盖本载体类别。"""
    day = _today(today)
    record = catalog.get("carrier_versions", carrier_version_id)
    if record["state"] != "待授权":
        raise StateError(f"{carrier_version_id} 需先通过专家审校")
    carrier = catalog.get("carriers", record["carrier_id"])
    required_scope = CARRIER_SCOPE[carrier["carrier_type"]]

    checked = []
    for binding in record["bindings"]:
        item = catalog.get("items", binding["item_id"])
        if item["kind"] != "image":
            continue
        valid = [
            lic
            for lic in catalog.where("licenses", image_version_id=binding["version_id"])
            if lic["status"] == "有效"
            and lic["valid_from"] <= day <= lic["valid_until"]
            and required_scope in lic["scope"]
        ]
        if not valid:
            raise ValidationError(
                f"图像 {binding['version_id']} 缺少覆盖{required_scope}的有效授权，"
                f"载体版本不能发布"
            )
        checked.append({"version_id": binding["version_id"], "license_id": valid[0]["license_id"]})

    record["license_check"] = {"checker": checker, "checked_at": day, "images": checked}
    return record


def release_carrier_version(
    catalog: Catalog, carrier_version_id: str, today: str | date | None = None
) -> dict:
    """双闸门通过后发布：旧当前版本被替代但留档，新指纹固化进二维码。"""
    day = _today(today)
    record = catalog.get("carrier_versions", carrier_version_id)
    if record["review"] is None:
        raise ValidationError("缺少专家审校记录，不能发布")
    if record["license_check"] is None:
        raise ValidationError("缺少图像授权核验记录，不能发布")
    if record["state"] != "待授权":
        raise StateError(f"{carrier_version_id} 当前为{record['state']}，不能发布")

    # 必须在新版本翻态之前捕获旧当前版本，否则会查到自己
    previous = catalog.active_carrier_version(record["carrier_id"])

    record["state"] = "已发布"
    record["published_at"] = day
    record["qr"] = {
        "payload": json.dumps(
            {"carrier_version_id": record["carrier_version_id"], "fp": record["fingerprint"]},
            ensure_ascii=False,
        ),
        "issued_at": day,
    }

    if previous is not None and previous["carrier_version_id"] != record["carrier_version_id"]:
        # 被新版本取代的旧版：留档为已归档，未召回库存冻结停发，不得继续流出
        previous["superseded"] = True
        previous["state"] = "已归档"
        for batch in catalog.where(
            "batches", carrier_version_id=previous["carrier_version_id"]
        ):
            if batch["status"] not in ("已召回", "已发完"):
                batch["status"] = "已停发"
    return record


# ---- 印刷批次 -----------------------------------------------------------


def print_batch(
    catalog: Catalog,
    batch_id: str,
    carrier_version_id: str,
    quantity: int,
    label: str,
    printed_at: str | date | None = None,
) -> dict:
    record = catalog.get("carrier_versions", carrier_version_id)
    if record["state"] != "已发布":
        raise ValidationError("只能为已发布的载体版本安排印刷")
    if quantity <= 0:
        raise ValidationError("印刷数量必须为正")
    return catalog.add(
        "batches",
        {
            "batch_id": batch_id,
            "carrier_version_id": carrier_version_id,
            "label": label,
            "printed_at": _today(printed_at),
            "quantity": quantity,
            "distributed": 0,
            "recalled": 0,
            "status": "待发放",
        },
    )


def distribute_batch(catalog: Catalog, batch_id: str, quantity: int) -> dict:
    """登记发放数量；已召回或已停发的批次不能继续发放。"""
    batch = catalog.get("batches", batch_id)
    if batch["status"] in ("已召回", "已停发"):
        raise StateError(f"批次 {batch_id} 已{batch['status']}，不能继续发放")
    if quantity <= 0 or batch["distributed"] + quantity > batch["quantity"] - batch["recalled"]:
        raise ValidationError("发放数量超出批次可发余量")
    batch["distributed"] += quantity
    batch["status"] = "发放中" if batch["distributed"] < batch["quantity"] else "已发完"
    return batch


def recall_batch(catalog: Catalog, batch_id: str, quantity: int, reason: str) -> dict:
    """召回批次中的实物；召回后该批次停止发放，旧版留档但不能再流出。

    已停发（被新版替代而冻结）的库存仍可被进一步召回。"""
    batch = catalog.get("batches", batch_id)
    if batch["status"] == "已召回":
        raise StateError(f"批次 {batch_id} 已召回")
    available = batch["quantity"] - batch["distributed"] - batch["recalled"]
    if quantity <= 0 or quantity > available:
        raise ValidationError("召回数量超出未发放余量")
    batch["recalled"] += quantity
    batch["status"] = "已召回"
    batch["recall_reason"] = reason
    return batch


def scan_qr(catalog: Catalog, payload: str, today: str | date | None = None) -> dict:
    """现场扫码核对：比对二维码指纹与当前有效版本，报告实物状态。"""
    try:
        data = json.loads(payload)
        carrier_version_id = data["carrier_version_id"]
        fp = data["fp"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return {"status": "无法识别", "detail": "二维码内容不是本系统签发的载体版本"}

    record = catalog.find("carrier_versions", carrier_version_id)
    if record is None:
        return {"status": "无法识别", "detail": f"不存在载体版本 {carrier_version_id}"}

    carrier = catalog.get("carriers", record["carrier_id"])
    point = catalog.get("points", carrier["point_id"])
    base = {
        "carrier_version_id": carrier_version_id,
        "carrier": carrier["title"],
        "point": point["name"],
        "version_no": record["version_no"],
    }

    if fp != record["fingerprint"]:
        return {**base, "status": "指纹不符", "detail": "实物内容与系统记录不一致，疑似混版"}

    active = catalog.active_carrier_version(record["carrier_id"])
    if record.get("recall") is not None:
        return {
            **base,
            "status": "已召回",
            "detail": f"该版本因「{record['recall']['reason']}」召回，不得继续发放",
        }
    if active is None or active["carrier_version_id"] != carrier_version_id:
        current = active["carrier_version_id"] if active else "无"
        return {
            **base,
            "status": "旧版留档",
            "detail": f"该版本已被替代，当前有效版本为 {current}，旧版不得继续发放",
        }
    return {**base, "status": "当前有效", "detail": "实物与当前发布版本一致"}
