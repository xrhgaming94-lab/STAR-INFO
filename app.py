from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
import binascii
import requests
from flask import Flask, jsonify, request
from data_pb2 import AccountPersonalShowInfo
from google.protobuf.json_format import MessageToDict
import uid_generator_pb2
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from collections import defaultdict

app = Flask(__name__)

# === TOKEN MANAGEMENT SYSTEM (ONLY JSON FILES) ===

class TokenManager:
    def __init__(self):
        self.tokens = {}
        self.current_token_index = defaultdict(int)
        self.token_locks = defaultdict(threading.Lock)
        self.load_tokens_from_files()
    
    def load_tokens_from_files(self):
        """Load tokens from JSON files only"""
        token_files = {
            'IND': 'token_ind.json',
            'BR': 'token_br.json',
            'ME': 'token_me.json',
            'BD': 'token_bd.json'
        }
        
        for region_group, filename in token_files.items():
            if os.path.exists(filename):
                try:
                    with open(filename, 'r', encoding='utf-8') as f:
                        token_list = json.load(f)
                        if isinstance(token_list, list) and token_list:
                            self.tokens[region_group] = token_list
                            print(f"[TOKEN] Loaded {len(token_list)} tokens for {region_group}")
                        else:
                            print(f"[TOKEN] Warning: {filename} is empty or invalid")
                            self.tokens[region_group] = []
                except Exception as e:
                    print(f"[TOKEN] Error loading {filename}: {e}")
                    self.tokens[region_group] = []
            else:
                print(f"[TOKEN] Error: {filename} not found")
                self.tokens[region_group] = []
    
    def get_region_group(self, region: str) -> str:
        """Get region group for a specific region"""
        region_upper = region.upper()
        
        # IND regions
        if region_upper in ["IND"]:
            return 'IND'
        # BR regions (BR, US, SAC, NA)
        elif region_upper in ["BR", "US", "SAC", "NA"]:
            return 'BR'
        # ME region
        elif region_upper in ["ME"]:
            return 'ME'
        # BD regions (all others)
        else:
            return 'BD'
    
    def get_token(self, region: str) -> str:
        """Get token for a specific region using round-robin"""
        region_group = self.get_region_group(region)
        
        with self.token_locks[region_group]:
            if region_group not in self.tokens or not self.tokens[region_group]:
                print(f"[TOKEN] No tokens available for {region_group}")
                return None
            
            token_list = self.tokens[region_group]
            # Round-robin selection
            index = self.current_token_index[region_group] % len(token_list)
            self.current_token_index[region_group] += 1
            
            token_data = token_list[index]
            token = token_data.get('token', '')
            
            if token:
                print(f"[TOKEN] Using token {index+1}/{len(token_list)} for {region_group}")
                return token
            else:
                print(f"[TOKEN] Invalid token at index {index} for {region_group}")
                return None
    
    def refresh_tokens(self):
        """Reload tokens from files"""
        self.tokens.clear()
        self.current_token_index.clear()
        self.load_tokens_from_files()
        return {"message": "Tokens refreshed successfully"}
    
    def get_status(self):
        """Get token status for all groups"""
        status = {}
        for group in ['IND', 'BR', 'ME', 'BD']:
            if group in self.tokens:
                status[group] = {
                    'count': len(self.tokens[group]),
                    'current_index': self.current_token_index[group] % len(self.tokens[group]) if self.tokens[group] else 0,
                    'available': len(self.tokens[group]) > 0,
                    'file': f'token_{group.lower()}.json'
                }
            else:
                status[group] = {'count': 0, 'current_index': 0, 'available': False, 'file': f'token_{group.lower()}.json'}
        return status

# Initialize token manager
token_manager = TokenManager()

# ---------------- API ENDPOINTS ----------------
def get_api_endpoint(region):
    """Get API endpoint for specific region"""
    endpoints = {
        "IND": "https://client.ind.freefiremobile.com/GetPlayerPersonalShow",
        "BR": "https://client.us.freefiremobile.com/GetPlayerPersonalShow",
        "US": "https://client.us.freefiremobile.com/GetPlayerPersonalShow",
        "SAC": "https://client.us.freefiremobile.com/GetPlayerPersonalShow",
        "NA": "https://client.us.freefiremobile.com/GetPlayerPersonalShow",
        "BD": "https://clientbp.ggpolarbear.com/GetPlayerPersonalShow",
        "ID": "https://clientbp.ggpolarbear.com/GetPlayerPersonalShow",
        "PK": "https://clientbp.ggpolarbear.com/GetPlayerPersonalShow",
        "VN": "https://clientbp.ggpolarbear.com/GetPlayerPersonalShow",
        "ME": "https://clientbp.ggpolarbear.com/GetPlayerPersonalShow",
        "TH": "https://clientbp.ggpolarbear.com/GetPlayerPersonalShow",
        "TW": "https://clientbp.ggpolarbear.com/GetPlayerPersonalShow",
        "SG": "https://clientbp.ggpolarbear.com/GetPlayerPersonalShow",
        "RU": "https://clientbp.ggpolarbear.com/GetPlayerPersonalShow",
        "CIS": "https://clientbp.ggpolarbear.com/GetPlayerPersonalShow",
        "EUROPE": "https://clientbp.ggpolarbear.com/GetPlayerPersonalShow",
        "default": "https://clientbp.ggpolarbear.com/GetPlayerPersonalShow"
    }
    return endpoints.get(region, endpoints["default"])

# ---------------- AES ENCRYPTION ----------------
default_key = "Yg&tc%DEuh6%Zc^8"
default_iv = "6oyZDr22E3ychjM%"

def encrypt_aes(hex_data, key, iv):
    key = key.encode()[:16]
    iv = iv.encode()[:16]
    cipher = AES.new(key, AES.MODE_CBC, iv)
    padded_data = pad(bytes.fromhex(hex_data), AES.block_size)
    encrypted_data = cipher.encrypt(padded_data)
    return binascii.hexlify(encrypted_data).decode()

# ---------------- API CALL ----------------
def get_player_info(region, encrypted_hex):
    """Get player info from specific region using token from JSON file"""
    token = token_manager.get_token(region)
    if not token:
        raise Exception(f"No token available for region {region}")
    
    endpoint = get_api_endpoint(region)
    headers = {
        'User-Agent': 'Dalvik/2.1.0 (Linux; U; Android 9; ASUS_Z01QD Build/PI)',
        'Connection': 'Keep-Alive',
        'Expect': '100-continue',
        'Authorization': f'Bearer {token}',
        'X-Unity-Version': '2018.4.11f1',
        'X-GA': 'v1 1',
        'ReleaseVersion': 'OB54',
        'Content-Type': 'application/x-www-form-urlencoded',
    }
    
    try:
        data = bytes.fromhex(encrypted_hex)
        response = requests.post(endpoint, headers=headers, data=data, timeout=10)
        response.raise_for_status()
        return response.content.hex()
    except requests.exceptions.RequestException as e:
        print(f"[API] Request to {endpoint} for region {region} failed: {e}")
        raise

# ---------------- FLASK ROUTES ----------------
@app.route('/accinfo', methods=['GET'])
def get_player_info_endpoint():
    try:
        uid = request.args.get('uid')
        region = request.args.get('region', '').upper()
        custom_key = request.args.get('key', default_key)
        custom_iv = request.args.get('iv', default_iv)
        
        if not uid:
            return jsonify({"error": "UID parameter is required"}), 400
        
        # Generate protobuf
        message = uid_generator_pb2.uid_generator()
        message.saturn_ = int(uid)
        message.garena = 1
        protobuf_data = message.SerializeToString()
        hex_data = binascii.hexlify(protobuf_data).decode()
        
        # Encrypt
        encrypted_hex = encrypt_aes(hex_data, custom_key, custom_iv)
        
        # If region is specified, try only that region
        if region:
            try:
                api_response = get_player_info(region, encrypted_hex)
                if api_response:
                    message = AccountPersonalShowInfo()
                    message.ParseFromString(bytes.fromhex(api_response))
                    result = MessageToDict(message)
                    return jsonify(result)
            except Exception as e:
                return jsonify({"error": f"Failed for region {region}: {str(e)}"}), 500
        
        # Try all regions in parallel - FAST (SPEED IMPROVED)
        all_regions = ["IND", "BR", "US", "SAC", "NA", "BD", "PK", "VN", "ME", "TH", "TW", "ID", "SG", "RU", "CIS", "EUROPE"]
        results = []
        
        # Increased workers for more speed
        with ThreadPoolExecutor(max_workers=20) as executor:
            future_to_region = {
                executor.submit(try_region, region_name, encrypted_hex): region_name 
                for region_name in all_regions
            }
            
            for future in as_completed(future_to_region):
                region_name = future_to_region[future]
                try:
                    result = future.result(timeout=10)
                    if result:
                        # Return first successful response
                        return jsonify(result)
                except Exception as e:
                    print(f"[ERROR] Region {region_name} failed: {e}")
                    results.append({"region": region_name, "error": str(e)})
        
        # If no region succeeded
        return jsonify({
            "error": "All regions failed",
            "details": results
        }), 404
        
    except ValueError:
        return jsonify({"error": "Invalid UID format"}), 400
    except Exception as e:
        print(f"[ERROR] Processing request: {e}")
        return jsonify({"error": f"Failure to process the data: {str(e)}"}), 500

def try_region(region, encrypted_hex):
    """Try to get player info from a specific region"""
    try:
        # Get token from JSON file
        token = token_manager.get_token(region)
        if not token:
            return None
        
        endpoint = get_api_endpoint(region)
        headers = {
            'User-Agent': 'Dalvik/2.1.0 (Linux; U; Android 9; ASUS_Z01QD Build/PI)',
            'Connection': 'Keep-Alive',
            'Expect': '100-continue',
            'Authorization': f'Bearer {token}',
            'X-Unity-Version': '2018.4.11f1',
            'X-GA': 'v1 1',
            'ReleaseVersion': 'OB54',
            'Content-Type': 'application/x-www-form-urlencoded',
        }
        
        data = bytes.fromhex(encrypted_hex)
        response = requests.post(endpoint, headers=headers, data=data, timeout=8)
        response.raise_for_status()
        
        api_response = response.content.hex()
        if api_response:
            message = AccountPersonalShowInfo()
            message.ParseFromString(bytes.fromhex(api_response))
            result = MessageToDict(message)
            print(f"[SUCCESS] Found player in region: {region}")
            return result
        
    except Exception as e:
        print(f"[DEBUG] Region {region} failed: {e}")
        return None
    
    return None

@app.route('/refresh_tokens', methods=['GET', 'POST'])
def refresh_tokens():
    """Refresh tokens from JSON files"""
    result = token_manager.refresh_tokens()
    return jsonify(result), 200

@app.route('/token_status', methods=['GET'])
def token_status():
    """Check token status"""
    status = token_manager.get_status()
    return jsonify({
        'token_status': status,
        'total_tokens': sum(info['count'] for info in status.values()),
        'available_groups': [group for group, info in status.items() if info['available']]
    }), 200

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    status = token_manager.get_status()
    return jsonify({
        'status': 'active',
        'token_groups': status,
        'total_tokens': sum(info['count'] for info in status.values())
    }), 200

@app.route('/favicon.ico')
def favicon():
    return '', 404

# ---------------- MAIN ----------------
if __name__ == "__main__":
    print("\n" + "="*50)
    print("   FREE FIRE ACCOUNT INFO API")
    print("="*50)
    print("\n[TOKEN STATUS]")
    status = token_manager.get_status()
    for group, info in status.items():
        print(f"  {group}: {info['count']} tokens available")
    print(f"\nTotal Tokens: {sum(info['count'] for info in status.values())}")
    print("="*50 + "\n")
    
    app.run(host="0.0.0.0", port=5000, threaded=True)