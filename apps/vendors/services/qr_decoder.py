
from io import BytesIO
from PIL import Image
from pyzbar.pyzbar import decode
from .qr_parser import QRParserService


class QRDecodeService:

    def decode_payload(self, payload):

        parser = QRParserService()

        return parser.parse(payload)

    def decode_image(self, image):

        img = Image.open(BytesIO(image.read()))

        decoded = decode(img)

        if not decoded:
            raise ValueError(
                "Unable to decode QR code."
            )

        payload = decoded[0].data.decode()

        return self.decode_payload(payload)