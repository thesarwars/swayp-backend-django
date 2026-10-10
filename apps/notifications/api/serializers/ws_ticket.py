from rest_framework import serializers


class WebSocketTicketSerializer(serializers.Serializer):
    ticket = serializers.CharField(
        help_text="Open wss://<host>/ws/notifications/?ticket=<this>."
    )
    expires_in = serializers.IntegerField(
        help_text="Seconds it stays valid. Single use either way."
    )
