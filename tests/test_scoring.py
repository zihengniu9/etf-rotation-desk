import unittest

import pandas as pd

from low_buy_selector.scoring import score_hot_topics, score_legitimacy


class ScoringTests(unittest.TestCase):
    def test_hot_topic_score_uses_top_heat_and_lists_concepts(self):
        keywords = pd.DataFrame(
            {
                "概念名称": ["固态电池", "小金属概念", "新材料"],
                "热度": [275, 189, 77],
            }
        )

        score = score_hot_topics(keywords)

        self.assertEqual(score.top_concept, "固态电池")
        self.assertEqual(score.top_heat, 275)
        self.assertAlmostEqual(score.score, 91.6667, places=3)
        self.assertIn("固态电池", score.concepts_text)

    def test_legitimacy_scores_core_business_matches_above_scope_only_matches(self):
        keywords = pd.DataFrame(
            {
                "概念名称": ["新材料", "航母概念"],
                "热度": [100, 5],
            }
        )
        business = pd.DataFrame(
            {
                "主营业务": ["锆系列制品研发、生产和销售。"],
                "产品类型": ["主要锆系产品"],
                "产品名称": ["复合氧化锆、陶瓷结构件、新材料"],
                "经营范围": ["航母配套材料销售。"],
            }
        )

        score = score_legitimacy(keywords, business)

        self.assertGreaterEqual(score.score, 80)
        self.assertIn("新材料", score.matched_keywords)
        self.assertIn("core business/product", score.reason)

    def test_legitimacy_handles_empty_inputs(self):
        score = score_legitimacy(pd.DataFrame(), pd.DataFrame())

        self.assertEqual(score.score, 0)
        self.assertEqual(score.matched_keywords, "")


if __name__ == "__main__":
    unittest.main()
