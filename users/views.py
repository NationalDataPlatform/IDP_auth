from logging import exception
from operator import contains
from django.shortcuts import render
from django.http import HttpResponse, JsonResponse
from django.http import Http404
import keycloak
from keycloak import KeycloakOpenID
import requests
import json
from django.views.decorators.csrf import csrf_exempt
import ast
from configparser import ConfigParser
from .models import *
import os
from users.utils import utils
from django_ratelimit.decorators import ratelimit
from django.db.models import Count
from keycloak import KeycloakAdmin

config = ConfigParser()
config.read("config.ini")


# configure keycloak client
keycloak_openid = KeycloakOpenID(
    server_url=os.environ.get("KEYCLOAK_URL", config.get("keycloak", "server_url")),
    client_id=os.environ.get("KEYCLOAK_CLIENT_ID", config.get("keycloak", "client_id")),
    realm_name=os.environ.get(
        "KEYCLOAK_REALM_NAME", config.get("keycloak", "realm_name")
    ),
    client_secret_key=os.environ.get(
        "KEYCLOAK_SECRET", config.get("keycloak", "client_secret_key")
    ),
)
config_well_known = keycloak_openid.well_known()

# configure keycloak admin client
keycloak_admin = KeycloakAdmin(
                        server_url=os.environ.get("KEYCLOAK_URL", config.get("keycloak", "server_url")),
                        username=os.environ.get("KEYCLOAK_ADMIN", config.get("keycloak", "admin")),
                        password=os.environ.get("KEYCLOAK_ADMINPASS", config.get("keycloak", "adminpass")),
                        verify=False)


# graphql config
password = os.environ.get("USER_PASS", config.get("graphql", "password"))
auth_url = os.environ.get("AUTH_GRAPHQL_URL", config.get("graphql", "base_url"))

# util functions
@csrf_exempt
def get_user(access_token):

    try:
        userinfo = keycloak_openid.userinfo(access_token)
        userinfo["success"] = True
    except Exception as error:
        print(error)
        userinfo = {
            "success": False,
            "error": "invalid_token",
            "error_description": "Token verification failed",
        }

    return userinfo


@csrf_exempt
def has_access(username, access_org_id, access_data_id, access_req):

    ispmu = False
    iscr = False

    is_data_owner = False
    if access_data_id:
        datasetobj = DatasetOwner.objects.filter(
            username__username=username, dataset_id=access_data_id
        ).values("is_owner")
        if len(datasetobj) != 0 and datasetobj[0]["is_owner"] == True:    
            is_data_owner = True

    userroleobj = UserRole.objects.filter(
        username__username=username, org_id=access_org_id
    ).values("org_id", "role__role_name")

    if "PMU" in [each["role__role_name"] for each in userroleobj]:
        ispmu = True

    if len(userroleobj) == 0:

        userroles = UserRole.objects.filter(username__username=username).values(
            "org_id", "role__role_name"
        )
        if len(userroles) != 0:
            if "PMU" in [each["role__role_name"] for each in userroles]:
                ispmu = True
            if "CR" in [each["role__role_name"] for each in userroles]:
                iscr = True
        if len(userroles) == 0:
            if access_req == "query":
                context = {"Success": True, "access_allowed": True, "role": "", "is_data_owner": is_data_owner}
                return JsonResponse(context, safe=False)
            context = {
                "Success": False,
                "error": "No Matching user role found",
                "error_description": "No Matching user role found",
            }
            return JsonResponse(context, safe=False)

    userrole = (
        "PMU"
        if ispmu == True
        else "CR"
        if iscr == True
        else userroleobj[0]["role__role_name"]
        if len(userroleobj) != 0
        else userroles[0]["role__role_name"]
    )
    userorg = (
        ""
        if (userrole in ["PMU", "CR"] or len(userroleobj) == 0)
        else userroleobj[0]["org_id"]
    )

    if access_req == "query":
        context = {"Success": True, "access_allowed": True, "role": userrole, "is_data_owner": is_data_owner}
        return JsonResponse(context, safe=False)

    if ispmu == True:
        context = {"Success": True, "access_allowed": True, "role": "PMU", "is_data_owner": is_data_owner}
        return JsonResponse(context, safe=False)

    # request_dataset_mod
    if (
        userrole == "DPA"
        and userorg != ""
        and access_req
        not in ["approve_organization", "publish_dataset", "approve_license", "approve_policy"]
    ):
        context = {"Success": True, "access_allowed": True, "role": "DPA", "is_data_owner": is_data_owner}
        return JsonResponse(context, safe=False)

    if (
        userrole == "DP"
        and userorg != ""
        and (("create" in access_req) or (access_req in ["list_review_request"]))
        and access_req not in ["create_dam"]
    ):
        context = {"Success": True, "access_allowed": True, "role": "DP", "is_data_owner": is_data_owner}
        return JsonResponse(context, safe=False)

    if (
        userrole == "DP"
        and userorg != ""
        and (
            "update" in access_req
            or "delete" in access_req
            or "patch" in access_req
            or "get_draft_datasets" in access_req
            or "request_dataset_review" in access_req
        )
        and access_data_id != None
    ):
        datasetobj = DatasetOwner.objects.filter(
            username__username=username, dataset_id=access_data_id
        ).values("is_owner")
        if len(datasetobj) != 0 and datasetobj[0]["is_owner"] == True:
            context = {"Success": True, "access_allowed": True, "role": "DP", "is_data_owner": is_data_owner}
            return JsonResponse(context, safe=False)

    context = {"Success": True, "access_allowed": False}
    return JsonResponse(context, safe=False)


# api functions
@csrf_exempt
# @ratelimit(key='ip', rate='2/m')
def verify_user_token(request):

    print("-----------------", request.body)
    post_data = json.loads(request.body.decode("utf-8"))
    access_token = request.META.get(
        "HTTP_ACCESS_TOKEN", post_data.get("access_token", None)
    )
    userinfo = get_user(access_token)

    return JsonResponse(userinfo, safe=False)


@csrf_exempt
# @ratelimit(key='ip', rate='2/m')
def check_user(request):
    post_data = json.loads(request.body.decode("utf-8"))
    access_token = request.META.get(
        "HTTP_ACCESS_TOKEN", post_data.get("access_token", None)
    )
    userinfo = get_user(access_token)

    if userinfo["success"] == False:
        context = {
            "Success": False,
            "error": userinfo["error"],
            "error_description": userinfo["error_description"],
        }
        return JsonResponse(context, safe=False)

    username = userinfo["preferred_username"]
    try:
        email = userinfo["email"]
    except Exception as e:
        context = {
            "Success": False,
            "error": "user doesn't have a email set",
            "error_description": "please set a valid email",
        }
        return JsonResponse(context, safe=False)

    # check if username is in auth db
    num_users = CustomUser.objects.filter(username=username).count()

    if num_users == 0:

        try:

            response_json = utils.create_user(auth_url, email, username, password)
            print(response_json)

            if response_json["data"]["register"]["success"] == True:
                createduserobj = CustomUser.objects.filter(username=username)
                if  userinfo.get("phone_number") != None: 
                    createduserobj.update(phn=userinfo.get("phone_number"))   
                context = {
                    "Success": True,
                    "username": username,
                    "email": email,
                    "access_token": access_token,
                    "Comment": "User Registration successful",
                }
            else:
                context = {
                    "Success": False,
                    "errors": response_json["data"]["register"]["errors"],
                }

            return JsonResponse(context, safe=False)

        except Exception as e:
            print(e)
            context = {
                "Success": False,
                "errors": response_json["data"]["register"]["errors"],
            }
            return JsonResponse(context, safe=False)
    else:
        UserObjs = CustomUser.objects.filter(username=username)
        if  userinfo.get("given_name") != None: #and UserObjs[0].first_name == None
            UserObjs.update(first_name=userinfo.get("given_name"))
        if  userinfo.get("family_name") != None: # and UserObjs[0].last_name == None
            UserObjs.update(last_name=userinfo.get("family_name")) 
        if  userinfo.get("phone_number") != None: # and UserObjs[0].last_name == None
            UserObjs.update(phn=userinfo.get("phone_number"))                        
                
        user_roles = UserRole.objects.filter(username__username=username).exclude(org_status="disabled").values(
            "org_id", "org_title", "role__role_name", "org_status"
        )
        user_roles_res = []
        for role in user_roles:
            user_roles_res.append(
                {
                    "org_id": role["org_id"],
                    "org_title": role["org_title"],
                    "role": role["role__role_name"],
                    "status": role["org_status"],
                }
            )
        context = {
            "Success": True,
            "username": username,
            "email": email,
            "access_token": access_token,
            "access": user_roles_res,
            "comment": "User already exists",
        }
        return JsonResponse(context, safe=False)


@csrf_exempt
# @ratelimit(key='ip', rate='2/m')
def check_user_access(request):

    print("-----------------", request.body)
    post_data = json.loads(request.body.decode("utf-8"))
    access_token = request.META.get(
        "HTTP_ACCESS_TOKEN", post_data.get("access_token", None)
    )
    access_org_id = post_data.get("access_org_id", None)
    access_data_id = post_data.get("access_data_id", None)
    access_req = post_data.get("access_req", None)
    userinfo = get_user(access_token)

    if userinfo["success"] == False:
        context = {
            "Success": False,
            "error": userinfo["error"],
            "error_description": userinfo["error_description"],
        }
        return JsonResponse(context, safe=False)

    username = userinfo["preferred_username"]

    has_access_res = has_access(username, access_org_id, access_data_id, access_req)

    return has_access_res  # JsonResponse(has_access_res, safe=False)


@csrf_exempt
def create_user_role(request):

    print("-----------------", request.body)
    post_data = json.loads(request.body.decode("utf-8"))
    access_token = request.META.get(
        "HTTP_ACCESS_TOKEN", post_data.get("access_token", None)
    )
    org_id = post_data.get("org_id", None)
    org_title = post_data.get("org_title", None)
    role_name = "DPA"

    userinfo = get_user(access_token)

    if userinfo["success"] == False:
        context = {
            "Success": False,
            "error": userinfo["error"],
            "error_description": userinfo["error_description"],
        }
        return JsonResponse(context, safe=False)

    if org_id == None:
        context = {
            "Success": False,
            "error": "wrong org_id",
            "error_description": "org_id is blank",
        }
        return JsonResponse(context, safe=False)

    username = userinfo["preferred_username"]

    try:
        role = Role.objects.get(role_name=role_name)
        user = CustomUser.objects.get(username=username)
        newUserRole = UserRole(
            username=user, org_id=org_id, org_title=org_title, role=role
        )

        newUserRole.save()
        context = {"Success": True, "comment": "User Role Added Successfully"}
        return JsonResponse(context, safe=False)
    except Exception as e:
        context = {"Success": False, "error": e, "error_description": e}
        return JsonResponse(context, safe=False)


@csrf_exempt
def modify_org_status(request):

    print("-----------------", request.body)
    post_data = json.loads(request.body.decode("utf-8"))
    access_token = request.META.get(
        "HTTP_ACCESS_TOKEN", post_data.get("access_token", None)
    )
    org_list = post_data.get("org_list", None)
    org_status = post_data.get("org_status", None)

    userinfo = get_user(access_token)

    if userinfo["success"] == False:
        context = {
            "Success": False,
            "error": userinfo["error"],
            "error_description": userinfo["error_description"],
        }
        return JsonResponse(context, safe=False)

    if len(org_list) == 0:
        context = {
            "Success": False,
            "error": "wrong org_id",
            "error_description": "org_list is blank",
        }
        return JsonResponse(context, safe=False)

    if org_status not in ["created", "approved", "rejected", "disabled"]:
        context = {
            "Success": False,
            "error": "wrong status",
            "error_description": "please send correct status",
        }
        return JsonResponse(context, safe=False)

    username = userinfo["preferred_username"]

    ispmu = False
    ispra = False
    userroleobj = UserRole.objects.filter(
        username__username=username, org_id__in=org_list
    ).values("org_id", "role__role_name")
    if len(userroleobj) == 0 or True:
        userroleobj = UserRole.objects.filter(username__username=username).values(
            "org_id", "role__role_name"
        )
        if len(userroleobj) != 0 and "PMU" in [
            each["role__role_name"] for each in userroleobj
        ]:
            ispmu = True
    else:
        if "DPA" in [each["role__role_name"] for each in userroleobj]:
            ispra = True

    if ispmu == False:
        context = {
            "Success": False,
            "error": "Access Denied",
            "error_description": "User is not Authorized",
        }
        return JsonResponse(context, safe=False)

    try:
        UserRoleObjs = UserRole.objects.filter(org_id__in=org_list)
        UserRoleObjCount = UserRoleObjs.count()
        if UserRoleObjCount == 0:
            context = {
                "Success": False,
                "error": "no matching org found",
                "error_description": "please send correct org_list",
            }
            return JsonResponse(context, safe=False)
        UserRoleObjs.update(org_status=org_status)
        context = {"Success": True, "comment": "org status updated successfully"}
        return JsonResponse(context, safe=False)
    except Exception as e:
        context = {"Success": False, "error": str(e), "error_description": str(e)}
        return JsonResponse(context, safe=False)


@csrf_exempt
# @ratelimit(key='ip', rate='2/m')
def get_users(request):

    print("-----------------", request.body)
    post_data = json.loads(request.body.decode("utf-8"))
    access_token = request.META.get(
        "HTTP_ACCESS_TOKEN", post_data.get("access_token", None)
    )
    org_id = post_data.get("org_id", None)
    user_type = post_data.get("user_type", None)

    userinfo = get_user(access_token)
    if userinfo["success"] == False:
        context = {
            "Success": False,
            "error": userinfo["error"],
            "error_description": userinfo["error_description"],
        }
        return JsonResponse(context, safe=False)
    username = userinfo["preferred_username"]

    # check for username access
    ispmu = False
    ispra = False
    isdp = False
    iscr = False
    calling_user = CustomUser.objects.get(username=username)
    ispmu, ispra, isdp, iscr = utils.check_user_role(calling_user, org_id)
    print(ispmu, ispra, isdp, iscr)





    '''ispmu = False
    ispra = False
    userroleobj = UserRole.objects.filter(
        username__username=username, org_id=org_id
    ).values("org_id", "role__role_name")
    if len(userroleobj) == 0:
        userroleobj = UserRole.objects.filter(username__username=username).values(
            "org_id", "role__role_name"
        )
        if len(userroleobj) != 0 and userroleobj[0]["role__role_name"] == "PMU":
            ispmu = True
    else:
        if userroleobj[0]["role__role_name"] == "DPA":
            ispra = True

    if ispmu == False and ispra == False:
        context = {
            "Success": False,
            "error": "No access for the org for this user",
            "error_description": "No access for the org for this user",
        }
        return JsonResponse(context, safe=False)

    userrole = userroleobj[0]["role__role_name"]
    userorg = userroleobj[0]["org_id"]'''

    if ispmu and org_id == "":
        users = CustomUser.objects.all().values(
            "username", "email", "first_name", "date_joined", "last_name"
        )
        # CustomUser.objects.exclude(username=username).values(
        #     "username", "email", "first_name", "date_joined", "last_name"
        # )
        if user_type == ["All"]:
            users_list = []
            for user in users:
                dataset_access_count = len(Datasetrequest.objects.filter(username__username=user['username']).values('dataset_id').annotate(dcount=Count('dataset_id')))
                dataset_obj = Datasetrequest.objects.filter(username__username=user["username"]).values_list("dataset_id", flat=True).order_by("dataset_id")
                dataset_list = list(set([id for id in dataset_obj]))
                users_list.append({"username": user['username'], "email":user["email"], "name":user["first_name"] + " " + user["last_name"], "date_joined": user["date_joined"], "dataset_access_count": dataset_access_count, "dataset_list": dataset_list})
            context = {"Success": True, "users": users_list}
            return JsonResponse(context, safe=False)
        users_list = []
        for user in users:
            user_roles = UserRole.objects.filter(
                username__username=user["username"], role__role_name__in=user_type
            ).values("org_id", "org_title", "role__role_name", "org_status", "updated")
            if len(user_roles) == 0:
                continue
            user_roles_res = []
            for role in user_roles:
                provider_count = UserRole.objects.filter(org_id=role["org_id"], role__role_name="DP").count()
                # print(role["org_title"], provider_count)
                dataset_obj = DatasetOwner.objects.filter(username__username=user["username"]).values_list("dataset_id", flat=True).order_by("dataset_id")
                dataset_list = [id for id in dataset_obj]
                user_roles_res.append(
                    {
                        "org_id": role["org_id"],
                        "org_title": role["org_title"],
                        "role": role["role__role_name"],
                        "status": role["org_status"],
                        "updated": role["updated"],
                        "dp_count": provider_count,
                        "dataset_list": dataset_list
                    }
                )
            users_list.append(
                {
                    "username": user["username"],
                    "email": user["email"],
                    "name": user["first_name"] + " " + user["last_name"],
                    "access": user_roles_res,
                }
            )

        context = {"Success": True, "users": users_list}
        return JsonResponse(context, safe=False)

    if (ispmu or ispra) and org_id != "":
        user_roles = (
            UserRole.objects.filter(org_id=org_id, role__role_name__in=user_type)
            # .exclude(role__role_name__in=["PMU", "DPA"])
            .exclude(username__username=username).values(
                "username__username",
                "username__email",
                "org_id",
                "org_title",
                "role__role_name",
                "org_status",
                "updated",
            )
        )
        user_roles_res = {}
        for role in user_roles:
            if role["username__username"] in user_roles_res:
                user_roles_res[role["username__username"]]["access"].append(
                    {
                        "org_id": role["org_id"],
                        "org_title": role["org_title"],
                        "role": role["role__role_name"],
                        "status": role["org_status"],
                        "updated": role["updated"],
                    }
                )
            else:
                user_roles_res[role["username__username"]] = {
                    "email": role["username__email"],
                    "access": [
                        {
                            "org_id": role["org_id"],
                            "org_title": role["org_title"],
                            "role": role["role__role_name"],
                            "status": role["org_status"],
                            "updated": role["updated"],
                        }
                    ],
                }

        users_list = []
        for key, value in user_roles_res.items():
            users_list.append(
                {"username": key, "email": value["email"], "access": value["access"]}
            )
        context = {"Success": True, "users": users_list}
        return JsonResponse(context, safe=False)

    context = {
        "Success": False,
        "error": "No Matching org and user found",
        "error_description": ("org is " + org_id + " and role is " + user_type),
    }
    return JsonResponse(context, safe=False)


@csrf_exempt
def update_user_role(request):

    print("-----------------", request.body)
    post_data = json.loads(request.body.decode("utf-8"))
    access_token = request.META.get(
        "HTTP_ACCESS_TOKEN", post_data.get("access_token", None)
    )
    org_id = post_data.get("org_id", None)
    org_parent_id = post_data.get("org_parent_id", None)
    org_title = post_data.get("org_title", None)
    role_name = post_data.get("role_name", None)
    tgt_user_name = post_data.get("tgt_user_name", None)
    tgt_user_email = post_data.get("tgt_user_email", None)
    action = post_data.get("action", None)

    userinfo = get_user(access_token)

    if userinfo["success"] == False:
        context = {
            "Success": False,
            "error": userinfo["error"],
            "error_description": userinfo["error_description"],
        }
        return JsonResponse(context, safe=False)

    if org_id == None:
        context = {
            "Success": False,
            "error": "wrong org_id",
            "error_description": "org_id is blank",
        }
        return JsonResponse(context, safe=False)

    if (
        role_name == None
        or role_name not in ["DPA", "DP", "PMU"]
        and action != "delete"
    ):
        context = {
            "Success": False,
            "error": "wrong role",
            "error_description": "role is not valid",
        }
        return JsonResponse(context, safe=False)

    username = userinfo["preferred_username"]
    # check for username access
    ispmu = False
    ispra = False
    isdp = False
    iscr = False
    calling_user = CustomUser.objects.get(username=username)
    ispmu, ispra, isdp, iscr = utils.check_user_role(calling_user, org_id)
    print(ispmu, ispra, isdp, iscr)

    # ispmu = False
    # ispra = False
    # userroleobj = UserRole.objects.filter(
    #     username__username=username, org_id=org_id
    # ).values("org_id", "role__role_name")
    # if len(userroleobj) == 0:
    #     userroleobj = UserRole.objects.filter(username__username=username).values(
    #         "org_id", "role__role_name"
    #     )
    #     if len(userroleobj) != 0 and "PMU" in [
    #         each["role__role_name"] for each in userroleobj
    #     ]:
    #         ispmu = True
    # else:
    #     if "DPA" in [each["role__role_name"] for each in userroleobj]:
    #         ispra = True

    if ispmu == False and ispra == False:
        context = {
            "Success": False,
            "error": "Access Denied",
            "error_description": "User is not Authorized",
        }
        return JsonResponse(context, safe=False)
    # TO Do: mark status as "approved" if update if new role create
    if action == "update":
        try:
            role = Role.objects.get(role_name=role_name)
            user = (
                CustomUser.objects.filter(username=tgt_user_name)
                if (tgt_user_email == None or tgt_user_email == "")
                else CustomUser.objects.filter(email=tgt_user_email)
            )
            
            if user.count() == 0 :
                if tgt_user_email: 
                    response_json = utils.create_user(auth_url, tgt_user_email, tgt_user_email, password)
                    
                    if response_json["data"]["register"]["success"] == True:
                        pass
                    else:
                        context = {
                            "Success": False,
                            "errors": "user doesn't exist.  Not able to register new user.",
                            "error_description": response_json["data"]["register"]["errors"],
                        }

                        return JsonResponse(context, safe=False)
                else:
                    context = {
                            "Success": False,
                            "error": "Not able to update userrole",
                            "error_description": "user doesn't exist.",
                        }
                    return JsonResponse(context, safe=False)

            UserRoleObjs = UserRole.objects.filter(username=user[0], org_id=org_id)
            UserRoleObjCount = UserRoleObjs.count()
            if UserRoleObjCount == 0:
                newUserRole = UserRole(
                    username=user[0],
                    org_id=org_id,
                    org_parent_id=org_parent_id,
                    org_title=org_title,
                    role=role,
                    org_status="approved",
                )
                newUserRole.save()
            else:
                UserRoleObjs.update(role=role)
                UserRoleObjs.update(org_status="approved")
                UserRoleObjs.update(org_parent_id=org_parent_id)
                UserRoleObjs.update(org_title=org_title)
            context = {
                "Success": True,
                "comment": "User Role Updated/Added Successfully",
            }
            return JsonResponse(context, safe=False)
        except Exception as e:
            context = {"Success": False, "error": str(e), "error_description": str(e)}
            return JsonResponse(context, safe=False)

    if action == "delete":
        try:
            role = Role.objects.get(role_name=role_name)
            user = (
                CustomUser.objects.filter(username=tgt_user_name)
                if (tgt_user_email == None or tgt_user_email == "")
                else CustomUser.objects.filter(email=tgt_user_email)
            )
            UserRoleObj = UserRole.objects.get(username=user[0], org_id=org_id, role=role)
            UserRoleObj.delete()
            context = {"Success": True, "comment": "User Role Deleted Successfully"}
            return JsonResponse(context, safe=False)
        except Exception as e:
            context = {"Success": False, "error": str(e), "error_description": str(e)}
            return JsonResponse(context, safe=False)


@csrf_exempt
def update_dataset_owner(request):

    print("-----------------", request.body)
    post_data = json.loads(request.body.decode("utf-8"))
    access_token = request.META.get(
        "HTTP_ACCESS_TOKEN", post_data.get("access_token", None)
    )
    dataset_id = post_data.get("dataset_id", None)
    org_id = post_data.get("org_id", None)
    tgt_user_name = post_data.get("tgt_user_name", None)
    action = post_data.get("action", None)
    userinfo = get_user(access_token)

    if userinfo["success"] == False:
        context = {
            "Success": False,
            "error": userinfo["error"],
            "error_description": userinfo["error_description"],
        }
        return JsonResponse(context, safe=False)

    if dataset_id == None:
        context = {
            "Success": False,
            "error": "wrong dataset_id",
            "error_description": "dataset_id is blank",
        }
        return JsonResponse(context, safe=False)

    username = userinfo["preferred_username"]
    if action == "create":

        user = CustomUser.objects.get(username=username)
        newDatasetOwner = DatasetOwner(
            username=user, dataset_id=dataset_id, is_owner=True
        )
        newDatasetOwner.save()
        context = {"Success": True, "comment": "Dataset owner created Successfully"}
        return JsonResponse(context, safe=False)

    ispmu = False
    ispra = False
    userroleobj = UserRole.objects.filter(
        username__username=username, org_id=org_id
    ).values("org_id", "role__role_name")
    if len(userroleobj) == 0:
        userroleobj = UserRole.objects.filter(username__username=username).values(
            "org_id", "role__role_name"
        )
        if len(userroleobj) != 0 and userroleobj[0]["role__role_name"] == "PMU":
            ispmu = True
    else:
        if userroleobj[0]["role__role_name"] == "DPA":
            ispra = True

    if ispmu == False and ispra == False:
        context = {
            "Success": False,
            "error": "access denied",
            "error_description": "access denied",
        }
        return JsonResponse(context, safe=False)

    if (ispmu or ispra) and action == "update" or action == "delete":
        try:
            user = CustomUser.objects.get(username=tgt_user_name)
            DatasetOwnerObjs = DatasetOwner.objects.filter(
                username=user, dataset_id=dataset_id
            )
            DOObjCount = DatasetOwnerObjs.count()
            if DOObjCount == 0:
                context = {
                    "Success": False,
                    "error": "user and dataset doesn't exist",
                    "error_description": "user and dataset doesn't exist",
                }
                return JsonResponse(context, safe=False)
            else:
                if action == "update":
                    DatasetOwnerObjs.update(is_owner=False)
                    context = {
                        "Success": True,
                        "comment": "Dataset owner updated Successfully",
                    }
                    return JsonResponse(context, safe=False)

                if action == "delete":
                    DatasetOwnerObjs.delete()
                    context = {
                        "Success": True,
                        "comment": "Dataset owner deleted Successfully",
                    }
                    return JsonResponse(context, safe=False)

        except Exception as e:
            context = {"Success": False, "error": str(e), "error_description": str(e)}
            return JsonResponse(context, safe=False)

    context = {
        "Success": False,
        "error": "Invalid action",
        "error_description": "Invalid action",
    }
    return JsonResponse(context, safe=False)


@csrf_exempt
def get_user_count(request):

    users = CustomUser.objects.all().values("username")
    user_count = len(users)
    context = {"Success": True, "user_count": user_count}
    return JsonResponse(context, safe=False)


@csrf_exempt
def get_access_datasets(request):

    print("-----------------", request.body)
    post_data = json.loads(request.body.decode("utf-8"))
    access_token = request.META.get(
        "HTTP_ACCESS_TOKEN", post_data.get("access_token", None)
    )
    org_id = post_data.get("org_id", None)

    userinfo = get_user(access_token)
    if userinfo["success"] == False:
        context = {
            "Success": False,
            "error": userinfo["error"],
            "error_description": userinfo["error_description"],
        }
        return JsonResponse(context, safe=False)
    username = userinfo["preferred_username"]

    ispmu = False
    ispra = False
    userroleobj = UserRole.objects.filter(
        username__username=username, org_id=org_id
    ).values("org_id", "role__role_name")
    if len(userroleobj) == 0:
        userroleobj = UserRole.objects.filter(username__username=username).values(
            "org_id", "role__role_name"
        )
        if len(userroleobj) != 0 and userroleobj[0]["role__role_name"] == "PMU":
            ispmu = True
    else:
        if userroleobj[0]["role__role_name"] == "DPA":
            ispra = True

    if ispmu == False and ispra == False:
        context = {
            "Success": False,
            "error": "No access for the org for this user",
            "error_description": "No access for the org for this user",
        }
        return JsonResponse(context, safe=False)

    userrole = userroleobj[0]["role__role_name"]
    userorg = userroleobj[0]["org_id"]

    if userrole == "PMU":
        users = CustomUser.objects.all().values("username")
        users_list = []
        for user in users:
            user_roles = UserRole.objects.filter(
                username__username=user["username"]
            ).values("org_id", "role__role_name")
            user_roles_res = []
            for role in user_roles:
                user_roles_res.append(
                    {"org_id": role["org_id"], "role": role["role__role_name"]}
                )
            users_list.append({"username": user["username"], "access": user_roles_res})

        context = {"Success": True, "users": users_list}
        return JsonResponse(context, safe=False)

    if userrole == "DPA" and userorg != None:
        user_roles = UserRole.objects.filter(org_id=userorg).values(
            "username__username", "org_id", "org_title", "role__role_name"
        )
        user_roles_res = {}
        for role in user_roles:
            if role["username__username"] in user_roles_res:
                user_roles_res[role["username__username"]].append(
                    {
                        "org_id": role["org_id"],
                        "org_title": role["org_title"],
                        "role": role["role__role_name"],
                    }
                )
            else:
                user_roles_res[role["username__username"]] = [
                    {
                        "org_id": role["org_id"],
                        "org_title": role["org_title"],
                        "role": role["role__role_name"],
                    }
                ]

        users_list = []
        for key, value in user_roles_res.items():
            users_list.append({"username": key, "access": value})
        context = {"Success": True, "users": users_list}
        return JsonResponse(context, safe=False)

    context = {
        "Success": False,
        "error": "No Matching org and user found",
        "error_description": ("org is " + userorg + " and role is " + userrole),
    }
    return JsonResponse(context, safe=False)


@csrf_exempt
def get_user_datasets(request):

    print("-----------------", request.body)
    post_data = json.loads(request.body.decode("utf-8"))
    access_token = request.META.get(
        "HTTP_ACCESS_TOKEN", post_data.get("access_token", None)
    )

    userinfo = get_user(access_token)
    if userinfo["success"] == False:
        context = {
            "Success": False,
            "error": userinfo["error"],
            "error_description": userinfo["error_description"],
        }
        return JsonResponse(context, safe=False)
    username = userinfo["preferred_username"]

    user_datasets = list(
        DatasetOwner.objects.filter(username__username=username).values_list(
            "dataset_id", flat=True
        )
    )

    context = {
        "Success": True,
        "datasets": user_datasets,
    }
    return JsonResponse(context, safe=False)


@csrf_exempt
def get_sys_token(request):

    # system config
    sys_user = (os.environ.get("SYSTEM_USER", config.get("sysuser", "sys_user")),)
    sys_pass = (os.environ.get("SYSTEM_USER_PASS", config.get("sysuser", "sys_pass")),)

    try:

        token = keycloak_openid.token(sys_user, sys_pass)
        access_token = token["access_token"]
        info = {
            "success": True,
            "access_token": access_token,
        }

    except Exception as error:
        print(error)
        info = {
            "success": False,
            "error": "Token generation failed",
            "error_description": str(error),
        }

    return JsonResponse(info, safe=False)


@csrf_exempt
def get_user_info(request):

    post_data = json.loads(request.body.decode("utf-8"))
    user_name = post_data.get("user_name", None)

    try:
        users = CustomUser.objects.filter(username=user_name).values(
            "username", "email", "first_name", "last_name", "user_type", "phn" 
        )
        
        user = users[0]
        
        user_roles = UserRole.objects.filter(username__username=user["username"]).values("org_id", "org_title", "role__role_name", "org_status", "updated")
        user_roles_res = {"DP": [], "DPA": [], "PMU": [], "CR": [], "SA": [], "AR":[]}

        for role in user_roles:
            user_roles_res[role["role__role_name"]].append(
                {
                    "org_id": role["org_id"],
                    "org_title": role["org_title"],
                    "role": role["role__role_name"],
                    "status": role["org_status"],
                    "updated": role["updated"],
                }
            )
        context = {
            "Success": True,
            "username": user_name,
            "email": user["email"],
            "first_name": user["first_name"],
            "last_name": user["last_name"],                        
            "user_type": user["user_type"],
            "phn": user["phn"],
            "access": user_roles_res,
        }
        return JsonResponse(context, safe=False)

    except Exception as error:
        info = {
            "Success": False,
            "error": "User Info Fetch Failed",
            "error_description": str(error),
        }

        return JsonResponse(info, safe=False)
    
    
@csrf_exempt
def update_user_info(request):

    post_data = json.loads(request.body.decode("utf-8"))
    user_name = post_data.get("user_name", None)
    first_name = post_data.get("first_name", None)
    last_name = post_data.get("last_name", None)    
    user_type = post_data.get("user_type", None)
    phn       = post_data.get("phn", None)
    dpa_org    = post_data.get("dpa_org", None)
    dpa_email  = post_data.get("dpa_email", None)
    dpa_phone  = post_data.get("dpa_phone", None)
    dpa_desg  = post_data.get("dpa_desg", None)
    dp_org    = post_data.get("dp_org", None)
    dp_email  = post_data.get("dp_email", None)
    dp_phone  = post_data.get("dp_phone", None)
    dp_desg  = post_data.get("dp_desg", None)
                                    
    access_token = request.META.get(
        "HTTP_ACCESS_TOKEN", post_data.get("access_token", None)
    )
    userinfo = get_user(access_token)

    if userinfo["success"] == False:
        context = {
            "Success": False,
            "error": userinfo["error"],
            "error_description": userinfo["error_description"],
        }
        return JsonResponse(context, safe=False)

    username = userinfo["preferred_username"]    
    
    if username != user_name:
        context = {
            "Success": False,
            "error": "Access Denied",
            "error_description": "User Mismatch",
        }
        return JsonResponse(context, safe=False)        
    

    try:
        # Get user ID from username
        keycloak_admin.realm_name=os.environ.get("KEYCLOAK_REALM_NAME", config.get("keycloak", "realm_name"))
        user_id_keycloak = keycloak_admin.get_user_id(username)
        print ('----id', user_id_keycloak)
        print ('---user', user_name)
        
        UserObjs = CustomUser.objects.filter(username=user_name)
        if  first_name != None:
            UserObjs.update(first_name=first_name)
            # Update User
            response = keycloak_admin.update_user(user_id=user_id_keycloak,
                                      payload={'firstName': first_name})
        if  last_name != None:
            UserObjs.update(last_name=last_name)
            # Update User
            response = keycloak_admin.update_user(user_id=user_id_keycloak,
                                      payload={'lastName':last_name})
        if  user_type != None:
            UserObjs.update(user_type=user_type)
        if  phn != None:
            UserObjs.update(phn=phn)
        if  dpa_org != None:
            UserObjs.update(dpa_org=dpa_org)
        if  dpa_email != None:
            UserObjs.update(dpa_email=dpa_email)
        if  dpa_phone != None:
            UserObjs.update(dpa_phone=dpa_phone)
        if  dpa_desg != None:
            UserObjs.update(dpa_desg=dpa_desg)            
        if  dp_org != None:
            UserObjs.update(dp_org=dp_org)
        if  dp_email != None:
            UserObjs.update(dp_email=dp_email)
        if  dp_phone != None:
            UserObjs.update(dp_phone=dp_phone)   
        if  dp_desg != None:
            UserObjs.update(dp_desg=dp_desg)                                                                                   

        context = {
            "Success": True,
            "username": user_name,
            "email": UserObjs[0].email,
            "message": "User profile updates successfully"
        }

        return JsonResponse(context, safe=False)

    except Exception as error:
        raise error
        info = {
            "Success": False,
            "error": "User Profile Update Failed",
            "error_description": str(error),
        }

        return JsonResponse(info, safe=False)    


@csrf_exempt
def update_datasetreq(request):

    post_data = json.loads(request.body.decode("utf-8"))
    username = post_data.get("username", "Anonymous")
    data_request_id = post_data.get("data_request_id", None)
    dataset_access_model_request_id = post_data.get(
        "dataset_access_model_request_id", None
    )
    dataset_access_model_id = post_data.get("dataset_access_model_id", None)
    dataset_id = post_data.get("dataset_id", None)
    username = "Anonymous" if (username == "" or username == None) else username

    try:
        user = CustomUser.objects.get(username=username)
        DataSetReqObjs = Datasetrequest.objects.filter(
            username=user,
            data_request_id=data_request_id,
            dataset_access_model_request_id=dataset_access_model_request_id,
            dataset_access_model_id=dataset_access_model_id,
            dataset_id=dataset_id,
        ).values("download_count")

        DataSetReqObjCount = DataSetReqObjs.count()
        if DataSetReqObjCount == 0:
            newDataSetReqObj = Datasetrequest(
                username=user,
                data_request_id=data_request_id,
                dataset_access_model_request_id=dataset_access_model_request_id,
                dataset_access_model_id=dataset_access_model_id,
                dataset_id=dataset_id,
                download_count=1,
            )
            newDataSetReqObj.save()
        else:
            download_count = DataSetReqObjs[0]["download_count"]
            DataSetReqObjs.update(download_count=download_count + 1)
        context = {"Success": True, "comment": "Datasetrequest updated Successfully"}
        return JsonResponse(context, safe=False)
    except Exception as e:
        context = {"Success": False, "error": str(e), "error_description": str(e)}
        return JsonResponse(context, safe=False)


@csrf_exempt
def get_org_requestor(request):

    print("-----------------", request.body)
    post_data = json.loads(request.body.decode("utf-8"))
    access_token = request.META.get(
        "HTTP_ACCESS_TOKEN", post_data.get("access_token", None)
    )
    org_id = post_data.get("org_id", None)

    userinfo = get_user(access_token)
    if userinfo["success"] == False:
        context = {
            "Success": False,
            "error": userinfo["error"],
            "error_description": userinfo["error_description"],
        }
        return JsonResponse(context, safe=False)
    username = userinfo["preferred_username"]

    ispmu = False
    userroleobj = UserRole.objects.filter(username__username=username).values(
        "org_id", "role__role_name"
    )
    if len(userroleobj) != 0 and "PMU" in [
        each["role__role_name"] for each in userroleobj
    ]:
        ispmu = True

    if ispmu == False:
        context = {
            "Success": False,
            "error": "Access Denied",
            "error_description": "No access for the org for this user",
        }
        return JsonResponse(context, safe=False)

    try:
        org_roles = UserRole.objects.filter(
            org_id=org_id, role__role_name__in=["DPA"]
        ).values(
            "username__username",
            "username__email",
            "org_id",
            "org_title",
            "role__role_name",
        )
        context = {
            "Success": True,
            "username": org_roles[0]["username__username"],
            "email": org_roles[0]["username__email"],
            "org_id": org_roles[0]["org_id"],
            "org_title": org_roles[0]["org_title"],
            "role": org_roles[0]["role__role_name"],
        }
    except Exception as e:
        context = {
            "Success": False,
            "error": str(e),
            "error_description": "Matching organization requestor not found",
        }
    return JsonResponse(context, safe=False)


@csrf_exempt
def get_user_orgs(request):

    print("-----------------", request.body)
    post_data = json.loads(request.body.decode("utf-8"))
    access_token = request.META.get(
        "HTTP_ACCESS_TOKEN", post_data.get("access_token", None)
    )
    user_email = post_data.get("user_email", None)

    userinfo = get_user(access_token)
    if userinfo["success"] == False and access_token != None:
        context = {
            "Success": False,
            "error": userinfo["error"],
            "error_description": userinfo["error_description"],
        }
        return JsonResponse(context, safe=False)
    username = userinfo.get("preferred_username", None)

    try:
        user = (
            CustomUser.objects.get(email=user_email)
            if (username == None or username == "")
            else CustomUser.objects.get(username=username)
        )

        userroleobj = UserRole.objects.filter(
            username=user, role__role_name__in=["DPA", "DP"]
        ).values("org_id", "role__role_name", "org_title")
        orgs = []
        org_details = []
        for roles in userroleobj:
            if roles["org_id"] != None:
                orgs.append(roles["org_id"])
                org_details.append(
                    {"org_id": roles["org_id"], "org_title": roles["org_title"]}
                )

        context = {"Success": True, "orgs": orgs, "org_details": org_details}
    except Exception as e:
        context = {
            "Success": False,
            "error": str(e),
            "error_description": "Matching organization requestor not found",
        }
    return JsonResponse(context, safe=False)


@csrf_exempt
def filter_orgs_without_dpa(request):

    print("-----------------", request.body)
    post_data = json.loads(request.body.decode("utf-8"))
    # access_token = request.META.get("HTTP_ACCESS_TOKEN", post_data.get("access_token", None))
    org_list = post_data.get("org_list", None)

    if len(org_list) == 0:
        context = {
            "Success": False,
            "error": "wrong org_id",
            "error_description": "org_list is blank",
        }
        return JsonResponse(context, safe=False)

    try:
        orgs_with_dpa = list(
            UserRole.objects.filter(
                org_id__in=org_list, role__role_name="DPA"
            ).values_list("org_id", flat=True)
        )
        orgs_without_dpa = [id for id in org_list if id not in orgs_with_dpa]

        context = {"Success": True, "org_without_dpa": orgs_without_dpa}
        return JsonResponse(context, safe=False)
    except Exception as e:
        context = {"Success": False, "error": str(e), "error_description": str(e)}
        return JsonResponse(context, safe=False)
    
    

@csrf_exempt
def get_org_providers(request):

    print("-----------------", request.body)
    post_data = json.loads(request.body.decode("utf-8"))
    access_token = request.META.get(
        "HTTP_ACCESS_TOKEN", post_data.get("access_token", None)
    )
    org_id = post_data.get("org_id", None)

    userinfo = get_user(access_token)
    if userinfo["success"] == False:
        context = {
            "Success": False,
            "error": userinfo["error"],
            "error_description": userinfo["error_description"],
        }
        return JsonResponse(context, safe=False)
    username = userinfo["preferred_username"]
    
    
    if org_id == None or org_id == "":
        context = {
            "Success": False,
            "error": "wrong org_id",
            "error_description": "org_id is blank",
        }
        return JsonResponse(context, safe=False)    

    # check for username access
    ispmu = False
    isdpa = False
    isdp = False
    iscr = False
    calling_user = CustomUser.objects.get(username=username)
    ispmu, isdpa, isdp, iscr = utils.check_user_role(calling_user, org_id)
    print(ispmu, isdpa, isdp, iscr)

    if ispmu == False and isdpa == False:
        context = {
            "Success": False,
            "error": "No access for the org for this user",
            "error_description": "No access for the org for this user",
        }
        return JsonResponse(context, safe=False)


    if (ispmu or isdpa):
        
        try:
            child_org_list_without_dpa = []
            child_org_list_without_dpa = utils.get_child_orgs_without_dpa(org_id, child_org_list_without_dpa)
            child_org_list_without_dpa.append(org_id)
            print (child_org_list_without_dpa)
            dp_roles = UserRole.objects.filter(org_id__in=child_org_list_without_dpa, role__role_name="DP")

            dp_list = []
            for role in dp_roles:
                dp_list.append({"username": role.username.username,
                            "email": role.username.email, 
                            "org_id": role.org_id,
                            "org_title": role.org_title,
                            "role": role.role.role_name,
                            "status": role.org_status,
                            "updated": role.updated,
                            })

            context = {"Success": True, "providers": dp_list}
            return JsonResponse(context, safe=False)
        except Exception as e:
            context = {"Success": False, "error": str(e), "error_description": str(e)}
            return JsonResponse(context, safe=False)
    

    context = {
        "Success": False,
        "error": "No Providers found",
        "error_description": "No Providers found",
    }
    return JsonResponse(context, safe=False)
    


@csrf_exempt
def login(request):

    post_data = json.loads(request.body.decode("utf-8"))
    token = post_data.get("token", None)

    userinfo = get_user(token)
    user_name = userinfo["preferred_username"]

    try:

        query = f"""
                mutation {{
                    token_auth(username: {user_name}, password: {password}) {{
                        success,
                        errors,
                        unarchiving,
                        token,
                        refresh_token,
                        unarchiving,
                        user {{
                        id,
                        username,
                        }}
                    }}
    }}"""

        headers = {}
        response = requests.post(auth_url, json={"query": query}, headers=headers)

        response_json = json.loads(response.text)
        print(response_json)

        return JsonResponse(response_json, safe=False)
    except Exception as e:
        raise Http404("login failed")
