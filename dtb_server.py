from flask import Flask, request, render_template
from werkzeug.utils import secure_filename
import hashlib
import os

from rocknix_dtbo import make_dtbo

app = Flask(__name__)
app.config['UPLOAD_DIR'] = 'uploads'
app.config['DTBO_DIR'] = 'dtbo'
app.config['MAX_CONTENT_LENGTH'] = 512 * 1024  # 512K should be enough, dtbs are usually about 100K

@app.route('/', methods=['GET'])
def index():
    return open('index.html').read()

@app.route('/dtbo/<md5>')
def download_dtbo(md5):
    try:
        f = open(os.path.join(app.config['DTBO_DIR'], md5), 'rb')
        dtbo = f.read()
        return (dtbo, 200, {'content-disposition': 'attachment; filename="mipi-panel.dtbo"'})
    except:
        return ('Not found', 404, {})


@app.route('/dtb_upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return 'No file part'
    file = request.files['file']
    content = file.read()
    md5 = hashlib.md5(content).hexdigest()
    filename = md5 + '-' + secure_filename(file.filename)
    with open(os.path.join(app.config['UPLOAD_DIR'], filename), 'wb') as f:
        f.write(content)

    dtbo = make_dtbo(content, {})
    with open(os.path.join(app.config['DTBO_DIR'], md5), 'wb') as f:
        f.write(dtbo)

    return (dtbo, 200, {'content-disposition': 'attachment; filename="mipi-panel.dtbo"'})

if __name__ == '__main__':
    os.makedirs(app.config['UPLOAD_DIR'], exist_ok=True)
    os.makedirs(app.config['DTBO_DIR'], exist_ok=True)
    app.run(debug=True)
