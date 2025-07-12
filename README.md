![gman](https://github.com/user-attachments/assets/f0f40d23-6de0-4ab3-b185-be5c4d32c812)
# Rise and shine. Mr. Freeman. Rise. And. Shine.
**This project is a fork of the original g_man bot. (https://github.com/nkrasn/g_man) So credits to nkrasn for making this bot.**

# G-Man
A Discord multi-purpose bot.

## Features
* Slash commands with user install support.
* Simple media editing commands.
* A block/allowlisting system along with bot owners being able to globally block users or servers.
* A command block/allowlisting system that works similar to the block and allowlist system.
* Many information commands.
  * Such as userinfo, channelinfo, and serverinfo (there's more of course.)
* A reminder system.
* A YouTube search command.
* Music commands with FFMPEG audio filters support along with a queue system.
* A prefix changing system.
* An AI chatbot command via Ollama.
* Code execution server and command that includes custom packages like yt-dlp, ffmpeg, etc.
* And lastly, a tag system with tagscripting support.

## Usage/Commands
You can now just type `g-help` in a channel to see all the commands.

## Requirements
* The FFMPEG binary/executable, and YT-DLP package from pip (remember, not the executable for yt-dlp)
* Ollama
* Docker
* A PostgreSQL database
  * see the `setup.sql` file and run the query. This is required for the prefix, command/bot block/allowlisting system, reminder system, and tags.
* All the Python packages in requirements.txt

You can install the Python packages, preferably in a virtual environment, by running
```
pip install -r requirements.txt
```

*Tip:* If you're using Mac or Linux, you may have Python 2/Pip 2 preinstalled. You should run:
```
pip3 install -r requirements.txt
```
<br> If the pip installation didn't work, try to install the packages seperately because I suck at finding a good compatible version for the requirements.txt file.
## Installation
* Download/install all requirements.
* Set up these folders with the following contents (if a folder doesn't exist, create it):
  * vids
    * Keep this folder empty as its contents are often deleted.
* Create a copy of `bot_info_template.json` and rename it to `bot_info.json`. Fill it in with the appropriate information (keep the quotes).
* Go to the g-coder directory and run `docker-compose up -d --build` to set up the code execution server.
  * Code execution server's port is 8000.
* Run `py gman.py` (or if you are on Linux/macOS, `python3 gman.py`)
# Terms of Service & Privacy Policy
**You must follow our ToS and Privacy Policy in order to use the public version of G-Man. Please keep in mind I am a normal human being and that I can make mistakes. I have a life.**
## Terms of Service
* Do not use G-Man in order to violate the public laws or Terms of Service/Privacy Policy of Discord or any other services.
  * Additionally, do not use G-Man in order to download or share media that is DRM-protected/illegal.
  * Also includes violating any other country laws including Türkiye.
  * Along with the `ai` command.
* I reserve the right to terminate your usage of G-Man for any reason, any time, any where.
* You may not use G-Man in order to target an individual or groups of individuals.
* You may not use G-Man if you are under the age of 13. Though it may depend on your country's laws in order to use Discord, so it can be higher than just 13.
## Privacy Policy
* We do not use your personal information whatsoever.
  * We only use these data: Guilds and their IDs (Servers), Channels and their IDs, Roles and their IDs, and Users/Members and their IDs. All of which are required for moderation purposes and for the bot to function perfectly.
  * Additionally, the command content will be included anytime you or anyone uses any commands. This is for moderation and monitoring purposes, along with debugging.
  * I do NOT share these data with anyone at all.
* I am not responsible/liable for any media/content that is created from other users using G-Man.
* **If you wish to opt-out of using G-Man and want your data removed completely, make sure to remove the G-Man bot from any servers you own/manage and deauthorize the bot from your account. If you however still want to use G-Man but don't want your data to be given at all, please look at the installation instructions in order to self-host G-Man.**
