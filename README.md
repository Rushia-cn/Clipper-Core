# Clipper-Core for Rushia Button


## About
Clipper is a library for automatically download, trim, normalize, 
upload and publish audio clips to Rushia Button.  
Procedure:

```
Download audio file from [url] 
 |
Trim audio file (while keep the downloaded file for future use)
 |
Normalized audio file
 |
Upload to B2 storage
 |
Publish to Rushia.moe/category
```
Since I'm using [Youtube-dl](https://github.com/ytdl-org/youtube-dl) here, it brings clipper the ability to download
audio from most mainstream websites.

## Directories
``/src/`` - Source code  
``/src/storage`` - downloaded audio file, in `opus` format  
``/src/trimmed`` - trimmed audio file, in `mp3` format
``/src/normalized`` - normalized audio file  
``/clips.lock`` - all `Clip` will be stored into this file to resume the breakpoint  
``/bat`` - file with multiple commands for `main.py` to use. 
See [this page](https://github.com/Rushia-cn/Rushia-button/blob/master/Contribute.md) for more information