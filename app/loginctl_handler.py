from base_handler import BaseHandler
import os
import dbus

CMD = 'cmd'


class LoginCtlHandler(BaseHandler):

    def __init__(self, cmd_lock):
        super().__init__({
            CMD: cmd_lock,
        })
        self.session_bus = dbus.SessionBus()

    def toggle_lock(self):

        def locked():
            screensaver_active = self.session_bus.get_object(
                'org.freedesktop.ScreenSaver', '/ScreenSaver').get_dbus_method('GetActive')

            return screensaver_active()

        def cmd():
            with self._acquire_timeout(CMD):
                if locked():
                    os.system('loginctl unlock-session')
                else:
                    os.system('loginctl lock-session')

        return (
            lambda: cmd(),
            lambda: 'images/locked.png' if locked() else 'images/unlocked.png'
        )
