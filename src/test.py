from src.clipper import Clipper
from pprint import pprint


a = Clipper()
for uid, clip in a.meta.clips.items():
    clip['url'] = f"https://rushia.moe/clips?uid={uid}"
a.meta.upload()