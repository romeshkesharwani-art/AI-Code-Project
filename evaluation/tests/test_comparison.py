import unittest

from evaluation.comparison import compare_run


def make_run(
    answer_a: dict[str, float | None],
    answer_b: dict[str, float | None],
    *,
    embedding_a: str = "text-embedding-3-small",
    embedding_b: str = "text-embedding-3-small",
    error_b: str | None = None,
) -> dict:
    return {
        "configs": {
            "a": {"name": "Baseline", "embedding_model": embedding_a},
            "b": {"name": "Experiment", "embedding_model": embedding_b},
        },
        "rows": [
            {
                "question": "Same test question?",
                "systems": {
                    "a": {
                        "answer": "answer a",
                        "metrics": answer_a.copy(),
                    },
                    "b": {
                        "answer": "answer b",
                        "error": error_b,
                        "metrics": answer_b.copy(),
                    },
                },
            }
        ],
    }


class AutomaticComparisonTests(unittest.TestCase):
    def test_generation_and_retrieval_scores_select_better_system(self):
        run = make_run(
            {
                "bleu": 80,
                "rouge_l": 0.8,
                "token_f1": 0.8,
                "precision_at_k": 0.5,
                "recall_at_k": 0.5,
                "mrr": 0.5,
                "ndcg": 0.5,
            },
            {
                "bleu": 50,
                "rouge_l": 0.5,
                "token_f1": 0.5,
                "precision_at_k": 0.5,
                "recall_at_k": 0.5,
                "mrr": 0.5,
                "ndcg": 0.5,
            },
        )
        result = compare_run(run)
        self.assertEqual(result["status"], "winner")
        self.assertEqual(result["winner"], "a")
        self.assertAlmostEqual(result["scores"]["a"], 0.68)
        self.assertAlmostEqual(result["scores"]["b"], 0.5)
        self.assertTrue(result["retrieval_included"])

    def test_generation_only_comparison_when_retrieval_labels_missing(self):
        generation = {
            "bleu": 80,
            "rouge_l": 0.8,
            "token_f1": 0.8,
            "recall_at_k": None,
            "mrr": None,
            "ndcg": None,
        }
        weaker = {**generation, "bleu": 40, "rouge_l": 0.4, "token_f1": 0.4}
        result = compare_run(make_run(generation, weaker))
        self.assertEqual(result["winner"], "a")
        self.assertAlmostEqual(result["scores"]["a"], 0.8)
        self.assertFalse(result["retrieval_included"])

    def test_partial_retrieval_labels_fall_back_without_partial_metric_bias(self):
        generation = {
            "bleu": 80,
            "rouge_l": 0.8,
            "token_f1": 0.8,
            "precision_at_k": None,
            "recall_at_k": None,
            "mrr": None,
            "ndcg": None,
        }
        run = make_run(generation, generation)
        first_row = run["rows"][0]
        first_row["systems"]["a"]["metrics"].update(
            {
                "precision_at_k": 1.0,
                "recall_at_k": 1.0,
                "mrr": 1.0,
                "ndcg": 1.0,
            }
        )
        first_row["systems"]["b"]["metrics"].update(
            {
                "precision_at_k": 1.0,
                "recall_at_k": 1.0,
                "mrr": 1.0,
                "ndcg": 1.0,
            }
        )
        run["rows"].append(
            {
                "question": "Second shared question?",
                "systems": {
                    system: {"answer": "answer", "metrics": generation.copy()}
                    for system in ("a", "b")
                },
            }
        )
        result = compare_run(run)
        self.assertTrue(result["status"] in {"winner", "tie"})
        self.assertFalse(result["retrieval_included"])
        self.assertEqual(result["scores"]["a"], result["generation_scores"]["a"])

    def test_tied_scores_have_no_automatic_winner(self):
        metrics = {
            "bleu": 50,
            "rouge_l": 0.5,
            "token_f1": 0.5,
            "recall_at_k": None,
            "mrr": None,
            "ndcg": None,
        }
        result = compare_run(make_run(metrics, metrics))
        self.assertEqual(result["status"], "tie")
        self.assertIsNone(result["winner"])

    def test_partial_run_does_not_choose_winner_from_different_question_sets(self):
        metrics = {"bleu": 90, "rouge_l": 0.9, "token_f1": 0.9}
        result = compare_run(make_run(metrics, metrics, error_b="endpoint unavailable"))
        self.assertEqual(result["status"], "incomplete")
        self.assertIsNone(result.get("winner"))

    def test_missing_answer_for_any_shared_question_prevents_winner_selection(self):
        metrics = {"bleu": 80, "rouge_l": 0.8, "token_f1": 0.8}
        run = make_run(metrics, metrics)
        run["rows"].append(
            {
                "question": "Second shared question?",
                "systems": {
                    "a": {"answer": "answer", "metrics": metrics.copy()},
                    "b": {
                        "answer": "",
                        "metrics": {"bleu": None, "rouge_l": None, "token_f1": None},
                    },
                },
            }
        )
        result = compare_run(run)
        self.assertEqual(result["status"], "unavailable")
        self.assertIsNone(result.get("winner"))

    def test_different_embedding_indexes_do_not_get_compared_as_equivalent(self):
        metrics = {"bleu": 90, "rouge_l": 0.9, "token_f1": 0.9}
        result = compare_run(
            make_run(metrics, metrics, embedding_b="text-embedding-3-large")
        )
        self.assertEqual(result["status"], "unavailable")
        self.assertIsNone(result.get("winner"))


if __name__ == "__main__":
    unittest.main()
