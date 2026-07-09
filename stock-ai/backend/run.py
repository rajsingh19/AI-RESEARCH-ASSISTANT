import uvicorn
from app.config import get_settings
# from memory_profiler import profile

# if __name__ == "__main__":
#     settings = get_settings()
#     uvicorn.run(
#         "app.main:app",
#         host="0.0.0.0",
#         port=8000,
#         reload=False,
#     )

def start():
    settings = get_settings()

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port= 8000,
        reload=False,
    )

if __name__ == "__main__":
    start()