from fastapi import FastAPI
from fastapi.responses import JSONResponse

app = FastAPI()

@app.get("/")
def root():
    return JSONResponse(
        status_code=200,
        content={"message": "API is running"}
    )

@app.get("/health")
def health():
    return JSONResponse(
        status_code=200,
        content={"message": "healthy"}
    )

@app.get("/me")
def me():
    return JSONResponse(
        status_code=200,
        content={
            "name": "Godand",
            "email": "g@gmail.com",
            "github": "https://github.com/godhanded"
        }
    )