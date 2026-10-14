from rest_framework import serializers


class OptionSerializer(serializers.Serializer):
    value = serializers.CharField(help_text="What to send.")
    label = serializers.CharField(help_text="What to show.")


class FormOptionsSerializer(serializers.Serializer):
    industries = OptionSerializer(many=True)
    business_sizes = OptionSerializer(many=True)
    business_types = OptionSerializer(many=True)
