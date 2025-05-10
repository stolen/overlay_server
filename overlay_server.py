from flask import Flask, request, render_template
from werkzeug.utils import secure_filename
import hashlib
import os, time
import requests, json, re

from rocknix_dtbo import make_dtbo

app = Flask(__name__)
try:
    app.config.from_file('config.json', load=json.load)
except:
    pass
app.config['UPLOAD_DIR'] = 'uploads'
app.config['DTBO_DIR'] = 'dtbo'
app.config['STATIC_DIR'] = 'static'
app.config['FEEDBACK_DIR'] = 'feedback'
app.config['MAX_CONTENT_LENGTH'] = 512 * 1024  # 512K should be enough, dtbs are usually about 100K


def send_to_telegram(message):
    """Send a message to a Telegram chat."""
    if not 'TELEGRAM_APIKEY' in app.config:
        return None
    apikey = app.config['TELEGRAM_APIKEY']
    url = f"https://api.telegram.org/bot{apikey}/sendMessage"
    for chat in app.config['TELEGRAM_CHATS']:
        payload = {
            "chat_id": chat,
            "text": message,
            "parse_mode": "Markdown"
        }
        response = requests.post(url, json=payload)
    return response.status_code, response.text


@app.route('/', methods=['GET'])
def index():
    return open('index.html').read()

@app.route('/dtbo/<md5>')
def download_dtbo(md5):
    try:
        f = open(os.path.join(app.config['DTBO_DIR'], secure_filename(md5)), 'rb')
        dtbo = f.read()
        return (dtbo, 200, {'content-disposition': 'attachment; filename="mipi-panel.dtbo"'})
    except:
        return ('Not found', 404, {})

@app.route('/static/<file>')
def download_static(file):
    try:
        f = open(os.path.join(app.config['STATIC_DIR'], secure_filename(file)), 'rb')
        body = f.read()
        headers = {}
        if re.search(r'\.js$', file):
            headers = {'content-type': 'application/javascript'}
        elif re.search(r'\.css$', file):
            headers = {'content-type': 'text/css'}
        else:
            headers = {'content-type': 'application/octet-stream', 'content-disposition': f'attachment; filename="{file}"'}
        return (body, 200, headers)
    except:
        return ('Not found', 404, {})

@app.route('/convert_dtb', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return 'No file part'
    file = request.files['file']
    content = file.read()

    md5 = hashlib.md5(content).hexdigest()
    opts = request.args.get('opts', '')

    ovlname = secure_filename(md5 + opts)
    filename = secure_filename(md5 + '-' + file.filename)

    flags = opts.split('-')
    flags = [ f for f in flags if f != '']
    dtbo = make_dtbo(content, {'flags': flags, 'logger': app.logger})

    # Save strictly after getting dtbo to lower abuse
    # Garbage will just crash the extractor, and nothing will be saved on disk
    os.makedirs(app.config['UPLOAD_DIR'], exist_ok=True)
    os.makedirs(app.config['DTBO_DIR'], exist_ok=True)
    with open(os.path.join(app.config['UPLOAD_DIR'], filename), 'wb') as f:
        f.write(content)
    with open(os.path.join(app.config['DTBO_DIR'], ovlname), 'wb') as f:
        f.write(dtbo)

    if 'silent' not in request.values:
        send_to_telegram(f"new overlay: {ovlname} for {file.filename}")
    app.logger.info(f"silent = {request.values.get('silent')}")
    #if request.values.get('silent'):
    #    pass
    #else:

    return (dtbo, 200, {'content-disposition': 'attachment; filename="mipi-panel.dtbo"'})


@app.route('/feedback/<md5>', methods=['POST'])
def feedback(md5):
    dev = request.form.get('device')
    desc = request.form.get('description')
    if (not dev) or (not desc):
        return ("Bad form", 400, {})
    os.makedirs(app.config['FEEDBACK_DIR'], exist_ok=True)
    filename = secure_filename(md5) + '-' + str(time.time())
    with open(os.path.join(app.config['FEEDBACK_DIR'], filename), 'w') as f:
        f.write('device: ' + dev)
        f.write('\n\n')
        f.write(desc)
        f.write('\n')
    send_to_telegram(f"feedback {filename}\ndev: {dev}\n\n{desc}")

    return ("Accepted", 201, {})


if __name__ == '__main__':
    app.run(debug=True)
