import os
import re
import uuid
import json
import atexit
import subprocess as sp
from logging import getLogger
from typing import Optional, Dict, AnyStr
from dataclasses import dataclass, field, asdict
from pathlib import Path
from time import time
from functools import wraps

from src.exception import ClipError

from requests import Session
from youtube_dl import YoutubeDL
from ffmpeg_normalize import FFmpegNormalize
from b2sdk.v1 import InMemoryAccountInfo, B2Api

lg = getLogger("Clipper")


def log(*args):
    lg.info(f"[Clipper] {' '.join([str(x) for x in args])}")


def log_this(func):
    @wraps(func)
    def inner(*args, **kwargs):
        log(func.__name__, "called")
        return func(*args, **kwargs)
    return inner


def gen_id():
    return str(uuid.uuid4())[:6]


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
    download_path: Path = None
    trimmed_path: Path = None
    normalized_path: Path = None
    file_url: str = None
    published: bool = False


class Clipper:
    _time_pattern = re.compile(r"\d*:[0-5]\d?:[0-5]\d?")
    _local_clips_path = Path("../clips.lock")
    instance = None

    def __new__(cls, *args, **kwargs):
        if not cls.instance:
            log("No Clipper instance found, creating new instance")
            obj = object.__new__(cls)
            cls.instance = obj
            return obj
        else:
            log("Instamce of Clipper already exists, return it")
            return cls.instance

    def __init__(self):
        log("Initializing Clipper")
        self.clips: Dict[AnyStr, Clip] = None
        self.load_local_clips()
        self.meta = ClipsMeta.from_url(os.environ["TOKEN"])
        key_id = os.environ["B2_KEY_ID"]
        app_key = os.environ["B2_APP_KEY"]
        if not (key_id and app_key):
            raise ClipError("Credential for B2 is needed, "
                            "set B2_KEY_ID and B2_APP_KEY "
                            "as environment variable or pass in as arguments")
        log("Initializing B2")
        info = InMemoryAccountInfo()
        self._api = B2Api(info)
        self._api.authorize_account("production", key_id, app_key)
        self._bucket = self._api.get_bucket_by_name("RushiaBtn")
        self._file_link_template = "https://f002.backblazeb2.com/file/RushiaBtn/{}"
        log("Done initializing Clipper")

    @log_this
    def load_local_clips(self):
        if self._local_clips_path.exists():
            log("Loading clip info from", self._local_clips_path)
            with open(self._local_clips_path, "r") as f:
                self.clips = {k: Clip(**v) for k, v in json.load(f).items()}
        else:
            log("Unable to find", self._local_clips_path, "creating")
            self._local_clips_path.touch()
            with open(self._local_clips_path, "w") as f:
                self.clips = dict()
                json.dump(self.clips, f, indent=4)

    def search(self, uid) -> Optional['Clip']:
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
        download_path = f"storage/{clip.uid}.%(ext)s"
        with YoutubeDL({
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'opus',
                'preferredquality': '192'
            }],
            'outtmpl': download_path
        }) as ytdl:
            ytdl.download([clip.url])
        print("done")
        clip.download_path = Path(download_path % {'ext': 'opus'})
        return True

    @log_this
    def trim_clip(self, uid):
        clip = self.search(uid)
        trimmed_path = f"trimmed/{uid}.mp3"
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
            raise ClipError(res.stderr)
        else:
            clip.trimmed_path = Path(trimmed_path)

    @log_this
    def normalize_clip(self, uid):
        clip = self.search(uid)
        fn = FFmpegNormalize(normalization_type="rms",
                             audio_codec="libmp3lame",
                             target_level=-16)
        out = f"normalized/{clip.uid}.mp3"
        fn.add_media_file(clip.trimmed_path, out)
        fn.run_normalization()
        clip.normalized_path = out

    @log_this
    def upload_clip(self, uid):
        clip = self.search(uid)
        full_name = f"{clip.uid}.mp3"
        self._bucket.upload_local_file(local_file=str(clip.normalized_path.absolute()),
                                       file_name=full_name)
        clip.file_url = self._file_link_template.format(full_name)

    @log_this
    def generate(self, url, start, end):
        uid = self.new_clip(url, start, end)
        self.download_clip(uid)
        self.trim_clip(uid)
        self.normalize_clip(uid)
        self.upload_clip(uid)
        return uid

    @log_this
    def publish_clip(self, uid, cat, names):
        clip = self.search(uid)
        self.meta.put_clip(clip, cat, names)
        self.meta.upload()
        clip.published = True

    @log_this
    def put_cat(self, _id, names):
        self.meta.put_cat(_id, names)

    def get_info(self, uid):
        return asdict(self.search(uid))

    def save(self):
        with open(self._local_clips_path, "w") as f:
            json.dump({clip.uid: asdict(clip) for clip in self.clips.values()}, f)


class ClipsMeta:
    _cf_endpoint = "https://category.rushia.moe"

    def __init__(self, url, token):
        self.s = Session()  # Requests Session for request and upload meta json
        self.url = url or self._cf_endpoint
        self.json = None
        self.categories = {}
        self.clips = {}
        self.token = token
        self.test_token()

    @classmethod
    def from_url(cls, token, url=None):
        obj = cls(url, token)
        obj.download()
        return obj

    @log_this
    def test_token(self):
        req = self.s.options(self._cf_endpoint, params={'t': self.token})
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
