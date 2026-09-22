"""编排核心的领域规则测试。"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from route_content import carrier_service, change_service, content_service, feedback_service  # noqa: E402
from route_content.catalog import Catalog  # noqa: E402
from route_content.errors import StateError, ValidationError  # noqa: E402
from route_content.model import binding_fingerprint  # noqa: E402
from route_content.preview_service import preview_point, preview_route  # noqa: E402
from route_content.seed import build_seed_catalog  # noqa: E402

DAY = "2026-09-22"
LATER = "2026-10-01"


class ContentGateTest(unittest.TestCase):
    def setUp(self):
        self.catalog = Catalog()
        content_service.add_source(self.catalog, "S1", "字书", "某社", 2000, "走部")
        content_service.create_item(self.catalog, "M1", "meaning", "走", "释义")

    def test_draft_requires_source(self):
        with self.assertRaises(ValidationError):
            content_service.draft_version(
                self.catalog, "M1", {"text": "无源释义"}, [], "编辑"
            )

    def test_dangling_source_ref_rejected(self):
        with self.assertRaises(ValidationError):
            content_service.draft_version(
                self.catalog, "M1", {"text": "x"}, [{"source_id": "不存在"}], "编辑"
            )

    def test_text_content_requires_expert_review(self):
        version = content_service.draft_version(
            self.catalog, "M1", {"text": "走，奔跑"}, [{"source_id": "S1"}], "编辑"
        )
        self.assertEqual(version["state"], "待编写")
        # 未审校不能被载体钉入
        with self.assertRaises(ValidationError):
            carrier_service.draft_carrier_version(
                self._carrier(),
                "C1",
                [{"item_id": "M1", "version_id": version["version_id"]}],
                "编辑",
            )
        content_service.publish_version(self.catalog, version["version_id"], "专家")
        self.assertEqual(
            content_service.current_version(self.catalog, "M1")["version_id"],
            version["version_id"],
        )

    def test_rejection_sends_back_to_draft(self):
        version = content_service.draft_version(
            self.catalog, "M1", {"text": "走，奔跑"}, [{"source_id": "S1"}], "编辑"
        )
        content_service.submit_review(self.catalog, version["version_id"])
        content_service.expert_reject(self.catalog, version["version_id"], "专家", "依据不足")
        self.assertEqual(version["state"], "待编写")

    def _carrier(self):
        carrier_service.add_point(self.catalog, "P1", "点", 1)
        carrier_service.create_carrier(self.catalog, "C1", "P1", "展签", "签")
        return self.catalog


class ImageLicenseGateTest(unittest.TestCase):
    def setUp(self):
        self.catalog = Catalog()
        content_service.add_source(self.catalog, "S1", "图像档案", "本馆", 2024, "库")
        content_service.create_item(self.catalog, "I1", "image", "走", "文物图")
        self.version = content_service.draft_version(
            self.catalog,
            "I1",
            {"asset_ref": "a.tif", "caption": "图"},
            [{"source_id": "S1"}],
            "编辑",
        )

    def test_image_cannot_publish_without_license(self):
        with self.assertRaises(ValidationError):
            content_service.approve_image(self.catalog, self.version["version_id"], DAY)

    def test_expired_license_rejected(self):
        content_service.register_license(
            self.catalog, "L1", self.version["version_id"], "方",
            ["展陈印刷"], "2020-01-01", "2020-12-31", "协议001",
        )
        with self.assertRaises(ValidationError):
            content_service.approve_image(self.catalog, self.version["version_id"], DAY)

    def test_valid_license_publishes_and_withdraw_blocks_reuse(self):
        content_service.register_license(
            self.catalog, "L1", self.version["version_id"], "方",
            ["互动活动"], "2026-01-01", "2027-12-31", "协议001",
        )
        content_service.approve_image(self.catalog, self.version["version_id"], DAY)
        self.assertEqual(self.version["state"], "已发布")
        change_service.withdraw_image(self.catalog, self.version["version_id"], "联络人", "撤权", LATER)
        self.assertEqual(self.version["state"], "需更换")
        # 已撤权图像不能编入新载体
        carrier_service.add_point(self.catalog, "P1", "点", 1)
        carrier_service.create_carrier(self.catalog, "C1", "P1", "互动活动", "拓印")
        with self.assertRaises(ValidationError):
            carrier_service.draft_carrier_version(
                self.catalog, "C1",
                [{"item_id": "I1", "version_id": self.version["version_id"]}],
                "编辑", today=LATER,
            )


class CarrierReleaseTest(unittest.TestCase):
    def setUp(self):
        self.catalog = build_seed_catalog()

    def _current_bindings(self, carrier_id):
        current = self.catalog.active_carrier_version(carrier_id)
        return {b["item_id"]: b["version_id"] for b in current["bindings"]}

    def test_double_gate_required(self):
        carrier_service.add_point(self.catalog, "PX", "临时点", 9)
        carrier_service.create_carrier(self.catalog, "CX", "PX", "展签", "临时签")
        draft = carrier_service.draft_carrier_version(
            self.catalog, "CX",
            [{"item_id": "走-meaning", "version_id": "走-meaning-v1"}],
            "编辑", today=DAY,
        )
        carrier_service.submit_carrier_review(self.catalog, draft["carrier_version_id"])
        with self.assertRaises(ValidationError):
            carrier_service.release_carrier_version(self.catalog, draft["carrier_version_id"], DAY)
        carrier_service.expert_approve_carrier(self.catalog, draft["carrier_version_id"], "专家")
        # 仍缺授权核验
        with self.assertRaises(ValidationError):
            carrier_service.release_carrier_version(self.catalog, draft["carrier_version_id"], DAY)
        carrier_service.verify_carrier_licenses(self.catalog, draft["carrier_version_id"], "联络人", DAY)
        carrier_service.release_carrier_version(self.catalog, draft["carrier_version_id"], DAY)
        self.assertIsNotNone(draft["qr"])

    def test_license_scope_must_cover_carrier_type(self):
        # 拓印底图仅授权"互动活动"，编入绘本（需"出版物"）必须被拦截
        draft = carrier_service.draft_carrier_version(
            self.catalog, "C-BOOK-1",
            [
                {"item_id": "走-glyph-regular", "version_id": "走-glyph-regular-v1"},
                {"item_id": "走-img-rubbing", "version_id": "走-img-rubbing-v1"},
            ],
            "编辑", "越权编入", DAY,
        )
        carrier_service.submit_carrier_review(self.catalog, draft["carrier_version_id"])
        carrier_service.expert_approve_carrier(self.catalog, draft["carrier_version_id"], "专家")
        with self.assertRaises(ValidationError):
            carrier_service.verify_carrier_licenses(
                self.catalog, draft["carrier_version_id"], "联络人", DAY
            )

    def test_published_carrier_version_is_immutable_fingerprint(self):
        current = self.catalog.active_carrier_version("C-SIGN-1")
        expected = binding_fingerprint(
            {"carrier_id": "C-SIGN-1", "version_no": 1, "bindings": current["bindings"]}
        )
        self.assertEqual(current["fingerprint"], expected)

    def test_superseded_batches_frozen(self):
        # 给绘本再加印一个未发完的批次，出新版后应冻结；冻结后不能发放
        carrier_service.print_batch(self.catalog, "B2", "C-BOOK-1-cv1", 100, "加印", DAY)
        self.assertEqual(self.catalog.get("batches", "B2")["status"], "待发放")
        new_glyph = change_service.correct_content(
            self.catalog, "走-glyph-seal-v1",
            {"period": "秦"}, [{"source_id": "SRC-003"}],
            "编辑", "专家", "更正", LATER,
        )[0]
        change_service.revise_carrier(
            self.catalog, "C-BOOK-1", {"走-glyph-seal": new_glyph["version_id"]}, None,
            "编辑", "专家", "联络人", "更正", "更正", LATER,
        )
        # 错字更正：旧版含错误，未发库存必须召回（而非仅冻结停发）
        self.assertEqual(self.catalog.get("batches", "B2")["status"], "已召回")
        with self.assertRaises(StateError):
            carrier_service.distribute_batch(self.catalog, "B2", 10)

    def test_cannot_distribute_recalled_batch(self):
        carrier_service.recall_batch(self.catalog, "B-ACT-1", 100, "测试召回")
        with self.assertRaises(StateError):
            carrier_service.distribute_batch(self.catalog, "B-ACT-1", 1)


class ChangeAndRecallTest(unittest.TestCase):
    def setUp(self):
        self.catalog = build_seed_catalog()

    def test_correction_precision_unrelated_carrier_untouched(self):
        new_version, impact = change_service.correct_content(
            self.catalog, "走-glyph-seal-v1",
            {"period": "秦"}, [{"source_id": "SRC-003"}],
            "编辑", "专家", "小篆年代更正", LATER,
        )
        self.assertEqual(new_version["state"], "已发布")
        self.assertEqual(
            self.catalog.get("versions", "走-glyph-seal-v1")["state"], "已归档"
        )
        affected = {c["carrier_version_id"] for c in impact["carrier_versions"]}
        # 展签与绘本钉了小篆；路牌只有楷书，讲解稿只有释义——均不受影响
        self.assertEqual(affected, {"C-SIGN-1-cv1", "C-BOOK-1-cv1"})
        # 展签批次已全发出：无库存可召回；绘本有 300 未发
        self.assertEqual({b["batch_id"] for b in impact["batches"]}, {"B-BOOK-1"})

        change_service.revise_carrier(
            self.catalog, "C-SIGN-1", {"走-glyph-seal": new_version["version_id"]}, None,
            "编辑", "专家", "联络人", "更正小篆", "更正", LATER,
        )
        sign = self.catalog.active_carrier_version("C-SIGN-1")
        self.assertEqual(sign["carrier_version_id"], "C-SIGN-1-cv2")
        self.assertEqual(
            sign["bindings"][0]["role"], "字形"  # 绑定顺序稳定
        )
        # 路牌批次完全不受影响
        self.assertEqual(self.catalog.get("batches", "B-BOARD-1")["status"], "已发完")

    def test_withdraw_and_replace_only_affects_activity(self):
        impact = change_service.withdraw_image(
            self.catalog, "走-img-ding-v1", "联络人", "撤权", LATER
        )
        # 鼎铭照片同时在展签与绘本中
        self.assertEqual(
            {c["carrier_version_id"] for c in impact["carrier_versions"]},
            {"C-SIGN-1-cv1", "C-BOOK-1-cv1"},
        )
        self.assertEqual(self.catalog.get("versions", "走-img-ding-v1")["state"], "需更换")

    def test_replace_image_repins_and_recalls(self):
        change_service.withdraw_image(
            self.catalog, "走-img-rubbing-v1", "联络人", "撤权", LATER
        )
        replacement = content_service.draft_version(
            self.catalog,
            "走-img-rubbing",
            {"asset_ref": "new.png", "caption": "新图"},
            [{"source_id": "SRC-005"}],
            "编辑",
        )
        content_service.register_license(
            self.catalog, "L9", replacement["version_id"], "本馆",
            ["互动活动"], LATER, "2028-12-31", "协议9",
        )
        content_service.approve_image(self.catalog, replacement["version_id"], LATER)
        new_cv, result = change_service.replace_image(
            self.catalog, "C-ACT-1", "走-img-rubbing-v1", replacement["version_id"],
            "编辑", "专家", "联络人", "换图", LATER,
        )
        pinned = {b["version_id"] for b in new_cv["bindings"]}
        self.assertIn(replacement["version_id"], pinned)
        self.assertNotIn("走-img-rubbing-v1", pinned)
        self.assertIn("B-ACT-1", result["recalled_batches"])
        self.assertEqual(
            self.catalog.active_carrier_version("C-ACT-1")["carrier_version_id"],
            new_cv["carrier_version_id"],
        )

    def test_retire_point_only_recalls_that_point(self):
        result = change_service.retire_point(self.catalog, "P2", "运营", "施工", LATER)
        self.assertIn("C-BOARD-1-cv1", result["recalled_carrier_versions"])
        self.assertFalse(self.catalog.get("points", "P2")["active"])
        # 其他点位的载体仍有当前版本
        self.assertIsNotNone(self.catalog.active_carrier_version("C-SIGN-1"))
        self.assertIsNone(self.catalog.active_carrier_version("C-BOARD-1"))
        # 路线预览不再包含 P2
        route = {p["point_id"] for p in preview_route(self.catalog, LATER)}
        self.assertNotIn("P2", route)

    def test_accessibility_addition_is_additive(self):
        before_book = self.catalog.active_carrier_version("C-BOOK-1")["carrier_version_id"]
        result = change_service.add_accessible_expression(
            self.catalog,
            group="走-释义表达", character="走",
            payload={
                "title": "触觉版",
                "text": "摸一摸奔跑的人形",
                "age_band": "4-6",
            },
            source_refs=[{"source_id": "SRC-006"}],
            author="编辑", reviewer="专家", license_checker="联络人",
            carrier_ids=["C-SCRIPT-1"], today=LATER,
        )
        self.assertEqual(result["upgraded_carrier_versions"], ["C-SCRIPT-1-cv2"])
        # 绘本既未升级也未召回
        self.assertEqual(
            self.catalog.active_carrier_version("C-BOOK-1")["carrier_version_id"], before_book
        )
        # 讲解稿新版包含无障碍角色绑定
        script = self.catalog.active_carrier_version("C-SCRIPT-1")
        self.assertIn("无障碍", {b["role"] for b in script["bindings"]})

    def test_onsite_replace_makes_scan_show_recalled(self):
        qr = self.catalog.active_carrier_version("C-SIGN-1")["qr"]["payload"]
        self.assertEqual(carrier_service.scan_qr(self.catalog, qr, DAY)["status"], "当前有效")
        change_service.onsite_replace(self.catalog, "C-SIGN-1-cv1", "组长", "损坏", LATER)
        scan = carrier_service.scan_qr(self.catalog, qr, LATER)
        self.assertEqual(scan["status"], "已召回")


class ScanQrTest(unittest.TestCase):
    def setUp(self):
        self.catalog = build_seed_catalog()

    def test_unknown_and_tampered_payloads(self):
        self.assertEqual(carrier_service.scan_qr(self.catalog, "乱码", DAY)["status"], "无法识别")
        self.assertEqual(
            carrier_service.scan_qr(
                self.catalog, '{"carrier_version_id": "X-cv9", "fp": "0"}', DAY
            )["status"],
            "无法识别",
        )
        tampered = json.dumps(
            {"carrier_version_id": "C-SIGN-1-cv1", "fp": "deadbeefdeadbeef"},
            ensure_ascii=False,
        )
        self.assertEqual(
            carrier_service.scan_qr(self.catalog, tampered, DAY)["status"], "指纹不符"
        )

    def test_old_version_scan_after_new_release(self):
        # 无障碍增补属于追加式升级：旧版冻结留档而非召回，扫码应提示"旧版留档"
        old_qr = self.catalog.get("carrier_versions", "C-SCRIPT-1-cv1")["qr"]["payload"]
        change_service.add_accessible_expression(
            self.catalog,
            group="走-释义表达", character="走",
            payload={"title": "触觉版", "text": "摸一摸奔跑的人形", "age_band": "4-6"},
            source_refs=[{"source_id": "SRC-006"}],
            author="编辑", reviewer="专家", license_checker="联络人",
            carrier_ids=["C-SCRIPT-1"], today=LATER,
        )
        scan = carrier_service.scan_qr(self.catalog, old_qr, LATER)
        self.assertEqual(scan["status"], "旧版留档")
        self.assertIn("C-SCRIPT-1-cv2", scan["detail"])


class PreviewTest(unittest.TestCase):
    def setUp(self):
        self.catalog = build_seed_catalog()

    def test_point_preview_resolves_family_view(self):
        point = preview_point(self.catalog, "P1", DAY)
        self.assertEqual(point["point_name"], "启程·奔跑的起点")
        sign = next(c for c in point["carriers"] if c["carrier_id"] == "C-SIGN-1")
        self.assertEqual(sign["status"], "当前有效")
        kinds = {c["kind"] for c in sign["version"]["content"]}
        self.assertEqual(kinds, {"glyph", "meaning", "expression", "image"})
        meaning = next(c for c in sign["version"]["content"] if c["kind"] == "meaning")
        # 每条内容带原始依据与审校信息
        self.assertTrue(meaning["sources"])
        self.assertEqual(meaning["expert_review"]["reviewer"], "外聘文字学专家")
        image = next(c for c in sign["version"]["content"] if c["kind"] == "image")
        self.assertTrue(image["license"]["valid"])

    def test_recalled_carrier_shows_taken_down(self):
        change_service.retire_point(self.catalog, "P2", "运营", "施工", LATER)
        point = preview_point(self.catalog, "P2", LATER)
        board = next(c for c in point["carriers"] if c["carrier_id"] == "C-BOARD-1")
        self.assertEqual(board["status"], "已撤下")


class FeedbackTest(unittest.TestCase):
    def setUp(self):
        self.catalog = build_seed_catalog()

    def _feedback(self, activity, rows):
        for fid, expr, age, level, concepts in rows:
            feedback_service.record_feedback(
                self.catalog, fid, activity, age, level,
                expression_version_id=expr, understood_concepts=concepts,
            )

    def test_report_rates_and_compares_variants(self):
        rows = [
            ("F1", "走-expr-story-v1", "4-6", "理解", ["奔跑"]),
            ("F2", "走-expr-story-v1", "4-6", "理解", ["奔跑", "演变"]),
            ("F3", "走-expr-story-v1", "4-6", "未理解", []),
            ("F4", "走-expr-plain-v1", "7-9", "部分理解", ["奔跑"]),
            ("F5", "走-expr-plain-v1", "7-9", "未理解", []),
        ]
        self._feedback("C-ACT-1-cv1", rows)
        report = feedback_service.understanding_report(self.catalog)
        by_id = {v["version_id"]: v for v in report["variants"]}
        self.assertAlmostEqual(by_id["走-expr-story-v1"]["understanding_rate"], 0.667, places=3)
        self.assertEqual(by_id["走-expr-story-v1"]["top_concepts"][0], ("奔跑", 2))
        comparison = next(c for c in report["comparisons"] if c["group"] == "走-释义表达")
        self.assertEqual(comparison["best_version_id"], "走-expr-story-v1")

    def test_feedback_requires_activity_carrier(self):
        with self.assertRaises(ValidationError):
            feedback_service.record_feedback(
                self.catalog, "FX", "C-SIGN-1-cv1", "4-6", "理解"
            )
        with self.assertRaises(ValidationError):
            feedback_service.record_feedback(
                self.catalog, "FX", "C-ACT-1-cv1", "3-5", "理解"
            )


class SeedAndPersistenceTest(unittest.TestCase):
    def test_seed_integrity_and_active_versions(self):
        catalog = build_seed_catalog()
        catalog.validate_integrity()
        for carrier_id in ["C-SIGN-1", "C-BOARD-1", "C-BOOK-1", "C-SCRIPT-1", "C-ACT-1"]:
            self.assertIsNotNone(catalog.active_carrier_version(carrier_id))

    def test_roundtrip_preserves_data(self):
        catalog = build_seed_catalog()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "catalog.json"
            catalog.save(path)
            reloaded = Catalog.load(path)
            self.assertEqual(
                reloaded.active_carrier_version("C-SIGN-1")["fingerprint"],
                catalog.active_carrier_version("C-SIGN-1")["fingerprint"],
            )

    def test_contract_schemas_are_valid_json(self):
        for name in ["domain.schema.json", "orchestration.schema.json"]:
            with open(ROOT / "contracts" / name, encoding="utf-8") as fh:
                json.load(fh)


if __name__ == "__main__":
    unittest.main()
