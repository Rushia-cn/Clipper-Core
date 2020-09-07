from pathlib import Path
import logging
from src.exception import ClipError
import yaml


def load_yaml(dir="config.yml"):
    with open(dir, "r", encoding="utf-8") as f:
        obj = yaml.safe_load(f)
        test_directories(obj["Directories"], False)
        test_directories(obj["FilePaths"], True)
        return obj


def test_directories(dirs, is_file):
    for key, dir in dirs.items():
        dir = Path(dir).absolute()
        try:
            if not dir.exists():
                if is_file:
                    dir.touch()
                else:
                    dir.mkdir()
            dirs[key] = dir
        except Exception as e:
            raise ClipError(f"Error while testing directory {key} ({dir})")