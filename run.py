"""Cardio 服务入口：uvicorn cardio.server:app"""
from cardio.server import app

if __name__ == "__main__":
    import uvicorn
    from cardio import config

    uvicorn.run(
        "cardio.server:app",
        host=config.HOST,
        port=config.PORT,
        reload=False,
        workers=1,
    )
