import unittest
from tempfile import TemporaryDirectory
from pathlib import Path

from evaluation.history import load_runs, save_run
from evaluation.metrics import (
    document_identifiers,
    parse_list,
    score_generation,
    score_retrieval,
)


class MetricsTests(unittest.TestCase):
    def test_parse_list_supports_json_and_delimited_values(self):
        self.assertEqual(parse_list('["doc-a", "doc-b"]'), ["doc-a", "doc-b"])
        self.assertEqual(parse_list("doc-a; doc-b"), ["doc-a", "doc-b"])
        self.assertEqual(parse_list(None), [])

    def test_retrieval_metrics_use_document_ids_and_rank(self):
        scores = score_retrieval(
            ["relevant", "also-relevant"],
            [{"id": "other"}, {"id": "relevant"}],
        )
        self.assertEqual(scores["precision_at_k"], 0.5)
        self.assertEqual(scores["recall_at_k"], 0.5)
        self.assertEqual(scores["mrr"], 0.5)
        rank_two_gain = 1 / 1.584962500721156
        self.assertAlmostEqual(scores["ndcg"], rank_two_gain / (1 + rank_two_gain))

    def test_precision_uses_all_returned_documents(self):
        scores = score_retrieval(
            ["relevant"],
            [{"text": "document without an ID"}, {"id": "relevant"}],
            k=2,
        )
        self.assertEqual(scores["precision_at_k"], 0.5)
        self.assertEqual(scores["mrr"], 0.5)

    def test_precision_uses_configured_k_when_fewer_documents_return(self):
        scores = score_retrieval(["relevant"], [{"id": "relevant"}], k=4)
        self.assertEqual(scores["precision_at_k"], 0.25)

    def test_empty_retrieval_is_scored_as_zero_when_labels_exist(self):
        scores = score_retrieval(["relevant"], [], k=3)
        self.assertEqual(scores["recall_at_k"], 0.0)
        self.assertEqual(scores["precision_at_k"], 0.0)

    def test_retrieval_metrics_are_unavailable_without_labels_or_ids(self):
        scores = score_retrieval(["relevant"], [{"text": "matching passage"}])
        self.assertIsNone(scores["recall_at_k"])

    def test_retrieval_metrics_match_stable_filename_aliases(self):
        identifiers = document_identifiers(
            {
                "id": "generated-database-id",
                "document_id": "generated-database-id",
                "filename": "13_sample_home_water_backup_endorsement.pdf",
            }
        )
        self.assertIn("13_sample_home_water_backup_endorsement.pdf", identifiers)
        scores = score_retrieval(
            ["13_sample_home_water_backup_endorsement.pdf"],
            [
                {
                    "id": "generated-database-id",
                    "filename": "13_sample_home_water_backup_endorsement.pdf",
                }
            ],
            k=1,
        )
        self.assertEqual(scores["recall_at_k"], 1.0)
        self.assertEqual(scores["mrr"], 1.0)

    def test_retrieval_does_not_count_repeated_chunks_as_new_documents(self):
        scores = score_retrieval(
            ["policy.pdf"],
            [
                {"document_id": "policy-uuid", "filename": "policy.pdf", "id": "chunk-1"},
                {"document_id": "policy-uuid", "filename": "policy.pdf", "id": "chunk-2"},
            ],
            k=2,
        )
        self.assertEqual(scores["precision_at_k"], 0.5)
        self.assertEqual(scores["recall_at_k"], 1.0)
        self.assertEqual(scores["mrr"], 1.0)

    def test_generation_metrics_score_exact_answer_highest(self):
        exact = score_generation("The policy covers theft.", "The policy covers theft.")
        unrelated = score_generation("The policy covers theft.", "Premiums renew each year.")
        self.assertEqual(exact["exact_match"], 1.0)
        self.assertEqual(exact["rouge_l"], 1.0)
        self.assertGreater(exact["bleu"], unrelated["bleu"])
        self.assertGreater(exact["token_f1"], unrelated["token_f1"])

    def test_generation_metrics_are_unavailable_for_blank_text(self):
        scores = score_generation("reference", "")
        self.assertIsNone(scores["rouge_l"])
        self.assertIsNone(scores["bleu"])

    def test_run_history_round_trips_json(self):
        run = {"id": "run-1", "rows": []}
        with TemporaryDirectory() as directory:
            path = Path(directory) / "runs.json"
            save_run(run, path)
            self.assertEqual(load_runs(path), [run])


if __name__ == "__main__":
    unittest.main()
