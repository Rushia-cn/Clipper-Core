import re
import os
import sys
import time

from src.clipper import Clipper, ClipError
from src.batchParser import load, ButtonBatchLine

"""
A bat program read contents from ../bat which contains clipper command like:
https://youtu.be/_6_gwZd-HEE 0:06:52 00:06:53 test_category zh:"rua" jp:"aaa" en:"fff"
^Url                         ^Start  ^End     ^cat          ^names(locale:"name")
"""


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


def main(path_to_batch="bat", yes_to_all=False, _raise=False, dry_run=False):
    clipper = Clipper() if not dry_run else None
    start_time = time.time()
    published = 0
    failed = 0
    all = 0
    with open(path_to_batch, encoding='utf8') as f:
        for line in load(f):
            try:

                print(f"\n[   !   ]  Generating {line.url} @ [{line.start} - {line.end}] called {line.names}\n")
                uid = clipper.generate(line.url, line.start, line.end, yes_to_all)
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
                            clipper.normalize_clip(uid)
                    else:
                        publish_approved = True
                clipper.upload_clip(uid)
                clipper.publish_clip(uid, line.cat, line.names)
                published += 1
            except Exception as e:
                if _raise:
                    raise
                print(e)
                failed += 1
    print(f"Work finished. {published}/{all} published, {failed}/{all} failed. "
          f"Used {int(time.time() - start_time)} seconds")


main(_raise=True)
