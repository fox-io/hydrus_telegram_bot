import json
import requests
import sched
import time
import shutil
import re
from urllib.parse import urlparse


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

    def print_username(self, message):
        # Prints the username of the user who sent the message.
        if 'from' in message:
            if 'username' in message['from']:
                print('(from ', message['from']['username'], ')', sep='')
            else:
                print('(from ', message['from']['first_name'], ' (', message['message']['from']['id'], '))', sep='')
        else:
            print('From unknown user')

    def save_data(self):
        with open('data.json', 'w') as data:
            json.dump({
                'files': self.file_list,
                'usedIDs': self.used_ids,
                'forwardList': self.forward_list,
            }, data)

    def api_url(self, method: str, payload: str, is_file: bool = False):
        url = 'https://api.telegram.org/'

        # Append to URL if this is a file request.
        if is_file:
            url += 'file/'

        url += 'bot' + self.access_token + '/'

        # Always append payload, include method if not a file request.
        if not is_file:
            url += method
        url += payload

        return url

    def get_bot_updates(self, flush=False):
        if flush:
            list_length = len(self.update_list)
            last_update_id = self.update_list[list_length - 1]['update_id']
            request = self.api_url('getUpdates', '?offset=' + str(last_update_id + 1), False)
        else:
            request = self.api_url('getUpdates', '', False)

        response = requests.get(request)
        response = response.json()
        if response['ok']:
            self.update_list = response['result']
        else:
            print('Failed to get updates.')

    def process_file_message(self, message):
        # Process the file message from the Telegram bot.

        # Get the file caption, if present.
        if 'caption' in message:
            message['document']['caption'] = message['caption']

        # Check if the file is already in our queue.
        if message['document'] in self.file_list:
            print('Skipping previously added file.')
        else:
            # Get the file caption, if present.
            if 'caption' in message:
                message['document']['caption'] = message['caption']

            # Add the file to the queue.
            self.file_list.append(message['document'])

    def download_file(self, file_id, mime_type):
        # Download the image from the Telegram bot.
        filename = 'image'

        # Verify the download
        request = self.api_url('getFile', '?file_id=' + file_id, False)
        response = requests.get(request)
        response = response.json()
        if response['ok']:
            # Generate the filename using the mime_type
            if 'image' in mime_type:
                is_image = True
                filename = filename + '.' + mime_type[6:]
            else:
                is_image = False
                mime_type = mime_type.split('/')
                filename = filename + '.' + mime_type[1]

            # Download the image data and save to disk.
            request = self.api_url('', response['result']['file_path'], True)
            response = requests.get(request, stream=True)  # stream=True IS REQUIRED
            if response.status_code == 200:
                with open(filename, 'wb') as image:
                    shutil.copyfileobj(response.raw, image)

                return True, filename, is_image
            else:
                self.send_message('Downloading image failed.', True)
                return False, '', False
        else:
            self.send_message('Downloading image failed.', True)
            return False, '', False

    def time_string(self, the_time):
        # Converts a time float to a string with padding.
        string_time = time.localtime(the_time).tm_hour < 10 and '0' or ''
        string_time = string_time + str(time.localtime(the_time).tm_hour) + ':'
        string_time = string_time + str(time.localtime(the_time).tm_min < 10 and '0' or '')
        string_time = string_time + str(time.localtime(the_time).tm_min)

        return string_time

    def is_int(self, number):
        try:
            int(number)
            return True
        except ValueError:
            return False

    def send_message(self, message, is_debug=False):
        # Sends a message to all admin users.
        if is_debug and not self.debug_mode:
            return

        if len(message) > 0:
            for i in range(len(self.admins)):
                admin = str(self.admins[i])
                if len(self.file_list) == 0:
                    message += ' NO PHOTOS IN QUEUE'
                requests.get(self.api_url('sendMessage', '?chat_id=' + admin + '&text=' + message + '&parse_mode=Markdown'))

    def load_config(self):
        with open('config.json') as config:
            # Load the config data from the file into a variable.
            config_data = json.load(config)

            # Save the config values to the db.
            self.access_token = config_data['credentials']['telegramAccessToken']
            self.channel = config_data['credentials']['telegramChannel']
            self.bot_id = config_data['credentials']['telegramBotID']
            self.admins = config_data['admins']
            self.delay = config_data['delay']
            self.timezone = config_data['timezone']

    def load_data(self):
        with open('data.json') as data:
            # Load the data from the file into a variable.
            data = json.load(data)

            # Save the data values to the db.
            self.file_list = data['files']
            self.used_ids = data['usedIDs']
            self.forward_list = data['forwardList']

    def update_data(self):
        self.load_data()

        # Get the latest updates from the Telegram bot.
        self.get_bot_updates()

        # If there are updates, process them.
        while len(self.update_list) > 0:

            for i in range(len(self.update_list)):
                # Dumps the list of updates to the console.
                # print('update_id:', db['data']['update_list'][i]['update_id'], '|', end=' ')

                if 'message' in self.update_list[i]:
                    if self.update_list[i]['message']['chat']['id'] in self.admins:
                        if 'document' in self.update_list[i]['message']:
                            self.process_file_message(self.update_list[i]['message'])
                        else:
                            self.send_message('Received a message from an admin which does not contain a document.')
                    else:
                        # Update is from a non-admin user. If the update is from the bot, add/remove the chat to the forward list.
                        if 'new_chat_member' in self.update_list[i]['message']:
                            if self.update_list[i]['message']['new_chat_member']['id'] == \
                                    self.bot_id:
                                self.forward_list.append(self.update_list[i]['message']['chat']['id'])
                                if 'username' in self.update_list[i]['message']['from']:
                                    print('\nadded ', self.update_list[i]['message']['chat']['title'], ' (',
                                          self.update_list[i]['message']['chat']['id'], ') to forwardList by ',
                                          str(self.update_list[i]['message']['from']['username']), ' (',
                                          self.update_list[i]['message']['from']['id'], ')', sep='')
                                else:
                                    print('\nadded ', self.update_list[i]['message']['chat']['title'], ' (',
                                          self.update_list[i]['message']['chat']['id'], ') to forwardList by ',
                                          str(self.update_list[i]['message']['from']), sep='')
                        elif 'left_chat_member' in self.update_list[i]['message']:
                            if self.update_list[i]['message']['left_chat_member']['id'] == \
                                    self.bot_id:
                                if self.update_list[i]['message']['chat']['id'] in self.forward_list:
                                    self.forward_list.remove(
                                        self.update_list[i]['message']['chat']['id'])
                                    print('\nremoved', self.update_list[i]['message']['chat']['title'],
                                          'from forwardList')
                        else:
                            print('Update is from a non-admin user.')
                            self.print_username(self.update_list[i]['message'])
                else:
                    print('update not does not contain message')
                    print(self.update_list[i])

            # If there are extraneous updates, flush the update list.
            if len(self.update_list) > 0:
                self.get_bot_updates(True)

    def post_image(self):
        remove_list = []
        forward_message = True

        if len(self.file_list) > 0:
            self.send_message('Attempting to post image.', True)
            link = None

            # Get the next file in the queue.
            file_to_send = self.file_list[0]

            # Set the caption, if present.
            try:
                file_caption = file_to_send['caption']
            except KeyError:
                file_caption = ''

            # Download the image from the Telegram bot.
            download_ok, filename, is_image = self.download_file(file_to_send['file_id'], file_to_send['mime_type'])

            # Abort on download error.
            if not download_ok:
                self.send_message('Failed to download image.', True)
                return

            self.send_message('Image downloaded successfully.', True)

            # Open the image from disk.
            image_file = open(filename, 'rb')

            # send to telegram
            if is_image:
                self.send_message('Sending photo to Telegram channel.', True)
                telegram_file = {'photo': image_file}
                channel = str(self.channel)

                if file_caption is not None:

                    # Build an InlineKeyboard list of buttons for URLs in the caption.
                    keyboard = {'inline_keyboard': []}

                    # Extract URLs.
                    url_column = 0
                    url_row = -1

                    for line in file_caption.split('\n'):
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
                                subreddit_match = re.search(self.subreddit_regex, link.geturl())
                                website = 'Reddit (' + subreddit_match.group(1) + ')' if subreddit_match else 'Reddit'
                            else:
                                website = link.netloc

                            url = link.geturl()

                            keyboard['inline_keyboard'][url_row].append({
                                'text': website,
                                'url': url
                            })

                            url_column = url_column == 0 and 1 or 0

                    print(keyboard)
                    # caption = file_caption.replace('&', '%26')
                    request = self.api_url('sendPhoto', '?chat_id=' + channel + '&reply_markup=' + json.dumps(keyboard),
                                      False)
                else:
                    request = self.api_url('sendPhoto', '?chat_id=' + channel, False)

                sent_file = requests.get(request, files=telegram_file)

                if sent_file.json()['ok']:
                    self.send_message('Photo sent successfully.', True)
                    sent_file = sent_file.json()

                    self.used_ids.append(sent_file['result']['photo'][-1]['file_id'])
                    self.file_list.pop(0)
                else:
                    self.send_message('Failed to send photo to Telegram channel.', True)

                    forward_message = False
                    self.file_list.pop(0)
            else:
                # Media is NOT an image.
                self.send_message('Attempting to send non-image file to Telegram channel.', True)

                channel = str(self.channel)
                file_id = file_to_send['file_id']

                if link:
                    # noinspection PyUnresolvedReferences
                    caption = link.replace('&', '%26')
                    request = self.api_url('sendDocument',
                                      '?chat_id=' + channel + '&document=' + file_id + '&caption=' + caption)
                else:
                    request = self.api_url('sendDocument', '?chat_id=' + channel + '&document=' + file_id)

                sent_file = requests.get(request)
                if sent_file.json()['ok']:
                    self.send_message('Non-image file sent successfully.', True)
                    sent_file = sent_file.json()
                    self.used_ids.append(sent_file['result']['document']['file_id'])
                    self.file_list.pop(0)
                else:
                    self.send_message('Failed to send non-image file to Telegram channel.', True)

                    forward_message = False

                    # Remove the file from the queue.
                    # TODO: Determine what is wrong with failed post files. File size? File type?
                    self.file_list.pop(0)

            # FORWARDING PHOTO
            if forward_message:
                self.send_message('Attempting to forward photo to chats.', True)

                successful_forwards = 0
                for i in range(len(self.forward_list)):
                    chat_id = str(self.forward_list[i])
                    from_chat_id = str(self.channel)
                    message_id = str(sent_file['result']['message_id'])
                    request = requests.get(self.api_url('forward_message',
                                                   '?chat_id=' + chat_id + '&from_chat_id=' + from_chat_id + '&message_id=' + message_id))
                    response = request.json()
                    if response['ok']:
                        self.send_message('Forwarded photo successfully.', True)
                        successful_forwards = successful_forwards + 1
                    elif 'description' in response:
                        if 'Forbidden' in response['description']:
                            remove_list.append(self.forward_list[i])
                        elif ('group chat was upgraded to a supergroup chat' in response['description'] and
                              'parameters' in response and 'migrate_to_chat_id' in response['parameters']):
                            self.forward_list[i] = response['parameters']['migrate_to_chat_id']
                            # try again
                            print('\ntrying with new ID...', end='')
                            chat_id = str(self.forward_list[i])
                            from_chat_id = str(self.channel)
                            message_id = str(sent_file['result']['message_id'])
                            second_try = requests.get(self.api_url('forward_message', '?chat_id=' + chat_id + '&from_chat_id=' + from_chat_id + '&message_id=' + message_id))
                            if second_try.json()['ok']:
                                successful_forwards = successful_forwards + 1
                    else:
                        self.send_message('Failed to forward photo to chats.', True)
                        chat_id = str(self.forward_list[i])
                        get_chat = requests.get(self.api_url('getChat', '?chat_id=' + chat_id, False))
                        get_chat = get_chat.json()
                        if get_chat['ok']:
                            print(
                                '\nforward[' + str(i) + '] failed (chat_id: ' + str(
                                    self.forward_list[i]) + ') ' +
                                get_chat['result']['title'], end='')
                        else:
                            if 'description' in get_chat:
                                print('\nforward[' + str(i) + '] failed (chat_id: ' + str(
                                    self.forward_list[i]) + ') ' + get_chat[
                                          'description'], end='')
                                if 'Forbidden' in get_chat['description']:
                                    remove_list.append(self.forward_list[i])

        if len(remove_list) > 0:
            self.send_message('Removing chats from forward list.', True)
            for i in range(len(remove_list)):
                self.forward_list.remove(remove_list[i])

        # Save changes to the data file to disk.
        self.save_data()

    def post_scheduled_image(self):
        # Update our data files and get new messages from the Telegram bot.
        self.update_data()

        # Post the next image in the queue to the Telegram channel
        self.post_image()

        # Schedule our next image post.
        self.schedule_next_image()

        # Run the scheduler.
        self.scheduler.run()

    def schedule_next_image(self):
        # Get the current time, adjusted for timezone.
        current_time = (time.time() + ((60 * 60) * self.timezone))

        # Calculate the next update time.
        next_update = (current_time - (current_time % (self.delay * 60))) + (self.delay * 60)

        # Notify admins of the scheduling results.
        # TODO: Limit the frequency of these messages?
        self.send_message(
            'Scheduling post every ' + str(self.delay) + ' minutes. ' +
            'The time is now ' + self.time_string(current_time) + '. ' +
            'The next post will be at ' + self.time_string(next_update) + '. ' +
            'There are ' + str(len(self.file_list)) + ' queued posts.'
        )

        # Use the scheduler to trigger the next post.
        self.scheduler.enterabs((next_update - (3600 * self.timezone)), 1, self.post_scheduled_image, ())

    def __init__(self):
        self.load_config()
        self.update_data()


if __name__ == '__main__':
    app = YiffBot()
    app.schedule_next_image()
    app.scheduler.run()
