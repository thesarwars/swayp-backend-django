from io import BytesIO

from PIL import Image

from .qr_parser import QRParserService


def _decode_image(img):
    """Reads the barcodes in an image with zbar.

    pyzbar is a thin ctypes wrapper around the native zbar library, and it
    resolves that library on import. A machine without it — a dev box that has
    not run ``brew install zbar``, a slim image built without ``libzbar0`` —
    raised ``ImportError`` from this module's import line, which Django
    resolves while loading ``apps.bills.urls``: one missing optional native
    library took down every endpoint in the project, not just QR decoding.

    Importing inside the call keeps that failure where it belongs. The QR
    endpoint answers with the error below; nothing else notices.
    """
    try:
        from pyzbar.pyzbar import decode
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise RuntimeError(
            "QR decoding is unavailable: the native zbar library is not "
            "installed. Install it with `brew install zbar` (macOS) or "
            "`apt-get install libzbar0` (Debian/Ubuntu)."
        ) from exc

    return decode(img)


class QRDecodeService:

    def decode_payload(self, payload):

        parser = QRParserService()

        return parser.parse(payload)

    def decode_image(self, image):

        img = Image.open(BytesIO(image.read()))

        decoded = _decode_image(img)

        if not decoded:
            raise ValueError(
                "Unable to decode QR code."
            )

        payload = decoded[0].data.decode()

        return self.decode_payload(payload)
