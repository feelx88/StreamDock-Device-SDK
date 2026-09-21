import json


class Configuration:
    def __init__(self, config_path='config.json'):
        self.config_path = config_path
        self.homeassistant_url = None
        self.homeassistant_token = None
        self.mpd_ip = None
        self.mpd_port = None
        self.elite_dangerous_status_path = None
        self.audio = {}
        self.load()

    def load(self):
        with open(self.config_path, 'r') as file:
            config = json.load(file)
            self.homeassistant_url = config.get('homeassistant_url')
            self.homeassistant_token = config.get('homeassistant_token')
            self.mpd_ip = config.get('mpd_ip')
            self.mpd_port = config.get('mpd_port')
            self.elite_dangerous_status_path = config.get('elite_dangerous_status_path')
            self.audio = config.get('audio', {})

    def __getitem__(self, key):
        return getattr(self, key)
