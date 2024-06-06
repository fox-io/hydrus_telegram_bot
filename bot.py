import pathlib
import json
import requests
import sched
import time
import os
import re
from urllib.parse import urlparse
import hydrus_api
import hydrus_api.utils
import typing as t


class YiffBot:
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
        current_time = (time.time() + ((60 * 60) * self.timezone))
        return (current_time - (current_time % (self.delay * 60))) + (self.delay * 60)

    def schedule_update(self):
        self.scheduler.enterabs((self.get_next_update_time() - (3600 * self.timezone)), 1, self.on_scheduler, ())

    def build_telegram_api_url(self, method: str, payload: str, is_file: bool = False):
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
                requests.get(self.build_telegram_api_url('sendMessage',
                                                         '?chat_id=' + admin + '&text=' + message + '&parse_mode=Markdown'))

    # ----------------------------

    def load_config(self):
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

    def load_queue(self):
        try:
            with open('queue.json', 'x') as queue_file:
                queue_file.write(json.dumps({
                    "queue": []
                }))
        except FileExistsError:
            pass

        with open('queue.json') as queue_file:
            self.queue_data = json.load(queue_file)

    def save_queue(self):
        with open('queue.json', 'w') as queue_file:
            json.dump(self.queue_data, queue_file)

    def update_queue(self):
        self.load_queue()
        self.get_new_hydrus_files()
        self.save_queue()

    def add_tag(self, file_id: list, tag: str):
        self.hydrus_client.add_tags(file_ids=file_id, service_keys_to_actions_to_tags={
            self.hydrus_service_key["my_tags"]: {
                str(hydrus_api.TagAction.ADD): [tag],
            }
        })

    def remove_tag(self, file_id: list, tag: str):
        self.hydrus_client.add_tags(file_ids=file_id, service_keys_to_actions_to_tags={
            self.hydrus_service_key["downloader_tags"]: {
                str(hydrus_api.TagAction.DELETE): [tag]
            }
        })

    def check_hydrus_permissions(self):
        try:
            if not hydrus_api.utils.verify_permissions(self.hydrus_client, self.permissions):
                print("The client does not have the required permissions.")
                return False
        except requests.exceptions.ConnectionError:
            print("The Hydrus client is not running.")
            return False
        return True

    # noinspection PyMethodMayBeStatic
    def concatenate_sauce(self, known_urls: list):
        sauce = ''
        for url in known_urls:
            # Skip direct links.
            if url.startswith("https://www."):
                sauce = sauce + url + ','
        return sauce

    def save_image_to_queue(self, file_id):
        metadata = self.hydrus_client.get_file_metadata(file_ids=file_id)
        filename = f"{metadata['metadata'][0]['hash']}{metadata['metadata'][0]['ext']}"
        path = t.cast(pathlib.Path,
                      pathlib.Path.cwd()) / "queue" / f"{metadata['metadata'][0]['hash']}{metadata['metadata'][0]['ext']}"
        path.write_bytes(self.hydrus_client.get_file(file_id=metadata['metadata'][0]['file_id']).content)
        caption = self.concatenate_sauce(metadata['metadata'][0]['known_urls'])
        add_to_queue = True
        self.load_queue()
        if len(self.queue_data['queue']) > 0:
            for entry in self.queue_data['queue']:
                if entry['path'] == str(filename):
                    add_to_queue = False
        if add_to_queue:
            self.queue_data['queue'].append({'path': str(filename), 'caption': caption})
            self.save_queue()

    def get_new_hydrus_files(self):
        if not self.check_hydrus_permissions():
            return
        all_tagged_file_ids = self.hydrus_client.search_files([self.queue_tag])["file_ids"]
        for file_ids in hydrus_api.utils.yield_chunks(all_tagged_file_ids, 100):
            for file_id in file_ids:
                self.save_image_to_queue([file_id])
                self.remove_tag([file_id], self.queue_tag)
                self.add_tag([file_id], self.posted_tag)

    def build_caption_buttons(self, caption: str):
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
        self.load_queue()
        if len(self.queue_data['queue']) > 0:
            current_queued_image = self.queue_data['queue'][0]
            path = "queue/" + current_queued_image['path']
            self.queue_data['queue'].pop(0)
            self.save_queue()

            # TODO: Images must be less than 10MB, 10,000x10,000px, and <20 h/w ratio

            image_file = open(path, 'rb')
            telegram_file = {'photo': image_file}
            channel = str(self.channel)
            caption = self.build_caption_buttons(current_queued_image['caption'])
            if caption is not None:
                request = self.build_telegram_api_url('sendPhoto', '?chat_id=' + channel + '&reply_markup=' + json.dumps(caption), False)
            else:
                request = self.build_telegram_api_url('sendPhoto', '?chat_id=' + channel, False)
            sent_file = requests.get(request, files=telegram_file)
            if sent_file.json()['ok']:
                pass
            else:
                print("Failed to send photo to Telegram channel.")

            # Delete image_file from disk.
            image_file.close()
            os.remove(path)
        else:
            self.send_message("Queue is empty.")

    def on_scheduler(self):
        self.update_queue()
        self.process_queue()
        self.schedule_update()

    def __init__(self):
        self.load_config()
        self.load_queue()
        self.hydrus_client = hydrus_api.Client(self.hydrus_api_key)
        self.schedule_update()


if __name__ == '__main__':
    app = YiffBot()
    app.scheduler.run()
