import unittest
from datetime import date
from io import BytesIO
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.app.db.base import CustomerBase
from backend.app.db.customer_session import get_customer_session
from backend.app.main import app
from backend.app.models.customer import Customer
from backend.app.services.customer_service import CustomerCsvError, parse_customer_csv

CUSTOMER_CSV = (
    "customer_id,first_name,last_name,date_of_birth,gender,phone,email,city,state,"
    "country,pincode,policy_id,policy_type,policy_term_years,policy_start_date,"
    "maturity_date,claim_type,policy_status\n"
    "CUST-1,Ada,Shah,1990-05-10,Female,+91-9000000000,ada@example.com,"
    "Pune,Maharashtra,India,411001,POL-1,Health Insurance,3,2024-01-01,"
    "2027-01-01,Medical Emergency,Active\n"
)


class CustomerImportTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        CustomerBase.metadata.create_all(self.engine)
        self.session = Session(self.engine, expire_on_commit=False)

        def override_session():
            yield self.session

        app.dependency_overrides[get_customer_session] = override_session
        self.initializer = patch("backend.app.main.initialize_customer_database")
        self.initializer.start()
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.initializer.stop()
        app.dependency_overrides.clear()
        self.session.close()
        self.engine.dispose()

    def test_upload_inserts_customers_and_customer_lookup_returns_row(self):
        with patch("backend.app.api.v1.endpoints.customers.get_settings") as get_settings:
            get_settings.return_value.max_upload_bytes = 1024 * 1024
            response = self.client.post(
                "/api/v1/customers/upload",
                files={"file": ("customers.csv", CUSTOMER_CSV.encode(), "text/csv")},
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            response.json(),
            {"rows_received": 1, "inserted": 1, "updated": 0},
        )
        lookup = self.client.get("/api/v1/customers/CUST-1")
        self.assertEqual(lookup.status_code, 200, lookup.text)
        self.assertEqual(lookup.json()["email"], "ada@example.com")
        self.assertEqual(lookup.json()["date_of_birth"], date(1990, 5, 10).isoformat())

    def test_upload_upserts_existing_customer_and_inserts_new_customer(self):
        record = parse_customer_csv(CUSTOMER_CSV.encode())[0]
        self.session.add(Customer(**record))
        self.session.commit()
        changed_csv = CUSTOMER_CSV.replace("Ada,Shah", "Ada,Patel").replace(
            "2024-01-01", "2025-01-01"
        )
        lines = changed_csv.splitlines()
        new_customer_row = lines[1].replace(
            "CUST-1", "CUST-2"
        ).replace("POL-1", "POL-2").replace("ada@example.com", "ada2@example.com")
        two_rows_csv = "\n".join([lines[0], lines[1], new_customer_row]) + "\n"

        with patch("backend.app.api.v1.endpoints.customers.get_settings") as get_settings:
            get_settings.return_value.max_upload_bytes = 1024 * 1024
            response = self.client.post(
                "/api/v1/customers/upload",
                files={"file": ("customers.csv", two_rows_csv.encode(), "text/csv")},
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            response.json(),
            {"rows_received": 2, "inserted": 1, "updated": 1},
        )
        self.session.expire_all()
        self.assertEqual(self.session.get(Customer, "CUST-1").last_name, "Patel")
        self.assertEqual(self.session.get(Customer, "CUST-1").policy_start_date, date(2025, 1, 1))
        self.assertEqual(self.session.get(Customer, "CUST-2").email, "ada2@example.com")

    def test_invalid_row_rejects_entire_import(self):
        invalid_csv = CUSTOMER_CSV.replace("1990-05-10", "not-a-date")

        with patch("backend.app.api.v1.endpoints.customers.get_settings") as get_settings:
            get_settings.return_value.max_upload_bytes = 1024 * 1024
            response = self.client.post(
                "/api/v1/customers/upload",
                files={"file": ("customers.csv", invalid_csv.encode(), "text/csv")},
            )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.session.query(Customer).count(), 0)

    def test_csv_duplicate_customer_ids_are_rejected(self):
        with self.assertRaisesRegex(CustomerCsvError, "duplicated within the CSV"):
            parse_customer_csv((CUSTOMER_CSV + CUSTOMER_CSV.splitlines()[1] + "\n").encode())

    def test_upload_rejects_non_csv_file(self):
        response = self.client.post(
            "/api/v1/customers/upload",
            files={"file": ("customers.txt", BytesIO(b"customer data"), "text/plain")},
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.session.query(Customer).count(), 0)


if __name__ == "__main__":
    unittest.main()
