from base_handler import BaseHandler
import homeassistant_api

HA = 'ha'


class HomeAssistantHandler(BaseHandler):

    def __init__(self, config, hass_lock):
        super().__init__({
            HA: hass_lock,
        })

        self._homeassistant_url = config['homeassistant_url']
        self._homeassistant_token = config['homeassistant_token']
        self._active_scene = None

        self.connect()
        self.update()

    def update(self):
        self.refresh_active_scene()

    def connect(self):
        try:
            self._client = homeassistant_api.Client(
                self._homeassistant_url,
                self._homeassistant_token,
                cache_session=False
            )
        except Exception:
            pass

    def client(self):
        return self._client

    def refresh_active_scene(self):
        with self._acquire_timeout(HA):
            try:
                self._active_scene = self._client.get_state(
                    entity_id='input_text.aktuelle_szene').state
            except Exception:
                self._active_scene = None
                self.connect()

    def scene(self, scene):
        entity_id = 'scene.{}'.format(scene)
        active = 'images/{}.active.png'.format(scene)
        inactive = 'images/{}.png'.format(scene)

        def trigger(entity_id):
            with self._acquire_timeout(HA):
                try:
                    self._client.trigger_service(
                        'scene', 'turn_on', entity_id=entity_id)
                except Exception:
                    pass

        def img():
            if self._active_scene is None:
                return 'images/error.png'
            return active if self._active_scene == entity_id else inactive

        return (
            lambda: trigger(entity_id),
            lambda: img()
        )

    def trigger_service(self, image, *args, **kwargs):
        return (
            lambda: self.guard(self._client.trigger_service, *args, **kwargs),
            image
        )

    def guard(self, command, *args, **kwargs):
        with self._acquire_timeout(HA):
            try:
                return command(*args, **kwargs)
            except Exception:
                return None
