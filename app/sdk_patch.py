# App-side monkeypatch for upstream SDK bugs, applied at app startup.
#
# The upstream Python-SDK tree (../Python-SDK/) is kept byte-for-byte
# verbatim so upstream updates can be merged without conflicts. Any SDK
# bug fixes therefore live here, in the app, instead of inside the SDK
# files.

import os
import tempfile

from PIL import Image

from StreamDock.InputTypes import ButtonKey
from StreamDock.ImageHelpers.PILHelper import to_native_key_format


def _patched_set_key_image(self, key, path):
    """StreamDock293.set_key_image replacement.

    Upstream saves the key icon to a hardcoded "Temporary.jpg" in the CWD,
    which can collide between devices and fails with a read-only CWD.
    This version uses a unique temporary file instead.
    """
    try:
        if isinstance(key, int):
            if key not in range(1, 16):
                print(f"key '{key}' out of range. you should set (1 ~ 15)")
                return -1
            logical_key = ButtonKey(key)
        else:
            logical_key = key

        if not os.path.exists(path):
            print(f"Error: The image file '{path}' does not exist.")
            return -1

        # Get hardware key value
        hardware_key = self.get_image_key(logical_key)

        image = Image.open(path)
        rotated_image = to_native_key_format(self, image)
        with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp:
            temp_image_path = tmp.name
        try:
            rotated_image.save(temp_image_path, "JPEG", subsampling=0, quality=95)
            returnvalue = self.transport.setKeyImg(bytes(temp_image_path, 'utf-8'), hardware_key)
        finally:
            os.remove(temp_image_path)
        return returnvalue

    except Exception as e:
        print(f"Error: {e}")
        return -1


def patch_streamdock293():
    """Replace the buggy StreamDock293.set_key_image with the fixed version."""
    from StreamDock.Devices.StreamDock293 import StreamDock293
    StreamDock293.set_key_image = _patched_set_key_image