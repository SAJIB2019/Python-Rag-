from fastapi import APIRouter, Depends

from app.api.dependencies import Query, authorize
from app.schemas import QueryInput, QueryResponse

router = APIRouter(prefix="/query", tags=["query"], dependencies=[Depends(authorize)])


@router.post("", response_model=QueryResponse, status_code=201)
async def query(body: QueryInput, service: Query):
    return await service.query(body.question)
