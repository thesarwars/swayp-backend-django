from .qr_strategy import DefaultQRParser


class QRParserService:

    def parse(self, payload: str):

        parser = DefaultQRParser()

        return parser.parse(payload)