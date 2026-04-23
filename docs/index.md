![gman](https://github.com/user-attachments/assets/f0f40d23-6de0-4ab3-b185-be5c4d32c812)

# Rise and shine. Mr. Freeman. Rise. And. Shine.
**This project is a fork of the original g_man bot. (https://github.com/nkrasn/g_man) So credits to nkrasn for making this bot.**

# G-Man
No bullshit Discord multi-purpose bot.

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
* An AI chatbot command via Ollama that supports executing TagScript.
* Code execution server and command that includes custom packages like yt-dlp, ffmpeg, etc. which is useful for scripting.
* And lastly, a tag system which has its own engine for formatting text and stuff called TagScript.

## Usage/Commands
You can now just type `g-help` in a channel to see all the commands.

## Requirements
* [FFmpeg](https://ffmpeg.org) for basic and advanced media manipulation, music commands, and generally for a lot of things.
* [Ollama](https://ollama.com) for G-AI related stuff. You aren't required to use models locally, as Ollama themselves have cloud models you can use.
* [Docker](https://www.docker.com) for the code execution server. Do keep in mind you **don't** need Docker Desktop, just Docker and Docker Compose is required.
* [LibreTranslate](https://docs.libretranslate.com/guides/installation/) for just a very specific TagScript function called `{translate}`. Completely optional.
* [PostgreSQL](https://www.postgresql.org) for pretty much a lot of major functionality.
  * Make sure to setup your own Postgres user and database, preferably called g-man and g-database respectively, though you can pick any name you want. **MAKE SURE TO NOT GIVE THE USER SUPERUSER PERMISSIONS. ALL IT NEEDS IS OWNERSHIP OF THE DATABASE ITSELF.**
  * After setting up the user and database, run the query inside the setup.sql file inside psql with: `\i setup.sql`
    * This sets up the database tables, required for the bot's major functionality.
* All the Python packages in requirements.txt.

You can install the Python packages, preferably in a virtual environment, by first running:
```
python -m venv .venv
source .venv/bin/activate # If you are in Bash.
source .venv/bin/activate.fish # If you are in Fish.
.venv\Scripts\activate.bat # If you are in Windows and using Command Prompt.
.venv\Scripts\activate.ps1 # If you are in PowerShell.
```
then:
```
pip install -r requirements.txt
```
## Installation
* Download/install all requirements.
* Create a copy of `bot_info_template.json` and rename it to `bot_info.json`. Fill it in with the appropriate information. (keep the quotes)
* Go to the g-coder directory and run `docker compose up -d --build` to set up the code execution server.
  * Code execution server's port will be 8000, so make sure it does not conflict with any existing stuff you host locally.
* Run `py gman.py` (or if you are on Linux/macOS, `python gman.py`)
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
### "We" refers to myself, because I am the only one working for this bot.
* We do not use your personal information whatsoever.
  * We log command usage to our local database. This is used for the `commandusage` command to help in moderation regarding potential bad actors. If you want your data removed from this, you'll have to contact me in discord at my support server. (my username is miniatureege2006)
  * Additionally, the command content will be included anytime you or anyone uses any commands. This is for moderation and monitoring purposes, along with debugging.
  * We do NOT share these data with anyone at all.
* I am not responsible/liable for any media/content that is created from other users using G-Man.
* **If you wish to opt-out of using G-Man and want your data removed completely, contact me in discord at my support server and I will handle it.**
