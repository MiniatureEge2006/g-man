![gman](https://github.com/user-attachments/assets/f0f40d23-6de0-4ab3-b185-be5c4d32c812)
# Rise and shine. Mr. Freeman. Rise. And. Shine.
**This project is a fork of the original g_man bot. (https://github.com/nkrasn/g_man) So credits to nkrasn for making this bot.**

# G-Man
A Discord multi-purpose bot.

## Features
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
You can now just type `g-help` in a channel to see all the commands.

## Requirements
* The FFMPEG binary, ImageMagick binary, and YT-DLP package from pip (remember, not the executable for yt-dlp)
* Ollama
* A PostgreSQL database
  * see the `setup.sql` file and run the query. This is required for the prefix, command/bot block/allowlisting system, and the reminder system.
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
  * vids
    * Keep this folder empty as its contents are often deleted. It's used by g_man for processing videos.
  * fonts
    * Add `arial.ttf` and `Futura Condensed Extra Bold.otf` fonts in this folder. Arial is required for g-tutorial while Futura is for g-caption.
  * tutorial/songs
    * Add any .mp3 background music you want for the g-tutorial command. Some fitting songs are:
      * Trance - 009 Sound System Dreamscape
      * Evanescence - Bring Me to Life
      * Papa Roach - Last Resort
      * Any other songs used in YouTube tutorial videos during the late 2000's.
* Create a copy of `bot_info_template.json` and rename it to `bot_info.json`. Fill it in with the appropriate information (keep the quotes).
* Run `python3 gman.py`
# Terms of Service & Privacy Policy
**You must follow our ToS and Privacy Policy in order to use the public version of G-Man.**
## Terms of Service
* Do not use G-Man in order to violate the public laws or Terms of Service/Privacy Policy of Discord or any other services.
  * Additionally, do not use G-Man in order to download or share media that is DRM-protected/illegal.
  * Also includes violating any other country laws including Türkiye.
  * Along with the `ai` command.
* We reserve the right to terminate your usage of our services at anytime, anywhere for any reason.
* You may not use G-Man in order to target an individual or groups of individuals.
* You may not use G-Man if you are under the age of 13. Though it may depend on your country's laws in order to use Discord, so it can be higher than just 13.
## Privacy Policy
* Everything is stored locally and not stored in some random public database.
* We do not use your personal information whatsoever.
  * We only use these data: Guilds and their IDs (Servers), Channels and their IDs, Roles and their IDs, and Users/Members and their IDs. All of which are required for moderation purposes and for the bot to function perfectly.
  * Additionally, the command content will be included anytime you or anyone uses any commands.
  * We do NOT share these data with anyone at all.
* **If you wish to opt-out of using G-Man and want your data removed completely, make sure to remove the G-Man bot from any servers you own/manage and deauthorize the bot from your account. If you however still want to use G-Man but don't want your data to be given at all, please look at the installation instructions in order to self-host G-Man.**
