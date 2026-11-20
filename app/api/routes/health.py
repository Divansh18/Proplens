from fastapi import APIRouter, Request

router = APIRouter(tags=["health"])


@router.get("/health")
def health(request: Request) -> dict[str, str | int]:
    return {"status": "ok", "documents_loaded": request.app.state.documents_loaded}
