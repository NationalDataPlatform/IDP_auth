from argparse import Action
from django.db import models

# Create your models here.

# users/models.py

from django.contrib.auth.models import AbstractUser
from django.utils.translation import gettext_lazy as _
from datetime import datetime


# user table
class CustomUser(AbstractUser):

    email = models.EmailField(blank=False, max_length=254, verbose_name="email address")
    
    user_type = models.CharField(max_length=100, null=True, blank=True)
    phn       = models.CharField(max_length=13, null=True, blank=True)
    dpa_org    = models.CharField(max_length=100, null=True, blank=True)
    dpa_email  = models.EmailField(max_length=100, null=True, blank=True)
    dpa_phone  = models.CharField(max_length=13, null=True, blank=True)
    dpa_desg   = models.CharField(max_length=100, null=True, blank=True)
    dp_org    = models.CharField(max_length=100, null=True, blank=True)
    dp_email  = models.EmailField(max_length=100, null=True, blank=True)
    dp_phone  = models.CharField(max_length=13, null=True, blank=True)
    dp_desg   = models.CharField(max_length=100, null=True, blank=True)

    USERNAME_FIELD = "username"
    EMAIL_FIELD = "email"

    def __str__(self):
        return self.username


# roles table
class Role(models.Model):
    class Roles_enum(models.TextChoices):
        PMU = "PMU", _("PMU")
        PROVIDER_ADMIN = "DPA", _("PROVIDER ADMIN")
        PROVIDER = "DP", _("PROVIDER")
        CONSUMER = "CR", _("CONSUMER")
        SYSTEMADMIN = "SA", _("SYSTEMADMIN")
        AUDITOR = "AR", _("AUDITOR")

    role_name = models.CharField(
        max_length=50,
        choices=Roles_enum.choices,
        default=Roles_enum.CONSUMER,
        unique=True,
    )
    role_verbose_name = models.CharField(max_length=100)

    def __str__(self):
        return self.role_verbose_name


# permission table
class Permission(models.Model):
    class Permissions_enum(models.TextChoices):
        CREATE_DATASET = "create_dataset", _("CREATE DATASET")
        LIST_DRAFT_DATASET = "list_drafts", _("LIST DRAFT DATASET")
        REQUEST_REVIEW = "request_review", _("REQUEST REVIEW")
        REQUEST_MODERATION = "request_moderation", _("REQUEST MODERATION")
        APPROVE_PUBLISH = "publish", _("APPROVE AND PUBLISH")
        CALLBACK_REVIEW_REQUEST = "call_back_review_request", _(
            "CALLBACK REVIEW REQUEST"
        )
        CALLBACK_MODERATION_REQUEST = "call_back_moderation_request", _(
            "CALLBACK MODERATION REQUEST"
        )
        EDIT_DATASET = "edit_dataset", _("EDIT DATASET")
        APPROVE_ACCESS_MODEL = "approve_access_model", _("APPROVE ACCESS MODEL")

    perm_name = models.CharField(
        max_length=50,
        choices=Permissions_enum.choices,
        default=Permissions_enum.CREATE_DATASET,
        unique=True,
    )
    perm_verbose_name = models.CharField(max_length=100)

    def __str__(self):
        return self.perm_verbose_name


# role permission table
class RolePermission(models.Model):

    role = models.ForeignKey(Role, on_delete=models.CASCADE)
    permission = models.ForeignKey(Permission, on_delete=models.CASCADE)


# user org role table
class UserRole(models.Model):
    class status_enum(models.TextChoices):
        CREATED = "created", _("created")
        APPROVED = "approved", _("approved")
        REJECTED = "rejected", _("rejected")
        DISABLED = "disabled", _("disabled")

    username = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    org_id = models.CharField(max_length=100, null=True, blank=True)
    org_parent_id = models.CharField(max_length=100, null=True, blank=True)
    org_title = models.CharField(max_length=100, null=True, blank=True)
    role = models.ForeignKey(Role, on_delete=models.CASCADE)
    org_status = models.CharField(
        max_length=100,
        choices=status_enum.choices,
        default=status_enum.CREATED,
    )
    added = models.DateTimeField(null=True, auto_now_add=True)
    updated = models.DateTimeField(null=True, auto_now=True)


# dataset owner table
class DatasetOwner(models.Model):

    username = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    dataset_id = models.CharField(max_length=100)
    is_owner = models.BooleanField()


# datasetreq download table
class Datasetrequest(models.Model):

    username = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    data_request_id = models.CharField(max_length=100)
    dataset_access_model_request_id = models.CharField(max_length=100)
    dataset_access_model_id = models.CharField(max_length=100)
    dataset_id = models.CharField(max_length=100)
    download_count = models.IntegerField(default=0)
