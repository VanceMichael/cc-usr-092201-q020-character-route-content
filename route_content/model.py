"""领域词汇、记录类型与内容指纹。

内容指纹用于现场扫码核对：载体版本签发时把各内容版本与绑定的指纹
固化下来，实物上的二维码携带同一指纹，任何一边被替换都会失配。
"""

from __future__ import annotations

import hashlib
import json

# 与 fixtures/domain.json 的公开约定保持一致
RECORD_TYPES = ["汉字条目", "来源材料", "图像授权", "点位载体", "印刷批次", "参与反馈"]
WORKFLOW_STATES = ["待编写", "专家审校", "待授权", "已发布", "需更换", "已归档"]

# 内容条目的类别：字形 / 释义 / 适龄表达 / 文物图像
CONTENT_KINDS = ["glyph", "meaning", "expression", "image"]

# 载体类别：点位展签 / 路牌 / 绘本 / 讲解稿 / 互动活动
CARRIER_TYPES = ["展签", "路牌", "绘本", "讲解稿", "互动活动"]

# 图像授权范围
LICENSE_SCOPES = ["展陈印刷", "出版物", "互动活动", "数字展示"]

# 反馈的适龄段
AGE_BANDS = ["4-6", "7-9", "10-12"]

# 互动活动的理解度选项
UNDERSTANDING_LEVELS = ["理解", "部分理解", "未理解"]

# 变更事件类型
EVENT_TYPES = ["发布", "更正", "撤权", "路线调整", "无障碍增补", "现场替换", "召回", "停用"]

# 需要专家审校的内容类别（图像走授权闸门，不走文字审校）
EXPERT_REVIEWED_KINDS = {"glyph", "meaning", "expression"}

_ID_FIELDS = {
    "sources": "source_id",
    "items": "item_id",
    "versions": "version_id",
    "licenses": "license_id",
    "points": "point_id",
    "carriers": "carrier_id",
    "carrier_versions": "carrier_version_id",
    "batches": "batch_id",
    "feedback": "feedback_id",
    "events": "event_id",
}


def id_field(section: str) -> str:
    """返回各区记录的主键字段名。"""
    return _ID_FIELDS[section]


def _canonical(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def content_fingerprint(payload: dict) -> str:
    """内容版本正文的指纹；正文任何改动都会产生新指纹。"""
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()[:16]


def binding_fingerprint(binding: dict) -> str:
    """载体版本整体绑定的指纹，签发二维码时固化到实物上。"""
    material = {
        "carrier_id": binding["carrier_id"],
        "version_no": binding["version_no"],
        "bindings": binding["bindings"],
    }
    return hashlib.sha256(_canonical(material).encode("utf-8")).hexdigest()[:16]
