from django.db import models
from django.contrib.auth.models import User
from apps.common.models import BaseModel
from apps.vendors.models.vendor import Vendor



class VendorMailingDetail(BaseModel):
    # Physical Check 
    vendor = models.OneToOneField(Vendor, on_delete=models.CASCADE, related_name='mailing_details')
    
    legal_name_on_check = models.CharField(max_length=255)
    street_address = models.CharField(max_length=255)
    address_line_2 = models.CharField(max_length=255, blank=True, null=True)
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=100)
    zip_code = models.CharField(max_length=20)
    memo_on_check = models.CharField(max_length=255, blank=True, null=True)

    def __str__(self):
        return f"Check Address for {self.vendor.name}"