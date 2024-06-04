import json
import requests
import sched
import time
import shutil
import re
from urllib.parse import urlparse

# Initialize the global variable db.
db = {
    'data': {
        'files': [],
        'used_ids': [],
        'forward_list': [],
        'update_list': [],
    },
    'config': {
        'admins': [],
        'credentials': {
            'access_token': "",
            'channel': 0,
            'bot_id': 0
        },
        'delay': 60,
        'timezone': -5
    },
    'report': "",
    'need_report': False
}

debug_mode = False

# Initialize the scheduler.
scheduler = sched.scheduler(time.time, time.sleep)


def print_username(message):
    # Prints the username of the user who sent the message.
    if 'from' in message:
        if 'username' in message['from']:
            print('(from ', message['from']['username'], ')', sep='')
        else:
            print('(from ', message['from']['first_name'], ' (', message['message']['from']['id'], '))', sep='')
    else:
        print('From unknown user')


def load_config():
    global db

    # Load the config values from config.json.
    with open('config.json') as config:
        print('Loading config')

        # Load the config data from the file into a variable.
        config_data = json.load(config)

        # Save the config values to the db.
        db['config']['credentials']['access_token'] = config_data['credentials']['telegramAccessToken']
        db['config']['credentials']['channel'] = config_data['credentials']['telegramChannel']
        db['config']['credentials']['bot_id'] = config_data['credentials']['telegramBotID']
        db['config']['admins'] = config_data['admins']
        db['config']['delay'] = config_data['delay']
        db['config']['timezone'] = config_data['timezone']


def load_data():
    global db

    # Load the data values from data.json.
    with open('data.json') as data:
        print('Loading data.json')

        # Load the data from the file into a variable.
        data = json.load(data)

        # Save the data values to the db.
        db['data']['files'] = data['files']
        db['data']['used_ids'] = data['usedIDs']
        db['data']['forwardList'] = data['forwardList']


def save_data():
    # Saves the data values to the data.json file.
    global db

    with open('data.json', 'w') as data:
        json.dump({
            'files': db['data']['files'],
            'usedIDs': db['data']['used_ids'],
            'forwardList': db['data']['forward_list'],
        }, data)

    print('data.json updated')


def api_url(method: str, payload: str, is_file: bool = False):
    url = 'https://api.telegram.org/'

    # Append to URL if this is a file request.
    if is_file:
        url += 'file/'

    url += 'bot' + db['config']['credentials']['access_token'] + '/'

    # Always append payload, include method if not a file request.
    if not is_file:
        url += method
    url += payload

    return url


def get_bot_updates(flush=False):
    global db

    if flush:
        list_length = len(db['data']['update_list'])
        last_update_id = db['data']['update_list'][list_length - 1]['update_id']
        request = api_url('getUpdates', '?offset=' + str(last_update_id + 1), False)
    else:
        request = api_url('getUpdates', '', False)

    response = requests.get(request)
    response = response.json()
    if response['ok']:
        db['data']['update_list'] = response['result']
    else:
        print('Failed to get updates.')


def process_file_message(message):
    # Process the file message from the Telegram bot.

    # Get the file caption, if present.
    if 'caption' in message:
        message['document']['caption'] = message['caption']

    # Check if the file is already in our queue.
    if message['document'] in db['data']['files']:
        print('Skipping previously added file.')
    else:
        # Get the file caption, if present.
        if 'caption' in message:
            message['document']['caption'] = message['caption']

        # Add the file to the queue.
        db['data']['files'].append(message['document'])


def update_data():
    # Loads all config values and data from disk and checks the Telegram bot for new messages.

    # Clear the report.
    db['report'] = ""

    # Load the JSON data.
    load_data()

    # Get the latest updates from the Telegram bot.
    get_bot_updates()

    # If there are updates, process them.
    while len(db['data']['update_list']) > 0:

        for i in range(len(db['data']['update_list'])):
            # Dumps the list of updates to the console.
            # print('update_id:', db['data']['update_list'][i]['update_id'], '|', end=' ')

            if 'message' in db['data']['update_list'][i]:
                if db['data']['update_list'][i]['message']['chat']['id'] in db['config']['admins']:
                    if 'document' in db['data']['update_list'][i]['message']:
                        process_file_message(db['data']['update_list'][i]['message'])
                    else:
                        send_message('Received a message from an admin which does not contain a document.')
                else:
                    # Update is from a non-admin user. If the update is from the bot, add/remove the chat to the forward list.
                    if 'new_chat_member' in db['data']['update_list'][i]['message']:
                        if db['data']['update_list'][i]['message']['new_chat_member']['id'] == \
                                db['config']['credentials']['bot_id']:
                            db['data']['forward_list'].append(db['data']['update_list'][i]['message']['chat']['id'])
                            if 'username' in db['data']['update_list'][i]['message']['from']:
                                print('\nadded ', db['data']['update_list'][i]['message']['chat']['title'], ' (',
                                      db['data']['update_list'][i]['message']['chat']['id'], ') to forwardList by ',
                                      str(db['data']['update_list'][i]['message']['from']['username']), ' (',
                                      db['data']['update_list'][i]['message']['from']['id'], ')', sep='')
                                db['report'] = db['report'] + '`added `' + str(
                                    db['data']['update_list'][i]['message']['chat'][
                                        'title']) + '` to forwardList by `%40' + str(
                                    db['data']['update_list'][i]['message']['from']['username']) + '\n'  # %40 = @
                            else:
                                print('\nadded ', db['data']['update_list'][i]['message']['chat']['title'], ' (',
                                      db['data']['update_list'][i]['message']['chat']['id'], ') to forwardList by ',
                                      str(db['data']['update_list'][i]['message']['from']), sep='')
                                db['report'] = db['report'] + '`added `' + str(
                                    db['data']['update_list'][i]['message']['chat'][
                                        'title']) + '` to forwardList by `' + str(
                                    db['data']['update_list'][i]['message']['from']['first_name']) + ' (' + str(
                                    db['data']['update_list'][i]['message']['from']['id']) + ')\n'
                            db['need_report'] = True
                    elif 'left_chat_member' in db['data']['update_list'][i]['message']:
                        if db['data']['update_list'][i]['message']['left_chat_member']['id'] == \
                                db['config']['credentials']['bot_id']:
                            if db['data']['update_list'][i]['message']['chat']['id'] in db['data']['forward_list']:
                                db['data']['forward_list'].remove(db['data']['update_list'][i]['message']['chat']['id'])
                                print('\nremoved', db['data']['update_list'][i]['message']['chat']['title'],
                                      'from forwardList')
                                db['report'] = db['report'] + '`removed `' + str(
                                    db['data']['update_list'][i]['message']['chat']['title']) + ' `from forwardList`\n'
                                db['need_report'] = True
                    else:
                        print('Update is from a non-admin user.')
                        print_username(db['data']['update_list'][i]['message'])
            else:
                print('update not does not contain message')
                print(db['data']['update_list'][i])

        # If there are extraneous updates, flush the update list.
        if len(db['data']['update_list']) > 0:
            get_bot_updates(True)

    else:
        print('update_list empty')


def download_file(file_id, mime_type):
    # Download the image from the Telegram bot.
    filename = 'image'

    # Verify the download
    request = api_url('getFile', '?file_id=' + file_id, False)
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
        request = api_url('', response['result']['file_path'], True)
        response = requests.get(request, stream=True)  # stream=True IS REQUIRED
        if response.status_code == 200:
            with open(filename, 'wb') as image:
                shutil.copyfileobj(response.raw, image)

            return True, filename, is_image
        else:
            send_message('Downloading image failed.', True)
            return False, '', False
    else:
        send_message('Downloading image failed.', True)
        return False, '', False


def post_image():
    remove_list = []
    forward_message = True

    if len(db['data']['files']) > 0:
        send_message('Attempting to post image.', True)
        link = None

        # Get the next file in the queue.
        file_to_send = db['data']['files'][0]

        # Set the caption, if present.
        try:
            file_caption = file_to_send['caption']
        except KeyError:
            file_caption = ''

        # Download the image from the Telegram bot.
        download_ok, filename, is_image = download_file(file_to_send['file_id'], file_to_send['mime_type'])

        # Abort on download error.
        if not download_ok:
            send_message('Failed to download image.', True)
            return

        send_message('Image downloaded successfully.', True)

        # Open the image from disk.
        image_file = open(filename, 'rb')

        # send to telegram
        if is_image:
            send_message('Sending photo to Telegram channel.', True)
            telegram_file = {'photo': image_file}
            channel = str(db['config']['credentials']['channel'])

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
                            subreddit_regex = "/(r/[a-z0-9][_a-z0-9]{2,20})/"
                            subreddit_match = re.search(subreddit_regex, link.geturl())
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
                request = api_url('sendPhoto', '?chat_id=' + channel + '&reply_markup=' + json.dumps(keyboard), False)
            else:
                request = api_url('sendPhoto', '?chat_id=' + channel, False)

            sent_file = requests.get(request, files=telegram_file)

            if sent_file.json()['ok']:
                send_message('Photo sent successfully.', True)
                sent_file = sent_file.json()

                db['report'] = db['report'] + '`telegram...success.`'
                if len(db['data']['files']) <= 10:
                    db['need_report'] = True

                db['data']['used_ids'].append(sent_file['result']['photo'][-1]['file_id'])
                db['data']['files'].pop(0)
            else:
                send_message('Failed to send photo to Telegram channel.', True)

                db['report'] = db['report'] + '`post failed.`\n`photo re-added to queue.`'
                db['need_report'] = True

                forward_message = False
                db['data']['files'].pop(0)
        else:
            # Media is NOT an image.
            send_message('Attempting to send non-image file to Telegram channel.', True)

            channel = str(db['config']['credentials']['channel'])
            file_id = file_to_send['file_id']

            if link:
                # noinspection PyUnresolvedReferences
                caption = link.replace('&', '%26')
                request = api_url('sendDocument', '?chat_id=' + channel + '&document=' + file_id + '&caption=' + caption)
            else:
                request = api_url('sendDocument', '?chat_id=' + channel + '&document=' + file_id)

            sent_file = requests.get(request)
            if sent_file.json()['ok']:
                send_message('Non-image file sent successfully.', True)
                sent_file = sent_file.json()
                db['report'] = db['report'] + '`telegram...success.`'
                if len(db['data']['files']) <= 10:
                    db['need_report'] = True

                db['data']['used_ids'].append(sent_file['result']['document']['file_id'])
                db['data']['files'].pop(0)
                print('success.')
            else:
                send_message('Failed to send non-image file to Telegram channel.', True)

                db['report'] = db['report'] + '`post failed.`\n`photo re-added to queue.`'
                db['need_report'] = True
                forward_message = False

                # Remove the file from the queue.
                # TODO: Determine what is wrong with failed post files. File size? File type?
                db['data']['files'].pop(0)

        # FORWARDING PHOTO
        if forward_message:
            send_message('Attempting to forward photo to chats.', True)

            successful_forwards = 0
            for i in range(len(db['data']['forward_list'])):
                chat_id = str(db['data']['forward_list'][i])
                from_chat_id = str(db['config']['credentials']['channel'])
                message_id = str(sent_file['result']['message_id'])
                request = requests.get(api_url('forward_message', '?chat_id=' + chat_id + '&from_chat_id=' + from_chat_id + '&message_id=' + message_id))
                response = request.json()
                if response['ok']:
                    send_message('Forwarded photo successfully.', True)
                    successful_forwards = successful_forwards + 1
                elif 'description' in response:
                    if 'Forbidden' in response['description']:
                        remove_list.append(db['data']['forward_list'][i])
                        db['report'] = db['report'] + '\n` removed `' + str(
                            db['data']['forward_list'][i]) + '` from forward list`'
                        db['need_report'] = True
                    elif ('group chat was upgraded to a supergroup chat' in response['description'] and
                          'parameters' in response and 'migrate_to_chat_id' in response['parameters']):
                        db['data']['forward_list'][i] = response['parameters']['migrate_to_chat_id']
                        # try again
                        print('\ntrying with new ID...', end='')
                        chat_id = str(db['data']['forward_list'][i])
                        from_chat_id = str(db['config']['credentials']['channel'])
                        message_id = str(sent_file['result']['message_id'])
                        second_try = requests.get(api_url('forward_message', '?chat_id=' + chat_id + '&from_chat_id=' + from_chat_id + '&message_id=' + message_id))
                        if second_try.json()['ok']:
                            successful_forwards = successful_forwards + 1
                            print('success.')
                        else:
                            db['need_report'] = True
                            print('failed')
                else:
                    send_message('Failed to forward photo to chats.', True)
                    chat_id = str(db['data']['forward_list'][i])
                    get_chat = requests.get(api_url('getChat', '?chat_id=' + chat_id, False))
                    get_chat = get_chat.json()
                    if get_chat['ok']:
                        print(
                            '\nforward[' + str(i) + '] failed (chat_id: ' + str(db['data']['forward_list'][i]) + ') ' +
                            get_chat['result']['title'], end='')
                        db['report'] = db['report'] + '\n`forward[`' + str(i) + '`] failed (chat_id: `' + str(
                            db['data']['forward_list'][i]) + '`) ` ' + get_chat['result']['title']
                        db['need_report'] = True
                    else:
                        if 'description' in get_chat:
                            print('\nforward[' + str(i) + '] failed (chat_id: ' + str(
                                db['data']['forward_list'][i]) + ') ' + get_chat[
                                      'description'], end='')
                            db['report'] = db['report'] + '\n`forward[`' + str(i) + '`] failed (chat_id: `' + str(
                                db['data']['forward_list'][i]) + '`) `' + get_chat['description']
                            if 'Forbidden' in get_chat['description']:
                                remove_list.append(db['data']['forward_list'][i])
                                db['report'] = db['report'] + '\n` removed `' + str(
                                    db['data']['forward_list'][i]) + '` from forward list`'
                                db['need_report'] = True
                        else:
                            print('\nforward[' + str(i) + '] failed (chat_id: ' + str(
                                db['data']['forward_list'][i]) + ')', end='')
                            db['report'] = db['report'] + '\n`forward[`' + str(i) + '`] failed (chat_id: `' + str(
                                db['data']['forward_list'][i]) + '`)'
                            db['need_report'] = True
                    if 'description' in response:
                        db['report'] = db['report'] + ' reason: `' + response['description']
                    else:
                        db['report'] = db['report'] + '`'
                    print('\nraw response:', response, end='')
                    print('\nraw command:', request.url)
            db['report'] = db['report'] + '\n` forwarded to: `' + str(successful_forwards) + '` chats`'
    else:
        send_message('No photos in queue.')
        db['report'] = db['report'] + '`post failed.`\n`no photos in queue.`\nADD PHOTOS IMMEDIATELY'
        db['need_report'] = True

    if len(remove_list) > 0:
        send_message('Removing chats from forward list.', True)
        for i in range(len(remove_list)):
            db['data']['forward_list'].remove(remove_list[i])

    # Save changes to the data file to disk.
    save_data()


def time_string(the_time):
    # Converts a time float to a string with padding.
    string_time = time.localtime(the_time).tm_hour < 10 and '0' or ''
    string_time = string_time + str(time.localtime(the_time).tm_hour) + ':'
    string_time = string_time + str(time.localtime(the_time).tm_min < 10 and '0' or '')
    string_time = string_time + str(time.localtime(the_time).tm_min)

    return string_time


def schedule_next_image():
    # Get the current time, adjusted for timezone.
    current_time = (time.time() + ((60 * 60) * db['config']['timezone']))

    # Calculate the next update time.
    next_update = (current_time - (current_time % (db['config']['delay'] * 60))) + (db['config']['delay'] * 60)

    # Notify admins of the scheduling results.
    # TODO: Limit the frequency of these messages?
    send_message(
        'Scheduling post every ' + str(db['config']['delay']) + ' minutes. ' +
        'The time is now ' + time_string(current_time) + '. ' +
        'The next post will be at ' + time_string(next_update) + '. ' +
        'There are ' + str(len(db['data']['files'])) + ' queued posts.'
    )

    # Use the scheduler to trigger the next post.
    scheduler.enterabs((next_update - (3600 * db['config']['timezone'])), 1, post_scheduled_image, ())


def is_int(s):
    try:
        int(s)
        return True
    except ValueError:
        return False


def send_message(message, is_debug=False):
    # Sends a message to all admin users.
    if is_debug and not debug_mode:
        return

    if len(message) > 0:
        for i in range(len(db['config']['admins'])):
            admin = str(db['config']['admins'][i])
            if len(db['data']['files']) == 0:
                message += ' NO PHOTOS IN QUEUE'
            requests.get(api_url('sendMessage', '?chat_id=' + admin + '&text=' + message + '&parse_mode=Markdown'))


def post_scheduled_image():
    # Update our data files and get new messages from the Telegram bot.
    update_data()

    # Post the next image in the queue to the Telegram channel
    post_image()

    # Schedule our next image post.
    schedule_next_image()

    # Run the scheduler.
    scheduler.run()


def main():
    # Get the configuration values.
    load_config()

    # Update our data files and get new messages from the Telegram bot.
    update_data()

    # Schedule our next image post.
    schedule_next_image()

    # Run the scheduler.
    scheduler.run()


if __name__ == '__main__':
    main()
