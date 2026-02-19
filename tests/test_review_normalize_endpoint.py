import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.review.router import get_review_service, review_router


class _FakeReviewService:
    def normalize_fields(self, *, document_id, fields, mode):
        self.last_payload = {
            "document_id": document_id,
            "fields": fields,
            "mode": mode,
        }
        return {
            "suggestions": {
                "supplier_name": {
                    "original": "Attijariwafa bnak",
                    "suggested": "Attijariwafa bank",
                    "score": 96.0,
                    "matched_id": 1,
                    "action": "replace",
                }
            },
            "applied_fields": {
                "supplier_name": {
                    "value": "Attijariwafa bank",
                    "bbox": [0.1, 0.2, 0.6, 0.25],
                    "page": 1,
                }
            }
            if mode == "apply"
            else None,
        }


class ReviewNormalizeEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fake_service = _FakeReviewService()
        app = FastAPI()
        app.include_router(review_router)
        app.dependency_overrides[get_review_service] = lambda: self.fake_service
        self.client = TestClient(app)

    def test_normalize_suggest_contract(self) -> None:
        response = self.client.post(
            "/review/normalize",
            json={
                "document_id": 42,
                "mode": "suggest",
                "fields": {
                    "supplier_name": {
                        "value": "Attijariwafa bnak",
                        "bbox": [0.1, 0.2, 0.6, 0.25],
                        "page": 1,
                    }
                },
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("suggestions", payload)
        self.assertIn("supplier_name", payload["suggestions"])
        self.assertEqual(payload["suggestions"]["supplier_name"]["action"], "replace")
        self.assertIsNone(payload["applied_fields"])

    def test_normalize_apply_returns_applied_fields(self) -> None:
        response = self.client.post(
            "/review/normalize",
            json={
                "document_id": 42,
                "mode": "apply",
                "fields": {
                    "supplier_name": {
                        "value": "Attijariwafa bnak",
                        "bbox": [0.1, 0.2, 0.6, 0.25],
                        "page": 1,
                    }
                },
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(
            payload["applied_fields"]["supplier_name"]["value"],
            "Attijariwafa bank",
        )


if __name__ == "__main__":
    unittest.main()
