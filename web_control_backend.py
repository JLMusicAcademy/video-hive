#!/usr/bin/env python3
"""
Web Control Backend for QLab Media Player
Provides HTTP API that sends OSC commands to the media player
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
from pythonosc import udp_client
import os

app = Flask(__name__)
CORS(app)  # Allow requests from the web interface

# OSC client (will be configured per request or use default)
DEFAULT_PI_IP = "192.168.1.100"
DEFAULT_PI_PORT = 53000

@app.route('/api/send', methods=['POST'])
def send_osc():
    """Send OSC command to media player"""
    try:
        data = request.json
        
        # Get connection settings
        pi_ip = data.get('ip', DEFAULT_PI_IP)
        pi_port = int(data.get('port', DEFAULT_PI_PORT))
        command = data.get('command')
        args = data.get('args', [])
        
        if not command:
            return jsonify({'error': 'No command provided'}), 400
        
        # Create OSC client
        client = udp_client.SimpleUDPClient(pi_ip, pi_port)
        
        # Send command
        if args:
            client.send_message(command, args)
        else:
            client.send_message(command, [])
        
        return jsonify({
            'success': True,
            'command': command,
            'args': args,
            'sent_to': f'{pi_ip}:{pi_port}'
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/play/image', methods=['POST'])
def play_image():
    """Play image"""
    data = request.json
    pi_ip = data.get('ip', DEFAULT_PI_IP)
    pi_port = int(data.get('port', DEFAULT_PI_PORT))
    filename = data.get('filename')
    duration = float(data.get('duration', 0))
    
    client = udp_client.SimpleUDPClient(pi_ip, pi_port)
    client.send_message('/image', [duration, filename])
    
    return jsonify({'success': True, 'type': 'image', 'filename': filename})

@app.route('/api/play/video', methods=['POST'])
def play_video():
    """Play video"""
    data = request.json
    pi_ip = data.get('ip', DEFAULT_PI_IP)
    pi_port = int(data.get('port', DEFAULT_PI_PORT))
    filename = data.get('filename')
    duration = float(data.get('duration', 0))
    loop = int(data.get('loop', 0))
    
    client = udp_client.SimpleUDPClient(pi_ip, pi_port)
    client.send_message('/video', [duration, loop, filename])
    
    return jsonify({'success': True, 'type': 'video', 'filename': filename})

@app.route('/api/control/<action>', methods=['POST'])
def control(action):
    """Control commands (stop, clear)"""
    data = request.json or {}
    pi_ip = data.get('ip', DEFAULT_PI_IP)
    pi_port = int(data.get('port', DEFAULT_PI_PORT))
    
    command_map = {
        'stop': '/stop',
        'clear': '/clear'
    }
    
    if action not in command_map:
        return jsonify({'error': 'Invalid action'}), 400
    
    client = udp_client.SimpleUDPClient(pi_ip, pi_port)
    client.send_message(command_map[action], [])
    
    return jsonify({'success': True, 'action': action})

@app.route('/api/test', methods=['GET'])
def test():
    """Test endpoint"""
    return jsonify({'status': 'ok', 'message': 'Backend is running'})

@app.route('/')
def index():
    """Serve the web interface"""
    try:
        with open('media_control.html', 'r') as f:
            return f.read()
    except:
        return '''
        <h1>Media Control Backend</h1>
        <p>Backend is running! Place media_control.html in the same directory.</p>
        <p>API Endpoints:</p>
        <ul>
            <li>POST /api/send - Send raw OSC command</li>
            <li>POST /api/play/image - Play image</li>
            <li>POST /api/play/video - Play video</li>
            <li>POST /api/control/stop - Stop playback</li>
            <li>POST /api/control/clear - Clear screen</li>
        </ul>
        '''

if __name__ == '__main__':
    print("=" * 60)
    print("Media Player Web Control - Backend Server")
    print("=" * 60)
    print()
    print("Starting server on http://localhost:5000")
    print()
    print("Open your browser to: http://localhost:5000")
    print("Or use the API endpoints to send commands")
    print()
    print("Press Ctrl+C to stop")
    print("=" * 60)
    print()
    
    app.run(host='0.0.0.0', port=5000, debug=True)
