from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class CustomerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    customer_id: str
    first_name: str
    last_name: str
    date_of_birth: date
    gender: str
    phone: str
    email: str
    city: str
    state: str
    country: str
    pincode: str
    policy_id: str
    policy_type: str
    policy_term_years: int
    policy_start_date: date
    maturity_date: date
    claim_type: str
    policy_status: str
    created_at: datetime
    updated_at: datetime


class CustomerList(BaseModel):
    items: list[CustomerResponse]
    total: int
    page: int
    page_size: int


class CountItem(BaseModel):
    name: str
    count: int


class CustomerStats(BaseModel):
    total: int
    by_policy_type: list[CountItem]
    by_status: list[CountItem]
    by_city: list[CountItem]


class CustomerImportResult(BaseModel):
    rows_received: int
    inserted: int
    updated: int
