import uuid
import logging
from functools import wraps
from src.load_config import load_yaml

lg = logging.getLogger("Clipper")


def log(*args):
    lg.info(' '.join([str(x) for x in args]))


def log_this(func):
    @wraps(func)
    def inner(*args, **kwargs):
        log(func.__name__, "called with arguments", ", ".join(
            [*[str(x) for x in args], *[f"{k}={v}" for k, v in kwargs.items()]]
        ))
        return func(*args, **kwargs)
    return inner


def gen_id():
    return str(uuid.uuid4())[:6]