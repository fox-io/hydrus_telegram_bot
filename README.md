# Telegram Photo Channel Controller Bot
## About
This bot was originally designed to control the telegram channel [Flickr Sneps](https://t.me/flickrsneps) and the twitter account [@flickrsneps](https://twitter.com/flickrsneps). You can find the original bot code and repository at https://github.com/kheina/hourly-photo-telegram-bot .

2024-05-16: Modifications have been made to the original bot to work as intended for my own personal use. @fox-io

It works by storing the file information of files sent to it by an admin, and keeping them in a queue.
By default, the delay is set to 60 minutes. Meaning, at the top of every hour, a file is downloaded
from the queue and sent as a photo (if it is actually an image file) to the telegram channel specified
and forwarded to all the groups the bot has been added to. Afterwards, it will also send the file to
twitter if it is either a photo or video.

## Usage
Start by cloning the repo into your desired folder.

1. Copy config.json.example to config.json and enter your information into this file.
2. Copy data.json.example to data.json. You do not need to make changes to this file.

The bot uses telegram's getUpdates method, so you can safely send it images and add it to groups while
it isn't running and it will add them all to the proper files once it is launched.

You may also run the http call https://api.telegram.org/bot[botToken]/getUpdates in your browser to
determine what your bot id and channel id are.

I'd also recommend looking through https://core.telegram.org/bots/api this resource for more information
on telegram bots and how they work.

Once you start the bot, admins should get a message on telegram from the bot with some information
including the current delay and number of photos in the queue.