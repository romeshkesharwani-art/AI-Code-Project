import logging

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import func, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.db.customer_session import get_customer_session
from backend.app.models.customer import Customer
from backend.app.schemas.customer import (
    CountItem,
    CustomerImportResult,
    CustomerList,
    CustomerResponse,
    CustomerStats,
)
from backend.app.services.customer_service import (
    CustomerCsvError,
    parse_customer_csv,
    upsert_customers,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/customers", tags=["customers"])


@router.post(
    "/upload",
    response_model=CustomerImportResult,
    status_code=status.HTTP_200_OK,
)
async def upload_customers(
    file: UploadFile = File(...),
    session: Session = Depends(get_customer_session),
) -> CustomerImportResult:
    maximum_size = get_settings().max_upload_bytes
    try:
        if not file.filename or not file.filename.lower().endswith(".csv"):
            raise HTTPException(status_code=422, detail="Upload a .csv customer data file.")
        data = await file.read(maximum_size + 1)
        if len(data) > maximum_size:
            raise HTTPException(status_code=413, detail="The customer CSV exceeds the upload limit.")
        records = parse_customer_csv(data)
        result = upsert_customers(session, records)
        return CustomerImportResult(**result)
    except CustomerCsvError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except SQLAlchemyError as error:
        session.rollback()
        logger.exception("Customer CSV import failed")
        raise HTTPException(
            status_code=503,
            detail="Customer data could not be saved to the database.",
        ) from error
    finally:
        await file.close()


def _counts(session: Session, column) -> list[CountItem]:
    rows = session.execute(
        select(column, func.count()).group_by(column).order_by(func.count().desc(), column)
    ).all()
    return [CountItem(name=name, count=count) for name, count in rows]


@router.get("", response_model=CustomerList)
def list_customers(
    search: str | None = Query(default=None, max_length=100),
    policy_type: str | None = Query(default=None, max_length=100),
    policy_status: str | None = Query(default=None, max_length=50),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    session: Session = Depends(get_customer_session),
) -> CustomerList:
    conditions = []
    if search and search.strip():
        pattern = f"%{search.strip()}%"
        conditions.append(
            or_(
                Customer.customer_id.ilike(pattern),
                Customer.first_name.ilike(pattern),
                Customer.last_name.ilike(pattern),
                Customer.email.ilike(pattern),
                Customer.city.ilike(pattern),
                Customer.policy_id.ilike(pattern),
            )
        )
    if policy_type:
        conditions.append(Customer.policy_type == policy_type)
    if policy_status:
        conditions.append(Customer.policy_status == policy_status)
    try:
        total = session.scalar(select(func.count()).select_from(Customer).where(*conditions)) or 0
        rows = session.scalars(
            select(Customer)
            .where(*conditions)
            .order_by(Customer.customer_id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
    except SQLAlchemyError as error:
        logger.exception("Customer list failed")
        raise HTTPException(status_code=503, detail="Customer data could not be loaded.") from error
    return CustomerList(
        items=[CustomerResponse.model_validate(row) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/stats", response_model=CustomerStats)
def customer_stats(session: Session = Depends(get_customer_session)) -> CustomerStats:
    try:
        total = session.scalar(select(func.count()).select_from(Customer)) or 0
        return CustomerStats(
            total=total,
            by_policy_type=_counts(session, Customer.policy_type),
            by_status=_counts(session, Customer.policy_status),
            by_city=_counts(session, Customer.city),
        )
    except SQLAlchemyError as error:
        logger.exception("Customer stats failed")
        raise HTTPException(status_code=503, detail="Customer data could not be loaded.") from error


@router.get("/{customer_id}", response_model=CustomerResponse)
def get_customer(
    customer_id: str,
    session: Session = Depends(get_customer_session),
) -> CustomerResponse:
    customer = session.get(Customer, customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found.")
    return CustomerResponse.model_validate(customer)
