from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from django.core.files.storage import FileSystemStorage
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.utils import timezone
from datetime import timedelta
from django.views.decorators.csrf import csrf_exempt

import random
import string
import json
import requests

from .models import Post, Like, Comment, UserProfile, Memory, TunnelSession, TunnelOTP

# --------------------
# HELPER
# --------------------
def generate_profile_code():
    return (
        random.choice(string.ascii_uppercase) +
        str(random.randint(1, 9)) +
        '-' +
        ''.join(random.choices(string.ascii_uppercase + string.digits, k=2)) +
        '-' +
        ''.join(random.choices(string.ascii_uppercase + string.digits, k=2))
    )

# --------------------
# GENERAL PAGES
# --------------------
def index_page(request):
    return render(request, 'index.html')

def login_page(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)
        if user:
            login(request, user)
            messages.success(request, 'Login successful!')
            return redirect('posts')
        else:
            messages.error(request, 'Invalid username or password.')
    if request.user.is_authenticated:
        return redirect('posts')
    return render(request, 'login.html')

@login_required
def logout_page(request):
    logout(request)
    messages.success(request, 'You have been logged out successfully.')
    return redirect('/')

# --------------------
# SIGNUP (NO EMAIL VERIFICATION)
# --------------------
def signup_view(request):
    if request.method == 'POST':
        email = request.POST.get('email')
        username = request.POST.get('username')
        password1 = request.POST.get('password')
        confirm_password = request.POST.get('confirm_password')
        profile_picture = request.FILES.get('profile_picture')

        # Password check
        if password1 != confirm_password:
            if request.headers.get("x-requested-with") == "XMLHttpRequest":
                return JsonResponse({"success": False, "message": "Passwords do not match"})
            messages.error(request, 'Passwords do not match.')
            return render(request, 'signup.html')

        # Email uniqueness check
        if User.objects.filter(email=email).exists():
            if request.headers.get("x-requested-with") == "XMLHttpRequest":
                return JsonResponse({"success": False, "message": "Email is already in use"})
            messages.error(request, 'Email is already in use.')
            return render(request, 'signup.html')

        # Username uniqueness check
        if User.objects.filter(username=username).exists():
            if request.headers.get("x-requested-with") == "XMLHttpRequest":
                return JsonResponse({"success": False, "message": "Username is already taken"})
            messages.error(request, 'Username is already taken.')
            return render(request, 'signup.html')

        # Create user + profile
        user = User.objects.create_user(username=username, email=email, password=password1)
        user_profile, created = UserProfile.objects.get_or_create(user=user)
        user_profile.profile_code = generate_profile_code()
        user_profile.is_verified = True  # Auto-verify since no email verification
        user_profile.verification_token = None  # No verification token needed
        if profile_picture:
            user_profile.profile_picture = profile_picture
        user_profile.save()

        # Auto-login after signup
        user = authenticate(request, username=username, password=password1)
        if user:
            login(request, user)

        # Response (Ajax vs normal form)
        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse({'success': True, 'message': 'Account created successfully!', 'redirect': '/posts/'})

        messages.success(request, 'Account created successfully!')
        return redirect('posts')

    if request.user.is_authenticated:
        return redirect('posts')
    return render(request, 'signup.html')

@login_required
def home_page(request):
    return render(request, 'chat.html')

# --------------------
# POSTS
# --------------------
@login_required
def posts_page(request):
    posts = Post.objects.all().order_by('-created_at')
    user_liked_post_ids = Like.objects.filter(user=request.user).values_list('post_id', flat=True)
    return render(request, 'posts.html', {'posts': posts, 'user_liked_post_ids': user_liked_post_ids})

@login_required
def new_post_view(request):
    if request.method == 'POST':
        title = request.POST.get('title')
        content = request.POST.get('content')
        photo = request.FILES.get('photo')

        if photo:
            fs = FileSystemStorage()
            filename = fs.save(photo.name, photo)
            Post.objects.create(author=request.user, title=title, content=content, photo=filename)
        else:
            Post.objects.create(author=request.user, title=title, content=content)

        return redirect('posts')
    return render(request, 'new_post.html')

@require_POST
@login_required
def like_post(request, post_id):
    post = get_object_or_404(Post, id=post_id)
    like_obj, created = Like.objects.get_or_create(post=post, user=request.user)
    liked = created
    if not created:
        like_obj.delete()
        liked = False
    return JsonResponse({'liked': liked, 'like_count': post.likes.count()})

@login_required
def comment_post(request, post_id):
    if request.method == 'POST':
        post = get_object_or_404(Post, id=post_id)
        comment_content = request.POST.get('comment')
        if comment_content:
            Comment.objects.create(post=post, content=comment_content, user=request.user)
        return redirect('posts')

# --------------------
# MEMORIES / SOULS
# --------------------
@login_required
def souls_tunnel(request):
    memories = Memory.objects.all().order_by('-created_at')
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        memories_data = [{
            'id': m.id,
            'name': m.name,
            'image_url': m.image.url,
            'caption': m.caption,
            'created_at': m.created_at.strftime("%b %d, %Y %I:%M %p")
        } for m in memories]
        return JsonResponse({'memories': memories_data})
    return render(request, 'souls.html', {'memories': memories})

@login_required
@require_POST
def add_memory(request):
    name = request.POST.get('name')
    caption = request.POST.get('caption')
    image = request.FILES.get('image')
    if not all([name, caption, image]):
        return JsonResponse({'status': 'error', 'message': 'All fields are required'})
    memory = Memory.objects.create(user=request.user, name=name, caption=caption, image=image)
    return JsonResponse({
        'status': 'success',
        'memory': {
            'id': memory.id,
            'name': memory.name,
            'image_url': memory.image.url,
            'caption': memory.caption,
            'created_at': memory.created_at.strftime("%b %d, %Y %I:%M %p")
        }
    })

@login_required
def go_to_souls(request):
    return redirect('souls-tunnel')

# --------------------
# CHAT REDIRECT
# --------------------
@login_required
def go_to_chat_with_user5(request):
    user5 = get_object_or_404(User, id=5)
    return redirect('chat', room_name=user5.username)

# --------------------
# PRIVATE TUNNEL
# --------------------
@login_required
def private_tunnel(request):
    return render(request, 'private_tunnel.html')

@login_required
@require_POST
@csrf_exempt
def initiate_tunnel(request):
    try:
        data = json.loads(request.body)
        recipient_username = data.get('recipient')
        recipient = User.objects.filter(username=recipient_username).first()
        if not recipient:
            return JsonResponse({'success': False, 'error': 'User not found'})
        if recipient == request.user:
            return JsonResponse({'success': False, 'error': 'Cannot chat with yourself'})

        tunnel = TunnelSession.objects.create(
            initiator=request.user,
            recipient=recipient,
            expires_at=timezone.now() + timedelta(minutes=30)
        )

        otp = TunnelOTP.objects.create(tunnel_session=tunnel)

        # Send OTP email (optional - you can remove this if you don't want OTP emails)
        from django.core.mail import send_mail
        send_mail(
            subject="Private Tunnel Access Code",
            message=f"Hello {recipient.username},\n{request.user.username} wants to chat with you.\nOTP: {otp.otp_code}\nValid for 5 minutes.",
            from_email="elyseniyonzima202@gmail.com",
            recipient_list=[recipient.email],
            fail_silently=False,
        )

        return JsonResponse({'success': True, 'tunnel_id': tunnel.tunnel_id, 'chat_room_id': tunnel.chat_room_id})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@login_required
@require_POST
@csrf_exempt
def verify_tunnel_otp(request):
    try:
        data = json.loads(request.body.decode('utf-8'))
        otp_code = str(data.get('otp')).strip()
        tunnel_id = data.get('tunnel_id')

        # Get the tunnel regardless of initiator or recipient
        tunnel = TunnelSession.objects.get(tunnel_id=tunnel_id)

        # Check if the logged-in user is part of this tunnel
        if request.user not in [tunnel.initiator, tunnel.recipient]:
            return JsonResponse({'success': False, 'error': 'Access denied'})

        # Get the latest unused OTP
        otp_obj = tunnel.otps.filter(is_used=False).latest('created_at')

        if not otp_obj or not otp_obj.is_valid():
            return JsonResponse({'success': False, 'error': 'OTP expired or invalid'})

        if otp_obj.otp_code != otp_code:
            return JsonResponse({'success': False, 'error': 'Invalid OTP code'})

        otp_obj.is_used = True
        otp_obj.save()

        tunnel.is_active = True
        tunnel.save()

        return JsonResponse({'success': True, 'chat_room_id': tunnel.chat_room_id})

    except TunnelSession.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Tunnel not found'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@login_required
def tunnel_chat(request, chat_room_id):
    """Render the private chat room"""
    try:
        tunnel_session = TunnelSession.objects.get(
            chat_room_id=chat_room_id,
            is_active=True
        )

        if request.user not in [tunnel_session.initiator, tunnel_session.recipient]:
            return JsonResponse({'success': False, 'error': 'Access denied'})

        other_user = tunnel_session.recipient if tunnel_session.initiator == request.user else tunnel_session.initiator

        return render(request, 'tunner_chat.html', {
            'chat_room_id': chat_room_id,
            'other_user': other_user,
            'tunnel_id': tunnel_session.tunnel_id
        })

    except TunnelSession.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Tunnel not found or inactive'})

# --------------------
# ARCHIVED MESSAGES SECURITY
# --------------------
@login_required
@require_POST
def unlock_archived_messages(request, chat_room_id):
    """
    Verify user's profile code and allow access to archived messages.
    If the code is wrong, email the account owner with intruder info including country and region.
    """
    try:
        data = json.loads(request.body.decode("utf-8"))
        entered_code = data.get("profile_code", "").strip()

        if not entered_code:
            return JsonResponse({"success": False, "error": "Profile code is required."})

        # Get current user's profile
        user_profile = UserProfile.objects.get(user=request.user)

        if user_profile.profile_code != entered_code:
            # --- Collect intruder info ---
            ip = request.META.get('REMOTE_ADDR', 'Unknown IP')
            user_agent = request.META.get('HTTP_USER_AGENT', 'Unknown UA')
            referer = request.META.get('HTTP_REFERER', 'Unknown referer')
            accept_lang = request.META.get('HTTP_ACCEPT_LANGUAGE', 'Unknown language')
            attempt_time = timezone.now().strftime("%Y-%m-%d %H:%M:%S")
            page = request.path

            # --- Get country and region from IP ---
            try:
                response = requests.get(f'https://ipinfo.io/{ip}/json')
                geo_data = response.json()
                country = geo_data.get('country', 'Unknown')
                region = geo_data.get('region', 'Unknown')
                city = geo_data.get('city', 'Unknown')
                org = geo_data.get('org', 'Unknown')  # ISP / Org info
            except:
                country = region = city = org = 'Unknown'

            # --- Send email to account owner ---
            account_owner_email = request.user.email
            subject = "⚠️ Intruder Alert: Wrong Profile Code Attempt"
            text_content = (
                f"A wrong profile code was entered on your account!\n\n"
                f"Username: {request.user.username}\n"
                f"IP Address: {ip}\n"
                f"Country: {country}\n"
                f"Region: {region}\n"
                f"City: {city}\n"
                f"ISP / Org: {org}\n"
                f"Browser / Device: {user_agent}\n"
                f"Page: {page}\n"
                f"Referer: {referer}\n"
                f"Language: {accept_lang}\n"
                f"Time: {attempt_time}\n"
                f"Entered Code: {entered_code}\n\n"
                f"If this wasn't you, please secure your account immediately."
            )
            html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <style>
        body {{
            font-family: 'Segoe UI', Arial, sans-serif;
            line-height: 1.6;
            color: #333;
            margin: 0;
            padding: 20px;
            background-color: #f9f9f9;
        }}
        .container {{
            max-width: 600px;
            margin: 0 auto;
            background: white;
            border-radius: 8px;
            overflow: hidden;
            box-shadow: 0 4px 10px rgba(0,0,0,0.1);
        }}
        .header {{
            background: linear-gradient(to right, #d32f2f, #b71c1c);
            padding: 20px;
            text-align: center;
            color: white;
        }}
        .alert-icon {{
            font-size: 40px;
            margin-bottom: 10px;
        }}
        .content {{
            padding: 25px;
        }}
        .info-grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 12px;
            margin: 20px 0;
        }}
        .info-item {{
            padding: 12px;
            background: #f5f5f5;
            border-radius: 6px;
            border-left: 3px solid #d32f2f;
        }}
        .label {{
            font-weight: bold;
            color: #d32f2f;
            font-size: 0.9em;
            margin-bottom: 5px;
        }}
        .warning {{
            background: #ffebee;
            padding: 15px;
            border-radius: 6px;
            margin: 20px 0;
            border: 1px solid #ffcdd2;
        }}
        .footer {{
            background: #f5f5f5;
            padding: 15px;
            text-align: center;
            font-size: 0.9em;
            color: #666;
        }}
        @media (max-width: 480px) {{
            .info-grid {{
                grid-template-columns: 1fr;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div class="alert-icon">⚠️</div>
            <h1>Security Alert: Unauthorized Access Attempt</h1>
        </div>
        
        <div class="content">
            <p>We detected an attempt to access your account using an incorrect profile code.</p>
            
            <div class="info-grid">
                <div class="info-item">
                    <div class="label">Username</div>
                    <div>{request.user.username}</div>
                </div>
                <div class="info-item">
                    <div class="label">IP Address</div>
                    <div>{ip}</div>
                </div>
                <div class="info-item">
                    <div class="label">Location</div>
                    <div>{city}, {region}, {country}</div>
                </div>
                <div class="info-item">
                    <div class="label">ISP/Organization</div>
                    <div>{org}</div>
                </div>
                <div class="info-item">
                    <div class="label">Time of Attempt</div>
                    <div>{attempt_time}</div>
                </div>
                <div class="info-item">
                    <div class="label">Entered Code</div>
                    <div>{entered_code}</div>
                </div>
                <div class="info-item" style="grid-column: 1 / -1;">
                    <div class="label">Browser/Device</div>
                    <div>{user_agent}</div>
                </div>
                <div class="info-item" style="grid-column: 1 / -1;">
                    <div class="label">Page Accessed</div>
                    <div>{page}</div>
                </div>
            </div>
            
            <div class="warning">
                <h3 style="margin-top: 0; color: #d32f2f;">Immediate Action Recommended</h3>
                <p>If you did not attempt to access your account, please take the following steps immediately:</p>
                <ol>
                    <li>Change your password</li>
                    <li>Review your account activity</li>
                    <li>Enable two-factor authentication if available</li>
                    <li>Contact support if you need assistance</li>
                </ol>
            </div>
        </div>
        
        <div class="footer">
            <p>This is an automated security alert. Please do not reply to this message.</p>
            <p>© {timezone.now().year} Your Company Name. All rights reserved.</p>
        </div>
    </div>
</body>
</html>
"""

            from django.core.mail import EmailMultiAlternatives
            email = EmailMultiAlternatives(
                subject=subject,
                body=text_content,
                from_email="elyseniyonzima202@gmail.com",
                to=[account_owner_email],
            )
            email.attach_alternative(html_content, "text/html")
            email.send(fail_silently=False)

            return JsonResponse({"success": False, "error": "Invalid profile code."})

        # Correct code: unlock messages
        request.session[f"unlocked_{chat_room_id}"] = True
        return JsonResponse({"success": True, "message": "Archived messages unlocked."})

    except UserProfile.DoesNotExist:
        return JsonResponse({"success": False, "error": "Profile not found."})
    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)})

@login_required
def fetch_messages(request, chat_room_id):
    # This is a placeholder - you'll need to implement your actual Message model
    # get messages for this chat room
    unlocked = request.session.get(f"unlocked_{chat_room_id}", False)
    
    # Example implementation - replace with your actual Message model
    try:
        from .models import Message  # Import your actual Message model
        messages_qs = Message.objects.filter(chat_room_id=chat_room_id).order_by("timestamp")
        messages_data = []
        for msg in messages_qs:
            messages_data.append({
                "id": msg.id,
                "sender": msg.sender.username,
                "sender_id": msg.sender.id,
                "content": msg.content if unlocked else "[Archived Content]",
                "timestamp": msg.timestamp.isoformat(),
            })
        return JsonResponse({"success": True, "messages": messages_data})
    except:
        return JsonResponse({"success": False, "error": "Message model not implemented"})
