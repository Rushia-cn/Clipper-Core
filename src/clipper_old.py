import re
import os
import uuid
import os.path as pt
import logging
import traceback
import subprocess as sp

from ffmpeg_normalize import FFmpegNormalize
from b2sdk.v1 import *

lg = logging.getLogger("ClipSync")


class Clipper:
    """
    Tool class for downloading clip from video rushia_clipper, upload to B2 storage and sync the info (.json) to CF Workers
    The code is really messed up, needed to be refactored in future #TODO
    """
    _time_pattern = re.compile(r"\d*:[0-5]\d?:[0-5]\d?")

    def __init__(self, account_id=None,
                 namespace=None,
                 cf_token=None,
                 cf_email=None,
                 key_id=None,
                 app_key=None,
                 bucket_name="RushiaBtn",
                 storage_path="storage",
                 proxy=None):
        lg.info("Start initializing ClipSync")
        account_id = account_id or os.environ["CF_ACCOUNT_ID"]
        namespace = namespace or os.environ["CF_NAMESPACE"]
        cf_token = cf_token or os.environ["CF_TOKEN"]
        cf_email = cf_email or os.environ["CF_EMAIL"]
        key_id = key_id or os.environ["B2_KEY_ID"]
        app_key = app_key or os.environ["B2_APP_KEY"]
        if not (account_id and namespace and cf_token and cf_email):
            raise ClipperError("Credential for CF is needed, "
                               "set CF_ACCOUNT_ID, CF_NAMESPACE, CF_TOKEN, CF_EMAIL "
                               "as environment variable or pass in as arguments")
        if not (key_id and app_key):
            raise ClipperError("Credential for B2 is needed, "
                               "set B2_KEY_ID and B2_APP_KEY "
                               "as environment variable or pass in as arguments")
        info = InMemoryAccountInfo()
        self._api = B2Api(info)
        self._api.authorize_account("production", key_id, app_key)
        self._bucket = self._api.get_bucket_by_name(bucket_name)
        self._file_link_template = f"https://f002.backblazeb2.com/file/{bucket_name}/{'{}'}"
        self._storage_path = storage_path
        self._proxy = proxy
        self._kv = WorkersKV(account_id, namespace, cf_token, cf_email)
        if not pt.exists(storage_path):
            os.mkdir(storage_path)
        self._categories = self.load_category()
        lg.info("Finished initializing ClipSync")

    def load_category(self):
        try:
            return self._kv['categories']
        except WorkersKVError:
            lg.warning("Cannot find categories in KV, creating")
            categories = []
            self._kv['categories'] = categories
            return categories

    def set_category(self):
        self._kv['categories'] = self._categories

    def _check_time_fmt(self, t):
        return bool(self._time_pattern.match(t))

    def _build_download_command(self, url, start: str, end: str):
        """if start:
            if not self._check_time_fmt(start):
                raise ClipperError("Invalid start")"""
        start = start or "00:00:00"
        if end:
            end = f"-to {end}"
        else:
            end = ""
        command = ["youtube-dl",
                   "-x",
                   "-o", f"{self._storage_path}/{uuid.uuid4()}.%(ext)s",
                   "--postprocessor-args", f"-ss {start} {end}",
                   "--audio-format", "mp3",
                   "--audio-quality", "0"]
        if self._proxy:
            command.extend(["--proxy", self._proxy])
        command.append(url)
        return command

    def _run(self, cmd):
        out = sp.run(cmd, capture_output=True)
        if err := out.stderr:
            raise ClipperError(err.decode())

    def _normalize(self, in_path, test_loadness=False):
        """
        Use ffmpeg-normalize to normalize a clip.
        :param in_path: path for the input audio file
        :param test_loadness: test loudness
        :return:
        """
        fn = FFmpegNormalize(normalization_type="rms", audio_codec="libmp3lame", output_format="mp3")
        name = pt.split(in_path)[-1]
        out_path = f"{self._storage_path}/normalized/{name}"
        fn.add_media_file(in_path, out_path)
        fn.run_normalization()
        if test_loadness:
            self._run(f"ffmpeg -i {out_path} -filter:a volumedetect -f null /dev/null".split())
        return out_path

    def _download(self, url, start: str, end: str):
        """
        Download clip from `url` which can be any video rushia_clipper that's supported by youtube-dl
        :param url:
        :param start:
        :param end:
        :return:
        """
        cmd = self._build_download_command(url, start, end)
        dir = cmd[3] % {"ext": "mp3"}
        lg.info(f"Start downloading audio to {dir}")
        self._run(cmd)
        lg.info("Done downloading, start normalizing")
        o_dir = self._normalize(dir)
        lg.info("Done normalizing")
        os.remove(dir)
        return o_dir

    def _upload(self, path, filename) -> FileVersionInfo:
        lg.info(f"Uploading {filename}")
        ret = self._bucket.upload_local_file(local_file=path, file_name=filename)
        lg.info("Done uploading")
        return ret

    def generate_clip(self, url,
                      start: str = None,
                      end: str = None):
        """
        Method for generating a clip, don't call directly. Use inquiry for a prompt env.
        First a clip will be downloaded into `_storage_path` and a random UUID will be generated for the clip
        Then the clip will be normalized with `ffmpeg-normalize`
        The clip will be stored inside `_storage_path/normalized`
        :param url: url for the clip. Reference purpose
        :param start: optional. start point of the clip from video. default to 0:0:0
        :param end: optional. end point of the clip from video. default to then end of video
        :return:
        """
        file_path = self._download(url, start, end)
        lg.info(f"File storaged at {file_path}")
        file_name = pt.split(file_path)[-1]
        self._upload(file_path, file_name)
        return self._file_link_template.format(file_name)

    def check_category(self, category):
        """
        Check if a category is existed. Search for all languages
        :param category: the category
        :return: Optional[dict]
        """
        for x in self._categories:
            if category in x["name"].values():
                return x
        return None

    def create_category(self, name_dict):
        """
        Create a empty category with no clip
        :param name_dict: a dict contains name info. e.g. {'en': 'foo', 'zh': 'bar'}
        """
        self._categories.append({
            "name": name_dict,
            "clips": []
        })

    @property
    def categories(self):
        return [x['name']["en"] for x in self._categories]


class ClipperError(Exception):
    pass
