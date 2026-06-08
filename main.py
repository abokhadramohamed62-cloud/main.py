import os
from flask import Flask, request, jsonify
import requests

app = Flask(__name__)

CLOUDFLARE_SECRET = os.getenv("CF_SECRET", "0x4AAAAAADg_QwNGvi2wp0eo")

@app.route('/verify', methods=['POST'])
def verify():
    data = request.json
    token = data.get('token')
    if not token:
        return jsonify({'success': False})
    
    response = requests.post(
        'https://challenges.cloudflare.com/turnstile/v0/siteverify',
        data={'secret': CLOUDFLARE_SECRET, 'response': token}
    )
    result = response.json()
    return jsonify({'success': result.get('success', False)})

@app.route('/')
def home():
    return 'OK'

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5000)))
