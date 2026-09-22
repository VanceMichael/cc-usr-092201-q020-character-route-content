"""把点位预览渲染为可离线打开的 HTML，供策展人员核对家庭实际所见。

仅依赖标准库 html 转义；字形、释义、适龄说明、文物图像与授权状态分区呈现，
并在页脚标注每个载体版本的指纹（与现场二维码一致）。
"""

from __future__ import annotations

import html

from .catalog import Catalog
from .preview_service import preview_point


def _esc(value) -> str:
    return html.escape(str(value), quote=True)


def _render_content(content: dict) -> str:
    payload = content["payload"]
    if content["kind"] == "glyph":
        body = (
            f"<p class=\"glyph\">{_esc(payload.get('glyph_ref', ''))}</p>"
            f"<p>字体：{_esc(payload['script_form'])}　年代：{_esc(payload['period'])}</p>"
        )
    elif content["kind"] == "meaning":
        body = f"<p>{_esc(payload['text'])}</p>"
    elif content["kind"] == "expression":
        tag = '<span class="tag">无障碍</span>' if payload.get("accessibility") else ""
        body = (
            f"<p>{tag}{_esc(payload['text'])}</p>"
            f"<p class=\"meta\">适龄：{_esc(payload.get('age_band', ''))}</p>"
        )
    else:
        license_ = content["license"]
        license_text = "、".join(
            f"{r['licensor']}（{'/'.join(r['scope'])}，至{r['valid_until']}，{r['status']}）"
            for r in license_["records"]
        ) or "无授权记录"
        license_cls = "ok" if license_["valid"] else "bad"
        body = (
            f"<p class=\"asset\">［文物图像］{_esc(payload.get('asset_ref', ''))}</p>"
            f"<p>{_esc(payload.get('caption', ''))}</p>"
            f"<p class=\"meta {license_cls}\">授权核验：{_esc(license_text)}</p>"
        )

    sources = "；".join(
        f"《{s['title']}》{s['publisher']} {s['year']}，{s['locator']}" for s in content["sources"]
    )
    review = content.get("expert_review")
    review_text = (
        f"专家审校：{_esc(review['reviewer'])}" if review and not review.get("rejected") else "—"
    )
    return (
        f"<div class=\"content kind-{content['kind']}\">"
        f"<h4>{_esc(content['kind_label'])}　<span class=\"meta\">{_esc(content['title'])}"
        f"（{_esc(content['version_id'])}）</span></h4>"
        f"{body}"
        f"<p class=\"meta\">依据：{_esc(sources)}</p>"
        f"<p class=\"meta\">{review_text}</p>"
        f"</div>"
    )


def render_point_html(catalog: Catalog, point_id: str, today: str | None = None) -> str:
    point = preview_point(catalog, point_id, today)
    carrier_blocks = []
    for carrier in point["carriers"]:
        if carrier["version"] is None:
            inner = f"<p class=\"meta\">{_esc(carrier['status'])}</p>"
        else:
            version = carrier["version"]
            inner = "".join(_render_content(c) for c in version["content"])
            inner += (
                f"<p class=\"meta fp\">版本 {version['version_no']}　"
                f"指纹 {_esc(version['fingerprint'])}　发布于 {_esc(version['published_at'])}</p>"
            )
        status_cls = "ok" if carrier["status"] == "当前有效" else "bad"
        carrier_blocks.append(
            f"<section class=\"carrier\">"
            f"<h3>[{_esc(carrier['carrier_type'])}] {_esc(carrier['title'])} "
            f"<span class=\"status {status_cls}\">{_esc(carrier['status'])}</span></h3>"
            f"{inner}</section>"
        )

    return (
        "<!doctype html><html lang=\"zh\"><head><meta charset=\"utf-8\">"
        f"<title>点位预览 · {_esc(point['point_name'])}</title>"
        "<style>"
        "body{font-family:sans-serif;max-width:860px;margin:24px auto;line-height:1.6;color:#222}"
        ".carrier{border:1px solid #ccc;border-radius:8px;padding:12px 18px;margin:14px 0}"
        ".content{border-left:4px solid #888;padding:4px 12px;margin:10px 0;background:#fafafa}"
        ".kind-glyph{border-color:#b8860b}.kind-meaning{border-color:#2e6da4}"
        ".kind-expression{border-color:#4cae4c}.kind-image{border-color:#a05a9f}"
        ".glyph{font-size:28px;font-weight:bold;margin:4px 0}"
        ".asset{font-weight:bold}.meta{color:#666;font-size:13px}"
        ".tag{background:#4cae4c;color:#fff;border-radius:4px;padding:1px 6px;margin-right:6px;font-size:12px}"
        ".ok{color:#2a7a2a}.bad{color:#b22}.status{font-size:13px}"
        ".fp{font-family:monospace}"
        "</style></head><body>"
        f"<h1>点位 {point['order']} · {_esc(point['point_name'])}</h1>"
        + "".join(carrier_blocks)
        + "</body></html>"
    )
