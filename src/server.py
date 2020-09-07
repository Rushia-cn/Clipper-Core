from dataclasses import asdict

from src.clipper import Clipper, Clip
from src.exception import ClipError

from fastapi import FastAPI, HTTPException


app = FastAPI(debug=True)
clipper = Clipper()


def handle(func, *args, **kwargs):
    try:
        return func(*args, **kwargs)
    except ClipError as e:
        raise HTTPException(400, e)
    except Exception as e:
        raise HTTPException(500, e)


@app.get("/clip")
def get_clip(uid: str):
    return handle(lambda : asdict(clipper.search(uid)))


@app.post("/clip")
def post_clip(url: str, start: str = None, end: str = None):
    return handle(lambda : {'uid': clipper.new_clip(url, start, end)})


@app.post("/publish")
def publish_clip(url: str, start: str = None, end: str = None):
    return handle(lambda : {'uid': clipper.generate(url, start, end)})


