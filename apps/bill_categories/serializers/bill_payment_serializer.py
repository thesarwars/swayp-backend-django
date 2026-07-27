from rest_framework import serializers


class BillPaymentSerializer(serializers.Serializer):
    payment_reference = serializers.CharField(max_length=255)