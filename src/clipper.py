import re
import json
import atexit
import logging
import functools
import subprocess as sp
from pathlib import Path
from typing import Optional, Dict, AnyStr
from dataclasses import dataclass, field, asdict
from datetime import datetime
from time import time

from src.utils import (
    log,
    log_this,
    gen_id
)
from src.load_config import load_yaml
from src.exception import ClipError

from requests import Session
from youtube_dl import YoutubeDL
from ffmpeg_normalize import FFmpegNormalize
from b2sdk.v1 import InMemoryAccountInfo, B2Api


@atexit.register
def clean():
    if instance := Clipper.instance:
        instance.save()


@dataclass
class Clip:
    url: str
    start: str = "0:0:0"
    end: str = None
    uid: str = field(default_factory=gen_id)
    download_path: str = None
    trimmed_path: str = None
    normalized_path: str = None
    file_url: str = None
    published: bool = False

    @property
    def saves(self):
        json = asdict(self)
        json["edit_time"] = datetime.now().isoformat()
        return json


class Clipper:
    _time_pattern = re.compile(r"\d*:[0-5]\d?:[0-5]\d?(.\d{3})?")
    _cmd_pattern = re.compile(r"(https?://\w*?.\w+?\.\w{2,}/.*?)\s"
                              r"(\d{1,2}:[0-5]?\d:[0-5]?\d(.\d{3})?\s)"
                              r"(\d{1,2}:[0-5]?\d:[0-5]?\d(.\d{3})?\s)"
                              r"(\w*?)"
                              r"(\s[a-zA-Z]{2}:\".*\")+")
    _lang_pattern = re.compile(r"[a-zA-Z]{2}:\".*?\"")
    _local_clips_path = Path("../clips.lock")
    instance = None

    def __new__(cls, *args, **kwargs):
        if not cls.instance:
            log("No Clipper instance found, creating new instance")
            obj = object.__new__(cls)
            cls.instance = obj
            return obj
        else:
            log("Instance of Clipper already exists, return it")
            return cls.instance

    def __init__(self):
        log("Initializing Clipper")
        self.clips: Dict[AnyStr, Clip] = None
        self.c = load_yaml()
        logging.basicConfig(
            level=self.c["Logging"]["level"],
            format=self.c["Logging"]["format"]
        )
        self.load_local_clips()
        self.meta = ClipsMeta.from_url(
            self.get_config("MetaSource", "endpoint"),
            self.get_config("MetaSource", "token")
        )
        key_id = self.get_config("B2", "key_id")
        app_key = self.get_config("B2", "app_key")
        log("Initializing B2")
        info = InMemoryAccountInfo()
        self._api = B2Api(info)
        self._api.authorize_account("production", key_id, app_key)
        self._bucket = self._api.get_bucket_by_name(
            self.get_config("B2", "bucket_name")
        )
        self._file_link_template = "https://rushia.moe/clips?uid={uid}"
        log("Done initializing Clipper")

    @log_this
    def load_local_clips(self):
        with open(self.c["FilePaths"]["clips_lock"], "r") as f:
            self.clips = {k: Clip(**v) for k, v in json.load(f).items()}

    def search(self, uid) -> Optional['Clip']:
        if uid is Clip:
            return uid
        clip = self.clips.get(uid)
        if not clip:
            raise ClipError(f"Unable to find clip #{uid}")
        return clip

    @log_this
    def new_clip(self, url, start=None, end=None):
        log("Creating new clip")
        if start and not self._time_pattern.match(start):
            raise ClipError("Invalid start")
        if end and not self._time_pattern.match(end):
            raise ClipError("Invalid end")
        clip = Clip(url, start, end)
        uid = clip.uid
        self.clips[uid] = clip
        return uid

    @log_this
    def download_clip(self, uid, force=False):
        clip = self.search(uid)
        for c in self.clips.values():
            if c.download_path and clip.url == c.url:
                clip.download_path = c.download_path
                break
        if clip.download_path and not force:
            log(f"{uid} is already downloaded, pass")
            return
        download_path = f"{self.get_config('Directories', 'downloaded')}/" \
                        f"{clip.uid}.%(ext)s"
        with YoutubeDL({
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec':self.get_config("Clips", "storage_codec"),
                'preferredquality': '192'
            }],
            'outtmpl': download_path
        }) as ytdl:
            ytdl.download([clip.url])
        clip.download_path = download_path % \
                             {'ext': self.get_config("Clips", "storage_ext")}
        return True

    @log_this
    def trim_clip(self, uid):
        clip = self.search(uid)
        trimmed_path = f"{self.get_config('Directories', 'trimmed')}" \
                       f"/{uid}.{self.get_config('Clips', 'trim_ext')}"
        cmd = [
            'ffmpeg',
            '-vn',
            '-y',
            '-i', clip.download_path,
            '-ss', clip.start
        ]
        if clip.end:
            cmd.extend(['-to', clip.end])
        cmd.append(trimmed_path)
        log("Trim", uid, "with cmd: ", *cmd)
        res = sp.Popen(cmd, stdout=sp.PIPE, stderr=sp.PIPE)
        try:
            code = res.wait(timeout=60)
        except sp.TimeoutExpired as e:
            raise ClipError(f"Timeout while trimming {uid}")
        if code != 0:
            raise ClipError(f"{res.stdout.read()}\n{res.stderr.read()}")
        else:
            clip.trimmed_path = trimmed_path

    @log_this
    def normalize_clip(self, uid):
        clip = self.search(uid)
        fn = FFmpegNormalize(normalization_type="rms",
                             audio_codec=self.get_config("Clips", "normalize_codec"),
                             target_level=-24)
        out = f"{self.get_config('Directories', 'normalized')}/{clip.uid}.{self.get_config('Clips', 'normalize_ext')}"
        fn.add_media_file(clip.trimmed_path, out)
        fn.run_normalization()
        clip.normalized_path = out

    @log_this
    def upload_clip(self, uid):
        clip = self.search(uid)
        full_name = f"{clip.uid}.mp3"
        self._bucket.upload_local_file(local_file=clip.normalized_path,
                                       file_name=full_name)
        clip.file_url = self.get_config("Clips", "file_url").format(uid=uid)

    @log_this
    def generate(self, url, start, end, upload=True):
        uid = self.new_clip(url, start, end)
        self.download_clip(uid)
        self.trim_clip(uid)
        self.normalize_clip(uid)
        if upload:
            self.upload_clip(uid)
        return uid

    def _parse_cmd(self, cmd):
        parsed = self._cmd_pattern.match(cmd).groups()
        if not parsed:
            raise ClipError("Unable to parse")
        url = parsed[0]
        start = parsed[1].strip()
        end = parsed[3].strip()
        cat = parsed[5]
        names = self._lang_pattern.findall(parsed[6])
        name_dict = {}
        for name in names:
            splited = name.strip().replace('"', '').split(":")
            name_dict[splited[0]] = splited[1].strip()
        return url, cat, start, end, name_dict

    @log_this
    def run_cmd(self, cmd, upload=True, publish=False):
        url, cat, start, end, name_dict = self._parse_cmd(cmd)
        uid = self.generate(url, start, end, upload)
        if publish:
            self.publish_clip(uid, cat, names=name_dict)
        return url, cat, start, end, name_dict

    @log_this
    def publish_clip(self, uid, cat, names):
        clip = self.search(uid)
        self.meta.put_clip(clip, cat, names)
        self.meta.upload()
        clip.published = True

    @log_this
    def put_cat(self, _id, names):
        self.meta.put_cat(_id, names)

    def get_config(self, *args):
        ret = self.c[args[0]]
        for arg in args[1:]:
            ret = ret[arg]
        return ret

    def get_info(self, uid):
        return asdict(self.search(uid))

    def save(self):
        if not self.clips:
            log("Clipper.clips is either not loaded or does not exist, quit without saving")
            return
        with open(self.get_config("FilePaths", "clips_lock"), "w") as f:
            json.dump({clip.uid: clip.saves for clip in self.clips.values()}, f, indent=4)


class ClipsMeta:

    def __init__(self, url, token):
        self.s = Session()  # Requests Session for request and upload meta json
        self.url = url
        self.json = None
        self.categories = {}
        self.clips = {}
        self.token = token
        self.test_token()

    @classmethod
    def from_url(cls, url, token):
        obj = cls(url, token)
        obj.download()
        return obj

    @log_this
    def test_token(self):
        req = self.s.options(self.url, params={'t': self.token})
        if not req.ok:
            raise ClipError("Invalid token")
        return True

    def download(self):
        self.json = self.s.get(self.url).json()
        self.categories = self.json['categories']
        self.clips = self.json['clips']

    def upload(self):
        res = self.s.put(self.url, json=self.json, params={'t': self.token})
        if not res.ok:
            raise ClipError(f"Upload failed: {res.text}")

    def put_cat(self, _id, names):
        self.categories[_id] = names
        self.upload()

    def put_clip(self, clip: Clip, cat, names):
        if cat not in self.categories.keys():
            raise ClipError(f"Unable to find {cat}, "
                            f"use `put_cat` to create")
        self.clips[clip.uid] = {
            "name": names,
            "category": cat,
            "url": clip.file_url,
            "publish_time": int(time())
        }
        self.upload()

    @log_this
    def update_clip(self, clip: Clip, cat=None, names=None):
        if not (cat or names):
            raise ClipError("At least input one of category or name dict")
        if cat not in self.categories.keys():
            raise ClipError(f"Unable to find {cat}, "
                            f"use `put_cat` to create")
        clip_record = self.clips.get(clip.uid)
        if not clip_record:
            raise ClipError("Cannot find this clip. Please publish it first.")
        if cat:
            clip_record['category'] = cat
        if names:
            clip_record['name'] = names
        self.upload()

    @log_this
    def remove_clip(self, uid):
        obj = self.clips.pop(uid, None)
        if obj:
            self.upload()
        return obj
