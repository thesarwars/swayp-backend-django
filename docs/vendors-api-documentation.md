 # Vendors API Documentation

This document covers the vendor-related APIs under the vendors module.

Base URL:
- `/api/v1/vendors/`

## Overview

These endpoints handle:
- vendor listing and detail retrieval
- vendor summary information
- vendor payment method management
- setting a payment method as primary
- provider directory search

All vendor endpoints require authentication via a valid access token.

---

## 1. List/Create Vendors

### Endpoint
- `GET /api/v1/vendors/`
- `POST /api/v1/vendors/`

### Purpose
Retrieve all vendors for the authenticated user or create a new vendor.

### Authentication
- Requires `Authorization: Bearer <access_token>`

### Success response (GET)
```json
{
  "count": 1,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": "<vendor_id>",
      "name": "ABC Supplies",
      "email": "vendor@example.com",
      "phone": "+8801712345678",
      "status": "ACTIVE"
    }
  ]
}
```

### Success response (POST)
```json
{
  "id": "<vendor_id>",
  "name": "ABC Supplies",
  "email": "vendor@example.com",
  "phone": "+8801712345678",
  "status": "ACTIVE"
}
```

---

## 2. Vendor Detail

### Endpoint
- `GET /api/v1/vendors/<vendor_id>/`
- `PUT /api/v1/vendors/<vendor_id>/`
- `DELETE /api/v1/vendors/<vendor_id>/`

### Purpose
Get or manage a specific vendor.

### Authentication
- Requires `Authorization: Bearer <access_token>`

### Success response (GET)
```json
{
  "id": "<vendor_id>",
  "name": "ABC Supplies",
  "email": "vendor@example.com",
  "phone": "+8801712345678",
  "status": "ACTIVE"
}
```

---

## 3. Vendor Summary

### Endpoint
- `GET /api/v1/vendors/summary/`

### Purpose
Get a summary view of the vendor-related data for the authenticated user.

### Authentication
- Requires `Authorization: Bearer <access_token>`

### Success response
```json
{
  "total_vendors": 5,
  "active_vendors": 4,
  "inactive_vendors": 1
}
```

---

## 4. List/Create Vendor Payment Methods

### Endpoint
- `GET /api/v1/vendors/<vendor_id>/payment-methods/`
- `POST /api/v1/vendors/<vendor_id>/payment-methods/`

### Purpose
List all payment methods for a vendor or add a new one.

### Authentication
- Requires `Authorization: Bearer <access_token>`

### Request body (POST)
```json
{
  "method_type": "ACH",
  "provider": "MOOV",
  "provider_token": "token-123",
  "account_last4": "4242",
  "account_holder_name": "John Doe",
  "is_primary": false,
  "supports_same_day": true
}
```

### Success response (GET)
```json
{
  "results": [
    {
      "id": "<method_id>",
      "method_type": "ACH",
      "is_primary": true,
      "supports_same_day": true,
      "provider": "MOOV",
      "account_ref": "****4242",
      "account_holder_name": "John Doe",
      "aba_bank_name": null,
      "payee_verified": false,
      "check_legal_name": null,
      "street": null,
      "line2": null,
      "city": null,
      "state": null,
      "zip_code": null,
      "check_memo": null
    }
  ]
}
```

### Notes
- `method_type` can be `ACH`, `CHECK`, or `NETWORK` depending on the payment method.
- For `ACH`, the serializer requires `provider`, `provider_token`, `account_last4`, and `account_holder_name`.
- For `CHECK`, the serializer requires `check_legal_name`, `street`, `city`, `state`, and `zip_code`.
- For `NETWORK`, `network_payee_ref` is required.

---

## 5. Retrieve/Update/Delete Vendor Payment Method

### Endpoint
- `GET /api/v1/vendors/<vendor_id>/payment-methods/<method_id>/`
- `PUT /api/v1/vendors/<vendor_id>/payment-methods/<method_id>/`
- `PATCH /api/v1/vendors/<vendor_id>/payment-methods/<method_id>/`
- `DELETE /api/v1/vendors/<vendor_id>/payment-methods/<method_id>/`

### Purpose
Retrieve or manage a specific vendor payment method.

### Authentication
- Requires `Authorization: Bearer <access_token>`

### Success response (GET)
```json
{
  "id": "<method_id>",
  "method_type": "ACH",
  "is_primary": true,
  "supports_same_day": true,
  "provider": "MOOV",
  "account_ref": "****4242",
  "account_holder_name": "John Doe"
}
```

---

## 6. Set Primary Payment Method

### Endpoint
- `POST /api/v1/vendors/<vendor_id>/payment-methods/<method_id>/set-primary/`

### Purpose
Mark a vendor payment method as the primary one.

### Authentication
- Requires `Authorization: Bearer <access_token>`

### Success response
```json
{
  "message": "Primary payment method updated."
}
```

---

## 7. Provider Directory Search

### Endpoint
- `GET /api/v1/vendors/directory-search/`

### Purpose
Search the provider directory.

### Authentication
- Requires `Authorization: Bearer <access_token>`

### Success response
```json
{
  "results": [
    {
      "id": "<provider_id>",
      "name": "Provider Name"
    }
  ]
}
```

---

## Common Notes

- Vendor APIs are authenticated endpoints.
- Payment method data keeps sensitive bank details masked where appropriate.
- The system uses the last four digits of the account for display purposes through the `account_ref` field.
