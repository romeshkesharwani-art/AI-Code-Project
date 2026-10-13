import csv
import io
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from backend.app.models.customer import Customer

CUSTOMER_COLUMNS = (
    "customer_id",
    "first_name",
    "last_name",
    "date_of_birth",
    "gender",
    "phone",
    "email",
    "city",
    "state",
    "country",
    "pincode",
    "policy_id",
    "policy_type",
    "policy_term_years",
    "policy_start_date",
    "maturity_date",
    "claim_type",
    "policy_status",
)
CUSTOMER_TEXT_LIMITS = {
    "customer_id": 36,
    "first_name": 100,
    "last_name": 100,
    "gender": 50,
    "phone": 50,
    "email": 320,
    "city": 100,
    "state": 100,
    "country": 100,
    "pincode": 20,
    "policy_id": 36,
    "policy_type": 100,
    "claim_type": 100,
    "policy_status": 50,
}
DATE_COLUMNS = ("date_of_birth", "policy_start_date", "maturity_date")
UPSERT_BATCH_SIZE = 100


class CustomerCsvError(ValueError):
    pass


def parse_customer_csv(data: bytes) -> list[dict[str, Any]]:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise CustomerCsvError("Upload a UTF-8 encoded customer CSV file.") from error

    try:
        reader = csv.DictReader(io.StringIO(text, newline=""), strict=True)
        headers = [header.strip() if header else "" for header in (reader.fieldnames or [])]
        if not headers:
            raise CustomerCsvError("The CSV file must include a header row.")
        missing = sorted(set(CUSTOMER_COLUMNS) - set(headers))
        if missing:
            raise CustomerCsvError(
                f"CSV is missing required column(s): {', '.join(missing)}."
            )
        if len(headers) != len(set(headers)):
            raise CustomerCsvError("The CSV header contains duplicate column names.")

        reader.fieldnames = headers
        records: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for row_number, row in enumerate(reader, start=2):
            if None in row or any(row.get(column) is None for column in CUSTOMER_COLUMNS):
                raise CustomerCsvError(f"Row {row_number} does not match the CSV header.")
            record: dict[str, Any] = {
                column: (row[column] or "").strip() for column in CUSTOMER_COLUMNS
            }
            for column, limit in CUSTOMER_TEXT_LIMITS.items():
                if not record[column]:
                    raise CustomerCsvError(
                        f"Row {row_number} has an empty required value in '{column}'."
                    )
                if len(record[column]) > limit:
                    raise CustomerCsvError(
                        f"Row {row_number} has a value that exceeds the limit for '{column}'."
                    )
            if record["customer_id"] in seen_ids:
                raise CustomerCsvError(
                    f"Customer ID is duplicated within the CSV at row {row_number}."
                )
            seen_ids.add(record["customer_id"])

            for column in DATE_COLUMNS:
                try:
                    record[column] = date.fromisoformat(record[column])
                except ValueError as error:
                    raise CustomerCsvError(
                        f"Row {row_number} has an invalid ISO date in '{column}'."
                    ) from error
            try:
                record["policy_term_years"] = int(record["policy_term_years"])
            except ValueError as error:
                raise CustomerCsvError(
                    f"Row {row_number} has an invalid integer in 'policy_term_years'."
                ) from error
            if record["policy_term_years"] < 1:
                raise CustomerCsvError(
                    f"Row {row_number} must have a positive 'policy_term_years' value."
                )
            records.append(record)
    except csv.Error as error:
        raise CustomerCsvError("The CSV file could not be parsed.") from error

    if not records:
        raise CustomerCsvError("The CSV file has no customer rows.")
    return records


def upsert_customers(session: Session, records: list[dict[str, Any]]) -> dict[str, int]:
    if session.bind is None:
        raise RuntimeError("The customer database session is not bound to an engine.")
    dialect_name = session.bind.dialect.name
    if dialect_name == "postgresql":
        insert_statement = postgresql_insert(Customer)
    elif dialect_name == "sqlite":
        insert_statement = sqlite_insert(Customer)
    else:
        raise RuntimeError(f"Customer imports are not supported for {dialect_name}.")

    customer_ids = [record["customer_id"] for record in records]
    existing_ids = set(
        session.scalars(
            select(Customer.customer_id).where(Customer.customer_id.in_(customer_ids))
        )
    )
    now = datetime.now(timezone.utc)
    try:
        for offset in range(0, len(records), UPSERT_BATCH_SIZE):
            batch = records[offset : offset + UPSERT_BATCH_SIZE]
            statement = insert_statement.values(batch)
            update_values = {
                column: getattr(statement.excluded, column)
                for column in CUSTOMER_COLUMNS
                if column != "customer_id"
            }
            update_values["updated_at"] = now
            session.execute(
                statement.on_conflict_do_update(
                    index_elements=[Customer.customer_id],
                    set_=update_values,
                )
            )
        session.commit()
    except Exception:
        session.rollback()
        raise

    return {
        "rows_received": len(records),
        "inserted": len(records) - len(existing_ids),
        "updated": len(existing_ids),
    }
