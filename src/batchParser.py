import re
from dataclasses import dataclass, asdict
from typing import Optional, List, TextIO
from src.exception import ClipError


__all__ = "load", "dump"


@dataclass
class ButtonBatchLine:
    url: str
    start: str
    end: str
    cat: str
    names: dict

    @property
    def json(self):
        return asdict(self)

    @property
    def line(self):

        return " ".join([_format_name_dict(x) for x in self.json.values()])


pattern = re.compile(r"(https?://\w*?.\w+?\.\w{2,}/.*?)\s"
                     r"(\d{1,2}:[0-5]?\d:[0-5]?\d(.\d{3})?\s)"
                     r"(\d{1,2}:[0-5]?\d:[0-5]?\d(.\d{3})?\s)"
                     r"(\w*?)"
                     r"(\s[a-zA-Z]{2}:\".*\")+")
lang_pattern = re.compile(r"[a-zA-Z]{2}:\".*?\"")


def load(fs: TextIO):
    for line in _yield_lines(fs):
        parsed = _parse_line(line)
        if parsed:
            yield parsed


def dump(obj: List[ButtonBatchLine], fp: TextIO):
    fp.writelines([x.line for x in obj])


def _yield_lines(fp: TextIO):
    while True:
        try:
            line = fp.readline()
        except UnicodeDecodeError as e:
            raise ClipError("Make sure use utf-8 decode")
        if not line:
            break
        else:
            yield line


def _parse_line(line: str) -> Optional[ButtonBatchLine]:
    if not line or line.startswith("#") or line == "\n":
        return None
    matched = pattern.match(line)
    parsed = matched.groups()
    if not parsed:
        raise ClipError(f"Error with line {line}")
    url = parsed[0]
    start = parsed[1].strip()
    end = parsed[3].strip()
    cat = parsed[5]
    names = lang_pattern.findall(parsed[6])
    name_dict = {}
    for name in names:
        splited = name.strip().replace('"', '').split(":")
        name_dict[splited[0]] = splited[1].strip()
    if not (url and start and end and cat and name_dict):
        raise ClipError(f"Error with line {line}")
    return ButtonBatchLine(
        url=url,
        start=start,
        end=end,
        cat=cat,
        names=name_dict
    )


def _format_name_dict(obj):
    if type(obj) is str:
        return obj
    return " ".join([f'{i}:"{v}"' for i, v in obj.items()])

