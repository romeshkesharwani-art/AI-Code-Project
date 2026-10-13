from fastapi import APIRouter

from backend.app.api.v1.endpoints import customers, policies, search

api_router = APIRouter()
api_router.include_router(customers.router)
api_router.include_router(policies.router)
api_router.include_router(search.router)
