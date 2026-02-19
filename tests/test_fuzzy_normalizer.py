import unittest

from app.review.fuzzy_normalizer import ReferenceEntity, match_reference


class FuzzyNormalizerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.suppliers = [
            ReferenceEntity(
                id=1,
                canonical_name="Attijariwafa bank",
                aliases=["Attijariwafa bnak", "Attijari wafa bank"],
            ),
            ReferenceEntity(
                id=2,
                canonical_name="BMCE Bank",
                aliases=["BMCE Bnak"],
            ),
        ]

    def test_match_typo_alias_returns_canonical(self) -> None:
        result = match_reference("Attijariwafa bnak", self.suppliers, threshold=85)
        self.assertEqual(result["canonical"], "Attijariwafa bank")
        self.assertEqual(result["matched_id"], 1)
        self.assertEqual(result["action"], "replace")
        self.assertGreaterEqual(result["score"], 85)

    def test_unknown_value_keeps_original(self) -> None:
        result = match_reference("Unknown Supplier", self.suppliers, threshold=85)
        self.assertEqual(result["canonical"], "Unknown Supplier")
        self.assertIsNone(result["matched_id"])
        self.assertEqual(result["action"], "keep")

    def test_city_with_minor_ocr_noise_matches(self) -> None:
        cities = [
            ReferenceEntity(id=10, canonical_name="Casablanca", aliases=["Casablanka"]),
            ReferenceEntity(id=11, canonical_name="Rabat", aliases=["Rabbat"]),
        ]
        result = match_reference("Casablanka", cities, threshold=80)
        self.assertEqual(result["canonical"], "Casablanca")
        self.assertEqual(result["matched_id"], 10)


if __name__ == "__main__":
    unittest.main()
