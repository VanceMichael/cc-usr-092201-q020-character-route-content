"""变更与召回服务：路线改变、错字更正、素材撤权、无障碍增补、现场替换。

核心原则：
- 任何变更先做影响分析，沿"内容版本 → 载体版本 → 印刷批次"的引用链
  精确闭包，只召回真正受影响的实物批次；
- 旧版一律留档（记录与指纹保留可审计），但被召回或被替代后不得继续发放；
- 替换内容必须重新走完审校与授权闸门，不能以"临时改稿"直接覆盖已发布版本。
"""

from __future__ import annotations

from datetime import date

from . import carrier_service, content_service
from .catalog import Catalog
from .errors import StateError, ValidationError


def _today(today: str | date | None) -> str:
    if today is None:
        return date.today().isoformat()
    return today.isoformat() if isinstance(today, date) else today


def _event(catalog: Catalog, event_type: str, actor: str, reason: str, day: str, **extra) -> dict:
    event_id = f"EV{len(catalog.all('events')) + 1:03d}"
    record = {"event_id": event_id, "type": event_type, "actor": actor, "reason": reason, "at": day}
    record.update(extra)
    catalog.add("events", record)
    return record


# ---- 影响分析 -----------------------------------------------------------


def _carrier_in_circulation(catalog: Catalog, carrier_version: dict) -> bool:
    """该载体版本是否仍有可发实物或仍在现场（已发完但未召回也视为在场）。"""
    if carrier_version.get("recall") is not None:
        return False
    batches = catalog.where("batches", carrier_version_id=carrier_version["carrier_version_id"])
    if not batches:
        return carrier_version["state"] == "已发布"
    return any(batch["status"] != "已召回" for batch in batches)


def impact_for_content_version(catalog: Catalog, version_id: str) -> dict:
    """沿引用链找出钉入该内容版本的全部在场载体与可召回批次。"""
    affected_carrier_versions: list[dict] = []
    affected_batches: list[dict] = []
    for carrier_version in catalog.all("carrier_versions"):
        pinned = [b for b in carrier_version["bindings"] if b["version_id"] == version_id]
        if not pinned:
            continue
        in_circulation = _carrier_in_circulation(catalog, carrier_version)
        carrier = catalog.get("carriers", carrier_version["carrier_id"])
        affected_carrier_versions.append(
            {
                "carrier_version_id": carrier_version["carrier_version_id"],
                "carrier_id": carrier_version["carrier_id"],
                "point_id": carrier["point_id"],
                "title": carrier["title"],
                "state": carrier_version["state"],
                "in_circulation": in_circulation,
            }
        )
        if in_circulation:
            for batch in catalog.where(
                "batches", carrier_version_id=carrier_version["carrier_version_id"]
            ):
                if batch["status"] == "已召回":
                    continue
                recallable = batch["quantity"] - batch["distributed"] - batch["recalled"]
                if recallable > 0:
                    affected_batches.append(
                        {
                            "batch_id": batch["batch_id"],
                            "carrier_version_id": batch["carrier_version_id"],
                            "label": batch["label"],
                            "recallable": recallable,
                        }
                    )
    return {
        "content_version_id": version_id,
        "carrier_versions": affected_carrier_versions,
        "batches": affected_batches,
    }


def execute_recall(
    catalog: Catalog,
    impact: dict,
    actor: str,
    reason: str,
    event_type: str,
    today: str | date | None = None,
) -> dict:
    """按影响分析执行召回：只停用报告内的载体版本与批次，其他载体不动。"""
    day = _today(today)
    recalled_batches: list[str] = []
    recalled_carrier_versions: list[str] = []

    for entry in impact["batches"]:
        if entry["recallable"] <= 0:
            continue
        batch = catalog.get("batches", entry["batch_id"])
        carrier_service.recall_batch(catalog, batch["batch_id"], entry["recallable"], reason)
        recalled_batches.append(batch["batch_id"])

    for entry in impact["carrier_versions"]:
        if not entry["in_circulation"]:
            continue
        record = catalog.get("carrier_versions", entry["carrier_version_id"])
        record["recall"] = {"reason": reason, "at": day, "event_type": event_type}
        recalled_carrier_versions.append(entry["carrier_version_id"])

    _event(
        catalog,
        event_type,
        actor,
        reason,
        day,
        content_version_id=impact.get("content_version_id"),
        carrier_version_ids=recalled_carrier_versions,
        batch_ids=recalled_batches,
    )
    return {
        "recalled_carrier_versions": recalled_carrier_versions,
        "recalled_batches": recalled_batches,
    }


# ---- 错字更正 -----------------------------------------------------------


def correct_content(
    catalog: Catalog,
    old_version_id: str,
    payload_overrides: dict,
    source_refs: list[dict],
    author: str,
    reviewer: str,
    reason: str,
    today: str | date | None = None,
) -> tuple[dict, dict]:
    """为错误内容建立新版本（重新引据、重新审校），返回新版本与旧版影响分析。

    不直接改动旧版本——已印出的物料必须能被追溯，影响面由调用方据此召回。
    """
    old = catalog.get("versions", old_version_id)
    if old["kind"] == "image":
        raise ValidationError("图像问题请使用撤权/替换流程")
    payload = {**old["payload"], **payload_overrides}
    new_version = content_service.draft_version(
        catalog, old["item_id"], payload, source_refs, author
    )
    content_service.publish_version(catalog, new_version["version_id"], reviewer, today)
    impact = impact_for_content_version(catalog, old_version_id)
    _event(
        catalog,
        "更正",
        author,
        reason,
        _today(today),
        item_id=old["item_id"],
        old_version_id=old_version_id,
        new_version_id=new_version["version_id"],
        affected_carrier_version_ids=[c["carrier_version_id"] for c in impact["carrier_versions"]],
    )
    return new_version, impact


def revise_carrier(
    catalog: Catalog,
    carrier_id: str,
    replacements: dict[str, str],
    additions: list[dict] | None,
    author: str,
    reviewer: str,
    license_checker: str,
    reason: str,
    event_type: str = "更正",
    today: str | date | None = None,
) -> tuple[dict, dict]:
    """基于载体当前版本起草新版本：replacements 为 {item_id: 新version_id}，
    additions 为追加绑定。自动走完双闸门并发布，随后召回旧版可发库存。"""
    day = _today(today)
    current = catalog.active_carrier_version(carrier_id)
    if current is None:
        raise StateError(f"载体 {carrier_id} 没有可修订的当前版本")

    bindings = []
    for binding in current["bindings"]:
        new_version_id = replacements.get(binding["item_id"], binding["version_id"])
        bindings.append({"item_id": binding["item_id"], "version_id": new_version_id, "role": binding["role"]})
    bindings.extend(additions or [])

    draft = carrier_service.draft_carrier_version(catalog, carrier_id, bindings, author, reason, day)
    carrier_service.submit_carrier_review(catalog, draft["carrier_version_id"])
    carrier_service.expert_approve_carrier(catalog, draft["carrier_version_id"], reviewer, reason)
    carrier_service.verify_carrier_licenses(catalog, draft["carrier_version_id"], license_checker, day)
    carrier_service.release_carrier_version(catalog, draft["carrier_version_id"], day)

    # 旧版本（及其批次）才是受影响载体；新版本发布本身不动其他载体
    impact = {
        "content_version_id": None,
        "carrier_versions": [
            {
                "carrier_version_id": current["carrier_version_id"],
                "carrier_id": carrier_id,
                "in_circulation": _carrier_in_circulation(catalog, current),
            }
        ],
        "batches": [],
    }
    for batch in catalog.where("batches", carrier_version_id=current["carrier_version_id"]):
        if batch["status"] != "已召回":
            recallable = batch["quantity"] - batch["distributed"] - batch["recalled"]
            if recallable > 0:
                impact["batches"].append(
                    {
                        "batch_id": batch["batch_id"],
                        "carrier_version_id": current["carrier_version_id"],
                        "label": batch["label"],
                        "recallable": recallable,
                    }
                )
    result = execute_recall(catalog, impact, author, reason, event_type, day)
    return draft, result


# ---- 素材撤权 -----------------------------------------------------------


def withdraw_image(
    catalog: Catalog,
    image_version_id: str,
    actor: str,
    reason: str,
    today: str | date | None = None,
) -> dict:
    """撤销图像授权：授权状态置为已撤权，图像转为需更换，并给出影响分析。

    撤权不删除素材（留档），但任何载体新版本都不能再钉入它；
    是否立即召回在场批次由 execute_recall 按影响分析处理。
    """
    day = _today(today)
    version = catalog.get("versions", image_version_id)
    if version["kind"] != "image":
        raise ValidationError("只能对图像内容撤权")
    for license_ in catalog.where("licenses", image_version_id=image_version_id):
        if license_["status"] == "有效":
            license_["status"] = "已撤权"
            license_["withdrawn"] = {"at": day, "actor": actor, "reason": reason}
    if version["state"] == "已发布":
        version["state"] = "需更换"
    impact = impact_for_content_version(catalog, image_version_id)
    _event(
        catalog,
        "撤权",
        actor,
        reason,
        day,
        content_version_id=image_version_id,
        carrier_version_ids=[c["carrier_version_id"] for c in impact["carrier_versions"]],
        batch_ids=[b["batch_id"] for b in impact["batches"]],
    )
    return impact


def replace_image(
    catalog: Catalog,
    carrier_id: str,
    old_image_version_id: str,
    new_image_version_id: str,
    author: str,
    reviewer: str,
    license_checker: str,
    reason: str,
    today: str | date | None = None,
) -> tuple[dict, dict]:
    """用已获授权的新图像替换载体中的撤权图像，并召回旧版库存。"""
    old = catalog.get("versions", old_image_version_id)
    new = catalog.get("versions", new_image_version_id)
    if old["item_id"] != new["item_id"]:
        raise ValidationError("替换图像必须属于同一条目")
    return revise_carrier(
        catalog,
        carrier_id,
        {old["item_id"]: new_image_version_id},
        None,
        author,
        reviewer,
        license_checker,
        reason,
        event_type="撤权",
        today=today,
    )


# ---- 路线改变 -----------------------------------------------------------


def retire_point(
    catalog: Catalog,
    point_id: str,
    actor: str,
    reason: str,
    today: str | date | None = None,
) -> dict:
    """撤点：该点位下全部在场载体停止使用并召回可发库存，其他点位不受影响。"""
    day = _today(today)
    point = catalog.get("points", point_id)
    point["active"] = False
    carrier_version_ids: list[str] = []
    batch_entries: list[dict] = []
    for carrier in catalog.where("carriers", point_id=point_id):
        current = catalog.active_carrier_version(carrier["carrier_id"])
        if current is None:
            continue
        carrier_version_ids.append(current["carrier_version_id"])
        for batch in catalog.where("batches", carrier_version_id=current["carrier_version_id"]):
            if batch["status"] != "已召回":
                recallable = batch["quantity"] - batch["distributed"] - batch["recalled"]
                if recallable > 0:
                    batch_entries.append(
                        {
                            "batch_id": batch["batch_id"],
                            "carrier_version_id": current["carrier_version_id"],
                            "label": batch["label"],
                            "recallable": recallable,
                        }
                    )
    impact = {
        "content_version_id": None,
        "carrier_versions": [
            {"carrier_version_id": cid, "carrier_id": cid.rsplit("-cv", 1)[0], "in_circulation": True}
            for cid in carrier_version_ids
        ],
        "batches": batch_entries,
    }
    result = execute_recall(catalog, impact, actor, reason, "路线调整", day)
    return {"point_id": point_id, **result}


def move_carrier_to_point(
    catalog: Catalog,
    carrier_id: str,
    new_point_id: str,
    actor: str,
    reason: str,
    today: str | date | None = None,
) -> dict:
    """载体迁移到新点位（如展区移位）：出新版载体标注新点位，旧版召回。

    点位归属挂在载体上，因此迁移即新载体；这里通过停用旧载体、由调用方
    在新点位创建载体完成。保留事件记录说明二者的替代关系。
    """
    day = _today(today)
    catalog.get("points", new_point_id)
    carrier = catalog.get("carriers", carrier_id)
    old_point_id = carrier["point_id"]
    current = catalog.active_carrier_version(carrier_id)
    carrier["point_id"] = new_point_id
    if current is not None:
        current["recall"] = {"reason": reason, "at": day, "event_type": "路线调整"}
    _event(
        catalog,
        "路线调整",
        actor,
        reason,
        day,
        carrier_id=carrier_id,
        old_point_id=old_point_id,
        new_point_id=new_point_id,
    )
    return carrier


# ---- 无障碍表达增补 -----------------------------------------------------


def add_accessible_expression(
    catalog: Catalog,
    group: str,
    character: str,
    payload: dict,
    source_refs: list[dict],
    author: str,
    reviewer: str,
    license_checker: str,
    carrier_ids: list[str],
    today: str | date | None = None,
    item_id: str | None = None,
) -> dict:
    """为既有释义增补无障碍表达（如触觉描述、大字版），并只升级指定载体。

    这是追加式变更：未指定的载体不受影响、不召回；被升级的载体走正常
    双闸门出新版，旧版库存按"停发"冻结而非撤下。
    """
    day = _today(today)
    payload = {**payload, "accessibility": True}
    item_id = item_id or f"{character}-expr-access-{len(catalog.all('items')) + 1}"
    content_service.create_item(
        catalog, item_id, "expression", character, payload.get("title", "无障碍表达"), group=group
    )
    version = content_service.draft_version(catalog, item_id, payload, source_refs, author)
    content_service.publish_version(catalog, version["version_id"], reviewer, day)

    upgraded: list[str] = []
    for carrier_id in carrier_ids:
        current = catalog.active_carrier_version(carrier_id)
        if current is None:
            raise StateError(f"载体 {carrier_id} 没有当前版本，无法增补")
        additions = [
            {"item_id": item_id, "version_id": version["version_id"], "role": "无障碍"}
        ]
        bindings = [
            {"item_id": b["item_id"], "version_id": b["version_id"], "role": b["role"]}
            for b in current["bindings"]
        ] + additions
        draft = carrier_service.draft_carrier_version(
            catalog, carrier_id, bindings, author, "无障碍增补", day
        )
        carrier_service.submit_carrier_review(catalog, draft["carrier_version_id"])
        carrier_service.expert_approve_carrier(catalog, draft["carrier_version_id"], reviewer, "无障碍增补")
        carrier_service.verify_carrier_licenses(catalog, draft["carrier_version_id"], license_checker, day)
        carrier_service.release_carrier_version(catalog, draft["carrier_version_id"], day)
        upgraded.append(draft["carrier_version_id"])

    _event(
        catalog,
        "无障碍增补",
        author,
        "增补无障碍表达",
        day,
        content_version_id=version["version_id"],
        carrier_version_ids=upgraded,
    )
    return {"expression_version_id": version["version_id"], "upgraded_carrier_versions": upgraded}


# ---- 现场替换 -----------------------------------------------------------


def onsite_replace(
    catalog: Catalog,
    carrier_version_id: str,
    actor: str,
    reason: str,
    today: str | date | None = None,
) -> dict:
    """登记现场临时替换：被换下的版本立即标记召回，扫码即可识别，禁止再挂出。"""
    day = _today(today)
    record = catalog.get("carrier_versions", carrier_version_id)
    record["recall"] = {"reason": reason, "at": day, "event_type": "现场替换"}
    for batch in catalog.where("batches", carrier_version_id=carrier_version_id):
        if batch["status"] != "已召回":
            recallable = batch["quantity"] - batch["distributed"] - batch["recalled"]
            if recallable > 0:
                carrier_service.recall_batch(catalog, batch["batch_id"], recallable, reason)
    _event(
        catalog,
        "现场替换",
        actor,
        reason,
        day,
        carrier_version_ids=[carrier_version_id],
        batch_ids=[b["batch_id"] for b in catalog.where("batches", carrier_version_id=carrier_version_id)],
    )
    return record
