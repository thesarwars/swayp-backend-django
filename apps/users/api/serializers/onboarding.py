"""Response shape of users/onboarding and skip-bank (BANK-2).

Documentation only — OnboardingService.state builds the body.
"""

from rest_framework import serializers


class OnboardingStepSerializer(serializers.Serializer):
    step = serializers.IntegerField()
    key = serializers.ChoiceField(
        choices=["business", "plan", "payment", "bank"]
    )
    label = serializers.CharField()
    complete = serializers.BooleanField()
    # Only on the bank step.
    skipped = serializers.BooleanField(required=False)
    skippable = serializers.BooleanField(required=False)


class OnboardingStateSerializer(serializers.Serializer):
    total_steps = serializers.IntegerField()
    current_step = serializers.IntegerField(
        allow_null=True,
        help_text="First step neither complete nor skipped; null when done.",
    )
    complete = serializers.BooleanField()
    steps = OnboardingStepSerializer(many=True)


class OnboardingStateResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField()
    message = serializers.CharField()
    data = OnboardingStateSerializer()
