from abc import ABC, abstractmethod


class BaseQRParser(ABC):

    @abstractmethod
    def parse(self, payload: str):
        pass


class DefaultQRParser(BaseQRParser):

    def parse(self, payload: str):
        """
        Temporary parser.

        Payload specification is pending.
        Replace this parser when PRD finalizes the QR format.
        """

        return {
            "vendor_name": None,
            "category": None,
            "payment_ref": payload,
            "provenance": {
                "payment_ref": "detected",
            },
        }