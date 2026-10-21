import logging

import uvicorn

from app.core.config import Settings

if __name__ == "__main__":
    settings = Settings()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    uvicorn.run("app.main:app", host="127.0.0.1", port=settings.port)
