import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pymupdf
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.app.db.base import Base
from backend.app.db.session import get_session
from backend.app.main import app


def sample_pdf() -> bytes:
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), "Coverage\nEmergency medical care is covered.")
    result = document.tobytes()
    document.close()
    return result


class PolicyApiTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
            execution_options={"schema_translate_map": {"insurance": None}},
        )
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine, expire_on_commit=False)
        self.upload_directory = TemporaryDirectory()

        def override_session():
            yield self.session

        app.dependency_overrides[get_session] = override_session
        self.initializer = patch("backend.app.main.initialize_database")
        self.initializer.start()
        self.customer_initializer = patch("backend.app.main.initialize_customer_database")
        self.customer_initializer.start()
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.initializer.stop()
        self.customer_initializer.stop()
        app.dependency_overrides.clear()
        self.session.close()
        self.engine.dispose()
        self.upload_directory.cleanup()

    def test_policy_upload_search_answer_and_archive(self):
        vector = [1.0] + [0.0] * 1535
        with patch(
            "backend.app.services.policy_service.embed_texts",
            return_value=[vector],
        ), patch(
            "backend.app.services.policy_service.get_settings"
        ) as get_settings:
            settings = get_settings.return_value
            settings.max_upload_bytes = 1024 * 1024
            settings.upload_directory = Path(self.upload_directory.name)
            settings.chunk_size = 1000
            settings.chunk_overlap = 100
            settings.openai_embedding_model = "text-embedding-3-small"
            upload = self.client.post(
                "/api/v1/policies/upload",
                files={"file": ("health.pdf", sample_pdf(), "application/pdf")},
                data={"name": "Health Policy", "category": "Health", "carrier": "Example Mutual"},
            )
        self.assertEqual(upload.status_code, 201, upload.text)
        policy = upload.json()
        self.assertEqual(policy["ingestion_status"], "ready")
        self.assertEqual(policy["chunk_count"], 1)

        with patch(
            "backend.app.services.policy_service.embed_texts",
            return_value=[vector],
        ):
            search = self.client.post(
                "/api/v1/search",
                json={
                    "query": "emergency care",
                    "top_k": 3,
                    "filters": {"category": "Health"},
                },
            )
        self.assertEqual(search.status_code, 200, search.text)
        self.assertEqual(search.json()["results"][0]["document_id"], policy["id"])
        self.assertEqual(search.json()["results"][0]["similarity_score"], 1.0)

        with patch(
            "backend.app.services.policy_service.embed_texts",
            return_value=[vector],
        ), patch(
            "backend.app.api.v1.endpoints.search.generate_answer",
            return_value=("Emergency care is covered. [S1]", False),
        ):
            answer = self.client.post(
                "/api/v1/answer",
                json={"query": "emergency care", "top_k": 3},
            )
        self.assertEqual(answer.status_code, 200, answer.text)
        self.assertIn("[S1]", answer.json()["answer"])
        self.assertEqual(len(answer.json()["sources"]), 1)

        with patch(
            "backend.app.api.v1.endpoints.search.get_settings"
        ) as get_settings, patch(
            "backend.app.services.policy_service.embed_texts",
            return_value=[vector],
        ), patch(
            "backend.app.api.v1.endpoints.search.generate_answer",
            return_value=("Emergency care is covered. [S1]", False),
        ):
            get_settings.return_value.openai_embedding_model = "text-embedding-3-small"
            evaluation = self.client.post(
                "/api/v1/evaluate",
                json={
                    "question": "emergency care",
                    "relevant_doc_ids": ["health.pdf"],
                    "config": {
                        "top_k": 3,
                        "embedding_model": "text-embedding-3-small",
                        "retriever": "pgvector cosine",
                    },
                },
            )
        self.assertEqual(evaluation.status_code, 200, evaluation.text)
        self.assertEqual(
            evaluation.json()["retrieved_documents"][0]["filename"],
            "health.pdf",
        )

        stats = self.client.get("/api/v1/policies/dashboard/stats")
        self.assertEqual(stats.status_code, 200, stats.text)
        self.assertEqual(stats.json()["indexed_policies"], 1)
        archive = self.client.delete(f"/api/v1/policies/{policy['id']}")
        self.assertEqual(archive.status_code, 204)
        self.assertEqual(self.client.get(f"/api/v1/policies/{policy['id']}").json()["status"], "archived")

    def test_evaluation_rejects_unindexed_embedding_model(self):
        with patch("backend.app.api.v1.endpoints.search.get_settings") as get_settings:
            get_settings.return_value.openai_embedding_model = "text-embedding-3-small"
            response = self.client.post(
                "/api/v1/evaluate",
                json={
                    "question": "What is covered?",
                    "config": {"embedding_model": "different-model"},
                },
            )
        self.assertEqual(response.status_code, 422)
        self.assertIn("Re-embed", response.json()["detail"])

    def test_evaluation_endpoint_returns_adapter_response_for_rag_studio(self):
        vector = [1.0] + [0.0] * 1535
        with patch(
            "backend.app.api.v1.endpoints.search.get_settings"
        ) as get_settings, patch(
            "backend.app.services.policy_service.embed_texts",
            return_value=[vector],
        ), patch(
            "backend.app.api.v1.endpoints.search.generate_answer",
            return_value=("Not enough indexed evidence.", True),
        ) as generate_answer:
            get_settings.return_value.openai_embedding_model = "text-embedding-3-small"
            response = self.client.post(
                "/api/v1/evaluate",
                json={
                    "question": "What is covered?",
                    "relevant_doc_ids": [],
                    "config": {
                        "top_k": 4,
                        "model": "gpt-4o-mini",
                        "embedding_model": "text-embedding-3-small",
                        "retriever": "pgvector cosine",
                        "prompt": "Use short answers.",
                    },
                },
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["abstained"])
        self.assertIn("retrieved_documents", response.json())
        request = generate_answer.call_args.args[0]
        self.assertEqual(request.top_k, 4)
        self.assertEqual(generate_answer.call_args.kwargs["prompt_instructions"], "Use short answers.")


if __name__ == "__main__":
    unittest.main()
