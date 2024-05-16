import json
import requests
import sched
import time
import shutil

# Initialize necessary variables (Set their values in config.json).
token = ''
channel = 0
bot_id = 0
admins = []
files = []
used_ids = []
forward_list = []
update_list = []
delay = 60
timezone = -5
report = ''
need_report = False

# Initialize the scheduler.
scheduler = sched.scheduler(time.time, time.sleep)


def update():
    print()
    # reinitialize all the lists and variables as global
    global token
    global bot_id
    global channel
    global admins
    global files
    global used_ids
    global forward_list
    global update_list
    global delay
    global timezone
    global report
    global need_report
    report = ''

    # Load the config values from config.json.
    print('loading config...', end='')
    with open('config.json') as config:
        configdata = json.load(config)
        token = configdata['credentials']['telegramAccessToken']
        print('token loaded')

        channel = configdata['credentials']['telegramChannel']
        print('channel loaded')

        bot_id = configdata['credentials']['telegramBotID']
        print('botID loaded')

        admins = configdata['admins']
        print(len(admins), 'admins')

        delay = configdata['delay']
        print(delay, 'minute delay')

        timezone = configdata['timezone']
        print('UTC', timezone)
    print('success.')

    print('Loading data...', end='')
    with open('data.json') as data:
        data = json.load(data)

        files = data['files']
        print(len(files), 'files')

        used_ids = data['usedIDs']
        print(len(used_ids), 'used ids')

        forward_list = data['forwardList']
        print(len(forward_list), 'forwards')
    print('success.')

    print()

    print('getUpdates')
    request = 'https://api.telegram.org/bot' + token + '/getUpdates'
    response = requests.get(request)
    # print(response.url)
    response = response.json()
    if response['ok']:
        print('response:', 'ok')
        update_list = response['result']
    else:
        print('response not ok')
    # BREAK

    print(' updates:', len(update_list))

    while len(update_list) > 0:
        for i in range(len(update_list)):
            # print()
            print('update_id:', update_list[i]['update_id'], '|', end=' ')
            if 'message' in update_list[i]:
                # print('  chat id:', updatelist[i]['message']['chat']['id'])
                if update_list[i]['message']['chat']['id'] in admins:
                    if 'document' in update_list[i]['message']:
                        # Save the caption to the document json object
                        if 'caption' in update_list[i]['message']:
                            update_list[i]['message']['document']['caption'] = update_list[i]['message']['caption']

                        print(json.dumps(update_list[i]['message']['document'], indent=2, sort_keys=True))
                        if update_list[i]['message']['document'] in files:
                            print('files already contains this photo')
                        else:
                            files.append(update_list[i]['message']['document'])
                            print('file added', end=' ')
                            if 'from' in update_list[i]['message']:
                                if 'username' in update_list[i]['message']['from']:
                                    print('(from ', update_list[i]['message']['from']['username'], ')', sep='')
                                else:
                                    print('(from ', update_list[i]['message']['from']['first_name'], ' (',
                                          update_list[i]['message']['from']['id'], '))', sep='')
                            else:
                                print()
                    else:
                        # MESSAGE DOESN'T CONTAIN A FILE, PUT PARSE CODE HERE
                        print('message does not contain a file', end=' ')
                        # print(json.dumps(updatelist[i], indent=2, sort_keys=True))
                        if 'from' in update_list[i]['message']:
                            if 'username' in update_list[i]['message']['from']:
                                print('(from ', update_list[i]['message']['from']['username'], ')', sep='')
                            else:
                                print('(from ', update_list[i]['message']['from']['first_name'], ' (',
                                      update_list[i]['message']['from']['id'], '))', sep='')
                        else:
                            print()
                else:
                    print('update not from admin', end=' ')
                    if 'new_chat_member' in update_list[i]['message']:
                        if update_list[i]['message']['new_chat_member']['id'] == bot_id:
                            forward_list.append(update_list[i]['message']['chat']['id'])
                            if 'username' in update_list[i]['message']['from']:
                                print('\nadded ', update_list[i]['message']['chat']['title'], ' (',
                                      update_list[i]['message']['chat']['id'], ') to forwardList by ',
                                      str(update_list[i]['message']['from']['username']), ' (',
                                      update_list[i]['message']['from']['id'], ')', sep='')
                                report = report + '`added `' + str(
                                    update_list[i]['message']['chat']['title']) + '` to forwardList by `%40' + str(
                                    update_list[i]['message']['from']['username']) + '\n'  # %40 = @
                            else:
                                print('\nadded ', update_list[i]['message']['chat']['title'], ' (',
                                      update_list[i]['message']['chat']['id'], ') to forwardList by ',
                                      str(update_list[i]['message']['from']), sep='')
                                report = report + '`added `' + str(
                                    update_list[i]['message']['chat']['title']) + '` to forwardList by `' + str(
                                    update_list[i]['message']['from']['first_name']) + ' (' + str(
                                    update_list[i]['message']['from']['id']) + ')\n'
                            need_report = True
                    elif 'left_chat_member' in update_list[i]['message']:
                        if update_list[i]['message']['left_chat_member']['id'] == bot_id:
                            if update_list[i]['message']['chat']['id'] in forward_list:
                                forward_list.remove(update_list[i]['message']['chat']['id'])
                                print('\nremoved', update_list[i]['message']['chat']['title'], 'from forwardList')
                                report = report + '`removed `' + str(
                                    update_list[i]['message']['chat']['title']) + ' `from forwardList`\n'
                                need_report = True
                    else:
                        if 'from' in update_list[i]['message']:
                            if 'username' in update_list[i]['message']['from']:
                                print('(from ', update_list[i]['message']['from']['username'], ')', sep='')
                            else:
                                print('(from ', update_list[i]['message']['from']['first_name'], ' (',
                                      update_list[i]['message']['from']['id'], '))', sep='')
                        else:
                            print()
                        print('   ', update_list[i]['message'])
            else:
                print('update not does not contain message')
                print(update_list[i])
        if len(update_list) > 0:
            mostrecentupdate = update_list[len(update_list) - 1]['update_id']
            print('clearing updatelist through to update_id', mostrecentupdate + 1)
            request = 'https://api.telegram.org/bot' + token + '/getUpdates'
            response = requests.get(request + '?offset=' + str(mostrecentupdate + 1))
            response = response.json()
            if response['ok']:
                update_list = response['result']
                print(' updates:', len(update_list))
                if len(update_list) <= 0:
                    print('...success')
                else:
                    print('updatelist not empty, repeating...')
            else:
                print('failed')
                need_report = True
    else:
        print('updatelist empty')

    print()


def report_forwards():
    print()
    global token
    global forward_list
    global report
    global admins
    report = ''

    with open('data.json') as data:
        data = json.load(data)
        forward_list = data['forwardList']
        print(len(forward_list), 'forwards')
    print()

    request = 'https://api.telegram.org/bot' + token + '/getChat'

    for i in range(len(forward_list)):
        response = requests.get(request + '?chat_id=' + str(forward_list[i]))
        response = response.json()
        if response['ok']:
            print('forward[', str(i), ']: (', str(response['result']['id']), ') ', response['result']['title'], sep='')
            report = report + '`forward[' + str(i) + ']: `' + response['result']['title'] + '\n'
        else:
            print('forward[', str(i), ']: (', str(forward_list[i]), ') ', response['description'], sep='')

    print()


def update_dropbox():
    print()
    # reinitialize all the lists and variables as global
    global files
    global used_ids
    global forward_list
    global delay

    with open('data.json', 'w') as data:
        json.dump({
            'files': files,
            'usedIDs': used_ids,
            'forwardList': forward_list,
        }, data)

    print()


def post_photo():
    print()
    global token
    global channel
    global files
    global used_ids
    global forward_list
    global report
    global need_report
    remove_list = []
    is_image = True
    forward_message = True

    if len(files) > 0:
        file_to_send = files[0]
        filename = 'image'
        filecaption = ''
        link = None
        request = 'https://api.telegram.org/bot' + token + '/getFile?file_id=' + file_to_send['file_id']
        # print(request)
        response = requests.get(request)
        response = response.json()
        if response['ok']:
            if 'image' in file_to_send['mime_type']:
                filename = filename + '.' + file_to_send['mime_type'][6:]  # cuts off the first 6 characters ('image/')
                try:
                    filecaption = file_to_send['caption']
                except KeyError:
                    filecaption = ''

            else:
                is_image = False
                mime_type = file_to_send['mime_type'].split('/')
                filename = filename + '.' + mime_type[1]  # uses anything found after the slash
            print('downloading...', end='')
            request = 'https://api.telegram.org/file/bot' + token + '/' + response['result']['file_path']
            response = requests.get(request, stream=True)  # stream=True IS REQUIRED
            print('done.', end='')
            if response.status_code == 200:
                with open(filename, 'wb') as image:
                    shutil.copyfileobj(response.raw, image)
            print(' saved as ' + filename)
        else:
            print('response not ok')
            report = report + '`post failed.`\n`photo re-added to queue.`'
            return  # we don't have a sendable file, so just return

        snep = open(filename, 'rb')

        # send to telegram
        if is_image:
            print('sending photo to telegram, chat_id:' + str(channel) + '...', end='')
            request = 'https://api.telegram.org/bot' + token + '/sendPhoto'
            telegramfile = {'photo': snep}
            if filecaption is not None:
                sent_file = requests.get(
                    request + '?chat_id=' + str(channel) + '&caption=' + filecaption.replace('&', '%26'),
                    files=telegramfile)
            else:
                sent_file = requests.get(request + '?chat_id=' + str(channel), files=telegramfile)
            if sent_file.json()['ok']:
                sent_file = sent_file.json()
                if len(files) <= 10:
                    report = report + '`telegram...success.`'
                    need_report = True
                else:
                    report = report + '`telegram...success.`'
                used_ids.append(sent_file['result']['photo'][-1]['file_id'])
                files.pop(0)
                print('success.')
            else:
                print('sent_file not ok, skipping forwards')
                print(sent_file.json())
                report = report + '`post failed.`\n`photo re-added to queue.`'
                print('failed.')
                need_report = True
                forward_message = False
        else:
            print('sending file to telegram, chat_id:' + str(channel) + '...', end='')
            if link is not None:
                request = 'https://api.telegram.org/bot' + token + '/sendDocument?chat_id=' + str(
                    channel) + '&document=' + file_to_send['file_id'] + '&caption=' + link.replace('&', '%26')
            else:
                request = 'https://api.telegram.org/bot' + token + '/sendDocument?chat_id=' + str(
                    channel) + '&document=' + file_to_send['file_id']
            sent_file = requests.get(request)
            if sent_file.json()['ok']:
                sent_file = sent_file.json()
                if len(files) <= 10:
                    report = report + '`telegram...success.`'
                    need_report = True
                # else :
                # report = report + '`telegram...success.`'
                files.pop(0)
                print('success.')
            else:
                print('sent_file not ok, skipping forwards')
                print(sent_file.json())
                report = report + '`post failed.`\n`photo re-added to queue.`'
                print('failed.')
                need_report = True
                forward_message = False

        # FORWARDING PHOTO
        if forward_message:
            print('forwarding photo to', len(forward_list), 'chats...', end='')
            successful_forwards = 0
            for i in range(len(forward_list)):
                request = requests.get('https://api.telegram.org/bot' + token + '/forward_message?chat_id=' + str(
                    forward_list[i]) + '&from_chat_id=' + str(channel) + '&message_id=' + str(
                    sent_file['result']['message_id']))
                response = request.json()
                if response['ok']:
                    successful_forwards = successful_forwards + 1
                # print('forward[' + str(i) + '] ok')
                elif 'description' in response:
                    if 'Forbidden' in response['description']:
                        remove_list.append(forward_list[i])
                        report = report + '\n` removed `' + str(forward_list[i]) + '` from forward list`'
                        need_report = True
                    elif ('group chat was upgraded to a supergroup chat' in response['description'] and
                          'parameters' in response and 'migrate_to_chat_id' in response['parameters']):
                        forward_list[i] = response['parameters']['migrate_to_chat_id']
                        # try again
                        print('\ntrying with new ID...', end='')
                        secondtry = requests.get(
                            'https://api.telegram.org/bot' + token + '/forward_message?chat_id=' + str(
                                forward_list[i]) + '&from_chat_id=' + str(channel) + '&message_id=' + str(
                                sent_file['result']['message_id']))
                        if secondtry.json()['ok']:
                            successful_forwards = successful_forwards + 1
                            print('success.')
                        else:
                            need_report = True
                            print('failed')
                else:
                    getchat = requests.get(
                        'https://api.telegram.org/bot' + token + '/getChat?chat_id=' + str(forward_list[i]))
                    getchat = getchat.json()
                    if getchat['ok']:
                        print('\nforward[' + str(i) + '] failed (chat_id: ' + str(forward_list[i]) + ') ' +
                              getchat['result']['title'], end='')
                        report = report + '\n`forward[`' + str(i) + '`] failed (chat_id: `' + str(
                            forward_list[i]) + '`) ` ' + getchat['result']['title']
                        need_report = True
                    else:
                        if 'description' in getchat:
                            print('\nforward[' + str(i) + '] failed (chat_id: ' + str(forward_list[i]) + ') ' + getchat[
                                'description'], end='')
                            report = report + '\n`forward[`' + str(i) + '`] failed (chat_id: `' + str(
                                forward_list[i]) + '`) `' + getchat['description']
                            if 'Forbidden' in getchat['description']:
                                remove_list.append(forward_list[i])
                                report = report + '\n` removed `' + str(forward_list[i]) + '` from forward list`'
                                need_report = True
                        else:
                            print('\nforward[' + str(i) + '] failed (chat_id: ' + str(forward_list[i]) + ')', end='')
                            report = report + '\n`forward[`' + str(i) + '`] failed (chat_id: `' + str(
                                forward_list[i]) + '`)'
                            need_report = True
                    if 'description' in response:
                        report = report + ' reason: `' + response['description']
                    else:
                        report = report + '`'
                    print('\nraw response:', response, end='')
                    print('\nraw command:', request.url)
            report = report + '\n` forwarded to: `' + str(successful_forwards) + '` chats`'
            print('done. ')
    else:
        report = report + '`post failed.`\n`no photos in queue.`\nADD PHOTOS IMMEDIATELY'
        need_report = True
    if len(remove_list) > 0:
        for i in range(len(remove_list)):
            forward_list.remove(remove_list[i])


def schedule_nextupdate():
    print()
    # reinitialize all the lists and variables as global
    global files
    global delay
    global timezone
    global report
    global scheduler
    global need_report

    nextupdate = currenttime = (time.time() + ((60 * 60) * timezone))
    nextupdate = (nextupdate - (nextupdate % (delay * 60))) + (delay * 60)

    noowtime = ''
    if time.localtime(currenttime).tm_hour < 10:
        noowtime = noowtime + '0'
    noowtime = noowtime + str(time.localtime(currenttime).tm_hour) + ':'
    if time.localtime(currenttime).tm_min < 10:
        noowtime = noowtime + '0'
    noowtime = noowtime + str(time.localtime(currenttime).tm_min)

    nexttime = ''
    if time.localtime(nextupdate).tm_hour < 10:
        nexttime = nexttime + '0'
    nexttime = nexttime + str(time.localtime(nextupdate).tm_hour) + ':'
    if time.localtime(nextupdate).tm_min < 10:
        nexttime = nexttime + '0'
    nexttime = nexttime + str(time.localtime(nextupdate).tm_min)

    report = report + '\n`current delay: `' + str(delay) + '` minutes\ncurrent queue: `' + str(
        len(files)) + '`\n current time: `' + noowtime + '`\n  next update: `' + nexttime
    if len(files) < 10:
        report = report + '\nLOW ON PHOTOS'
        need_report = True
    # report = report + '\n`next photo in queue: `'

    print('current time:', noowtime)
    print(' next update:', nexttime)
    print()
    print('scheduling update for', delay, 'minutes from now')
    # scheduler.enter((delay * 60), 1, scheduled_post, ())
    scheduler.enterabs((nextupdate - (3600 * timezone)), 1, scheduled_post, ())


def schedule_firstupdate():
    print()
    # reinitialize all the lists and variables as global
    global files
    global delay
    global timezone
    global forward_list
    global report
    global scheduler

    nextupdate = currenttime = (time.time() + ((60 * 60) * timezone))
    nextupdate = (nextupdate - (nextupdate % (delay * 60))) + (delay * 60)

    noowtime = ''
    if time.localtime(currenttime).tm_hour < 10:
        noowtime = noowtime + '0'
    noowtime = noowtime + str(time.localtime(currenttime).tm_hour) + ':'
    if time.localtime(currenttime).tm_min < 10:
        noowtime = noowtime + '0'
    noowtime = noowtime + str(time.localtime(currenttime).tm_min)

    nexttime = ''
    if time.localtime(nextupdate).tm_hour < 10:
        nexttime = nexttime + '0'
    nexttime = nexttime + str(time.localtime(nextupdate).tm_hour) + ':'
    if time.localtime(nextupdate).tm_min < 10:
        nexttime = nexttime + '0'
    nexttime = nexttime + str(time.localtime(nextupdate).tm_min)

    report = report + '`  bot started`\n`current delay: `' + str(delay) + '` minutes`\n`current queue: `' + str(
        len(files)) + '\n`     forwards: `' + str(
        len(forward_list)) + '\n` current time: `' + noowtime + '\n`  next update: `' + nexttime
    # report = report + '\n`next photo in queue: `'

    print('current time:', noowtime)
    print('next update: ', nexttime)
    print('bot started. scheduling first post...')
    print('scheduling update for', nexttime)
    # post_photo()
    scheduler.enterabs((nextupdate - (3600 * timezone)), 1, scheduled_post, ())


# https://stackoverflow.com/a/1267145/8197207
def is_int(s):
    try:
        int(s)
        return True
    except ValueError:
        return False


def send_report():
    print()
    # reinitialize all the lists and variables as global
    global token
    global admins
    global files
    global report

    if len(files) > 0:
        request = 'https://api.telegram.org/bot' + token + '/sendMessage'
        for i in range(len(admins)):
            request = requests.get(request + '?chat_id=' + str(admins[i]) + '&text=' + report + '&parse_mode=Markdown')
            response = request.json()
            if response['ok']:
                print('report[' + str(i) + ']: ok')
            else:
                print('report[' + str(i) + ']: failed (' + str(admins[i]) + ')')
                if 'description' in response:
                    print('reason: ' + response['description'])
                print('raw response:', response)
                print('raw request:', request.url)
    else:
        request = 'https://api.telegram.org/bot' + token + '/sendMessage'
        for i in range(len(admins)):
            requests.get(request + '?chat_id=' + str(admins[i]) + '&text=' + report + '&parse_mode=Markdown')
            requests.get(request + '?chat_id=' + str(admins[i]) + '&text=NO PHOTOS IN QUEUE&parse_mode=Markdown')

    print('report sent')


def initial_startup():
    print('initial_startup()')
    # reinitialize all the lists and variables as global
    global scheduler

    report_forwards()
    update()
    update_dropbox()
    schedule_firstupdate()
    send_report()

    scheduler.run()


def scheduled_post():
    print()
    # reinitialize all the lists and variables as global
    global scheduler
    global need_report

    update()
    post_photo()
    update_dropbox()
    schedule_nextupdate()
    if need_report:
        send_report()
    need_report = False
    scheduler.run()


initial_startup()
