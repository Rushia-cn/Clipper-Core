import re
import os
import time
from logging import basicConfig
from src.clipper import Clipper
from src.exception import ClipError

basicConfig(level="INFO")

"""
A bat program read contents from ../bat which contains clipper command like:
https://youtu.be/_6_gwZd-HEE 0:06:52 00:06:53 test_category zh:rua jp:aaa en:fff
^Url                         ^Start  ^End     ^cat          ^names(locale:name)
"""

pattern = re.compile(r"(https?://\w*?.\w+?\.\w{2,}/.*?)\s(\d{1,2}:[0-5]?\d:[0-5]?\d(.\d{3})?\s){2}(\w*?)(\s[a-zA-Z]{2}:\w*)+")
time_ptrn = re.compile(r"\d{1,2}:[0-5]?\d:[0-5]?\d(.\d{3})?\s\d{1,2}:[0-5]?\d:[0-5]?\d(.\d{3})?")
lang_ptrn = re.compile(r"[a-zA-Z]{2}:\".*?\"")
clipper = Clipper()


def inquire(msg, boolean=False):
    if boolean:
        msg += " (y/N): "
    else:
        msg += ": "
    result = input(msg)
    if boolean:
        return result.lower() in ["y", "yes"]
    else:
        return result


def parse_line(line):
    parsed = [x.strip() for x in pattern.match(line).groups()]
    url = parsed[0]
    cat = parsed[3]
    time = time_ptrn.search(line)[0].split()
    names = lang_ptrn.findall(line)
    name_dict = {}
    for name in names:
        splited = name.strip().replace('"', '').split(":")
        name_dict[splited[0]] = splited[1].strip()
    return url, cat, time[0].strip(), time[1].strip(), name_dict


def main(path_to_batch="../bat", yes_to_all=False):
    start_time = time.time()
    published = 0
    failed = 0
    all = 0
    with open(path_to_batch, encoding='utf8') as f:
        for i, line in enumerate(f.readlines()):
            if not line or line == "\n":
                continue
            all += 1
            try:
                url, cat, start, end, name = parse_line(line)
                print(f"\n[   !   ]  Generating {url} @ [{start} - {end}] called {name}\n")
                uid = clipper.generate(url, start, end, yes_to_all)
                publish_approved = yes_to_all
                while not publish_approved:
                    play = inquire("Want to play the audio?", True)
                    if play:
                        clip = clipper.search(uid)
                        os.startfile(os.path.abspath(clip.normalized_path))
                        publish_approved = inquire("Approve publish?", True)
                        if not publish_approved:
                            clip.start = inquire("Start")
                            clip.end = inquire("End")
                            clipper.trim_clip(uid)
                    else:
                        publish_approved = True
                clipper.upload_clip(uid)
                clipper.publish_clip(uid, cat, name)
                published += 1
            except Exception as e:
                print(e)
                failed += 1
    print(f"Work finished. {published}/{all} published, {failed}/{all} failed. "
          f"Used {int(time.time() - start_time)} seconds")


main()
