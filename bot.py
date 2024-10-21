import pathlib
import json
import random
import requests
import sched
import time
import os
import re
from urllib.parse import urlparse
import hydrus_api
import hydrus_api.utils
import typing as t
from wand.image import Image


class HydrusTelegramBot:
    file_list = []
    used_ids = []
    forward_list = []
    update_list = []
    admins = []
    access_token = ""
    channel = 0
    bot_id = 0
    delay = 60
    timezone = -5
    scheduler = sched.scheduler(time.time, time.sleep)
    debug_mode = False
    subreddit_regex = "/(r/[a-z0-9][_a-z0-9]{2,20})/"
    hydrus_api_key = ""
    queue_data = []
    queue_loaded = False
    queue_tag = ""
    posted_tag = ""
    hydrus_service_key = {
        "my_tags": "6c6f63616c2074616773",
        "downloader_tags": "646f776e6c6f616465722074616773"
    }
    permissions = (
        hydrus_api.Permission.IMPORT_URLS,
        hydrus_api.Permission.IMPORT_FILES,
        hydrus_api.Permission.ADD_TAGS,
        hydrus_api.Permission.SEARCH_FILES,
        hydrus_api.Permission.MANAGE_PAGES,
    )

    # ----------------------------

    def get_next_update_time(self):
        # Calculate the next update time.
        current_time = (time.time() + ((60 * 60) * self.timezone))
        return (current_time - (current_time % (self.delay * 60))) + (self.delay * 60)

    def schedule_update(self):
        # Schedules an event for the next update time.
        next_time = self.get_next_update_time() - (3600 * self.timezone)
        print(f"Next update scheduled for {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(next_time))}.")
        self.scheduler.enterabs(next_time, 1, self.on_scheduler, ())

    def build_telegram_api_url(self, method: str, payload: str, is_file: bool = False):
        # Constructs a Telegram API url for bot communication.
        url = 'https://api.telegram.org/'
        if is_file:
            url += 'file/'
        url += 'bot' + self.access_token + '/'
        if not is_file:
            url += method
        url += payload
        return url

    def send_message(self, message):
        # Sends a message to all admin users.
        if len(message) > 0:
            for i in range(len(self.admins)):
                admin = str(self.admins[i])
                requests.get(
                    self.build_telegram_api_url('sendMessage', '?chat_id=' + admin + '&text=' + message + '&parse_mode=Markdown'))

    # ----------------------------

    def load_config(self):
        # Load the config file.
        with open('config.json') as config:
            config_data = json.load(config)
            self.access_token = config_data['telegram_access_token']
            self.channel = config_data['telegram_channel']
            self.bot_id = config_data['telegram_bot_id']
            self.hydrus_api_key = config_data['hydrus_api_key']
            self.queue_tag = config_data['queue_tag']
            self.posted_tag = config_data['posted_tag']
            self.admins = config_data['admins']
            self.delay = config_data['delay']
            self.timezone = config_data['timezone']

    def verify_queue_file(self):
        # Create a queue file if not present.
        try:
            with open('queue.json', 'r'):
                pass
        except FileNotFoundError:
            with open('queue.json', 'w+') as queue_file:
                queue_file.write(json.dumps({
                    "queue": []
                }))
            print("Created new queue file.")

    def load_queue(self):
        # Load queue from file.
        if not self.queue_loaded:
            self.verify_queue_file()
            with open('queue.json') as queue_file:
                self.queue_data = json.load(queue_file)
            self.queue_loaded = True

    def save_queue(self):
        # Save queue to file.
        with open('queue.json', 'w+') as queue_file:
            json.dump(self.queue_data, queue_file)
        self.queue_loaded = False

    def update_queue(self):
        # Update queue from Hydrus, then save queue to file.
        self.load_queue()
        self.get_new_hydrus_files()
        self.save_queue()

    def add_tag(self, file_id: list, tag: str):
        # Add Hydrus tag to indicate image has been posted (enqueued).
        self.hydrus_client.add_tags(file_ids=file_id, service_keys_to_actions_to_tags={
            self.hydrus_service_key["my_tags"]: {
                str(hydrus_api.TagAction.ADD): [tag],
            }
        })

    def remove_tag(self, file_id: list, tag: str):
        # Remove Hydrus tag indicating image should be posted.
        self.hydrus_client.add_tags(file_ids=file_id, service_keys_to_actions_to_tags={
            self.hydrus_service_key["downloader_tags"]: {
                str(hydrus_api.TagAction.DELETE): [tag]
            }
        })
        self.hydrus_client.add_tags(file_ids=file_id, service_keys_to_actions_to_tags={
            self.hydrus_service_key["my_tags"]: {
                str(hydrus_api.TagAction.DELETE): [tag]
            }
        })

    def check_hydrus_permissions(self):
        # Check that Hydrus is running and the current permissions are valid.
        try:
            if not hydrus_api.utils.verify_permissions(self.hydrus_client, self.permissions):
                print("    The client does not have the required permissions.")
                return False
        except requests.exceptions.ConnectionError:
            print("    The Hydrus client is not running.")
            return False
        return True

    # noinspection PyMethodMayBeStatic
    def concatenate_sauce(self, known_urls: list):
        # Return source URLs.
        sauce = ''
        for url in known_urls:
            # Skip direct links.
            if url.startswith("https://www."):
                sauce = sauce + url + ','
        return sauce
    
    def image_is_queued(self, filename: str):
        # Check that image being enqueued is not already queued.
        self.load_queue()
        if len(self.queue_data['queue']) > 0:
            for entry in self.queue_data['queue']:
                if entry['path'] == filename:
                    return True
        return False

    def save_image_to_queue(self, file_id):
        # Insert an image into the queue.

        # Load metadata from Hydrus.
        metadata = self.hydrus_client.get_file_metadata(file_ids=file_id)

        # Save image from Hydrus to queue folder. Creates filename based on hash.
        filename = str(f"{metadata['metadata'][0]['hash']}{metadata['metadata'][0]['ext']}")
        path = t.cast(pathlib.Path, pathlib.Path.cwd()) / "queue" / filename
        path.write_bytes(self.hydrus_client.get_file(file_id=metadata['metadata'][0]['file_id']).content)

        # Extract creator tag if present.
        creator = None
        tags = metadata['metadata'][0]['tags']['646f776e6c6f616465722074616773']['display_tags']['0']
        for tag in tags:
            if "creator:" in tag:
                creator = tag.split(":")[1]

        # Create sauce links.
        sauce = self.concatenate_sauce(metadata['metadata'][0]['known_urls'])

        # Add image to queue if not present.
        if not self.image_is_queued(filename):
            if creator is not None and creator != "":
                self.queue_data['queue'].append({'path': filename, 'sauce': sauce, 'creator': creator})
            else:
                self.queue_data['queue'].append({'path': filename,'sauce': sauce})
            self.save_queue()
            return 1
        else:
            return 0

    def get_new_hydrus_files(self):
        # Check Hydrus for new images to enqueue.
        print("Checking Hydrus for new files.")
        if not self.check_hydrus_permissions():
            return
        num_images = 0
        all_tagged_file_ids = self.hydrus_client.search_files([self.queue_tag])["file_ids"]
        for file_ids in hydrus_api.utils.yield_chunks(all_tagged_file_ids, 100):
            for file_id in file_ids:
                num_images += self.save_image_to_queue([file_id])
                self.remove_tag([file_id], self.queue_tag)
                self.add_tag([file_id], self.posted_tag)
        if num_images > 0:
            print(f"    Added {num_images} image(s) to the queue.")
        else:
            print("    No new images found.")

    def build_caption_buttons(self, caption: str):
        # Assembles buttons to display under the Telegram post.
        if caption is not None:
            keyboard = {'inline_keyboard': []}
            url_column = 0
            url_row = -1
            for line in caption.split(','):
                if 'http' in line:
                    if url_column == 0:
                        keyboard['inline_keyboard'].append([])
                        url_row += 1
                    link = urlparse(line)
                    # Pretty print known site names.
                    if 'furaffinity' in link.netloc:
                        website = 'Furaffinity'
                    elif 'e621' in link.netloc:
                        website = 'e621'
                    elif 'reddit' in link.netloc:
                        subreddit_match = re.search(self.subreddit_regex, link.geturl(), re.IGNORECASE)
                        website = 'Reddit (' + subreddit_match.group(1) + ')' if subreddit_match else 'Reddit'
                    else:
                        website = link.netloc
                    url = link.geturl()
                    keyboard['inline_keyboard'][url_row].append({
                        'text': website,
                        'url': url
                    })
                    url_column = url_column == 0 and 1 or 0
            return keyboard
        else:
            return None

    def process_queue(self):
        # Post next image to Telegram and remove it from the queue.
        print("Processing next image in queue.")
        self.load_queue()
        if len(self.queue_data['queue']) > 0:
            random_index = random.randint(0, len(self.queue_data['queue']) - 1)

            current_queued_image = self.queue_data['queue'][random_index]
            path = "queue/" + current_queued_image['path']

            # Telegram has limits on image file size and dimensions. We resize large things here.
            with Image(filename=path) as img:
                if img.width > 10000 or img.height > 10000:
                    img.transform(resize='1024x768')
                    img.save(filename=path)

                while os.path.getsize(path) > 10000000:
                    img.resize(int(img.width * 0.9), int(img.height * 0.9))
                    img.save(filename=path)

            image_file = open(path, 'rb')
            telegram_file = {'photo': image_file}
            channel = str(self.channel)

            creator = None
            if "creator" in current_queued_image:
                creator = str(current_queued_image['creator'])
                if creator == "None" or creator == "":
                    creator = None

            sauce = None
            if "sauce" in current_queued_image:
                sauce = self.build_caption_buttons(current_queued_image['sauce'])

            if sauce is not None:
                if creator is not None:
                    request = self.build_telegram_api_url('sendPhoto', '?chat_id=' + channel + '&reply_markup=' + json.dumps(sauce) + '&caption=Uploader: ' + creator, False)
                else:
                    request = self.build_telegram_api_url('sendPhoto', '?chat_id=' + channel + '&reply_markup=' + json.dumps(sauce), False)
            else:
                if creator is not None:
                    request  = self.build_telegram_api_url('sendPhoto', '?chat_id=' + channel + '&caption=Uploader: '+ creator, False)
                else:
                    request = self.build_telegram_api_url('sendPhoto', '?chat_id=' + channel, False)

            sent_file = requests.get(request, files=telegram_file)
            if sent_file.json()['ok']:
                print("    Image sent successfully.")
            else:
                print("    Image failed to send.")
                self.send_message(f"Image failed to send. {path}")

            # Delete the image from disk and queue.
            image_file.close()
            os.remove(path)
            self.queue_data['queue'].pop(random_index)
            self.save_queue()
            print("Queued images remaining: " + str(len(self.queue_data['queue'])))

        else:
            print("Queue is empty.")
            self.send_message("Queue is empty.")

    def on_scheduler(self):
        # Event handler.
        self.update_queue()
        self.process_queue()
        self.schedule_update()

    def __init__(self):
        # Startup sequence.
        self.load_config()
        self.hydrus_client = hydrus_api.Client(self.hydrus_api_key)
        self.on_scheduler()


if __name__ == '__main__':
    # Main program.
    app = HydrusTelegramBot()
    app.scheduler.run()
