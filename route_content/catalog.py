"""编排资料的仓储：负责存取、查询与引用完整性。

仓储只做数据层面的组织与校验；发布闸门、版本推进、召回等业务规则
在 service.py 中实现。资料整体是 JSON 可序列化结构，便于审阅与留档。
"""

from __future__ import annotations

import json
from pathlib import Path

from .errors import NotFoundError, ValidationError
from .model import (
    CARRIER_TYPES,
    CONTENT_KINDS,
    id_field,
)

SECTIONS = [
    "sources",
    "items",
    "versions",
    "licenses",
    "points",
    "carriers",
    "carrier_versions",
    "batches",
    "feedback",
    "events",
]


def empty_catalog() -> dict:
    """一份空的编排资料。"""
    return {
        "domain": "character-route-content",
        "catalog_version": 1,
        **{section: [] for section in SECTIONS},
    }


class Catalog:
    """围绕编排资料字典的查询与写入入口。"""

    def __init__(self, data: dict | None = None):
        self.data = data or empty_catalog()
        for section in SECTIONS:
            self.data.setdefault(section, [])

    # ---- 存取 ----------------------------------------------------------

    @classmethod
    def load(cls, path: str | Path) -> "Catalog":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        catalog = cls(data)
        catalog.validate_integrity()
        return catalog

    def save(self, path: str | Path) -> None:
        self.validate_integrity()
        Path(path).write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    # ---- 通用查询 ------------------------------------------------------

    def all(self, section: str) -> list[dict]:
        return self.data[section]

    def find(self, section: str, record_id: str) -> dict | None:
        field = id_field(section)
        for record in self.data[section]:
            if record[field] == record_id:
                return record
        return None

    def get(self, section: str, record_id: str) -> dict:
        record = self.find(section, record_id)
        if record is None:
            raise NotFoundError(f"{section} 中不存在 {record_id}")
        return record

    def add(self, section: str, record: dict) -> dict:
        field = id_field(section)
        if self.find(section, record[field]) is not None:
            raise ValidationError(f"{record[field]} 已存在")
        self.data[section].append(record)
        return record

    def where(self, section: str, **predicate) -> list[dict]:
        return [
            record
            for record in self.data[section]
            if all(record.get(key) == value for key, value in predicate.items())
        ]

    # ---- 便捷查询 ------------------------------------------------------

    def item_versions(self, item_id: str) -> list[dict]:
        return sorted(self.where("versions", item_id=item_id), key=lambda r: r["version_no"])

    def carrier_versions(self, carrier_id: str) -> list[dict]:
        return sorted(
            self.where("carrier_versions", carrier_id=carrier_id),
            key=lambda r: r["version_no"],
        )

    def active_carrier_version(self, carrier_id: str) -> dict | None:
        """当前应当发放的版本：已发布且未被召回。"""
        for record in reversed(self.carrier_versions(carrier_id)):
            if record["state"] == "已发布" and record.get("recall") is None:
                return record
        return None

    def next_version_no(self, section: str, parent_field: str, parent_id: str) -> int:
        field = id_field(section)
        used = [
            record["version_no"]
            for record in self.data[section]
            if record[parent_field] == parent_id
        ]
        return (max(used) + 1) if used else 1

    # ---- 引用完整性 ----------------------------------------------------

    def validate_integrity(self) -> None:
        """检查全部内部引用可解析、标识唯一、取值合法。"""
        if self.data.get("domain") != "character-route-content":
            raise ValidationError("编排资料 domain 不匹配")

        seen: dict[str, str] = {}
        for section in SECTIONS:
            field = id_field(section)
            for record in self.data[section]:
                if field not in record:
                    raise ValidationError(f"{section} 存在缺少 {field} 的记录")
                key = f"{section}:{record[field]}"
                if key in seen:
                    raise ValidationError(f"标识重复：{record[field]}")
                seen[key] = record[field]

        def require(section: str, record_id: str | None, context: str) -> None:
            if record_id and self.find(section, record_id) is None:
                raise ValidationError(f"{context} 引用了不存在的 {record_id}")

        for version in self.data["versions"]:
            if version.get("kind") not in CONTENT_KINDS:
                raise ValidationError(f"{version['version_id']} 的内容类别非法")
            if not version.get("source_refs"):
                raise ValidationError(f"{version['version_id']} 缺少原始依据引用")
            for ref in version["source_refs"]:
                require("sources", ref.get("source_id"), version["version_id"])

        for license_ in self.data["licenses"]:
            require("versions", license_.get("image_version_id"), license_["license_id"])

        for carrier in self.data["carriers"]:
            require("points", carrier.get("point_id"), carrier["carrier_id"])
            if carrier.get("carrier_type") not in CARRIER_TYPES:
                raise ValidationError(f"{carrier['carrier_id']} 的载体类别非法")

        for carrier_version in self.data["carrier_versions"]:
            require("carriers", carrier_version.get("carrier_id"),
                    carrier_version["carrier_version_id"])
            for binding in carrier_version.get("bindings", []):
                item = self.find("items", binding["item_id"])
                if item is None:
                    raise ValidationError(
                        f"{carrier_version['carrier_version_id']} 绑定了不存在的条目 "
                        f"{binding['item_id']}"
                    )
                version = self.find("versions", binding["version_id"])
                if version is None:
                    raise ValidationError(
                        f"{carrier_version['carrier_version_id']} 绑定了不存在的版本 "
                        f"{binding['version_id']}"
                    )
                if version["item_id"] != binding["item_id"]:
                    raise ValidationError(
                        f"{carrier_version['carrier_version_id']} 的绑定版本与条目不匹配"
                    )

        for batch in self.data["batches"]:
            require("carrier_versions", batch.get("carrier_version_id"), batch["batch_id"])

        for note in self.data["feedback"]:
            require(
                "carrier_versions", note.get("activity_carrier_version_id"), note["feedback_id"]
            )
            if note.get("expression_version_id"):
                require("versions", note["expression_version_id"], note["feedback_id"])
