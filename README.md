![gman](https://github.com/user-attachments/assets/f0f40d23-6de0-4ab3-b185-be5c4d32c812)
# Rise and shine. Mr. Freeman. Rise. And. Shine.
**This project is a fork of the original g_man bot. (https://github.com/nkrasn/g_man) So credits to nkrasn for making this bot.**

# g_man
A Discord bot for editing videos, useful for simple edits or making memes. It can apply a large variety of filters, modify bitrate, and create glitch art. <br>
Filters are applied using FFMPEG, with some corruption commands using tomato.py (https://github.com/itsKaspar/tomato) or AviGlitch (https://github.com/ucnv/aviglitch).

## Features
* Change video and audio bitrate.
* Easily apply various filters such as contrast, blur, volume, etc.
  * For advanced users, there is a !filter command that can apply almost any filter available in FFMPEG.
* Apply premade sequences of filters, such as !tutorial to convert a video into an old-school YouTube tutorial.
* Corrupt videos in various ways, such as datamoshing and modifying random chunks of bytes in the video file.
* Save your videos using a personal bookmark system, and load your bookmarks in any server g_man is in.
* Slash commands with user install support.
* An FFMPEG, ImageMagick, and YT-DLP wrapper commands.
  * This includes a premade caption command too.
* Media EXIF command which uses FFPROBE.
* A block/allowlisting system along with bot owners being able to globally block users or servers.
* A command block/allowlisting system that works similar to the block and allowlist system.
* Many information commands.
  * Such as userinfo, channelinfo, and serverinfo (there's more of course.)
* A reminder system.
* A YouTube search command.
* Music commands with FFMPEG audio filters support along with a queue system.
* A prefix changing system.
* And lastly, an AI chatbot command that will do things like helping you execute commands in human language and general purpose stuff.

## Usage/Commands
You can now just type `!help` in a channel to see all the commands.

## Requirements
* Static build of ffmpeg (version 4.2 or above)
* A PostgreSQL database
  * see the `setup.sql` file and run the query. This is required for the prefix, command/bot block/allowlisting system, and the reminder system.
* ~~A MongoDB database~~ **This is deprecated and I will rewrite the way the old commands work.**
  * ~~The bot looks for a database called `gman`. It uses a collection called `inventory` for the bookmark system and `videos` for keeping track of videos sent.~~
* AviGlitch, see https://github.com/ucnv/aviglitch for installation instructions. This is needed for the !mosh command.
* All the Python packages in requirements.txt

You can install the Python packages, preferably in a virtual environment, by running
```
pip install -r requirements.txt
```

*Tip:* If your using Mac or Linux, you may have Python 2/Pip 2 preinstalled. You should run:
```
pip3 install -r requirements.txt
```
<br> If the pip installation didn't work, try to install the packages seperately because I suck at finding a good compatible version for the requirements.txt file.
## Installation
* Download/install all requirements.
* Set up these folders with the following contents (if a folder doesn't exist, create it):
  * ffmpeg-static
    * Add the static build of ffmpeg to this folder (the executable ffmpeg file should be in this folder).
  * vids
    * Keep this folder empty as its contents are often deleted. It's used by g_man for processing videos.
  * fonts
    * Add .ttf files for the Arial and Impact fonts (called `arial.ttf` and `impact.ttf`) to this folder. Arial is required for the `!tutorial` command and Impact for `!text`.
    * (Optional) Upload any additional .ttf you want to use (useful if you use the `!filter` command).
  * tutorial/songs
    * Add any .mp3 background music you want for the !tutorial command. Some fitting songs are:
      * Trance - 009 Sound System Dreamscape
      * Evanescence - Bring Me to Life
      * Papa Roach - Last Resort
      * Any other songs used in YouTube tutorial videos during the late 2000's.
  * clips
    * Add the following .mp3 files if you wish to use the commands associated with them:
      * `americ.mp3` (The song "Never Meant" by American Football, used with the `!americ` command).
      * `mahna.mp3` (The song "Mah Na Mah Na" from the Muppets soundtrack, used with the `!mahna` command).
      * `tetris.mp3` (The Tetris beatbox song by Verbalase, used with the `!tetris` command).
* Create a copy of `bot_info_template.json` and rename it to `bot_info.json`. Fill it in with the appropriate information (keep the quotes).
* Run `python3 gman.py`
