from fastapi import FastAPI

from app.config import settings
from app.routes.images import router as images_router
from app.routes.jobs import router as jobs_router
from app.routes.posts import router as posts_router
from app.routes.reviews import router as reviews_router


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
)
app.include_router(images_router)
app.include_router(posts_router)
app.include_router(jobs_router)
app.include_router(reviews_router)


@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "environment": settings.environment,
    }