# Hydrus Telegram Bot

## About

Posts images to a Telegram channel from Hydrus Network client based on a target tag. This is a personal project that started as a forked repository. Not much left of the original. It has come a long way! 

I am personally running this bot from a Windows 11 system (For better Hydrus support/performance). Changing the platform may require modifying things.

Currently supports image formats such as jpg and png. webp is partially supported. Video support is currently limited to webm (you need ffmpeg binaries installed) and mp4. Some other media formats may be supported as well. YMMV.

## Usage

1. Clone the repository
```sh
git clone https://github.com/fox-io/hydrus_telegram_bot.git
```
2. Copy config/config.json.example to config/config.json and enter your information into this file. In it, you will need:
	- Telegram Admin ID
	- Telegram Bot API Access Token
	- Telegram Channel ID
	- Hydrus API Key
	- Hydrus tag for images to post
	- Hydrus tag for images that have been posted
	- Delay (in minutes) between Telegram posts
	- Timezone offset
3. Enable the Client API in Hydrus.
4. Tag images you want to post to Telegram in Hydrus with the queue_tag value in config/config.json.
5. Image metadata from Hydrus will be displayed:
	- Title
	- Creator
	- Character(s)
	- Source URL(s)
6. After being posted via the bot, the images will be tagged with the posted_tag value from config/config.json in Hydrus (the queue_tag will also be removed).